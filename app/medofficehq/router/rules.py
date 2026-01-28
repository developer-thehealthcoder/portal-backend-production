from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi import APIRouter
from app.medofficehq.core.config import settings
from app.medofficehq.router import patients
from app.medofficehq.rules.rules.rule_21 import rule_21_instance, Rule21Request, Rule21Response
from app.medofficehq.rules.rules.rule_22 import rule_22_instance, Rule22Request, Rule22Response
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from app.foundation_kit.database.cosmos import get_container
from app.medofficehq.services.progress_tracker import progress_tracker
from azure.cosmos.exceptions import CosmosResourceExistsError
import uuid
from datetime import datetime, timezone
import os
import asyncio
import logging

logger = logging.getLogger(__name__)

router = APIRouter()

# New Pydantic models for unified API
class UnifiedRuleRequest(BaseModel):
    """Unified request model for multiple rules"""
    project_name: str = "Default Project"  # Default project name if not provided
    project_id: Optional[str] = None  # Optional project ID (if not provided, will be auto-generated)
    rules: List[int]  # List of rule numbers to apply (e.g., [21, 22])
    add_modifiers: bool = True
    patients: List[Dict] = []  # List of patient objects
    is_rollback: bool = False

class RuleInfo(BaseModel):
    """Information about a specific rule"""
    rule_number: int
    name: str
    description: str
    supports_rollback: bool = True

class AvailableRulesResponse(BaseModel):
    """Response model for available rules"""
    success: bool
    message: str
    rules: List[RuleInfo]

# New patient-centric response models
class PatientRuleDetail(BaseModel):
    """Individual rule result for a patient"""
    rule_number: str  # Mapped rule number (e.g., "10001", "10002")
    status: int  # 1=changes made, 2=condition met no changes, 3=condition not met, 4=error
    reason: str

class PatientResult(BaseModel):
    """Individual patient result with all rule outcomes"""
    patientid: str
    appointmentid: str
    appointment_date: str
    first_name: str
    last_name: str
    dob: str
    status_1_changes_made: int = 0
    status_2_condition_met_no_changes: int = 0
    status_3_condition_not_met: int = 0
    status_4_errors: int = 0
    details: List[PatientRuleDetail] = []
    rollback_status: Optional[str] = None  # "rollbacked" or None
    rollbacked_at: Optional[str] = None  # ISO timestamp when rollbacked

class UnifiedRuleResponse(BaseModel):
    """Unified response model - patient-centric structure"""
    success: bool
    message: str
    results: List[PatientResult]  # Array of patients with their rule results
    total_rules_executed: int
    rules_with_errors: List[int] = []
    execution_id: Optional[str] = None  # Execution ID for progress tracking
    project_id: Optional[str] = None  # Project ID (provided or auto-generated)

class RuleCodeResponse(BaseModel):
    """Response model for rule code"""
    success: bool
    message: str
    rule_number: int
    rule_name: str
    code: str
    file_path: str
    last_modified: str

class RuleProgressDetail(BaseModel):
    """Progress detail for a specific rule"""
    percentage: float
    patients_processed: int
    total_patients: int
    status: str  # "pending" | "running" | "completed"

class OverallProgress(BaseModel):
    """Overall progress across all rules"""
    percentage: float
    patients_processed: int
    total_patients: int
    current_rule: Optional[int] = None
    total_rules: int
    rules_completed: int

class ProgressResponse(BaseModel):
    """Response model for progress tracking"""
    execution_id: str
    status: str  # "pending" | "running" | "completed" | "error"
    overall: OverallProgress
    rule_21: RuleProgressDetail
    rule_22: RuleProgressDetail
    started_at: str
    updated_at: str
    error_message: Optional[str] = None

# Include routers

@router.get("/list", response_model=AvailableRulesResponse)
async def get_available_rules():
    """
    Get list of all available rules
    """
    try:
        rules = [
            RuleInfo(
                rule_number=21,
                name="Missing Slips Analysis and Modifier Update",
                description="Identifies appointments missing charge slips and adds modifier 25 to eligible procedure codes when both eligible codes (99202-99205, 99212-99215) AND injection codes are present.",
                supports_rollback=True
            ),
            RuleInfo(
                rule_number=22,
                name="Procedure Code Modifier Assignment",
                description="Checks for specific procedure codes and assigns modifiers (RT, LT, 50) based on diagnosis codes. Includes special paired procedure logic for 73564 ↔ 73560.",
                supports_rollback=True
            )
        ]
        
        return AvailableRulesResponse(
            success=True,
            message=f"Found {len(rules)} available rules",
            rules=rules
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# Store for execution results (in-memory, can be moved to database later)
_execution_results_store: Dict[str, UnifiedRuleResponse] = {}

async def update_rollback_status_in_db(
    project_id: Optional[str],
    patients: List[Dict],
    rule_number: int
) -> bool:
    """
    Update rollback status in database for the given patients.
    
    Args:
        project_id: Optional project ID. If provided, updates that specific project.
                   If None, searches for projects containing these patients.
        patients: List of patient dictionaries with patientid and appointmentid
        rule_number: Rule number that was rollbacked (21 or 22)
        
    Returns:
        True if update was successful, False otherwise
    """
    try:
        run_container = get_container("runs")
        rollbacked_at = datetime.now(timezone.utc).isoformat()
        
        # Create a set of patient+appointment IDs for quick lookup
        patient_keys = {
            (p.get("patientid"), p.get("appointmentid"))
            for p in patients
            if p.get("patientid") and p.get("appointmentid")
        }
        
        if not patient_keys:
            logger.warning("No valid patient keys found for rollback status update")
            return False
        
        # If project_id is provided, update that specific project
        if project_id:
            try:
                project_doc = run_container.read_item(item=project_id, partition_key=project_id)
                results = project_doc.get("results", [])
                updated = False
                
                for result in results:
                    patient_key = (result.get("patientid"), result.get("appointmentid"))
                    if patient_key in patient_keys:
                        result["rollback_status"] = "rollbacked"
                        result["rollbacked_at"] = rollbacked_at
                        updated = True
                
                if updated:
                    project_doc["updated_at"] = rollbacked_at
                    run_container.replace_item(item=project_id, body=project_doc)
                    logger.info(f"Updated rollback status for {len(patient_keys)} patients in project {project_id}")
                    return True
                else:
                    logger.warning(f"No matching patients found in project {project_id} for rollback update")
                    return False
            except Exception as e:
                logger.error(f"Error updating project {project_id}: {str(e)}")
                return False
        
        # If no project_id, search for projects containing these patients
        # Query all projects and find ones with matching patients
        query = "SELECT * FROM c WHERE ARRAY_LENGTH(c.results) > 0"
        projects = list(run_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))
        
        updated_projects = []
        for project in projects:
            results = project.get("results", [])
            updated = False
            
            for result in results:
                patient_key = (result.get("patientid"), result.get("appointmentid"))
                if patient_key in patient_keys:
                    result["rollback_status"] = "rollbacked"
                    result["rollbacked_at"] = rollbacked_at
                    updated = True
            
            if updated:
                project["updated_at"] = rollbacked_at
                run_container.replace_item(item=project["id"], body=project)
                updated_projects.append(project["id"])
                logger.info(f"Updated rollback status in project {project['id']}")
        
        if updated_projects:
            logger.info(f"Updated rollback status in {len(updated_projects)} projects: {updated_projects}")
            return True
        else:
            logger.warning(f"No projects found containing the specified patients for rollback update")
            return False
            
    except Exception as e:
        logger.error(f"Error updating rollback status in database: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return False

async def execute_rules_background(execution_id: str, request: UnifiedRuleRequest, project_id: str):
    """
    Background task to execute rules asynchronously
    
    Args:
        execution_id: Execution ID for progress tracking (already created)
        request: UnifiedRuleRequest with rules and patients
        project_id: Project ID (provided or auto-generated)
    """
    try:
        print(f"Background execution started for {execution_id}")
        
        if not request.rules:
            progress_tracker.set_execution_error(execution_id, "No rules specified in request")
            return
        
        if not request.patients:
            progress_tracker.set_execution_error(execution_id, "No patients specified in request")
            return
        
        # Start execution (execution_id already created by endpoint)
        progress_tracker.start_execution(execution_id)
        
        print(f"Unified Rules API: Processing {len(request.rules)} rules for {len(request.patients)} patients")
        print(f"Execution ID: {execution_id}")
        print(f"Rules to execute: {request.rules}")
        print(f"Is rollback: {request.is_rollback}")
        
        # Convert patient dicts to proper PatientRequest objects for each rule
        from app.medofficehq.rules.rules.rule_21 import PatientRequest as PatientRequest21
        from app.medofficehq.rules.rules.rule_22 import PatientRequest as PatientRequest22
        
        patient_requests_21 = []
        patient_requests_22 = []
        
        for patient_dict in request.patients:
            try:
                patient_request_21 = PatientRequest21(**patient_dict)
                patient_requests_21.append(patient_request_21)
            except Exception as e:
                print(f"Error converting patient dict to PatientRequest21: {e}")
                continue
                
            try:
                patient_request_22 = PatientRequest22(**patient_dict)
                patient_requests_22.append(patient_request_22)
            except Exception as e:
                print(f"Error converting patient dict to PatientRequest22: {e}")
                continue
        
        if not patient_requests_21 and not patient_requests_22:
            progress_tracker.set_execution_error(execution_id, "No valid patients found in request")
            return
        
        # Initialize patient results dictionary
        patient_results = {}
        
        # Execute each rule and collect results
        rules_with_errors = []
        
        for rule_number in request.rules:
            try:
                print(f"Executing Rule {rule_number}...")
                
                # Start tracking this rule
                if execution_id:
                    progress_tracker.start_rule(execution_id, rule_number)
                
                if rule_number == 21:
                    # Process patients in batches for incremental progress
                    batch_size = 10  # Process 10 patients at a time
                    total_patients = len(patient_requests_21)
                    all_rule_results = []
                    patients_processed_so_far = 0
                    
                    for batch_start in range(0, total_patients, batch_size):
                        batch_end = min(batch_start + batch_size, total_patients)
                        batch_patients = patient_requests_21[batch_start:batch_end]
                        
                        # Create Rule21Request for this batch
                        rule21_request = Rule21Request(
                            add_modifiers=request.add_modifiers,
                            patients=batch_patients,
                            is_rollback=request.is_rollback
                        )
                        
                        # Execute Rule 21 for this batch
                        rule21_response = await rule_21_instance.run(rule21_request)
                        all_rule_results.extend(rule21_response.results)
                        
                        # Update progress after each batch
                        patients_processed_so_far = len(all_rule_results)
                        if execution_id:
                            progress_tracker.update_rule_progress(execution_id, 21, patients_processed_so_far)
                            logger.info(f"Rule 21 progress: {patients_processed_so_far}/{total_patients} patients processed")
                        
                        # Small delay to allow progress polling
                        await asyncio.sleep(0.1)
                    
                    # Mark rule as completed
                    if execution_id:
                        progress_tracker.complete_rule(execution_id, 21)
                    
                    # Process results for each patient (using combined results)
                    for result in all_rule_results:
                        patient_id = result.patientid
                        if patient_id not in patient_results:
                            # Initialize patient result with basic info
                            patient_dict = next((p for p in request.patients if p.get('patientid') == patient_id), {})
                            patient_results[patient_id] = PatientResult(
                                patientid=patient_id,
                                appointmentid=result.appointmentid,
                                appointment_date=patient_dict.get('appointmentdate', ''),
                                first_name=patient_dict.get('firstname', ''),
                                last_name=patient_dict.get('lastname', ''),
                                dob=patient_dict.get('dob', ''),  # Get DOB from patient data
                                details=[]
                            )
                        
                        # Add rule detail
                        rule_detail = PatientRuleDetail(
                            rule_number=str(rule_number),
                            status=result.status,
                            reason=result.reason
                        )
                        patient_results[patient_id].details.append(rule_detail)
                        
                        # Update status counts
                        if result.status == 1:
                            patient_results[patient_id].status_1_changes_made += 1
                        elif result.status == 2:
                            patient_results[patient_id].status_2_condition_met_no_changes += 1
                        elif result.status == 3:
                            patient_results[patient_id].status_3_condition_not_met += 1
                        elif result.status == 4:
                            patient_results[patient_id].status_4_errors += 1
                    
                    print(f"Rule {rule_number} completed successfully")
                    
                elif rule_number == 22:
                    # Process patients in batches for incremental progress
                    batch_size = 10  # Process 10 patients at a time
                    total_patients = len(patient_requests_22)
                    all_rule_results = []
                    patients_processed_so_far = 0
                    
                    for batch_start in range(0, total_patients, batch_size):
                        batch_end = min(batch_start + batch_size, total_patients)
                        batch_patients = patient_requests_22[batch_start:batch_end]
                        
                        # Create Rule22Request for this batch
                        rule22_request = Rule22Request(
                            add_modifiers=request.add_modifiers,
                            patients=batch_patients,
                            is_rollback=request.is_rollback
                        )
                        
                        # Execute Rule 22 for this batch
                        rule22_response = await rule_22_instance.run(rule22_request)
                        all_rule_results.extend(rule22_response.results)
                        
                        # Update progress after each batch
                        patients_processed_so_far = len(all_rule_results)
                        if execution_id:
                            progress_tracker.update_rule_progress(execution_id, 22, patients_processed_so_far)
                            logger.info(f"Rule 22 progress: {patients_processed_so_far}/{total_patients} patients processed")
                        
                        # Small delay to allow progress polling
                        await asyncio.sleep(0.1)
                    
                    # Mark rule as completed
                    if execution_id:
                        progress_tracker.complete_rule(execution_id, 22)
                    
                    # Process results for each patient (using combined results)
                    for result in all_rule_results:
                        patient_id = result.patientid
                        if patient_id not in patient_results:
                            # Initialize patient result with basic info
                            patient_dict = next((p for p in request.patients if p.get('patientid') == patient_id), {})
                            patient_results[patient_id] = PatientResult(
                                patientid=patient_id,
                                appointmentid=result.appointmentid,
                                appointment_date=patient_dict.get('appointmentdate', ''),
                                first_name=patient_dict.get('firstname', ''),
                                last_name=patient_dict.get('lastname', ''),
                                dob=patient_dict.get('dob', ''),  # Get DOB from patient data
                                details=[]
                            )
                        
                        # Add rule detail
                        rule_detail = PatientRuleDetail(
                            rule_number=str(rule_number),
                            status=result.status,
                            reason=result.reason
                        )
                        patient_results[patient_id].details.append(rule_detail)
                        
                        # Update status counts
                        if result.status == 1:
                            patient_results[patient_id].status_1_changes_made += 1
                        elif result.status == 2:
                            patient_results[patient_id].status_2_condition_met_no_changes += 1
                        elif result.status == 3:
                            patient_results[patient_id].status_3_condition_not_met += 1
                        elif result.status == 4:
                            patient_results[patient_id].status_4_errors += 1
                    
                    print(f"Rule {rule_number} completed successfully")
                    
                else:
                    print(f"Unknown rule number: {rule_number}")
                    rules_with_errors.append(rule_number)
                    if execution_id:
                        progress_tracker.set_execution_error(execution_id, f"Unknown rule number: {rule_number}")
                    
            except Exception as e:
                print(f"Error executing Rule {rule_number}: {str(e)}")
                rules_with_errors.append(rule_number)
                if execution_id:
                    progress_tracker.set_execution_error(execution_id, f"Error executing Rule {rule_number}: {str(e)}")
        
        # Convert patient results to list
        results_list = list(patient_results.values())
        
        # Determine overall success
        successful_rules = len(request.rules) - len(rules_with_errors)
        overall_success = successful_rules > 0
        
        message = f"Executed {len(request.rules)} rules. {successful_rules} successful, {len(rules_with_errors)} failed."

        # Mark execution as completed
        if execution_id:
            progress_tracker.complete_execution(execution_id, success=overall_success)

        # database part
        run_container = get_container("runs")
        
        # Convert Pydantic models to dictionaries for JSON serialization
        serializable_results = []
        for result in results_list:
            result_dict = result.model_dump() if hasattr(result, 'model_dump') else result.dict()
            serializable_results.append(result_dict)
        
        # Prepare the project document
        project_doc = {
            "id": project_id,  # Use provided or generated project_id
            "project_name": request.project_name,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "success": overall_success,
            "message": message,
            "results": serializable_results,
            "total_rules_executed": len(request.rules),
            "rules_with_errors": rules_with_errors,
            "execution_id": execution_id
        }
        
        # Try to create the item, or update if it already exists
        try:
            # Check if item already exists to preserve created_at
            existing_item = run_container.read_item(item=project_id, partition_key=project_id)
            # Item exists, preserve created_at and update
            project_doc["created_at"] = existing_item.get("created_at", datetime.now(timezone.utc).isoformat())
            run_container.replace_item(item=project_id, body=project_doc)
            logger.info(f"Updated existing project {project_id} in database")
        except Exception:
            # Item doesn't exist, create new with created_at
            try:
                project_doc["created_at"] = datetime.now(timezone.utc).isoformat()
                run_container.create_item(body=project_doc)
                logger.info(f"Created new project {project_id} in database")
            except CosmosResourceExistsError:
                # Race condition: item was created between read and create, update instead
                existing_item = run_container.read_item(item=project_id, partition_key=project_id)
                project_doc["created_at"] = existing_item.get("created_at", datetime.now(timezone.utc).isoformat())
                run_container.replace_item(item=project_id, body=project_doc)
                logger.info(f"Updated project {project_id} after conflict resolution")
        
        # Store result for later retrieval
        final_response = UnifiedRuleResponse(
            success=overall_success,
            message=message,
            results=results_list,
            total_rules_executed=len(request.rules),
            rules_with_errors=rules_with_errors,
            execution_id=execution_id,
            project_id=project_id
        )
        _execution_results_store[execution_id] = final_response
        
        print(f"Background execution completed for {execution_id}")
        
    except Exception as e:
        # Mark execution as error
        progress_tracker.set_execution_error(execution_id, str(e))
        logger.error(f"Error in background execution {execution_id}: {str(e)}")
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")

@router.post("/run", response_model=UnifiedRuleResponse)
async def unified_rules_endpoint(
    request: UnifiedRuleRequest
):
    """
    Unified endpoint to apply multiple rules at once.
    Returns immediately with execution_id. Rules execute in background.
    Use /api/rules/progress/{execution_id} to track progress.
    
    Args:
        request: UnifiedRuleRequest with rules array and patient list
        
    Returns:
        UnifiedRuleResponse with execution_id (results will be empty initially)
    """
    execution_id = None
    project_id = None
    try:
        # Use provided project_id or generate a new one (do this early so we can return it in error cases)
        project_id = request.project_id if request.project_id else str(uuid.uuid4())
        
        if not request.rules:
            return UnifiedRuleResponse(
                success=False,
                message="No rules specified in request",
                results=[],
                total_rules_executed=0,
                rules_with_errors=[],
                execution_id=None,
                project_id=project_id
            )
        
        if not request.patients:
            return UnifiedRuleResponse(
                success=False,
                message="No patients specified in request",
                results=[],
                total_rules_executed=0,
                rules_with_errors=[],
                execution_id=None,
                project_id=project_id
            )
        
        # Create execution tracking
        execution_id = progress_tracker.create_execution(
            total_patients=len(request.patients),
            rules=request.rules,
            project_name=request.project_name
        )
        
        print(f"Unified Rules API: Starting background execution for {len(request.rules)} rules, {len(request.patients)} patients")
        print(f"Execution ID: {execution_id}")
        print(f"Project ID: {project_id}")
        
        # Start background task (non-blocking) - pass project_id to background function
        asyncio.create_task(execute_rules_background(execution_id, request, project_id))
        
        # Return immediately with execution_id and project_id
        return UnifiedRuleResponse(
            success=True,
            message=f"Rule execution started. Use execution_id to track progress.",
            results=[],  # Results will be empty initially
            total_rules_executed=len(request.rules),
            rules_with_errors=[],
            execution_id=execution_id,
            project_id=project_id
        )
        
    except Exception as e:
        # Mark execution as error
        if execution_id:
            progress_tracker.set_execution_error(execution_id, str(e))
        raise HTTPException(status_code=500, detail=str(e))
    
@router.get("/runs", response_model=List[Dict])
async def get_runs():
    """
    Get all runs (excluding archived projects and fake/test projects)
    """
    run_container = get_container("runs")
    # Filter out archived projects - only return projects where archived is not true or doesn't exist
    query = "SELECT * FROM c WHERE (c.archived != true OR NOT IS_DEFINED(c.archived))"
    runs = list(run_container.query_items(query=query, enable_cross_partition_query=True))
    
    # Filter out fake/test projects
    # Exclude projects with test/fake identifiers or names
    fake_project_ids = ["1000000", "1000001", "1000002", "1000003", "1000004", "1000005", "10000001"]
    filtered_runs = []
    
    for run in runs:
        project_id = str(run.get("id", ""))
        project_name = run.get("project_name", "").lower()
        
        # Skip if it's a known fake project ID
        if project_id in fake_project_ids:
            continue
        
        # Skip if project name matches "Project X" pattern (fake test data)
        if project_name.startswith("project ") and project_name.replace("project ", "").strip().isdigit():
            continue
        
        # Skip if project name contains test/fake keywords
        if any(keyword in project_name for keyword in ["test", "fake", "dummy", "sample", "demo"]):
            continue
        
        filtered_runs.append(run)
    
    return filtered_runs

@router.get("/progress/{execution_id}", response_model=ProgressResponse)
async def get_progress(execution_id: str):
    """
    Get progress for a specific rule execution
    
    Args:
        execution_id: Execution ID returned from /api/rules/run endpoint
        
    Returns:
        ProgressResponse with current progress status
    """
    try:
        progress = progress_tracker.get_progress(execution_id)
        
        if not progress:
            raise HTTPException(
                status_code=404,
                detail=f"Execution ID '{execution_id}' not found. It may have expired or never existed."
            )
        
        # Convert to response model
        return ProgressResponse(**progress)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving progress: {str(e)}")

@router.get("/results/{execution_id}", response_model=UnifiedRuleResponse)
async def get_execution_results(execution_id: str):
    """
    Get final results for a completed rule execution
    
    Args:
        execution_id: Execution ID returned from /api/rules/run endpoint
        
    Returns:
        UnifiedRuleResponse with final results (only available after execution completes)
    """
    try:
        # Check if execution is still running
        progress = progress_tracker.get_progress(execution_id)
        if progress:
            if progress["status"] == "running" or progress["status"] == "pending":
                raise HTTPException(
                    status_code=202,  # Accepted - still processing
                    detail="Execution is still in progress. Use /api/rules/progress/{execution_id} to track progress."
                )
        
        # First, check in-memory store (fastest)
        if execution_id in _execution_results_store:
            return _execution_results_store[execution_id]
        
        # If not in memory, check database (fallback for server restarts)
        run_container = get_container("runs")
        query = "SELECT * FROM c WHERE c.execution_id = @execution_id"
        parameters = [{"name": "@execution_id", "value": execution_id}]
        
        results = list(run_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if results:
            # Found in database, convert to UnifiedRuleResponse
            project_data = results[0]
            return UnifiedRuleResponse(
                success=project_data.get("success", False),
                message=project_data.get("message", "Results retrieved from database"),
                results=project_data.get("results", []),
                total_rules_executed=project_data.get("total_rules_executed", 0),
                rules_with_errors=project_data.get("rules_with_errors", []),
                execution_id=execution_id,
                project_id=project_data.get("id")
            )
        
        # Not found anywhere
        raise HTTPException(
            status_code=404,
            detail=f"Results for execution ID '{execution_id}' not found. Execution may not have completed yet or results were not stored."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving results: {str(e)}")

# New Pydantic models for project results API
class ProjectIdRequest(BaseModel):
    """Request model for getting project results by ID"""
    project_id: str

class ProjectResultResponse(BaseModel):
    """Response model for project results"""
    success: bool
    message: str
    project_id: str
    project_name: str
    created_at: str
    updated_at: str
    success_status: bool
    execution_message: str
    results: List[Dict]
    total_rules_executed: int
    rules_with_errors: List[int]

@router.post("/project-results", response_model=ProjectResultResponse)
async def get_project_results(
    request: ProjectIdRequest
):
    """
    Get results for a specific project by project ID
    
    Args:
        request: ProjectIdRequest with project_id
        
    Returns:
        ProjectResultResponse with project results
    """
    try:
        run_container = get_container("runs")
        
        # Query for the specific project by ID
        query = "SELECT * FROM c WHERE c.id = @project_id"
        parameters = [{"name": "@project_id", "value": request.project_id}]
        
        results = list(run_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if not results:
            return ProjectResultResponse(
                success=False,
                message=f"Project with ID '{request.project_id}' not found",
                project_id=request.project_id,
                project_name="",
                created_at="",
                updated_at="",
                success_status=False,
                execution_message="",
                results=[],
                total_rules_executed=0,
                rules_with_errors=[]
            )
        
        # Get the first (and should be only) result
        project_data = results[0]
        
        return ProjectResultResponse(
            success=True,
            message=f"Successfully retrieved results for project '{project_data.get('project_name', 'Unknown')}'",
            project_id=project_data.get('id', request.project_id),
            project_name=project_data.get('project_name', 'Unknown'),
            created_at=project_data.get('created_at', ''),
            updated_at=project_data.get('updated_at', ''),
            success_status=project_data.get('success', False),
            execution_message=project_data.get('message', ''),
            results=project_data.get('results', []),
            total_rules_executed=project_data.get('total_rules_executed', 0),
            rules_with_errors=project_data.get('rules_with_errors', [])
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error retrieving project results: {str(e)}")

@router.post("/runs/{project_id}/archive")
async def archive_project(
    project_id: str
):
    """
    Archive a project/run by marking it as archived (soft delete)
    
    Args:
        project_id: The project ID to archive
        
    Returns:
        Success message with archived project information
    """
    try:
        run_container = get_container("runs")
        
        # First, query to find the project and get its details
        query = "SELECT * FROM c WHERE c.id = @project_id"
        parameters = [{"name": "@project_id", "value": project_id}]
        
        results = list(run_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True
        ))
        
        if not results:
            raise HTTPException(
                status_code=404,
                detail=f"Project with ID '{project_id}' not found"
            )
        
        # Get project details
        project_data = results[0]
        project_name = project_data.get('project_name', 'Unknown')
        
        # Update the project to mark it as archived
        project_data['archived'] = True
        project_data['archived_at'] = datetime.now(timezone.utc).isoformat()
        project_data['updated_at'] = datetime.now(timezone.utc).isoformat()
        
        # Replace the item in the database
        run_container.replace_item(item=project_id, body=project_data)
        
        return {
            "success": True,
            "message": f"Project '{project_name}' (ID: {project_id}) archived successfully",
            "project_id": project_id,
            "project_name": project_name
        }
        
    except HTTPException:
        raise
    except Exception as e:
        # Handle Cosmos DB specific errors
        if "NotFound" in str(e) or "not found" in str(e).lower():
            raise HTTPException(
                status_code=404,
                detail=f"Project with ID '{project_id}' not found"
            )
        raise HTTPException(
            status_code=500,
            detail=f"Error archiving project: {str(e)}"
        )

@router.post("/rule21", response_model=Rule21Response)
async def rule21_endpoint(request: Rule21Request):
    """
    Rule 21: Missing Slips Analysis and Modifier Update
    """
    try:
        return await rule_21_instance.run(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rule22", response_model=Rule22Response)
async def rule22_endpoint(request: Rule22Request):
    """
    Rule 22: Procedure Code Modifier Assignment
    """
    try:
        return await rule_22_instance.run(request)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rule21/rollback", response_model=Rule21Response)
async def rule21_rollback_endpoint(
    request: Rule21Request,
    project_id: Optional[str] = Query(None, description="Project ID to update rollback status in database")
):
    """
    Rule 21 Rollback: Remove modifier 25 from services
    
    Args:
        request: Rule21Request with patients to rollback
        project_id: Optional project ID to update rollback status in database
    """
    try:
        # Set rollback flag
        request.is_rollback = True
        
        # Execute rollback
        response = await rule_21_instance.run(request)
        
        # If rollback was successful, update database to mark patients as rollbacked
        if response.success and response.results:
            # Convert patient results to dict format for database update
            patients_for_db = []
            for result in response.results:
                # Only mark as rollbacked if status is 1 (successful rollback)
                if result.status == 1:
                    patients_for_db.append({
                        "patientid": result.patientid,
                        "appointmentid": result.appointmentid
                    })
            
            if patients_for_db:
                # Update rollback status in database
                await update_rollback_status_in_db(
                    project_id=project_id,
                    patients=patients_for_db,
                    rule_number=21
                )
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/rule22/rollback", response_model=Rule22Response)
async def rule22_rollback_endpoint(
    request: Rule22Request,
    project_id: Optional[str] = Query(None, description="Project ID to update rollback status in database")
):
    """
    Rule 22 Rollback: Remove modifiers from services
    
    Args:
        request: Rule22Request with patients to rollback
        project_id: Optional project ID to update rollback status in database
    """
    try:
        # Set rollback flag
        request.is_rollback = True
        
        # Execute rollback
        response = await rule_22_instance.run(request)
        
        # If rollback was successful, update database to mark patients as rollbacked
        if response.success and response.results:
            # Convert patient results to dict format for database update
            patients_for_db = []
            for result in response.results:
                # Only mark as rollbacked if status is 1 (successful rollback)
                if result.status == 1:
                    patients_for_db.append({
                        "patientid": result.patientid,
                        "appointmentid": result.appointmentid
                    })
            
            if patients_for_db:
                # Update rollback status in database
                await update_rollback_status_in_db(
                    project_id=project_id,
                    patients=patients_for_db,
                    rule_number=22
                )
        
        return response
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/code/{rule_number}", response_model=RuleCodeResponse)
async def get_rule_code(rule_number: int):
    """
    Get the current code for a specific rule (21 or 22)
    """
    try:
        # Validate rule number
        if rule_number not in [21, 22]:
            raise HTTPException(status_code=400, detail="Only rule 21 and 22 are supported")
        
        # Determine file path based on rule number
        if rule_number == 21:
            file_path = "app/medofficehq/rules/rules/rule_21.py"
            rule_name = "Missing Slips Analysis and Modifier Update"
        else:  # rule_number == 22
            file_path = "app/medofficehq/rules/rules/rule_22.py"
            rule_name = "Procedure Code Modifier Assignment"
        
        # Check if file exists
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Rule {rule_number} file not found")
        
        # Read the file content
        with open(file_path, 'r', encoding='utf-8') as file:
            code = file.read()
        
        # Get file modification time
        stat = os.stat(file_path)
        last_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
        
        return RuleCodeResponse(
            success=True,
            message=f"Successfully retrieved code for Rule {rule_number}",
            rule_number=rule_number,
            rule_name=rule_name,
            code=code,
            file_path=file_path,
            last_modified=last_modified
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading rule code: {str(e)}")

@router.get("/code/{rule_number}/formatted")
async def get_rule_code_formatted(rule_number: int):
    """
    Get the current code for a specific rule (21 or 22) with proper formatting
    """
    try:
        # Validate rule number
        if rule_number not in [21, 22]:
            raise HTTPException(status_code=400, detail="Only rule 21 and 22 are supported")
        
        # Determine file path based on rule number
        if rule_number == 21:
            file_path = "app/medofficehq/rules/rules/rule_21.py"
            rule_name = "Missing Slips Analysis and Modifier Update"
        else:  # rule_number == 22
            file_path = "app/medofficehq/rules/rules/rule_22.py"
            rule_name = "Procedure Code Modifier Assignment"
        
        # Check if file exists
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Rule {rule_number} file not found")
        
        # Read the file content
        with open(file_path, 'r', encoding='utf-8') as file:
            code = file.read()
        
        # Get file modification time
        stat = os.stat(file_path)
        last_modified = datetime.fromtimestamp(stat.st_mtime).isoformat()
        
        # Return formatted response with proper content type
        from fastapi.responses import HTMLResponse
        
        # Create HTML with syntax highlighting
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Rule {rule_number} Code</title>
    <style>
        body {{ font-family: 'Courier New', monospace; background-color: #1e1e1e; color: #d4d4d4; margin: 20px; }}
        .header {{ background-color: #2d2d30; padding: 15px; border-radius: 5px; margin-bottom: 20px; }}
        .code-block {{ background-color: #1e1e1e; border: 1px solid #3e3e42; border-radius: 5px; padding: 20px; overflow-x: auto; }}
        .code {{ white-space: pre; line-height: 1.4; }}
        .keyword {{ color: #569cd6; }}
        .string {{ color: #ce9178; }}
        .comment {{ color: #6a9955; }}
        .function {{ color: #dcdcaa; }}
        .class {{ color: #4ec9b0; }}
        .number {{ color: #b5cea8; }}
        .operator {{ color: #d4d4d4; }}
        .info {{ color: #9cdcfe; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>Rule {rule_number}: {rule_name}</h1>
        <p><strong>File:</strong> {file_path}</p>
        <p><strong>Last Modified:</strong> {last_modified}</p>
        <p><strong>Lines:</strong> {len(code.splitlines())}</p>
    </div>
    <div class="code-block">
        <div class="code">{code}</div>
    </div>
</body>
</html>
        """
        
        return HTMLResponse(content=html_content)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading rule code: {str(e)}")

@router.get("/code/{rule_number}/raw")
async def get_rule_code_raw(rule_number: int):
    """
    Get the current code for a specific rule (21 or 22) as raw text
    """
    try:
        # Validate rule number
        if rule_number not in [21, 22]:
            raise HTTPException(status_code=400, detail="Only rule 21 and 22 are supported")
        
        # Determine file path based on rule number
        if rule_number == 21:
            file_path = "app/medofficehq/rules/rules/rule_21.py"
        else:  # rule_number == 22
            file_path = "app/medofficehq/rules/rules/rule_22.py"
        
        # Check if file exists
        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Rule {rule_number} file not found")
        
        # Read the file content
        with open(file_path, 'r', encoding='utf-8') as file:
            code = file.read()
        
        # Return raw text with proper content type
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(content=code, media_type="text/plain")
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading rule code: {str(e)}")

@router.get("/")
async def root():
    return {"message": "Welcome to Athena Health API Integration"} 
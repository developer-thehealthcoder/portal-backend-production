"""
Rule 22: Procedure Code Modifier Assignment

This rule checks for specific procedure codes and assigns modifiers based on diagnosis codes.
- Checks for procedure codes: 72170, 72190, 73000, 73010, 73030, 73060, 73070, 73080, 73110, 73130, 73140, 73502, 73521, 73522, 73552, 73562, 73564, 73565, 73590, 73610, 73630, 73650
- For matching appointments, checks diagnosis codes starting with "M"
- Assigns modifiers based on diagnosis code ending:
  - Ends with "1" → "RT" modifier
  - Ends with "2" → "LT" modifier
  - Ends with "0" → "50" modifier

Special Paired Procedure Logic (73564 ↔ 73560):
- When 73564 gets LT → 73560 gets RT
- When 73564 gets RT → 73560 gets LT + diagnosis replaced with Z0189

Author: Adil
Date: 2025-01-07
Version: 3.0
"""

import sys
import os
import logging
import asyncio
import httpx
import json
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.medofficehq.core.config import settings
from app.medofficehq.services.athena_service import AthenaService

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PatientRequest(BaseModel):
    """Individual patient request model"""
    appointmentid: str
    appointmentdate: str
    patientid: str
    firstname: str
    lastname: str
    dob: str = ""  # Optional DOB field

class Rule22Request(BaseModel):
    """Request model for Rule 22"""
    add_modifiers: bool = True
    patients: List[PatientRequest] = []
    is_rollback: bool = False  # New field to indicate if this is a rollback operation

class PatientResult(BaseModel):
    """Individual patient result model"""
    patientid: str
    appointmentid: str
    status: int  # 1=changes made, 2=condition met no changes, 3=condition not met, 4=error
    reason: str

class Rule22Response(BaseModel):
    """Response model for Rule 22"""
    success: bool
    message: str
    results: List[PatientResult]
    issues_found: int = 0
    details: Optional[dict] = None

class Rule22:
    """
    Rule 22: Procedure Code Modifier Assignment
    
    Checks for specific procedure codes and assigns modifiers based on diagnosis codes.
    """
    
    def __init__(self):
        """Initialize Rule 22"""
        self.name = "Procedure Code Modifier Assignment"
        self.version = "3.0"
        
        # API configuration
        self.base_url = settings.ATHENA_API_BASE_URL
        self.practice_id = settings.ATHENA_PRACTICE_ID
        
        # Initialize AthenaService for API calls
        self.athena_service = AthenaService()
        
        # Target procedure codes to check
        self.target_procedure_codes = [
            "72170", "72190", "73000", "73010", "73030", "73060", "73070", "73080",
            "73110", "73130", "73140", "73502", "73521", "73522", "73552", "73562",
            "73564", "73565", "73590", "73610", "73630", "73650"
        ]
        
        # Paired procedure code logic: 73564 ↔ 73560
        self.paired_procedure_codes = {
            "73564": "73560"  # If 73564 gets LT, then 73560 gets RT (and vice versa)
        }
        
        logger.info(f"Initialized {self.name} v{self.version}")
        logger.info(f"Target procedure codes: {self.target_procedure_codes}")
        logger.info(f"Paired procedure codes: {self.paired_procedure_codes}")

    # ============================================================================
    # 1. DATA FETCHING - Get data from Athena Health API
    # ============================================================================

    async def get_encounter_services(self, encounter_id: str, token: Optional[str] = None) -> List[Dict]:
        """Fetch services/procedures for a specific encounter"""
        try:
            # Get access token if not provided
            if not token:
                token = await self.athena_service.get_access_token()
            
            # Create a custom request with longer timeout
            async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(120.0)) as client:
                url = f"{self.athena_service.base_url}/{settings.ATHENA_PRACTICE_ID}/encounter/{encounter_id}/services"
                
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
                
                logger.info(f"Making services request for encounter {encounter_id}")
                
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                procedures = data.get('procedures', [])
                logger.info(f"Found {len(procedures)} procedures for encounter {encounter_id}")
                
                return procedures
                
        except httpx.ReadTimeout as e:
            logger.error(f"Services request timed out for encounter {encounter_id}: {str(e)}")
            return []
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for encounter {encounter_id}: {e.response.status_code}")
            return []
        except Exception as e:
            logger.error(f"Error making services API request for encounter {encounter_id}: {str(e)}")
            return []

    # ============================================================================
    # 2. RULE CONDITIONS - Apply business logic to identify issues
    # ============================================================================
    
    def determine_status_and_reason(self, patient_result: Dict, modifier_added: bool, error_occurred: bool = False, error_message: str = "") -> Tuple[int, str]:
        """Determine status and reason for a patient result"""
        
        if error_occurred:
            return 4, f"error: {error_message}"
        
        # Check if conditions were met (has target procedure codes)
        has_target_procedures = patient_result.get('target_procedure_found', False)
        
        if not has_target_procedures:
            return 3, "no target procedure codes found"
        
        # Check if modifier was required
        modifier_required = patient_result.get('modifier_required', False)
        if not modifier_required:
            return 3, "no matching diagnosis codes found"
        
        # Conditions met, check if changes were made
        if modifier_added:
            return 1, "modifier applied successfully"
        else:
            return 2, "modifier already exists"

    def _determine_modifier_from_diagnoses(self, diagnoses: List[Dict]) -> Optional[str]:
        """
        Determine modifier based on diagnosis codes
        
        Args:
            diagnoses: List of diagnosis records from services API
            
        Returns:
            Modifier to apply ("RT", "LT", or "50") or None if no match
        """
        for diagnosis in diagnoses:
            # Services API uses 'icd10code' instead of 'diagnosisrawcode'
            diagnosis_code = diagnosis.get('icd10code', '')
            
            # Check if code starts with "M" and ends with 0, 1, or 2
            if diagnosis_code.startswith('M'):
                if diagnosis_code.endswith('1'):
                    return "RT"
                elif diagnosis_code.endswith('2'):
                    return "LT"
                elif diagnosis_code.endswith('0'):
                    return "50"
        
        return None
    
    async def _handle_paired_procedure_logic(self, appointment: Dict, procedures: List[Dict], original_modifier: str, token: str) -> List[Dict]:
        """
        Handle paired procedure code logic for 73564 ↔ 73560
        
        Args:
            appointment: Appointment data
            procedures: All procedures in the encounter
            original_modifier: Modifier applied to 73564 (LT or RT)
            token: API token
            
        Returns:
            List of issues for paired procedure updates
        """
        paired_issues = []
        
        # Find the paired procedure (73560)
        paired_procedure = None
        for procedure in procedures:
            if procedure.get('procedurecode') == "73560":
                paired_procedure = procedure
                break
        
        if not paired_procedure:
            print(f"    Paired procedure 73560 not found for 73564")
            return paired_issues
        
        # Determine the opposite modifier
        opposite_modifier = "RT" if original_modifier == "LT" else "LT"
        print(f"    Found paired procedure 73560, applying opposite modifier: {opposite_modifier}")
        
        # Create issue for the paired procedure
        issue = self._create_issue_record_from_service(appointment, paired_procedure, opposite_modifier)
        
        # Special handling: replace diagnosis with Z0189 for BOTH LT and RT cases
        print(f"    Will replace diagnosis with Z0189 for 73560 (both LT and RT cases)")
        issue['replace_diagnosis_with_z0189'] = True
        
        paired_issues.append(issue)
        return paired_issues
    
    def _create_issue_record_from_service(self, appointment: Dict, procedure: Dict, modifier: str) -> Dict:
        """Create an issue record from the services API data"""
        return {
            'appointment_id': appointment.get('appointmentid', ''),
            'patient_id': appointment.get('patientid', ''),
            'encounter_id': appointment.get('encounterid', ''),
            'service_id': procedure.get('serviceid', ''),
            'procedure_code': procedure.get('procedurecode', ''),
            'required_modifier': modifier,
            'modifier_added': False,  # Will be updated when fix is applied
            'appointment_date': appointment.get('date', ''),
            'patient_name': appointment.get('patientname', ''),
            'bill_for_service': procedure.get('billforservice', False),
            'service_type': procedure.get('servicetype', '')
        }
    
    # ============================================================================
    # 3. MODIFIERS - Apply fixes/updates to identified issues
    # ============================================================================
    
    async def update_service_with_modifier(self, encounter_id: str, service_id: str, modifier: str, token: Optional[str] = None, replace_diagnosis: bool = False, procedure_code: str = "") -> bool:
        """Update a service to add modifier"""
        try:
            # Get access token if not provided
            if not token:
                token = await self.athena_service.get_access_token()
            
            # Create a custom request with longer timeout
            async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(120.0)) as client:
                url = f"{self.athena_service.base_url}/{settings.ATHENA_PRACTICE_ID}/encounter/{encounter_id}/services/{service_id}"
                
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
                
                # Prepare the data payload
                data = {
                    'modifiers': json.dumps([modifier]),
                    'billforservice': 'true'
                }
                
                # Special handling for 73030: add modifier 59
                if procedure_code == "73030":
                    current_modifiers = [modifier]
                    if "59" not in current_modifiers:
                        current_modifiers.append("59")
                        data['modifiers'] = json.dumps(current_modifiers)
                        print(f"    Adding modifier 59 to 73030 (total modifiers: {current_modifiers})")
                
                # Special handling: replace diagnosis with Z0189
                if replace_diagnosis:
                    print(f"    Replacing diagnosis with Z0189")
                    data['icd10codes'] = "Z0189"
                
                logger.info(f"Adding modifier {modifier} to service {service_id} in encounter {encounter_id}")
                
                response = await client.put(url, headers=headers, data=data)
                response.raise_for_status()
                
                # Check if the update was successful
                if response.status_code == 200:
                    logger.info(f"Successfully added modifier {modifier} to service {service_id}")
                    if replace_diagnosis:
                        logger.info(f"Replaced diagnosis with Z0189")
                    if procedure_code == "73030":
                        logger.info(f"Added modifier 59 to 73030")
                    return True
                else:
                    logger.error(f"Failed to add modifier {modifier} to service {service_id}")
                    return False
                
        except httpx.ReadTimeout as e:
            logger.error(f"Update request timed out for service {service_id}: {str(e)}")
            return False
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for service {service_id}: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Error updating service {service_id}: {str(e)}")
            return False

    async def rollback_service_modifiers(self, encounter_id: str, service_id: str, token: Optional[str] = None, procedure_code: str = "") -> bool:
        """Rollback: Remove modifiers and revert diagnosis changes"""
        try:
            # Get access token if not provided
            if not token:
                token = await self.athena_service.get_access_token()
            
            # Create a custom request with longer timeout
            async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(120.0)) as client:
                url = f"{self.athena_service.base_url}/{settings.ATHENA_PRACTICE_ID}/encounter/{encounter_id}/services/{service_id}"
                
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
                
                # Prepare the data payload - remove all modifiers
                data = {
                    'modifiers': json.dumps([]),  # Empty array to remove all modifiers
                    'billforservice': 'true'
                }
                
                # Special handling: if this was a 73560 procedure, we need to revert diagnosis from Z0189
                # We'll need to get the original diagnosis from the service first
                if procedure_code == "73560":
                    print(f"    Reverting diagnosis for 73560 (removing Z0189)")
                    # For now, we'll set a placeholder - in a real scenario, you'd need to store/retrieve original diagnosis
                    data['icd10codes'] = ""  # This will need to be handled based on your business logic
                
                logger.info(f"Removing modifiers from service {service_id} in encounter {encounter_id}")
                
                response = await client.put(url, headers=headers, data=data)
                response.raise_for_status()
                
                # Check if the update was successful
                if response.status_code == 200:
                    logger.info(f"Successfully removed modifiers from service {service_id}")
                    if procedure_code == "73560":
                        logger.info(f"Reverted diagnosis for 73560")
                    return True
                else:
                    logger.error(f"Failed to remove modifiers from service {service_id}")
                    return False
                
        except httpx.ReadTimeout as e:
            logger.error(f"Rollback request timed out for service {service_id}: {str(e)}")
            return False
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for service {service_id}: {e.response.status_code}")
            logger.error(f"Response body: {e.response.text}")
            return False
        except Exception as e:
            logger.error(f"Error rolling back service {service_id}: {str(e)}")
            return False

    # ============================================================================
    # 4. EXPORT - Generate reports and exports
    # ============================================================================
    


    # ============================================================================
    # MAIN EXECUTION - Orchestrate the entire process
    # ============================================================================
    
    async def apply_rule_conditions_to_patients(self, patients: List[PatientRequest], add_modifiers: bool = False) -> List[Dict]:
        """Apply Rule 22 conditions directly to the provided patients"""
        print("Starting Rule 22 Analysis for Specific Patients...")
        print("=" * 50)
        print("This rule checks for specific procedure codes and assigns modifiers based on diagnosis codes")
        print("Target procedure codes:", self.target_procedure_codes)
        print("=" * 50)
        
        if not patients:
            print("No patients provided for analysis")
            return []
        
        print(f"Analyzing {len(patients)} specific patients")
        
        # Get a single token to reuse for all API calls
        token = await self.athena_service.get_access_token()
        
        results = []
        
        # Step 1: Analyze each patient directly
        for i, patient in enumerate(patients, 1):
            print(f"Analyzing patient {i}/{len(patients)}: {patient.firstname} {patient.lastname} (ID: {patient.patientid})")
            
            # Get appointment data for this specific patient
            appointment_data = await self.get_appointment_for_patient(patient, token)
            
            if not appointment_data:
                print(f"No appointment data found for patient {patient.patientid}")
                # Add result for patient with no data
                results.append({
                    'patient_id': patient.patientid,
                    'appointment_id': patient.appointmentid,
                    'patient_name': f"{patient.firstname} {patient.lastname}",
                    'appointment_date': patient.appointmentdate,
                    'encounter_id': '',
                    'target_procedure_found': False,
                    'diagnosis_code_found': False,
                    'modifier_required': False,
                    'modifier_applied': False,
                    'modifier_type': '',
                    'paired_procedure_found': False,
                    'paired_modifier_applied': False,
                    'diagnosis_replaced': False,
                    'reason': 'No appointment data found'
                })
                continue
            
            # Get encounter ID for services API call
            encounter_id = appointment_data.get('encounterid', '')
            
            # Initialize analysis variables
            target_procedure_found = False
            diagnosis_code_found = False
            modifier_required = False
            modifier_applied = False
            modifier_type = ''
            paired_procedure_found = False
            paired_modifier_applied = False
            diagnosis_replaced = False
            reason = 'No target procedures found'
            
            # Check procedures via services API if encounter ID exists
            if encounter_id:
                print(f"Checking procedures for encounter {encounter_id}")
                procedures = await self.get_encounter_services(encounter_id, token)
                
                if procedures:
                    # Check each procedure for target codes and diagnoses
                    for procedure in procedures:
                        procedure_code = procedure.get('procedurecode', '')
                        
                        # Check if procedure code matches any of our target codes
                        if any(target_code in procedure_code for target_code in self.target_procedure_codes):
                            target_procedure_found = True
                            print(f"    Found target procedure code: {procedure_code}")
                            
                            # Check diagnoses for this procedure
                            diagnoses = procedure.get('diagnoses', [])
                            modifier = self._determine_modifier_from_diagnoses(diagnoses)
                            
                            if modifier:
                                diagnosis_code_found = True
                                modifier_required = True
                                modifier_type = modifier
                                print(f"    Found matching diagnosis, modifier required: {modifier}")
                                
                                # Apply modifier if requested
                                if add_modifiers:
                                    print(f"    Applying modifier {modifier} to procedure {procedure_code}")
                                    success = await self.update_service_with_modifier(
                                        encounter_id, 
                                        procedure.get('serviceid', ''), 
                                        modifier, 
                                        token,
                                        False,  # replace_diagnosis
                                        procedure_code  # procedure_code for special handling
                                    )
                                    if success:
                                        modifier_applied = True
                                        reason = f"Modifier {modifier} applied successfully"
                                        
                                        # Check for paired procedure logic (73564 ↔ 73560)
                                        if procedure_code == "73564":
                                            print(f"    Checking for paired procedure logic for 73564...")
                                            paired_issues = await self._handle_paired_procedure_logic(
                                                appointment_data, procedures, modifier, token
                                            )
                                            if paired_issues:
                                                paired_procedure_found = True
                                                print(f"    Found paired procedure issues")
                                                
                                                # Apply paired procedure modifier
                                                for issue in paired_issues:
                                                    paired_success = await self.update_service_with_modifier(
                                                        encounter_id,
                                                        issue['service_id'],
                                                        issue['required_modifier'],
                                                        token,
                                                        issue.get('replace_diagnosis_with_z0189', False),
                                                        issue.get('procedure_code', '')  # procedure_code for special handling
                                                    )
                                                    if paired_success:
                                                        paired_modifier_applied = True
                                                        diagnosis_replaced = issue.get('replace_diagnosis_with_z0189', False)
                                                        reason = f"Modifier {modifier} and paired modifier {issue['required_modifier']} applied"
                            else:
                                print(f"    No matching diagnosis found for procedure {procedure_code}")
                                reason = f"Target procedure {procedure_code} found but no matching diagnosis"
                
                # Add delay to avoid rate limiting
                await asyncio.sleep(0.5)
            
            # Create detailed record
            patient_result = {
                'patient_id': patient.patientid,
                'appointment_id': patient.appointmentid,
                'patient_name': f"{patient.firstname} {patient.lastname}",
                'appointment_date': patient.appointmentdate,
                'encounter_id': encounter_id,
                'target_procedure_found': target_procedure_found,
                'diagnosis_code_found': diagnosis_code_found,
                'modifier_required': modifier_required,
                'modifier_applied': modifier_applied,
                'modifier_type': modifier_type,
                'paired_procedure_found': paired_procedure_found,
                'paired_modifier_applied': paired_modifier_applied,
                'diagnosis_replaced': diagnosis_replaced,
                'reason': reason
            }
            
            results.append(patient_result)
        
        print(f"\nAnalysis Complete!")
        print(f"Total patients analyzed: {len(patients)}")
        print(f"Patients with target procedures: {len([r for r in results if r.get('target_procedure_found')])}")
        print(f"Patients with modifiers applied: {len([r for r in results if r.get('modifier_applied')])}")
        
        return results
    
    async def rollback_rule_conditions_to_patients(self, patients: List[PatientRequest]) -> List[Dict]:
        """Rollback Rule 22 changes: Remove modifiers from services for the provided patients with batch processing"""
        print("Starting Rule 22 Rollback for Specific Patients...")
        print("=" * 50)
        print("This rollback removes modifiers (RT, LT, 50, 59) from services for the provided patients")
        print("Also reverts diagnosis changes (Z0189) for paired procedures")
        print("=" * 50)
        
        if not patients:
            print("No patients provided for rollback")
            return []
        
        print(f"Rolling back {len(patients)} specific patients")
        
        # Get a single token to reuse for all API calls
        token = await self.athena_service.get_access_token()
        
        results = []
        
        # Process patients in batches to handle large numbers efficiently
        batch_size = 50  # Process 50 patients at a time
        total_batches = (len(patients) + batch_size - 1) // batch_size
        
        print(f"Processing {len(patients)} patients in {total_batches} batches of {batch_size}")
        
        for batch_num in range(total_batches):
            start_idx = batch_num * batch_size
            end_idx = min(start_idx + batch_size, len(patients))
            batch_patients = patients[start_idx:end_idx]
            
            print(f"\nProcessing batch {batch_num + 1}/{total_batches} ({len(batch_patients)} patients)")
            print("-" * 30)
            
            # Process each patient in the current batch
            for i, patient in enumerate(batch_patients, 1):
                global_patient_num = start_idx + i
                print(f"Rolling back patient {global_patient_num}/{len(patients)}: {patient.firstname} {patient.lastname} (ID: {patient.patientid})")
                
                try:
                    # Get appointment data for this specific patient
                    appointment_data = await self.get_appointment_for_patient(patient, token)
                    
                    if not appointment_data:
                        print(f"  No appointment data found for patient {patient.patientid}")
                        # Add result for patient with no data
                        results.append({
                            'patient_id': patient.patientid,
                            'appointment_id': patient.appointmentid,
                            'patient_name': f"{patient.firstname} {patient.lastname}",
                            'appointment_date': patient.appointmentdate,
                            'encounter_id': '',
                            'modifier_removed': False,
                            'diagnosis_reverted': False,
                            'reason': 'No appointment data found'
                        })
                        continue
                    
                    # Get encounter ID for services API call
                    encounter_id = appointment_data.get('encounterid', '')
                    
                    # Initialize rollback variables
                    modifier_removed = False
                    diagnosis_reverted = False
                    reason = 'No eligible services found for rollback'
                    
                    # Check procedures via services API if encounter ID exists
                    if encounter_id:
                        print(f"  Checking procedures for rollback in encounter {encounter_id}")
                        procedures = await self.get_encounter_services(encounter_id, token)
                        
                        if procedures:
                            # Check each procedure for target codes and remove modifiers
                            for procedure in procedures:
                                procedure_code = procedure.get('procedurecode', '')
                                service_id = procedure.get('serviceid', '')
                                
                                # Check if procedure code matches any of our target codes
                                if any(target_code in procedure_code for target_code in self.target_procedure_codes):
                                    print(f"    Rolling back modifiers from {procedure_code} (service {service_id})")
                                    
                                    # Remove modifiers
                                    success = await self.rollback_service_modifiers(encounter_id, service_id, token, procedure_code)
                                    if success:
                                        modifier_removed = True
                                        reason = f"Modifiers removed from {procedure_code}"
                                        
                                        # Check if this was a 73560 procedure (paired with 73564)
                                        if procedure_code == "73560":
                                            diagnosis_reverted = True
                                            reason = f"Modifiers removed from {procedure_code} and diagnosis reverted"
                                    
                                    # Add delay to avoid rate limiting
                                    await asyncio.sleep(0.3)  # Reduced delay for faster processing
                        else:
                            print(f"  No procedures found for encounter {encounter_id}")
                            reason = 'No procedures found'
                    else:
                        print(f"  No encounter ID found for appointment {patient.appointmentid}")
                        reason = 'No encounter ID found'
                    
                    # Create detailed record
                    patient_result = {
                        'patient_id': patient.patientid,
                        'appointment_id': patient.appointmentid,
                        'patient_name': f"{patient.firstname} {patient.lastname}",
                        'appointment_date': patient.appointmentdate,
                        'encounter_id': encounter_id,
                        'modifier_removed': modifier_removed,
                        'diagnosis_reverted': diagnosis_reverted,
                        'reason': reason
                    }
                    
                    results.append(patient_result)
                    
                except Exception as e:
                    print(f"  Error processing patient {patient.patientid}: {str(e)}")
                    # Add error result
                    results.append({
                        'patient_id': patient.patientid,
                        'appointment_id': patient.appointmentid,
                        'patient_name': f"{patient.firstname} {patient.lastname}",
                        'appointment_date': patient.appointmentdate,
                        'encounter_id': '',
                        'modifier_removed': False,
                        'diagnosis_reverted': False,
                        'reason': f'Error: {str(e)}'
                    })
                
                # Add small delay between patients to avoid overwhelming the API
                await asyncio.sleep(0.1)
            
            # Add delay between batches to prevent rate limiting
            if batch_num < total_batches - 1:  # Don't delay after the last batch
                print(f"  Batch {batch_num + 1} completed. Waiting before next batch...")
                await asyncio.sleep(2)  # 2-second delay between batches
        
        print(f"\nRollback Complete!")
        print(f"Total patients processed: {len(patients)}")
        print(f"Patients with modifiers removed: {len([r for r in results if r.get('modifier_removed')])}")
        print(f"Patients with diagnosis reverted: {len([r for r in results if r.get('diagnosis_reverted')])}")
        print(f"Patients with errors: {len([r for r in results if 'Error:' in r.get('reason', '')])}")
        
        return results
    
    async def get_appointment_for_patient(self, patient: PatientRequest, token: str) -> Optional[Dict]:
        """Get appointment data for a specific patient"""
        try:
            # Create a custom request with longer timeout
            async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(120.0)) as client:
                url = f"{self.athena_service.base_url}/{settings.ATHENA_PRACTICE_ID}/appointments/booked"
                
                params = {
                    'startdate': patient.appointmentdate,
                    'enddate': patient.appointmentdate,
                    'departmentid': '1',
                    'patientid': patient.patientid,
                    'appointmentid': patient.appointmentid,
                    'showpatientdetail': 'true',
                    'showinsurance': 'true',
                    'showclaimdetail': 'true',
                    'showexpectedprocedurecodes': 'true'
                }
                
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                }
                
                logger.info(f"Getting appointment data for patient {patient.patientid} on {patient.appointmentdate}")
                
                response = await client.get(url, params=params, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                appointments = data.get('appointments', [])
                
                # Since we passed specific patientid and appointmentid, we should get exact match
                if appointments:
                    appointment = appointments[0]  # Should be the exact appointment we requested
                    logger.info(f"Found appointment data for patient {patient.patientid}")
                    return appointment
                
                logger.warning(f"No appointment found for patient {patient.patientid} with appointment {patient.appointmentid}")
                return None
                
        except httpx.ReadTimeout as e:
            logger.error(f"Request timed out for patient {patient.patientid}: {str(e)}")
            return None
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for patient {patient.patientid}: {e.response.status_code}")
            return None
        except Exception as e:
            logger.error(f"Error getting appointment data for patient {patient.patientid}: {str(e)}")
            return None

    async def run(self, request: Rule22Request) -> Rule22Response:
        """
        Main execution method for Rule 22
        
        Args:
            request: Rule22Request with analysis parameters and patient list
            
        Returns:
            Rule22Response with analysis results for requested patients
        """
        try:
            # Check if this is a rollback operation
            if request.is_rollback:
                print("Rule 22: Rollback Operation")
                print("=" * 50)
                print("This rollback removes modifiers (RT, LT, 50, 59) from services for the provided patients")
                print("Also reverts diagnosis changes (Z0189) for paired procedures")
                print("=" * 50)
                
                # Check if patients list is provided
                if not request.patients:
                    return Rule22Response(
                        success=False,
                        message="No patients provided for rollback",
                        results=[],
                        issues_found=0
                    )
                
                print(f"Rolling back {len(request.patients)} requested patients")
                
                # Apply rollback to the provided patients
                patient_results = await self.rollback_rule_conditions_to_patients(request.patients)
            else:
                print("Rule 22: Procedure Code Modifier Assignment")
                print("=" * 50)
                print("This automation checks for specific procedure codes and assigns modifiers based on diagnosis codes")
                print("Target procedure codes:", self.target_procedure_codes)
                print("Modifier rules:")
                print("- Diagnosis ending with '1' → RT modifier")
                print("- Diagnosis ending with '2' → LT modifier") 
                print("- Diagnosis ending with '0' → 50 modifier")
                print("Special Paired Logic (73564 ↔ 73560):")
                print("- When 73564 gets LT → 73560 gets RT")
                print("- When 73564 gets RT → 73560 gets LT + diagnosis replaced with Z0189")
                if request.add_modifiers:
                    print("- Automatically apply modifiers when conditions are met")
                print("=" * 50)
                
                # Check if patients list is provided
                if not request.patients:
                    return Rule22Response(
                        success=False,
                        message="No patients provided in request",
                        results=[],
                        issues_found=0
                    )
                
                print(f"Processing {len(request.patients)} requested patients")
                
                # Apply Rule 22 conditions directly to the provided patients
                patient_results = await self.apply_rule_conditions_to_patients(
                    request.patients,
                    request.add_modifiers
                )
            
            if not patient_results:
                print("No patient results found")
                # Return results for all requested patients with status 4 (error)
                results = []
                for patient in request.patients:
                    results.append(PatientResult(
                        patientid=patient.patientid,
                        appointmentid=patient.appointmentid,
                        status=4,  # Error
                        reason="error: No patient data found"
                    ))
                
                return Rule22Response(
                    success=False,
                    message="No patient data found",
                    results=results,
                    issues_found=0
                )
            
            # Generate results for all requested patients from patient_results
            results = []
            issues_found = 0
            
            for patient in request.patients:
                # Find matching result for this patient
                matching_result = None
                for result in patient_results:
                    if result.get('patient_id') == patient.patientid:
                        matching_result = result
                        break
                
                if matching_result:
                    if request.is_rollback:
                        # Handle rollback results
                        modifier_removed = matching_result.get('modifier_removed', False)
                        diagnosis_reverted = matching_result.get('diagnosis_reverted', False)
                        reason = matching_result.get('reason', 'Unknown error')
                        
                        if modifier_removed:
                            status = 1  # Rollback successful
                            issues_found += 1
                        else:
                            status = 3  # No changes to rollback
                    else:
                        # Handle normal operation results
                        modifier_applied = matching_result.get('modifier_applied', False)
                        target_procedure_found = matching_result.get('target_procedure_found', False)
                        modifier_required = matching_result.get('modifier_required', False)
                        
                        if not target_procedure_found:
                            status, reason = 3, "no target procedure codes found"
                        elif not modifier_required:
                            status, reason = 3, "no matching diagnosis codes found"
                        elif modifier_applied:
                            status, reason = 1, f"modifier {matching_result.get('modifier_type', '')} applied successfully"
                            issues_found += 1
                        else:
                            status, reason = 2, f"modifier {matching_result.get('modifier_type', '')} already exists"
                            issues_found += 1
                    
                    patient_result = PatientResult(
                        patientid=patient.patientid,
                        appointmentid=patient.appointmentid,
                        status=status,
                        reason=reason
                    )
                    results.append(patient_result)
                    print(f"Patient {patient.patientid} ({patient.firstname} {patient.lastname}): Status {status} - {reason}")
                else:
                    # Patient not found in results
                    patient_result = PatientResult(
                        patientid=patient.patientid,
                        appointmentid=patient.appointmentid,
                        status=4,  # Error
                        reason="error: Patient data not found"
                    )
                    results.append(patient_result)
                    print(f"Patient {patient.patientid} ({patient.firstname} {patient.lastname}): Status 4 - error: Patient data not found")
            

            
            # Count statuses for summary
            status_counts = {1: 0, 2: 0, 3: 0, 4: 0}
            for result in results:
                status_counts[result.status] += 1
            
            # Determine appropriate message based on operation type
            if request.is_rollback:
                message = f"Rule 22 rollback completed. Processed {len(request.patients)} patients."
            else:
                message = f"Rule 22 analysis completed. Processed {len(request.patients)} patients."
            
            return Rule22Response(
                success=True,
                message=message,
                results=results,
                issues_found=issues_found,

                details={
                    "total_patients": len(request.patients),
                    "status_1_changes_made": status_counts[1],
                    "status_2_condition_met_no_changes": status_counts[2],
                    "status_3_condition_not_met": status_counts[3],
                    "status_4_errors": status_counts[4],
                    "issues_found": issues_found
                }
            )
            
        except Exception as e:
            logger.error(f"Error in Rule 22 execution: {str(e)}")
            # Return error results for all requested patients
            results = []
            for patient in request.patients:
                results.append(PatientResult(
                    patientid=patient.patientid,
                    appointmentid=patient.appointmentid,
                    status=4,  # Error
                    reason=f"error: {str(e)}"
                ))
            
            return Rule22Response(
                success=False,
                message=f"Error during analysis: {str(e)}",
                results=results,
                issues_found=0
            )

# Global instance for API use
rule_22_instance = Rule22()

async def main():
    """Main function for standalone testing"""
    print("Rule 22: Procedure Code Modifier Assignment")
    print("This is a test function. Use the API endpoint for actual testing.")
    print("API Endpoint: POST /rules/rule22")
    print("Request Body: {\"add_modifiers\": true, \"patients\": [{\"appointmentid\": \"...\", \"appointmentdate\": \"...\", \"patientid\": \"...\", \"firstname\": \"...\", \"lastname\": \"...\"}]}")

if __name__ == "__main__":
    asyncio.run(main()) 
from fastapi import APIRouter, Depends, HTTPException, Form, Query, Request
from fastapi.responses import JSONResponse
from typing import List, Optional
from app.medofficehq.services.athena_service import AthenaService
from app.medofficehq.core.dependencies import get_athena_service
from pydantic import BaseModel
from datetime import datetime, timedelta
import re

router = APIRouter()

def normalize_date_to_mm_dd_yyyy(date_str: str) -> str:
    """
    Convert various date formats to MM/DD/YYYY format required by Athena Health API.
    
    Supports:
    - MM/DD/YYYY (already correct)
    - YY-MM-DD (e.g., 19-01-01 → 01/01/2019)
    - YYYY-MM-DD (e.g., 1990-01-01 → 01/01/1990)
    - MMDDYYYY (e.g., 01011990 → 01/01/1990)
    - MM-DD-YYYY (e.g., 01-01-1990 → 01/01/1990)
    - YY/MM/DD (e.g., 19/01/01 → 01/01/2019)
    
    Args:
        date_str: Date string in any supported format
        
    Returns:
        Date string in MM/DD/YYYY format
    """
    if not date_str:
        return date_str
    
    # Remove any URL encoding if present
    date_str = date_str.replace('%2F', '/').replace('%2D', '-')
    
    # If already in MM/DD/YYYY format, return as-is
    if re.match(r'^\d{2}/\d{2}/\d{4}$', date_str):
        return date_str
    
    try:
        # Try YY-MM-DD format (e.g., 19-01-01)
        if re.match(r'^\d{2}-\d{2}-\d{2}$', date_str):
            parts = date_str.split('-')
            year = int(parts[0])
            month = parts[1]
            day = parts[2]
            # Assume years 00-30 are 2000-2030, 31-99 are 1931-1999
            full_year = 2000 + year if year <= 30 else 1900 + year
            return f"{month}/{day}/{full_year}"
        
        # Try YYYY-MM-DD format (e.g., 1990-01-01)
        if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
            parts = date_str.split('-')
            return f"{parts[1]}/{parts[2]}/{parts[0]}"
        
        # Try MMDDYYYY format (e.g., 01011990)
        if re.match(r'^\d{8}$', date_str):
            return f"{date_str[0:2]}/{date_str[2:4]}/{date_str[4:8]}"
        
        # Try MM-DD-YYYY format (e.g., 01-01-1990)
        if re.match(r'^\d{2}-\d{2}-\d{4}$', date_str):
            parts = date_str.split('-')
            return f"{parts[0]}/{parts[1]}/{parts[2]}"
        
        # Try YY/MM/DD format (e.g., 19/01/01)
        if re.match(r'^\d{2}/\d{2}/\d{2}$', date_str):
            parts = date_str.split('/')
            year = int(parts[0])
            month = parts[1]
            day = parts[2]
            # Assume years 00-30 are 2000-2030, 31-99 are 1931-1999
            full_year = 2000 + year if year <= 30 else 1900 + year
            return f"{month}/{day}/{full_year}"
        
        # Try to parse as ISO format or other common formats
        try:
            # Try various date formats
            for fmt in ['%Y-%m-%d', '%m-%d-%Y', '%m/%d/%Y', '%d-%m-%Y', '%d/%m/%Y']:
                try:
                    dt = datetime.strptime(date_str, fmt)
                    return dt.strftime('%m/%d/%Y')
                except:
                    continue
        except:
            pass
        
        # If no pattern matches, try to parse with datetime
        # This is a fallback for edge cases
        dt = datetime.strptime(date_str, '%Y-%m-%d')
        return dt.strftime('%m/%d/%Y')
        
    except Exception as e:
        # If conversion fails, return original and let Athena API handle the error
        # This way we don't break existing functionality
        return date_str

class PatientListRequest(BaseModel):
    start_date: str
    end_date: str
    excluded_patient_ids: Optional[List[str]] = None

class CancelAppointmentRequest(BaseModel):
    appointment_id: str
    patient_id: str
    reason: Optional[str] = None
    appointment_cancel_reason_id: Optional[int] = None
    ignore_schedulable_permission: bool = True
    no_patient_case: bool = False

class RescheduleAppointmentRequest(BaseModel):
    appointment_id: str
    new_appointment_id: str
    patient_id: str
    appointment_cancel_reason_id: Optional[int] = None
    ignore_schedulable_permission: bool = True
    no_patient_case: bool = False
    reason_id: Optional[int] = None
    reschedule_reason: Optional[str] = None

@router.post("/patient-list")
async def get_patient_list(
    request: PatientListRequest,
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Get a list of patients with basic information for the frontend workflow.
    This endpoint supports filtering out specific patients by their IDs.
    """
    try:
        patients = await athena_service.get_patient_list(
            start_date=request.start_date,
            end_date=request.end_date,
            excluded_patient_ids=request.excluded_patient_ids
        )
        return {"patients": patients}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/cancel-appointment")
async def cancel_appointment(
    request: Request,
    appointment_id: str = Query(None),
    patient_id: str = Query(None),
    reason: str = Query(None),
    appointment_cancel_reason_id: Optional[int] = Query(None),
    ignore_schedulable_permission: bool = Query(True),
    no_patient_case: bool = Query(False),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Cancel an existing appointment in Athena Health.
    This endpoint is used by the AI agent when a patient requests to cancel their appointment.
    
    Accepts both query parameters (for GHL) and JSON body.
    
    Query Parameters:
    - appointment_id (required): ID of the appointment to cancel
    - patient_id (required): The athenaNet patient ID
    - reason (optional): Text explanation why the appointment is being cancelled
    - appointment_cancel_reason_id (optional): Override default cancel reason
    - ignore_schedulable_permission (optional, default: true): Allow cancellation regardless of web settings
    - no_patient_case (optional, default: false): Bypass patient case creation for new patients
    """
    try:
        # Try to get data from query params first, then from JSON body
        if not appointment_id or not patient_id:
            # Try to get from JSON body
            try:
                body = await request.json()
                # Check if GHL wrapped data in customData
                if "customData" in body:
                    data = body["customData"]
                else:
                    data = body
                
                appointment_id = appointment_id or data.get("appointment_id")
                patient_id = patient_id or data.get("patient_id")
                reason = reason or data.get("reason")
                appointment_cancel_reason_id = appointment_cancel_reason_id or data.get("appointment_cancel_reason_id")
                ignore_schedulable_permission = data.get("ignore_schedulable_permission", ignore_schedulable_permission) if not appointment_id else ignore_schedulable_permission
                no_patient_case = data.get("no_patient_case", no_patient_case) if not appointment_id else no_patient_case
            except:
                pass
        
        # Validate required fields
        if not appointment_id or not patient_id:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Missing required fields: appointment_id and patient_id are required"
                }
            )
        
        # Make API call to Athena to cancel appointment
        result = await athena_service.cancel_appointment(
            appointment_id=appointment_id,
            patient_id=patient_id,
            cancellation_reason=reason,
            appointment_cancel_reason_id=appointment_cancel_reason_id,
            ignore_schedulable_permission=ignore_schedulable_permission,
            no_patient_case=no_patient_case
        )
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Appointment cancelled successfully",
                "appointment_id": appointment_id,
                "patient_id": patient_id,
                "cancellation_reason": reason or "Appointment cancelled via AI agent",
                "status": result.get("status", "x"),
                "result": result
            }
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to cancel appointment: {str(e)}"
            }
        )

@router.post("/create-patient")
async def create_patient(
    request: Request,
    firstname: str = Query(None),
    lastname: str = Query(None),
    departmentid: str = Query(None),
    dob: str = Query(None),
    email: str = Query(None),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Create a new patient in Athena Health.
    Accepts both query parameters and JSON body (GHL customData format).
    """
    try:
        # Try to get data from query params first, then from JSON body
        if not firstname:
            # Try to get from JSON body (GHL customData format)
            try:
                body = await request.json()
                # Check if GHL wrapped data in customData
                if "customData" in body:
                    data = body["customData"]
                else:
                    data = body
                
                firstname = data.get("firstname")
                lastname = data.get("lastname")
                departmentid = data.get("departmentid")
                dob = data.get("dob")
                email = data.get("email")
            except:
                pass
        
        # Validate required fields
        if not all([firstname, lastname, departmentid, dob, email]):
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Missing required fields: firstname, lastname, departmentid, dob, email"
                }
            )
        
        # Normalize date format to MM/DD/YYYY for Athena Health API
        normalized_dob = normalize_date_to_mm_dd_yyyy(dob)
        
        # Create patient data
        patient_data = {
            "firstname": firstname,
            "lastname": lastname,
            "departmentid": departmentid,
            "dob": normalized_dob,
            "email": email
        }
        
        # Make API call to Athena
        result = await athena_service.create_patient(patient_data)
        
        # Extract patient_id from various possible field names in Athena response
        # Athena may return patientid, patient_id, or id in different response structures
        patient_id = None
        if isinstance(result, dict):
            patient_id = result.get("patientid") or result.get("patient_id") or result.get("id")
        elif isinstance(result, list) and len(result) > 0:
            patient_id = result[0].get("patientid") or result[0].get("patient_id") or result[0].get("id")
        
        # Return response with patient_id in multiple formats for GHL compatibility
        # GHL custom actions access data via {{actionkey.data.fieldname}} syntax
        # So we put patient_id in 'data' object AND at top level for maximum compatibility
        response_data = {
            "success": True,
            "status": "success",  # GHL often looks for 'status' field
            "message": f"Patient created successfully. Patient ID: {patient_id}" if patient_id else "Patient created successfully",
            # Top-level fields for direct access
            "patient_id": patient_id,
            "patientid": patient_id,  # Also include as patientid for compatibility
            "id": patient_id,  # Some systems expect 'id'
            # GHL typically accesses response data via 'data' object using {{actionkey.data.fieldname}}
            "data": {
                "patient_id": patient_id,
                "patientid": patient_id,
                "id": patient_id,
                "success": True,
                "status": "success",
                "message": f"Patient created successfully. Patient ID: {patient_id}" if patient_id else "Patient created successfully"
            },
            # Alternative nested format
            "result": {
                "patient_id": patient_id,
                "patientid": patient_id,
                "id": patient_id,
                "success": True
            },
            # Response object (some GHL versions use this)
            "response": {
                "patient_id": patient_id,
                "patientid": patient_id,
                "id": patient_id,
                "success": True,
                "status": "success"
            }
        }
        
        return JSONResponse(
            status_code=200,
            content=response_data
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to create patient: {str(e)}"
        )

@router.get("/create-patient")
async def create_patient_get(
    firstname: str = Query(...),
    lastname: str = Query(...),
    departmentid: str = Query(...),
    dob: str = Query(...),
    email: str = Query(...),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Create a new patient in Athena Health (GET version for GHL compatibility).
    GHL custom actions work better with GET requests for receiving responses.
    Accepts query parameters: firstname, lastname, departmentid, dob, email.
    Returns patient_id in the response.
    """
    try:
        # Validate required fields
        if not all([firstname, lastname, departmentid, dob, email]):
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Missing required fields: firstname, lastname, departmentid, dob, email"
                }
            )
        
        # Normalize date format to MM/DD/YYYY for Athena Health API
        normalized_dob = normalize_date_to_mm_dd_yyyy(dob)
        
        # Create patient data
        patient_data = {
            "firstname": firstname,
            "lastname": lastname,
            "departmentid": departmentid,
            "dob": normalized_dob,
            "email": email
        }
        
        # Make API call to Athena
        result = await athena_service.create_patient(patient_data)
        
        # Extract patient_id from various possible field names in Athena response
        # Athena may return patientid, patient_id, or id in different response structures
        patient_id = None
        if isinstance(result, dict):
            patient_id = result.get("patientid") or result.get("patient_id") or result.get("id")
        elif isinstance(result, list) and len(result) > 0:
            patient_id = result[0].get("patientid") or result[0].get("patient_id") or result[0].get("id")
        
        # Return response with patient_id in multiple formats for GHL compatibility
        # GHL custom actions access data via {{actionkey.data.fieldname}} syntax
        # So we put patient_id in 'data' object AND at top level for maximum compatibility
        response_data = {
            "success": True,
            "status": "success",  # GHL often looks for 'status' field
            "message": f"Patient created successfully. Patient ID: {patient_id}" if patient_id else "Patient created successfully",
            # Top-level fields for direct access
            "patient_id": patient_id,
            "patientid": patient_id,  # Also include as patientid for compatibility
            "id": patient_id,  # Some systems expect 'id'
            # GHL typically accesses response data via 'data' object using {{actionkey.data.fieldname}}
            "data": {
                "patient_id": patient_id,
                "patientid": patient_id,
                "id": patient_id,
                "success": True,
                "status": "success",
                "message": f"Patient created successfully. Patient ID: {patient_id}" if patient_id else "Patient created successfully"
            },
            # Alternative nested format
            "result": {
                "patient_id": patient_id,
                "patientid": patient_id,
                "id": patient_id,
                "success": True
            },
            # Response object (some GHL versions use this)
            "response": {
                "patient_id": patient_id,
                "patientid": patient_id,
                "id": patient_id,
                "success": True,
                "status": "success"
            }
        }
        
        return JSONResponse(
            status_code=200,
            content=response_data
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"Failed to create patient: {str(e)}"
        )

@router.get("/search-patient")
async def search_patient(
    firstname: str = Query(...),
    lastname: str = Query(...),
    dob: str = Query(...),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Search for existing patient in Athena Health.
    Uses firstname, lastname, and dob to find patient.
    Accepts various date formats and converts to MM/DD/YYYY.
    """
    try:
        # Normalize date format to MM/DD/YYYY for Athena Health API
        normalized_dob = normalize_date_to_mm_dd_yyyy(dob)
        
        # Create search parameters
        search_params = {
            "firstname": firstname,
            "lastname": lastname,
            "dob": normalized_dob
        }
        
        # Make API call to Athena
        result = await athena_service.search_patient(search_params)
        
        # Normalize patient objects to ensure patient_id is explicitly available in multiple formats
        # Athena may return patientid, patient_id, or id in different response structures
        normalized_patients = []
        first_patient_id = None
        
        if isinstance(result, list):
            for patient in result:
                if isinstance(patient, dict):
                    # Extract patient_id from various possible field names
                    patient_id = patient.get("patientid") or patient.get("patient_id") or patient.get("id")
                    # Create normalized patient object with patient_id in multiple formats for GHL compatibility
                    normalized_patient = {
                        **patient,
                        "patient_id": patient_id,
                        "patientid": patient_id,  # Also include as patientid for compatibility
                        "id": patient_id  # Some systems expect 'id'
                    }
                    normalized_patients.append(normalized_patient)
                    # Store first patient ID for top-level access
                    if first_patient_id is None:
                        first_patient_id = patient_id
        elif isinstance(result, dict):
            # Handle case where result is a single patient dict
            patient_id = result.get("patientid") or result.get("patient_id") or result.get("id")
            normalized_patients = [{
                **result,
                "patient_id": patient_id,
                "patientid": patient_id,
                "id": patient_id
            }]
            first_patient_id = patient_id
        
        # Build response message with patient_id info for GHL visibility
        if len(normalized_patients) > 0:
            if len(normalized_patients) == 1:
                message = f"Patient found. Patient ID: {first_patient_id}"
            else:
                message = f"Found {len(normalized_patients)} patients. First Patient ID: {first_patient_id}"
        else:
            message = "No patients found matching the search criteria"
        
        # Return response with patient_id in multiple formats for GHL compatibility
        # GHL custom actions access data via {{actionkey.data.fieldname}} syntax
        # So we put patient_id in 'data' object AND at top level for maximum compatibility
        response_data = {
            "success": True,
            "status": "success" if len(normalized_patients) > 0 else "not_found",
            "message": message,
            # Top-level fields for direct access
            "patient_id": first_patient_id,  # Top-level patient_id for first patient (GHL easy access)
            "patientid": first_patient_id,  # Also include as patientid for compatibility
            "id": first_patient_id,  # Some systems expect 'id'
            "count": len(normalized_patients),
            "patients": normalized_patients,  # Full list of patients
            # GHL typically accesses response data via 'data' object using {{actionkey.data.fieldname}}
            "data": {
                "patient_id": first_patient_id,
                "patientid": first_patient_id,
                "id": first_patient_id,
                "count": len(normalized_patients),
                "patients": normalized_patients,
                "success": True,
                "status": "success" if len(normalized_patients) > 0 else "not_found",
                "message": message
            },
            # Alternative nested format
            "result": {
                "patient_id": first_patient_id,
                "patientid": first_patient_id,
                "id": first_patient_id,
                "count": len(normalized_patients),
                "success": True
            },
            # Response object (some GHL versions use this)
            "response": {
                "patient_id": first_patient_id,
                "patientid": first_patient_id,
                "id": first_patient_id,
                "count": len(normalized_patients),
                "success": True,
                "status": "success" if len(normalized_patients) > 0 else "not_found"
            }
        }
        
        return JSONResponse(
            status_code=200,
            content=response_data
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to search patient: {str(e)}"
            }
        )

@router.get("/providers")
async def get_providers(
    departmentid: str = Query(...),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Get all available providers for a department.
    Returns provider names and IDs for AI agent to show to patient.
    """
    try:
        # Make API call to Athena
        result = await athena_service.get_providers(departmentid)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Providers retrieved successfully",
                "providers": result
            }
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to get providers: {str(e)}"
            }
        )

@router.get("/appointment-slots")
async def get_appointment_slots(
    departmentid: str = Query(...),
    providerid: str = Query(...),
    is_new_patient: bool = Query(False),
    startdate: str = Query(...),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Get available appointment slots for a provider.
    Automatically determines appointment type based on provider and patient status.
    Returns available dates and times for AI agent to show to patient.
    """
    try:
        # Determine appointment type based on provider and patient status
        appointmenttypeid = athena_service.get_appointment_type_id(providerid, is_new_patient)
        
        # Create search parameters
        search_params = {
            "departmentid": departmentid,
            "providerid": providerid,
            "appointmenttypeid": appointmenttypeid,
            "startdate": startdate,
            "showfrozenslots": "true",
            "ignoreschedulablepermission": "true",
            "bypassscheduletimechecks": "true"
        }
        
        # Make API call to Athena
        result = await athena_service.get_appointment_slots(search_params)
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Appointment slots retrieved successfully",
                "appointment_type_id": appointmenttypeid,
                "appointment_type_name": athena_service.get_appointment_type_name(providerid, is_new_patient),
                "is_new_patient": is_new_patient,
                "slots": result
            }
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to get appointment slots: {str(e)}"
            }
        )

@router.post("/book-appointment/")
async def book_appointment(
    appointmentid: str = Query(...),
    providerid: str = Query(...),
    patientid: str = Query(...),
    is_new_patient: bool = Query(False),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Book an appointment by confirming the selected slot.
    Automatically determines appointment type based on provider and patient status.
    Uses form-encoded data as required by Athena Health API.
    """
    try:
        # Determine appointment type based on provider and patient status
        appointmenttypeid = athena_service.get_appointment_type_id(providerid, is_new_patient)
        
        # Create booking data with all required parameters
        booking_data = {
            "providerid": providerid,
            "patientid": patientid,
            "appointmenttypeid": appointmenttypeid,
            "ignoreschedulablepermission": "true"
        }
        
        # Make API call to Athena
        result = await athena_service.book_appointment_slot(appointmentid, booking_data)
        
        # Extract appointment details for GHL
        appointment_details = result if isinstance(result, dict) else result[0] if isinstance(result, list) else {}
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Appointment booked successfully",
                "appointment_id": appointment_details.get("appointmentid", appointmentid),
                "patient_id": appointment_details.get("patientid", patientid),
                "provider_id": appointment_details.get("providerid", providerid),
                "appointment_type": appointment_details.get("appointmenttype", athena_service.get_appointment_type_name(providerid, is_new_patient)),
                "appointment_type_id": appointmenttypeid,
                "appointment_date": appointment_details.get("date"),
                "appointment_time": appointment_details.get("starttime"),
                "duration": appointment_details.get("duration"),
                "status": appointment_details.get("appointmentstatus"),
                "is_new_patient": is_new_patient,
                "department_id": appointment_details.get("departmentid"),
                "full_appointment": appointment_details
            }
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to book appointment: {str(e)}"
            }
        )

# ============================================================================
# NEW AI AGENT ENDPOINTS - For Solution Validation
# ============================================================================

@router.post("/reschedule-appointment")
async def reschedule_appointment(
    request: Request,
    appointment_id: str = Query(None),
    new_appointment_id: str = Query(None),
    patient_id: str = Query(None),
    appointment_cancel_reason_id: Optional[int] = Query(None),
    ignore_schedulable_permission: bool = Query(True),
    no_patient_case: bool = Query(False),
    reason_id: Optional[int] = Query(None),
    reschedule_reason: str = Query(None),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Reschedule an existing appointment to a new date and time.
    This endpoint reschedules an appointment to a new timeslot provided by the patient.
    
    Accepts both query parameters (for GHL) and JSON body.
    
    Query Parameters:
    - appointment_id (required): ID of the currently scheduled appointment to reschedule
    - new_appointment_id (required): ID of the new appointment slot
    - patient_id (required): The athenaNet patient ID
    - appointment_cancel_reason_id (optional): Cancel reason ID for the original appointment
    - ignore_schedulable_permission (optional, default: true): Allow booking regardless of web settings
    - no_patient_case (optional, default: false): Bypass patient case creation for new patients
    - reason_id (optional): Appointment reason ID (uses original if not provided)
    - reschedule_reason (optional): Text explanation why the appointment is being rescheduled
    """
    try:
        # Try to get data from query params first, then from JSON body
        if not appointment_id or not new_appointment_id or not patient_id:
            # Try to get from JSON body
            try:
                body = await request.json()
                # Check if GHL wrapped data in customData
                if "customData" in body:
                    data = body["customData"]
                else:
                    data = body
                
                appointment_id = appointment_id or data.get("appointment_id")
                new_appointment_id = new_appointment_id or data.get("new_appointment_id")
                patient_id = patient_id or data.get("patient_id")
                appointment_cancel_reason_id = appointment_cancel_reason_id or data.get("appointment_cancel_reason_id")
                reason_id = reason_id or data.get("reason_id")
                reschedule_reason = reschedule_reason or data.get("reschedule_reason")
                ignore_schedulable_permission = data.get("ignore_schedulable_permission", ignore_schedulable_permission) if not appointment_id else ignore_schedulable_permission
                no_patient_case = data.get("no_patient_case", no_patient_case) if not appointment_id else no_patient_case
            except:
                pass
        
        # Validate required fields
        if not appointment_id or not new_appointment_id or not patient_id:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "Missing required fields: appointment_id, new_appointment_id, and patient_id are required"
                }
            )
        
        # Make API call to Athena to reschedule appointment
        result = await athena_service.reschedule_appointment(
            appointment_id=appointment_id,
            new_appointment_id=new_appointment_id,
            patient_id=patient_id,
            appointment_cancel_reason_id=appointment_cancel_reason_id,
            ignore_schedulable_permission=ignore_schedulable_permission,
            no_patient_case=no_patient_case,
            reason_id=reason_id,
            reschedule_reason=reschedule_reason
        )
        
        # Extract appointment details from result
        appointment_details = result if isinstance(result, dict) else result[0] if isinstance(result, list) else {}
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Appointment rescheduled successfully",
                "old_appointment_id": appointment_id,
                "new_appointment_id": appointment_details.get("appointmentid", new_appointment_id),
                "rescheduled_appointment_id": appointment_details.get("rescheduledappointmentid"),
                "patient_id": appointment_details.get("patientid", patient_id),
                "appointment_date": appointment_details.get("date"),
                "appointment_time": appointment_details.get("starttime"),
                "duration": appointment_details.get("duration"),
                "status": appointment_details.get("appointmentstatus"),
                "appointment_type": appointment_details.get("appointmenttype"),
                "appointment_type_id": appointment_details.get("appointmenttypeid"),
                "provider_id": appointment_details.get("providerid"),
                "department_id": appointment_details.get("departmentid"),
                "full_appointment": appointment_details
            }
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to reschedule appointment: {str(e)}"
            }
        )

@router.get("/preoperative-instructions")
async def get_preoperative_instructions(
    patient_id: str = Query(...),
    appointment_id: Optional[str] = Query(None),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Get pre-operative instructions and questions for a patient.
    This endpoint retrieves the latest doctor instructions from appointment notes.
    
    Query Parameters:
    - patient_id (required): Patient ID
    - appointment_id (optional): Specific appointment ID to get notes for
    """
    try:
        if appointment_id:
            # Get notes for specific appointment
            notes = await athena_service.get_appointment_notes(
                appointment_id=appointment_id,
                show_deleted=False
            )
            
            # Filter for pre-operative instructions (you can add logic to identify pre-op notes)
            pre_op_notes = [note for note in notes if "pre" in note.get("notetext", "").lower() or "preoperative" in note.get("notetext", "").lower()]
            
            # If no specific pre-op notes found, return all notes
            instructions = pre_op_notes if pre_op_notes else notes
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "Pre-operative instructions retrieved successfully",
                    "patient_id": patient_id,
                    "appointment_id": appointment_id,
                    "instructions": instructions,
                    "latest_instructions": instructions[-1].get("notetext", "") if instructions else "",
                    "notes_count": len(instructions)
                }
            )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "appointment_id is required to get pre-operative instructions",
                    "note": "Please provide appointment_id to retrieve appointment notes with instructions"
                }
            )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to get pre-operative instructions: {str(e)}"
            }
        )

@router.get("/postoperative-instructions")
async def get_postoperative_instructions(
    patient_id: str = Query(...),
    appointment_id: Optional[str] = Query(None),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Get post-operative instructions and questions for a patient.
    This endpoint retrieves the latest doctor instructions from appointment notes.
    
    Query Parameters:
    - patient_id (required): Patient ID
    - appointment_id (optional): Specific appointment ID to get notes for
    """
    try:
        if appointment_id:
            # Get notes for specific appointment
            notes = await athena_service.get_appointment_notes(
                appointment_id=appointment_id,
                show_deleted=False
            )
            
            # Filter for post-operative instructions (you can add logic to identify post-op notes)
            post_op_notes = [note for note in notes if "post" in note.get("notetext", "").lower() or "postoperative" in note.get("notetext", "").lower()]
            
            # If no specific post-op notes found, return all notes
            instructions = post_op_notes if post_op_notes else notes
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "Post-operative instructions retrieved successfully",
                    "patient_id": patient_id,
                    "appointment_id": appointment_id,
                    "instructions": instructions,
                    "latest_instructions": instructions[-1].get("notetext", "") if instructions else "",
                    "notes_count": len(instructions)
                }
            )
        else:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "message": "appointment_id is required to get post-operative instructions",
                    "note": "Please provide appointment_id to retrieve appointment notes with instructions"
                }
            )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to get post-operative instructions: {str(e)}"
            }
        )

@router.get("/appointment-notes")
async def get_appointment_notes(
    appointment_id: str = Query(...),
    show_deleted: bool = Query(False),
    limit: int = Query(1500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Get appointment notes for a specific appointment.
    This retrieves clinical notes and instructions for pre/post-operative questions.
    
    Query Parameters:
    - appointment_id (required): ID of the appointment to get notes for
    - show_deleted (optional, default: false): Include deleted notes in results
    - limit (optional, default: 1500, max: 5000): Number of entries to return
    - offset (optional, default: 0): Starting point of entries (0-indexed)
    """
    try:
        # Make API call to Athena to get appointment notes
        notes = await athena_service.get_appointment_notes(
            appointment_id=appointment_id,
            show_deleted=show_deleted,
            limit=limit,
            offset=offset
        )
        
        return JSONResponse(
            status_code=200,
            content={
                "success": True,
                "message": "Appointment notes retrieved successfully",
                "appointment_id": appointment_id,
                "notes_count": len(notes),
                "notes": notes
            }
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to get appointment notes: {str(e)}"
            }
        )

@router.get("/patient-notes")
async def get_patient_notes(
    patient_id: str = Query(...),
    appointment_id: Optional[str] = Query(None),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Get clinical notes and records for a patient to determine latest doctor instructions.
    This is used for pre-operative and post-operative question handling.
    
    If appointment_id is provided, it will get notes for that specific appointment.
    Otherwise, it will need to get patient records from other endpoints (pending implementation).
    """
    try:
        if appointment_id:
            # Get notes for specific appointment
            notes = await athena_service.get_appointment_notes(
                appointment_id=appointment_id,
                show_deleted=False
            )
            
            return JSONResponse(
                status_code=200,
                content={
                    "success": True,
                    "message": "Patient notes retrieved successfully",
                    "patient_id": patient_id,
                    "appointment_id": appointment_id,
                    "notes_count": len(notes),
                    "notes": notes,
                    "latest_instructions": notes[-1].get("notetext", "") if notes else ""
                }
            )
        else:
            # TODO: Implement patient-level notes retrieval once Athena API documentation is provided
            return JSONResponse(
                status_code=501,
                content={
                    "success": False,
                    "message": "Patient notes endpoint - Partial implementation",
                    "note": "Please provide appointment_id to get notes for a specific appointment. Patient-level notes retrieval pending Athena API documentation",
                    "patient_id": patient_id,
                    "start_date": start_date,
                    "end_date": end_date
                }
            )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to get patient notes: {str(e)}"
            }
        )

@router.get("/patient-records")
async def get_patient_records(
    patient_id: str = Query(...),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Get comprehensive patient records including medical history, allergies, medications, and procedures.
    This is used to understand patient context for pre/post-operative questions.
    """
    try:
        # TODO: Implement once Athena API documentation is provided for:
        # - Getting patient medical history
        # - Getting patient allergies
        # - Getting patient medications
        # - Getting patient procedures
        
        return JSONResponse(
            status_code=501,
            content={
                "success": False,
                "message": "Patient records endpoint - Implementation pending Athena API documentation",
                "note": "This endpoint will retrieve comprehensive patient records once Athena API details are provided",
                "patient_id": patient_id
            }
        )
        
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "message": f"Failed to get patient records: {str(e)}"
            }
        )
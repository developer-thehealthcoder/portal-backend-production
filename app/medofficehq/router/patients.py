from fastapi import APIRouter, Depends, HTTPException, Query
from typing import List, Optional
from datetime import datetime
import logging
import csv
from io import StringIO
from fastapi.responses import StreamingResponse
# from app.models.schemas import PatientData  # Removed - not used
from app.medofficehq.services.athena_service import AthenaService
from app.medofficehq.core.dependencies import get_athena_service
from app.medofficehq.schemas.patient import PatientListResponse, PatientDetailResponse, Encounter, CPTCode, Diagnosis
from pydantic import BaseModel

# Set up logging
logger = logging.getLogger(__name__)

router = APIRouter()

class ProcessPatientsRequest(BaseModel):
    patients: List[dict]  # List of patients from first API

@router.get("/list")
async def get_patient_list(
    start_date: str = Query(..., description="Start date in MM/DD/YYYY format"),
    end_date: str = Query(..., description="End date in MM/DD/YYYY format"),
    excluded_patient_ids: Optional[List[str]] = Query(None, description="List of patient IDs to exclude"),
    athena_service: AthenaService = Depends(get_athena_service)
):
    """
    Get a list of patients with basic information for the frontend workflow.
    Returns: appointmentid, appointmentdate, patientid, firstname, lastname
    
    Args:
        start_date: Start date in MM/DD/YYYY format (e.g., 04/01/2025)
        end_date: End date in MM/DD/YYYY format (e.g., 04/07/2025)
        excluded_patient_ids: Optional list of patient IDs to exclude from the results
    """
    try:
        # Validate date format
        try:
            datetime.strptime(start_date, "%m/%d/%Y")
            datetime.strptime(end_date, "%m/%d/%Y")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format. Please use MM/DD/YYYY format (e.g., 04/01/2025)"
            )

        patients = await athena_service.get_patient_list(
            start_date=start_date,
            end_date=end_date,
            excluded_patient_ids=excluded_patient_ids
        )
        return patients
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in get_patient_list: {str(e)}")
        import traceback
        logger.error(f"Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@router.get("/data")
async def get_patient_data(
    start_date: str = Query(..., description="Startc date in MM/DD/YYYY format"),
    end_date: str = Query(..., description="End date in MM/DD/YYYY format"),
    athena_service: AthenaService = Depends()
):
    """
    Get patient data for all departments within a date range and export to CSV.
    The response will be a downloadable CSV file.
    """
    try:
        logger.info(f"Received request for patient data from {start_date} to {end_date}")
        
        # Validate date format
        try:
            datetime.strptime(start_date, "%m/%d/%Y")
            datetime.strptime(end_date, "%m/%d/%Y")
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail="Invalid date format. Please use MM/DD/YYYY format."
            )
        
        # Get patient data
        logger.info("Calling athena_service.get_patient_data")
        patient_data = await athena_service.get_patient_data(
            start_date=start_date,
            end_date=end_date
        )
        
        logger.info(f"Successfully retrieved data for {len(patient_data)} patients")
        
        if not patient_data:
            logger.warning("No patient data found")
            return StreamingResponse(
                iter([""]),
                media_type="text/csv",
                headers={
                    "Content-Disposition": f"attachment; filename=no_data.csv",
                    "Content-Length": "0",
                    "Content-Type": "text/csv; charset=utf-8"
                }
            )
        
        # Create CSV in memory
        logger.info("Creating CSV file")
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=[
            "patientid",
            "firstname",
            "lastname",
            "dob",
            "insuranceprovider",
            "memberid",
            "cpt_codes",
            "diagnosis_codes"
        ])
        
        # Write header and data
        writer.writeheader()
        for patient in patient_data:
            # Convert lists to comma-separated strings
            patient_row = patient.copy()
            patient_row["cpt_codes"] = ",".join(patient_row["cpt_codes"])
            patient_row["diagnosis_codes"] = ",".join(patient_row["diagnosis_codes"])
            writer.writerow(patient_row)
        
        # Get the CSV content
        csv_content = output.getvalue()
        logger.info(f"Generated CSV content of length {len(csv_content)}")
        
        # Create filename with date range
        filename = f"patient_data_{start_date.replace('/', '-')}_to_{end_date.replace('/', '-')}.csv"
        
        # Return CSV file with explicit headers
        logger.info(f"Returning CSV file: {filename}")
        return StreamingResponse(
            iter([csv_content]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Length": str(len(csv_content)),
                "Content-Type": "text/csv; charset=utf-8"
            }
        )
        
    except Exception as e:
        logger.error(f"Error processing request: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error fetching patient data: {str(e)}"
        )

@router.post("/process", response_model=List[PatientDetailResponse])
async def process_selected_patients(
    request: ProcessPatientsRequest,
    athena_service: AthenaService = Depends(get_athena_service)
):
    """Process selected patients and return detailed information"""
    try:
        results = []
        for patient in request.patients:
            # Get patient encounters
            encounters = await athena_service.get_patient_encounters(
                patient["patient_id"],
                patient["department_id"]
            )
            
            # Extract encounters from the response
            encounter_list = encounters.get('encounters', [])
            
            # Find the matching encounter for this appointment
            matching_encounter = None
            for encounter in encounter_list:
                if str(encounter.get('appointmentid')) == patient["appointment_id"]:
                    matching_encounter = encounter
                    break
            
            if not matching_encounter:
                logger.warning(f"No matching encounter found for appointment {patient['appointment_id']}")
                continue

            # Get CPT codes for the encounter
            procedures = await athena_service.get_encounter_services(
                matching_encounter.get('encounterid')
            )
            cpt_codes = [p.procedurecode for p in procedures]

            # Get diagnosis codes for the encounter
            diagnoses = await athena_service.get_encounter_diagnoses(
                matching_encounter.get('encounterid')
            )
            diagnosis_codes = [d.icd10code for d in diagnoses]

            # Create response with all the information
            result = PatientDetailResponse(
                patient_id=patient["patient_id"],
                first_name=patient["first_name"],
                last_name=patient["last_name"],
                dob=patient["dob"],
                appointment_id=patient["appointment_id"],
                department_id=patient["department_id"],
                encounter_id=str(matching_encounter.get('encounterid')),
                encounter_date=matching_encounter.get('encounterdate', ''),
                cpt_codes=cpt_codes,
                diagnosis_codes=diagnosis_codes,
                encounters=[Encounter(
                    encounter_id=str(matching_encounter.get('encounterid')),
                    date=matching_encounter.get('encounterdate', ''),
                    cpt_codes=[CPTCode(code=code) for code in cpt_codes],
                    diagnoses=[Diagnosis(icd10code=code) for code in diagnosis_codes]
                )]
            )
            results.append(result)

        return results

    except Exception as e:
        logger.error(f"Error processing patients: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Error processing patients: {str(e)}"
        ) 
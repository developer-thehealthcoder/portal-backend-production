"""
Rule 21: Missing Slips Analysis and Modifier Update

This rule identifies appointments that are missing charge slips and adds modifier 25
to eligible procedure codes (99202-99205, 99212-99215).

Structure:
1. Data Fetching - Get appointments from Athena Health API
2. Rule Conditions - Identify missing slips based on criteria
3. Modifiers - Add modifier 25 to eligible procedure codes
4. Export - Generate CSV report with results

Author: Adil
Date: 2025-01-07
Version: 4.0
"""

import sys
import os
import logging
import asyncio
import httpx
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Tuple
from pydantic import BaseModel
from app.medofficehq.core.config import settings
from app.medofficehq.services.athena_service import AthenaService

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

class Rule21Request(BaseModel):
    """Request model for Rule 21"""
    add_modifiers: bool = True
    patients: List[PatientRequest] = []
    is_rollback: bool = False  # New field to indicate if this is a rollback operation

class PatientResult(BaseModel):
    """Individual patient result model"""
    patientid: str
    appointmentid: str
    status: int  # 1=changes made, 2=condition met no changes, 3=condition not met, 4=error
    reason: str

class Rule21Response(BaseModel):
    """Response model for Rule 21"""
    success: bool
    message: str
    results: List[PatientResult]
    missing_slips_count: int = 0
    details: Optional[dict] = None

class Rule21:
    """
    Rule 21: Missing Slips Analysis and Modifier Update
    
    This rule identifies appointments that are missing charge slips and adds modifier 25
    ONLY when BOTH eligible codes (99202-99205, 99212-99215) AND injection codes 
    (20526, 20527, 20550, 20551, 20552, 20553, 20600, 20604, 20605, 20610, 20611) are present.
    
    Simple structure with clear separation of concerns:
    1. Data Fetching - Get appointments from Athena Health API
    2. Rule Conditions - Identify missing slips based on criteria
    3. Modifiers - Add modifier 25 to eligible procedure codes (only when both types present)
    4. Process results and return response
    """
    
    def __init__(self):
        """Initialize Rule 21"""
        self.name = "Missing Slips Analysis and Modifier Update"
        self.version = "4.0"
        
        # Define the procedure codes that need modifiers
        self.eligible_codes = ['99202', '99203', '99204', '99205', '99212', '99213', '99214', '99215']
        self.injection_codes = ['20526', '20527', '20550', '20551', '20552', '20553', '20600', '20604', '20605', '20610', '20611']
        
        # Modifier to add
        self.modifier = "25"
        
        # API configuration
        self.base_url = settings.ATHENA_API_BASE_URL
        self.practice_id = settings.ATHENA_PRACTICE_ID
        
        # Initialize AthenaService for API calls
        self.athena_service = AthenaService()
        
        logger.info(f"Initialized {self.name} v{self.version}")
        logger.info(f"Looking for eligible codes: {self.eligible_codes}")
        logger.info(f"Looking for injection codes: {self.injection_codes}")
        logger.info(f"Modifier to add: {self.modifier}")
        logger.info(f"Practice ID: {self.practice_id}")
    
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
                url = f"{self.athena_service.base_url}/{self.practice_id}/encounter/{encounter_id}/services"
                
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
    
    def determine_status_and_reason(self, slip: Dict, modifier_added: bool, error_occurred: bool = False, error_message: str = "") -> Tuple[int, str]:
        """Determine status and reason for a patient result"""
        
        if error_occurred:
            return 4, f"error: {error_message}"
        
        # Check if conditions were met (has eligible codes)
        has_eligible_codes = slip.get('addmodifier', False)
        
        if not has_eligible_codes:
            # Provide more specific reason based on which codes are present
            has_eligible = slip.get('has_eligible_code', False)
            has_injection = slip.get('has_injection_code', False)
            
            if has_eligible and not has_injection:
                return 3, "not eligible for modifier: E&M codes present but missing injection codes (requires both 99202-99215 and 20526-20611)"
            elif has_injection and not has_eligible:
                return 3, "not eligible for modifier: injection codes present but missing E&M visit codes (requires both 99202-99215 and 20526-20611)"
            else:
                return 3, "not eligible for modifier: missing required procedure codes (requires both E&M codes 99202-99215 and injection codes 20526-20611)"
        
        # Conditions met, check if changes were made
        if modifier_added:
            return 1, "modifier 25 added"
        else:
            return 2, "modifier 25 already exists"
    
    def is_missing_slip(self, appointment: Dict) -> Tuple[bool, str]:
        """Determine if an appointment has a missing slip based on criteria"""
        
        # Check if appointment is from the past (appointment happened)
        appointment_date = appointment.get('date', '')
        if appointment_date:
            try:
                appointment_dt = datetime.strptime(appointment_date, '%m/%d/%Y').date()
                if appointment_dt >= date.today():
                    return False, "Future appointment"
            except:
                pass
        
        # Check encounter status - if it's CLOSED, it's not missing
        encounter_status = appointment.get('encounterstatus', '')
        if encounter_status == 'CLOSED':
            return False, "Encounter status is CLOSED"
        
        # Check if charge entry is required
        charge_entry_not_required = appointment.get('chargeentrynotrequired', False)
        if charge_entry_not_required:
            return False, "Charge entry not required"
        
        # Get claims and procedures
        claims = appointment.get('claims', [])
        
        # Check if there are any claims - if no claims at all, it's missing
        if not claims:
            return True, "No claims found"
        
        # If there are claims, check if they have procedures
        has_procedures = False
        for claim in claims:
            procedures = claim.get('procedures', [])
            if procedures:
                has_procedures = True
                break
        
        if not has_procedures:
            return True, "No procedures found in claims"
        
        return False, "Slip appears complete"

    def check_procedure_codes_for_modifier_25(self, procedures: List[Dict]) -> bool:
        """Check if BOTH eligible codes AND injection codes are present to need modifier 25"""
        has_eligible_code = False
        has_injection_code = False
        
        for procedure in procedures:
            procedure_code = procedure.get('procedurecode', '')
            
            # Check for eligible codes
            if procedure_code in self.eligible_codes:
                has_eligible_code = True
            
            # Check for injection codes
            if procedure_code in self.injection_codes:
                has_injection_code = True
            
            # If we have both types, we can return True early
            if has_eligible_code and has_injection_code:
                return True
        
        # Only return True if we have BOTH eligible codes AND injection codes
        return has_eligible_code and has_injection_code
    
    def check_procedure_codes_detailed(self, procedures: List[Dict]) -> Dict[str, bool]:
        """Check which types of codes are present and return detailed information"""
        has_eligible_code = False
        has_injection_code = False
        
        for procedure in procedures:
            procedure_code = procedure.get('procedurecode', '')
            
            # Check for eligible codes
            if procedure_code in self.eligible_codes:
                has_eligible_code = True
            
            # Check for injection codes
            if procedure_code in self.injection_codes:
                has_injection_code = True
        
        return {
            'has_eligible_code': has_eligible_code,
            'has_injection_code': has_injection_code,
            'has_both': has_eligible_code and has_injection_code
        }

    # ============================================================================
    # 3. MODIFIERS - Apply fixes/updates to identified issues
    # ============================================================================
    
    async def update_service_with_modifier_25(self, encounter_id: str, service_id: str, token: Optional[str] = None) -> bool:
        """Update a service to add modifier 25"""
        try:
            # Get access token if not provided
            if not token:
                token = await self.athena_service.get_access_token()
            
            # Create a custom request with longer timeout
            async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(120.0)) as client:
                url = f"{self.athena_service.base_url}/{self.practice_id}/encounter/{encounter_id}/services/{service_id}"
                
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
                
                # Prepare the form data payload
                form_data = {
                    "modifiers": "[\"25\"]",
                    "billforservice": "true"
                }
                
                logger.info(f"Adding modifier 25 to service {service_id} in encounter {encounter_id}")
                
                response = await client.put(url, headers=headers, data=form_data)
                response.raise_for_status()
                
                # Check if the update was successful
                if response.status_code == 200:
                    logger.info(f"Successfully added modifier 25 to service {service_id}")
                    return True
                else:
                    logger.error(f"Failed to add modifier 25 to service {service_id}")
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

    async def rollback_service_modifier_25(self, encounter_id: str, service_id: str, token: Optional[str] = None) -> Tuple[bool, str]:
        """Rollback: Remove modifier 25 from a service
        
        Returns:
            Tuple[bool, str]: (success, reason_message)
        """
        try:
            # Get access token if not provided
            if not token:
                token = await self.athena_service.get_access_token()
            
            # Create a custom request with longer timeout
            async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(120.0)) as client:
                url = f"{self.athena_service.base_url}/{self.practice_id}/encounter/{encounter_id}/services/{service_id}"
                
                headers = {
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
                
                # Prepare the form data payload - remove modifier 25 by setting empty modifiers
                form_data = {
                    "modifiers": "[]",  # Empty array to remove all modifiers
                    "billforservice": "true"
                }
                
                logger.info(f"Removing modifier 25 from service {service_id} in encounter {encounter_id}")
                
                response = await client.put(url, headers=headers, data=form_data)
                response.raise_for_status()
                
                # Check if the update was successful
                if response.status_code == 200:
                    logger.info(f"Successfully removed modifier 25 from service {service_id}")
                    return True, "Modifier 25 removed successfully"
                else:
                    logger.error(f"Failed to remove modifier 25 from service {service_id}")
                    return False, "Failed to remove modifier 25"
                
        except httpx.ReadTimeout as e:
            logger.error(f"Rollback request timed out for service {service_id}: {str(e)}")
            return False, "Request timed out"
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error for service {service_id}: {e.response.status_code}")
            error_text = e.response.text
            logger.error(f"Response body: {error_text}")
            
            # Check for specific error messages
            if e.response.status_code == 400:
                if "claim has already been created" in error_text.lower():
                    return False, "Cannot remove modifier: claim already created for this encounter"
                elif "not allowed" in error_text.lower():
                    return False, "Cannot remove modifier: changes not allowed for this encounter"
                else:
                    return False, f"Cannot remove modifier: {error_text[:100]}"
            elif e.response.status_code == 404:
                return False, "Service or encounter not found"
            else:
                return False, f"HTTP error {e.response.status_code}: {error_text[:100]}"
        except Exception as e:
            logger.error(f"Error rolling back service {service_id}: {str(e)}")
            return False, f"Error: {str(e)}"

    # ============================================================================
    # 4. PROCESSING - Process results and return response
    # ============================================================================

    # ============================================================================
    # MAIN EXECUTION - Orchestrate the entire process
    # ============================================================================
    
    async def apply_rule_conditions_to_patients(self, patients: List[PatientRequest], add_modifiers: bool = False) -> List[Dict]:
        """Apply Rule 21 conditions directly to the provided patients (no missing slips fetching)"""
        print("Starting Rule 21 Analysis for Specific Patients...")
        print("=" * 50)
        print("This rule applies conditions directly to the provided patients")
        print("No missing slips fetching - only patient-specific analysis")
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
                    'addmodifier': False,
                    'has_eligible_code': False,
                    'has_injection_code': False,
                    'modifier_added_successfully': False,
                    'missing_reason': 'No appointment data found'
                })
                continue
            
            # Step 2: Check if this appointment meets rule conditions
            is_missing, reason = self.is_missing_slip(appointment_data)
            
            if is_missing:
                print(f"Missing slip found: {reason}")
                
                # Get encounter ID for services API call
                encounter_id = appointment_data.get('encounterid', '')
                
                # Initialize procedure check variables
                addmodifier = False
                modifier_added_successfully = False
                
                # Check procedures via services API if encounter ID exists
                code_details = {'has_eligible_code': False, 'has_injection_code': False}
                if encounter_id:
                    print(f"Checking procedures for encounter {encounter_id}")
                    procedures = await self.get_encounter_services(encounter_id, token)
                    
                    # Check if any procedures need modifier 25
                    if procedures:
                        code_details = self.check_procedure_codes_detailed(procedures)
                        addmodifier = code_details['has_both']
                        if addmodifier:
                            print(f"Found codes requiring modifier 25 in encounter {encounter_id}")
                            
                            # Add modifier 25 if requested
                            if add_modifiers:
                                print(f"Adding modifier 25 to eligible services in encounter {encounter_id}")
                                for procedure in procedures:
                                    procedure_code = procedure.get('procedurecode', '')
                                    service_id = procedure.get('serviceid', '')
                                    
                                    # Only add modifier if this code is in either eligible or injection lists
                                    if ((procedure_code in self.eligible_codes or procedure_code in self.injection_codes) 
                                        and service_id):
                                        print(f"  Adding modifier 25 to {procedure_code} (service {service_id})")
                                        
                                        # Add modifier 25
                                        success = await self.update_service_with_modifier_25(encounter_id, service_id, token)
                                        if success:
                                            modifier_added_successfully = True
                                        
                                        # Add delay to avoid rate limiting
                                        await asyncio.sleep(0.5)
                    else:
                        addmodifier = False
                    
                    # Add delay to avoid rate limiting
                    await asyncio.sleep(0.5)
                
                # Create detailed record
                patient_result = {
                    'patient_id': patient.patientid,
                    'appointment_id': patient.appointmentid,
                    'patient_name': f"{patient.firstname} {patient.lastname}",
                    'appointment_date': patient.appointmentdate,
                    'encounter_id': encounter_id,
                    'addmodifier': addmodifier,
                    'has_eligible_code': code_details.get('has_eligible_code', False),
                    'has_injection_code': code_details.get('has_injection_code', False),
                    'modifier_added_successfully': modifier_added_successfully,
                    'missing_reason': reason
                }
                
                results.append(patient_result)
            else:
                print(f"Appointment {patient.appointmentid} does not meet missing slip criteria")
                # Add result for patient that doesn't meet criteria
                results.append({
                    'patient_id': patient.patientid,
                    'appointment_id': patient.appointmentid,
                    'patient_name': f"{patient.firstname} {patient.lastname}",
                    'appointment_date': patient.appointmentdate,
                    'encounter_id': appointment_data.get('encounterid', ''),
                    'addmodifier': False,
                    'has_eligible_code': False,
                    'has_injection_code': False,
                    'modifier_added_successfully': False,
                    'missing_reason': 'Does not meet missing slip criteria'
                })
        
        print(f"\nAnalysis Complete!")
        print(f"Total patients analyzed: {len(patients)}")
        print(f"Patients meeting criteria: {len([r for r in results if r.get('missing_reason') != 'Does not meet missing slip criteria'])}")
        
        return results
    
    async def rollback_rule_conditions_to_patients(self, patients: List[PatientRequest]) -> List[Dict]:
        """Rollback Rule 21 changes: Remove modifier 25 from services for the provided patients with batch processing"""
        print("Starting Rule 21 Rollback for Specific Patients...")
        print("=" * 50)
        print("This rollback removes modifier 25 from services for the provided patients")
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
                            'reason': 'No appointment data found'
                        })
                        continue
                    
                    # Get encounter ID for services API call
                    encounter_id = appointment_data.get('encounterid', '')
                    
                    # Initialize rollback variables
                    modifier_removed = False
                    reason = 'No eligible services found for rollback (no matching procedure codes)'
                    
                    # Check procedures via services API if encounter ID exists
                    if encounter_id:
                        print(f"  Checking procedures for rollback in encounter {encounter_id}")
                        procedures = await self.get_encounter_services(encounter_id, token)
                        
                        if procedures:
                            # Check each procedure for eligible codes and remove modifier 25
                            for procedure in procedures:
                                procedure_code = procedure.get('procedurecode', '')
                                service_id = procedure.get('serviceid', '')
                                
                                # Check if procedure code matches any of our target codes
                                if ((procedure_code in self.eligible_codes or procedure_code in self.injection_codes) 
                                    and service_id):
                                    print(f"    Rolling back modifier 25 from {procedure_code} (service {service_id})")
                                    
                                    # Remove modifier 25
                                    success, error_reason = await self.rollback_service_modifier_25(encounter_id, service_id, token)
                                    if success:
                                        modifier_removed = True
                                        reason = f"Modifier 25 removed from {procedure_code}"
                                    else:
                                        # Update reason with specific error if we haven't removed modifier yet
                                        if not modifier_removed:
                                            reason = f"Eligible for rollback but {error_reason.lower()}"
                                    
                                    # Add delay to avoid rate limiting
                                    await asyncio.sleep(0.3)  # Reduced delay for faster processing
                        else:
                            print(f"  No procedures found for encounter {encounter_id}")
                            reason = 'No procedures found in encounter'
                    else:
                        print(f"  No encounter ID found for appointment {patient.appointmentid}")
                        reason = 'No encounter ID found for appointment'
                    
                    # Create detailed record
                    patient_result = {
                        'patient_id': patient.patientid,
                        'appointment_id': patient.appointmentid,
                        'patient_name': f"{patient.firstname} {patient.lastname}",
                        'appointment_date': patient.appointmentdate,
                        'encounter_id': encounter_id,
                        'modifier_removed': modifier_removed,
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
        print(f"Patients with errors: {len([r for r in results if 'Error:' in r.get('reason', '')])}")
        
        return results
    
    async def get_appointment_for_patient(self, patient: PatientRequest, token: str) -> Optional[Dict]:
        """Get appointment data for a specific patient"""
        try:
            # Create a custom request with longer timeout
            async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(120.0)) as client:
                url = f"{self.athena_service.base_url}/{self.practice_id}/appointments/booked"
                
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

    async def run(self, request: Rule21Request) -> Rule21Response:
        """
        Main execution method for Rule 21
        
        Args:
            request: Rule21Request with analysis parameters and patient list
            
        Returns:
            Rule21Response with analysis results for requested patients
        """
        try:
            # Check if this is a rollback operation
            if request.is_rollback:
                print("Rule 21: Rollback Operation")
                print("=" * 50)
                print("This rollback removes modifier 25 from services for the provided patients")
                print("=" * 50)
                
                # Check if patients list is provided
                if not request.patients:
                    return Rule21Response(
                        success=False,
                        message="No patients provided for rollback",
                        results=[],
                        missing_slips_count=0
                    )
                
                print(f"Rolling back {len(request.patients)} requested patients")
                
                # Apply rollback to the provided patients
                patient_results = await self.rollback_rule_conditions_to_patients(request.patients)
            else:
                print("Rule 21: Missing Slips Analysis and Modifier Update")
            print("=" * 50)
            print("This automation identifies appointments that are missing charge slips")
            print("Criteria:")
            print("- Encounter status ≠ CLOSED")
            print("- Charge entry required = true")
            print("- No claims OR no procedures in claims")
            print("- Appointment date in the past")
            if request.add_modifiers:
                print("- Automatically add modifier 25 when BOTH eligible codes (99202-99205, 99212-99215) AND injection codes (20526, 20527, 20550, 20551, 20552, 20553, 20600, 20604, 20605, 20610, 20611) are present")
            print("=" * 50)
            
            # Check if patients list is provided
            if not request.patients:
                return Rule21Response(
                    success=False,
                    message="No patients provided in request",
                    results=[],
                    missing_slips_count=0
                )
            
            print(f"Processing {len(request.patients)} requested patients")
            
            # Apply Rule 21 conditions directly to the provided patients
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
                
                return Rule21Response(
                    success=False,
                    message="No patient data found",
                    results=results,
                    missing_slips_count=0
                )
            
            # Generate results for all requested patients from patient_results
            results = []
            for patient in request.patients:
                # Find matching result for this patient
                matching_result = None
                for result in patient_results:
                    if result.get('patient_id') == patient.patientid:
                        matching_result = result
                        break
                
                # Process the matching result (outside the loop)
                if matching_result:
                    if request.is_rollback:
                        # Handle rollback results
                        modifier_removed = matching_result.get('modifier_removed', False)
                        reason = matching_result.get('reason', 'Unknown error')
                        
                        if modifier_removed:
                            status = 1  # Rollback successful
                        else:
                            status = 3  # No changes to rollback
                            # Provide more specific reason for rollback failure
                            if 'claim has already been created' in reason.lower():
                                reason = "not eligible for rollback: claim already created, cannot modify services"
                            elif 'no eligible services' in reason.lower() or 'no procedures found' in reason.lower():
                                reason = "not eligible for rollback: no modifier 25 found to remove"
                            elif reason == 'Unknown error' or not reason:
                                reason = "Eligible for rollback but claim already created"
                    else:
                        # Handle normal operation results
                        status, reason = self.determine_status_and_reason(
                            matching_result, 
                            matching_result.get('modifier_added_successfully', False)
                        )
                    
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
                    status = 4
                    reason = "error: Patient data not found"
                    
                    patient_result = PatientResult(
                        patientid=patient.patientid,
                        appointmentid=patient.appointmentid,
                        status=status,
                        reason=reason
                    )
                    results.append(patient_result)
                    print(f"Patient {patient.patientid} ({patient.firstname} {patient.lastname}): Status {status} - {reason}")
            

            
            # Count statuses for summary
            status_counts = {1: 0, 2: 0, 3: 0, 4: 0}
            for result in results:
                status_counts[result.status] += 1
            
            # Determine appropriate message based on operation type
            if request.is_rollback:
                message = f"Rule 21 rollback completed. Processed {len(request.patients)} patients."
            else:
                message = f"Rule 21 analysis completed. Processed {len(request.patients)} patients."
            
            return Rule21Response(
                success=True,
                message=message,
                results=results,
                missing_slips_count=len(patient_results),

                details={
                    "total_patients": len(request.patients),
                    "status_1_changes_made": status_counts[1],
                    "status_2_condition_met_no_changes": status_counts[2],
                    "status_3_condition_not_met": status_counts[3],
                    "status_4_errors": status_counts[4]
                }
            )
            
        except Exception as e:
            logger.error(f"Error in Rule 21 execution: {str(e)}")
            # Return error results for all requested patients
            results = []
            for patient in request.patients:
                results.append(PatientResult(
                    patientid=patient.patientid,
                    appointmentid=patient.appointmentid,
                    status=4,  # Error
                    reason=f"error: {str(e)}"
                ))
            
            return Rule21Response(
                success=False,
                message=f"Error during analysis: {str(e)}",
                results=results,
                missing_slips_count=0
            )

# Global instance for API use
rule_21_instance = Rule21()

async def main():
    """Main function for standalone testing"""
    print("Rule 21: Missing Slips Analysis and Modifier Update")
    print("This is a test function. Use the API endpoint for actual testing.")
    print("API Endpoint: POST /rules/rule21")
    print("Request Body: {\"add_modifiers\": true, \"patients\": [{\"appointmentid\": \"...\", \"appointmentdate\": \"...\", \"patientid\": \"...\", \"firstname\": \"...\", \"lastname\": \"...\"}]}")

if __name__ == "__main__":
    asyncio.run(main()) 
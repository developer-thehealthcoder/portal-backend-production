import httpx
import logging
import base64
import asyncio
from typing import List, Optional, Dict
from datetime import datetime, timedelta
from app.medofficehq.core.config import settings
from app.medofficehq.schemas import Department

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class AthenaService:
    def __init__(
        self,
        client_id: Optional[str] = None,
        client_secret: Optional[str] = None,
        practice_id: Optional[str] = None,
        base_url: Optional[str] = None,
        environment: Optional[str] = None
    ):
        """
        Initialize AthenaService with environment-specific credentials.
        
        Args:
            client_id: Athena Client ID (if None, uses settings)
            client_secret: Athena Client Secret (if None, uses settings)
            practice_id: Athena Practice ID (if None, uses settings)
            base_url: Athena API Base URL (if None, uses settings)
            environment: Environment name (sandbox/production) for logging
        """
        # Use provided credentials or fall back to settings (backward compatibility)
        self.client_id = client_id or settings.ATHENA_Client_ID
        self.client_secret = client_secret or settings.ATHENA_Client_Secret
        self.practice_id = practice_id or settings.ATHENA_PRACTICE_ID
        self.base_url = base_url or settings.ATHENA_API_BASE_URL
        self.environment = environment or "default"
        
        # Derive token URL from base URL (replace /v1 with /oauth2/v1/token)
        base_domain = self.base_url.replace("/v1", "")
        self.token_url = f"{base_domain}/oauth2/v1/token"
        self.access_token = None
        self.token_expires_at = None
        
        logger.info(
            f"Initialized AthenaService [environment={self.environment}] "
            f"with practice_id={self.practice_id}, base_url={self.base_url}"
        )

    async def get_access_token(self) -> str:
        """Get OAuth2 access token using client credentials with retry logic"""
        # Check if we have a valid token
        if self.access_token and self.token_expires_at and datetime.now() < self.token_expires_at:
            return self.access_token

        max_retries = 3
        retry_delay = 5  # seconds
        
        for attempt in range(max_retries):
            try:
                # Create basic auth header
                auth_string = f"{self.client_id}:{self.client_secret}"
                auth_bytes = auth_string.encode('ascii')
                base64_auth = base64.b64encode(auth_bytes).decode('ascii')
                
                async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(60.0)) as client:
                    logger.info(f"Requesting new access token (attempt {attempt + 1}/{max_retries})")
                    response = await client.post(
                        self.token_url,
                        headers={
                            "Authorization": f"Basic {base64_auth}",
                            "Content-Type": "application/x-www-form-urlencoded"
                        },
                        data={
                            "grant_type": "client_credentials",
                            "scope": "athena/service/Athenanet.MDP.*"
                        }
                    )
                    response.raise_for_status()
                    token_data = response.json()
                    
                    self.access_token = token_data["access_token"]
                    # Set token expiration (subtract 5 minutes for safety)
                    expires_in = token_data.get("expires_in", 3600)
                    self.token_expires_at = datetime.now() + timedelta(seconds=expires_in - 300)
                    
                    logger.info("Successfully obtained new access token")
                    return self.access_token
                    
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 403:
                    # 403 Forbidden usually means IP whitelisting issue
                    error_msg = (
                        "403 Forbidden: Your server's IP address is not whitelisted by Athena Health. "
                        "Please contact Athena Health support to whitelist your Azure App Service outbound IP addresses. "
                        "Reference error: AWS Geo and Vendor Rule"
                    )
                    logger.error(error_msg)
                    raise Exception(error_msg) from e
                elif e.response.status_code in [504, 502, 503] and attempt < max_retries - 1:
                    logger.warning(f"Athena API timeout/error (attempt {attempt + 1}), retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                    continue
                else:
                    logger.error(f"Error getting access token after {max_retries} attempts: {str(e)}")
                    raise
            except Exception as e:
                if attempt < max_retries - 1:
                    logger.warning(f"Error getting access token (attempt {attempt + 1}), retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                    continue
                else:
                    logger.error(f"Error getting access token after {max_retries} attempts: {str(e)}")
                    raise

    async def _make_request(self, method: str, endpoint: str, timeout: float = 180.0, **kwargs) -> httpx.Response:
        """
        Make an authenticated request to the Athena API with configurable timeout
        
        Args:
            method: HTTP method (GET, POST, PUT, etc.)
            endpoint: API endpoint path
            timeout: Request timeout in seconds (default: 180 for large data operations)
            **kwargs: Additional arguments to pass to httpx request
        """
        try:
            # Get access token
            token = await self.get_access_token()
            
            # Prepare headers
            headers = kwargs.pop("headers", {})
            headers["Authorization"] = f"Bearer {token}"
            
            # Make request with timeout
            async with httpx.AsyncClient(verify=True, timeout=httpx.Timeout(timeout)) as client:
                url = f"{self.base_url}/{endpoint}"
                logger.info(f"Making {method} request to: {url} (timeout: {timeout}s)")
                
                response = await client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    **kwargs
                )
                response.raise_for_status()
                return response
                
        except httpx.TimeoutException as e:
            logger.error(f"Timeout error making request to {endpoint}: {str(e)}")
            raise Exception(f"Request to {endpoint} timed out after {timeout} seconds. The date range may be too large. Try splitting into smaller ranges.") from e
        except Exception as e:
            logger.error(f"Error making request to {endpoint}: {str(e)}")
            raise

    async def get_departments(self) -> List[Department]:
        """Get all departments for the practice"""
        try:
            response = await self._make_request(
                "GET",
                f"{self.practice_id}/departments"
            )
            data = response.json()
            departments = [Department(**dept) for dept in data.get("departments", [])]
            logger.info(f"Found {len(departments)} departments")
            return departments
        except Exception as e:
            logger.error(f"Error fetching departments: {str(e)}")
            raise

    async def get_booked_appointments(
        self,
        department_id: str,
        start_date: str,
        end_date: str,
        batch_by_month: bool = True
    ) -> List[Dict]:
        """
        Get booked appointments for a department within a date range with enhanced details.
        For large date ranges (2-3 months), automatically batches by month to avoid timeouts.
        
        Args:
            department_id: Department ID
            start_date: Start date in MM/DD/YYYY format
            end_date: End date in MM/DD/YYYY format
            batch_by_month: If True, split large date ranges into monthly batches (default: True)
            
        Returns:
            List of appointment dictionaries
        """
        try:
            # Parse dates to determine if batching is needed
            start_date_obj = datetime.strptime(start_date, "%m/%d/%Y")
            end_date_obj = datetime.strptime(end_date, "%m/%d/%Y")
            date_range_days = (end_date_obj - start_date_obj).days
            
            # If date range is > 60 days and batching is enabled, split into monthly chunks
            if batch_by_month and date_range_days > 60:
                logger.info(f"Large date range detected ({date_range_days} days). Batching by month to avoid timeouts.")
                all_appointments = []
                current_date = start_date_obj
                
                while current_date <= end_date_obj:
                    # Calculate the end of current month
                    if current_date.month == 12:
                        next_month = current_date.replace(year=current_date.year + 1, month=1, day=1)
                    else:
                        next_month = current_date.replace(month=current_date.month + 1, day=1)
                    
                    # End date for this month (last day of current month)
                    month_end = next_month - timedelta(days=1)
                    
                    # If month_end exceeds our target end_date, use end_date instead
                    if month_end > end_date_obj:
                        month_end = end_date_obj
                    
                    # Format dates for API call
                    month_start_str = current_date.strftime("%m/%d/%Y")
                    month_end_str = month_end.strftime("%m/%d/%Y")
                    
                    logger.info(f"Fetching appointments for {month_start_str} to {month_end_str}")
                    
                    # Recursively call for this month (with batching disabled to avoid infinite recursion)
                    month_appointments = await self.get_booked_appointments(
                        department_id=department_id,
                        start_date=month_start_str,
                        end_date=month_end_str,
                        batch_by_month=False  # Disable batching for monthly chunks
                    )
                    
                    all_appointments.extend(month_appointments)
                    logger.info(f"Found {len(month_appointments)} appointments for this month. Total so far: {len(all_appointments)}")
                    
                    # Small delay to avoid rate limiting
                    await asyncio.sleep(0.5)
                    
                    # Move to next month
                    current_date = next_month
                
                logger.info(f"Total appointments found across all months: {len(all_appointments)}")
                return all_appointments
            
            # For smaller ranges or when batching is disabled, make direct API call
            token = await self.get_access_token()
            
            url = f"{self.base_url}/{self.practice_id}/appointments/booked"
            params = {
                'startdate': start_date,
                'enddate': end_date,
                'departmentid': department_id,
                'showpatientdetail': 'true',
                'showinsurance': 'true',
                'showclaimdetail': 'true',
                'showexpectedprocedurecodes': 'true'
            }
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            logger.info(f"Making appointment request with params: {params}")
            
            # Use longer timeout for large date ranges (180 seconds)
            timeout_seconds = 180.0 if date_range_days > 30 else 60.0
            
            max_retries = 3
            retry_delay = 2  # seconds
            
            for attempt in range(max_retries):
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds)) as client:
                        response = await client.get(url, params=params, headers=headers)
                
                    if response.status_code == 200:
                        data = response.json()
                        appointments = data.get("appointments", [])
                        logger.info(f"Found {len(appointments)} appointments")
                        return appointments
                    else:
                        logger.error(f"API error: {response.status_code} - {response.text}")
                        raise Exception(f"API request failed with status {response.status_code}")
                            
                except (httpx.TimeoutException, httpx.ReadTimeout) as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Timeout on attempt {attempt + 1}/{max_retries}. Retrying in {retry_delay} seconds...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                        continue
                    else:
                        logger.error(f"Timeout after {max_retries} attempts: {str(e)}")
                        raise Exception(f"Request timed out after {max_retries} attempts. The date range may be too large. Try splitting into smaller ranges.") from e
                except Exception as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Error on attempt {attempt + 1}/{max_retries}: {str(e)}. Retrying...")
                        await asyncio.sleep(retry_delay)
                        retry_delay *= 2
                        continue
                    else:
                        raise
                    
        except Exception as e:
            logger.error(f"Error fetching appointments: {str(e)}")
            logger.error(f"Full error details: {type(e).__name__}: {e}")
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise

    async def get_patient_data(
        self,
        start_date: str,
        end_date: str
    ) -> List[Dict]:
        """Get complete patient data for all departments within date range using enhanced appointment data"""
        try:
            logger.info(f"Starting patient data collection from {start_date} to {end_date}")
            
            # Step 1: Get all departments
            logger.info("Step 1: Getting all departments")
            departments = await self.get_departments()
            if not departments:
                logger.warning("No departments found")
                return []
            logger.info(f"Found {len(departments)} departments")
            
            all_patient_data = []
            total_appointments = 0
            processed_patients = 0  # Counter for processed patients
            
            # Step 2: For each department, get booked appointments with enhanced details
            for dept in departments:
                if processed_patients >= 5:  # Stop after processing 5 patients
                    logger.info("Reached limit of 5 patients, stopping processing")
                    break
                    
                logger.info(f"Step 2: Processing department {dept.departmentid} - {dept.name}")
                
                # Get appointments with enhanced details (patient, insurance, claims)
                appointments = await self.get_booked_appointments(
                    department_id=dept.departmentid,
                    start_date=start_date,
                    end_date=end_date
                )
                
                total_appointments += len(appointments)
                logger.info(f"Found {len(appointments)} appointments in department {dept.departmentid}")
                
                # Step 3: Process each appointment using enhanced data
                for apt in appointments:
                    if processed_patients >= 5:  # Stop after processing 5 patients
                        break
                        
                    try:
                        logger.info(f"Step 3: Processing appointment {apt.get('appointmentid', 'N/A')} for patient {apt.get('patientid', 'N/A')}")
                        
                        # Extract patient info from enhanced appointment data
                        patient_info = apt.get('patient', {})
                        if not patient_info:
                            logger.warning(f"No patient details found for patient {apt.get('patientid', 'N/A')}")
                            continue
                        
                        logger.info(f"Found patient info for {patient_info.get('firstname', '')} {patient_info.get('lastname', '')}")
                        
                        # Extract insurance info from enhanced appointment data
                        insurances = apt.get('insurances', [])
                        logger.info(f"Found {len(insurances)} insurance records")
                        
                        # Extract CPT codes and diagnosis codes from claims
                        cpt_codes = []
                        diagnosis_codes = []
                        
                        claims = apt.get('claims', [])
                        if claims:
                            logger.info(f"Found {len(claims)} claims for appointment {apt.get('appointmentid', 'N/A')}")
                            for claim in claims:
                                # Extract procedures (CPT codes)
                                procedures = claim.get("procedures", [])
                                for procedure in procedures:
                                    cpt_code = procedure.get("procedurecode", "")
                                    if cpt_code:
                                        cpt_codes.append(cpt_code)
                                
                                # Extract diagnoses
                                diagnoses = claim.get("diagnoses", [])
                                for diagnosis in diagnoses:
                                    diagnosis_code = diagnosis.get("diagnosisrawcode", "")
                                    if diagnosis_code:
                                        diagnosis_codes.append(diagnosis_code)
                        
                        logger.info(f"Found CPT codes: {cpt_codes}")
                        logger.info(f"Found diagnosis codes: {diagnosis_codes}")
                        
                        # Create patient data
                        patient_data = {
                            "patientid": apt.get('patientid', ''),
                            "firstname": patient_info.get("firstname", ""),
                            "lastname": patient_info.get("lastname", ""),
                            "dob": patient_info.get("dob", ""),
                            "insuranceprovider": insurances[0].get("insurancepayername") if insurances else None,
                            "memberid": insurances[0].get("insuranceidnumber") if insurances else None,
                            "cpt_codes": cpt_codes,
                            "diagnosis_codes": diagnosis_codes
                        }
                        
                        all_patient_data.append(patient_data)
                        processed_patients += 1  # Increment the counter
                        logger.info(f"Successfully processed patient {apt.get('patientid', 'N/A')} ({processed_patients}/5)")
                        
                    except Exception as e:
                        logger.error(f"Error processing appointment {apt.get('appointmentid', 'N/A')}: {str(e)}")
                        continue
            
            logger.info(f"Completed processing {len(all_patient_data)} patients from {total_appointments} appointments")
            return all_patient_data
            
        except Exception as e:
            logger.error(f"Error in get_patient_data: {str(e)}")
            raise

    async def get_patient_list(
        self,
        start_date: str,
        end_date: str,
        excluded_patient_ids: Optional[List[str]] = None
    ) -> List[Dict]:
        """
        Get a list of patients with basic information for the frontend workflow.
        Returns specific fields: appointmentid, appointmentdate, patientid, firstname, lastname
        
        Args:
            start_date: Start date for the appointment range
            end_date: End date for the appointment range
            excluded_patient_ids: Optional list of patient IDs to exclude from the results
            
        Returns:
            List of dictionaries containing patient information with specified fields
        """
        try:
            logger.info(f"Getting patient list from {start_date} to {end_date}")
            
            # Get all departments
            departments = await self.get_departments()
            all_patients = []
            
            # Get appointments for each department with enhanced details
            for dept in departments:
                try:
                    appointments = await self.get_booked_appointments(
                        dept.departmentid,
                        start_date,
                        end_date
                    )
                    
                    logger.info(f"Processing {len(appointments)} appointments from department {dept.departmentid}")
                    
                    # Process each appointment using enhanced data
                    for apt in appointments:
                        # Skip if patient is in excluded list
                        if excluded_patient_ids and apt.get('patientid') in excluded_patient_ids:
                            continue
                        
                        # Extract patient info from enhanced appointment data
                        patient_info = apt.get('patient', {})
                        
                        # Create patient data with specific fields
                        patient_data = {
                            "appointmentid": apt.get('appointmentid', ''),
                            "appointmentdate": apt.get('date', ''),
                            "patientid": apt.get('patientid', ''),
                            "firstname": patient_info.get("firstname", ""),
                            "lastname": patient_info.get("lastname", "")
                        }
                        all_patients.append(patient_data)
                        
                except Exception as e:
                    logger.error(f"Error processing department {dept.departmentid}: {str(e)}")
                    continue  # Continue with next department
            
            logger.info(f"Found {len(all_patients)} patients in total")
            return all_patients
            
        except Exception as e:
            logger.error(f"Error getting patient list: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    async def book_appointment(self, appointment_data: Dict) -> Dict:
        """
        Book a new appointment in Athena Health.
        
        Args:
            appointment_data: Dictionary containing appointment details
            
        Returns:
            Dictionary with appointment booking result
        """
        try:
            logger.info(f"Booking appointment for patient {appointment_data.get('patientid')}")
            
            # Get access token
            token = await self.get_access_token()
            
            # Prepare the appointment booking request
            url = f"{self.base_url}/{self.practice_id}/appointments"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            logger.info(f"Making appointment booking request to: {url}")
            logger.info(f"Appointment data: {appointment_data}")
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                response = await client.post(url, json=appointment_data, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully booked appointment: {result}")
                    return result
                else:
                    logger.error(f"Failed to book appointment: {response.status_code} - {response.text}")
                    raise Exception(f"Appointment booking failed with status {response.status_code}: {response.text}")
                    
        except Exception as e:
            logger.error(f"Error booking appointment: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    async def cancel_appointment(
        self, 
        appointment_id: str, 
        patient_id: str,
        cancellation_reason: Optional[str] = None,
        appointment_cancel_reason_id: Optional[int] = None,
        ignore_schedulable_permission: bool = True,
        no_patient_case: bool = False
    ) -> Dict:
        """
        Cancel an existing appointment in Athena Health.
        
        Args:
            appointment_id: ID of the appointment to cancel
            patient_id: The athenaNet patient ID (required)
            cancellation_reason: Optional text explanation why the appointment is being cancelled
            appointment_cancel_reason_id: Optional ID to override default cancel reason
            ignore_schedulable_permission: Allow cancellation regardless of web settings (default: True)
            no_patient_case: Bypass patient case creation for new patients (default: False)
            
        Returns:
            Dictionary with cancellation result containing status
        """
        try:
            logger.info(f"Cancelling appointment {appointment_id} for patient {patient_id}")
            
            # Get access token
            token = await self.get_access_token()
            
            # Prepare the appointment cancellation request
            url = f"{self.base_url}/{self.practice_id}/appointments/{appointment_id}/cancel"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            # Prepare cancellation data according to Athena API specification
            cancellation_data = {
                "patientid": patient_id  # Required field
            }
            
            # Add optional parameters if provided
            if cancellation_reason:
                cancellation_data["cancellationreason"] = cancellation_reason
            
            if appointment_cancel_reason_id is not None:
                cancellation_data["appointmentcancelreasonid"] = str(appointment_cancel_reason_id)
            
            if ignore_schedulable_permission:
                cancellation_data["ignoreschedulablepermission"] = "true"
            else:
                cancellation_data["ignoreschedulablepermission"] = "false"
            
            if no_patient_case:
                cancellation_data["nopatientcase"] = "true"
            else:
                cancellation_data["nopatientcase"] = "false"
            
            logger.info(f"Making appointment cancellation request to: {url}")
            logger.info(f"Cancellation data: {cancellation_data}")
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
                response = await client.put(url, data=cancellation_data, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully cancelled appointment: {result}")
                    return result
                else:
                    logger.error(f"Failed to cancel appointment: {response.status_code} - {response.text}")
                    raise Exception(f"Appointment cancellation failed with status {response.status_code}: {response.text}")
                    
        except Exception as e:
            logger.error(f"Error cancelling appointment: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    async def create_patient(self, patient_data: Dict) -> Dict:
        """
        Create a new patient in Athena Health.
        
        Args:
            patient_data: Dictionary containing patient details
            
        Returns:
            Dictionary with patient creation result
        """
        try:
            logger.info(f"Creating patient: {patient_data.get('firstname')} {patient_data.get('lastname')}")
            
            # Get access token
            token = await self.get_access_token()
            
            # Prepare the patient creation request
            url = f"{self.base_url}/{self.practice_id}/patients"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            logger.info(f"Making patient creation request to: {url}")
            logger.info(f"Patient data: {patient_data}")
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                response = await client.post(url, data=patient_data, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully created patient: {result}")
                    
                    # Handle case where Athena returns a list instead of dict
                    if isinstance(result, list) and len(result) > 0:
                        return result[0]  # Return first patient from list
                    elif isinstance(result, dict):
                        return result
                    else:
                        return {"patientid": "unknown", "status": "created"}
                else:
                    logger.error(f"Failed to create patient: {response.status_code} - {response.text}")
                    raise Exception(f"Patient creation failed with status {response.status_code}: {response.text}")
                    
        except Exception as e:
            logger.error(f"Error creating patient: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    async def search_patient(self, search_params: Dict) -> List[Dict]:
        """
        Search for existing patients in Athena Health.
        
        Args:
            search_params: Dictionary containing search parameters
            
        Returns:
            List of matching patients
        """
        try:
            logger.info(f"Searching for patient: {search_params.get('firstname')} {search_params.get('lastname')}")
            
            # Get access token
            token = await self.get_access_token()
            
            # Prepare the patient search request
            url = f"{self.base_url}/{self.practice_id}/patients"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            logger.info(f"Making patient search request to: {url}")
            logger.info(f"Search parameters: {search_params}")
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.get(url, params=search_params, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully searched patients: {result}")
                    
                    # Handle case where Athena returns a list of patients
                    if isinstance(result, list):
                        return result
                    elif isinstance(result, dict) and "patients" in result:
                        return result["patients"]
                    else:
                        return []
                else:
                    logger.error(f"Failed to search patients: {response.status_code} - {response.text}")
                    raise Exception(f"Patient search failed with status {response.status_code}: {response.text}")
                    
        except Exception as e:
            logger.error(f"Error searching patients: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    async def get_providers(self, departmentid: str) -> List[Dict]:
        """
        Get all available providers for a department.
        
        Args:
            departmentid: Department ID to get providers for
            
        Returns:
            List of providers with names and IDs
        """
        try:
            logger.info(f"Getting providers for department: {departmentid}")
            
            # Get access token
            token = await self.get_access_token()
            
            # Prepare the providers request
            url = f"{self.base_url}/{self.practice_id}/providers"
            params = {"departmentid": departmentid}
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            logger.info(f"Making providers request to: {url}")
            logger.info(f"Parameters: {params}")
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.get(url, params=params, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully retrieved providers: {result}")
                    
                    # Extract providers and return simplified format
                    providers = result.get("providers", [])
                    simplified_providers = []
                    
                    for provider in providers:
                        simplified_providers.append({
                            "providerid": provider.get("providerid"),
                            "displayname": provider.get("displayname"),
                            "firstname": provider.get("firstname"),
                            "lastname": provider.get("lastname"),
                            "specialty": provider.get("specialty")
                        })
                    
                    return simplified_providers
                else:
                    logger.error(f"Failed to get providers: {response.status_code} - {response.text}")
                    raise Exception(f"Providers request failed with status {response.status_code}: {response.text}")
                    
        except Exception as e:
            logger.error(f"Error getting providers: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    async def get_appointment_slots(self, search_params: Dict) -> List[Dict]:
        """
        Get available appointment slots for a provider.
        
        Args:
            search_params: Dictionary containing search parameters
            
        Returns:
            List of available appointment slots
        """
        try:
            logger.info(f"Getting appointment slots with params: {search_params}")
            
            # Get access token
            token = await self.get_access_token()
            
            # Prepare the appointment slots request
            url = f"{self.base_url}/{self.practice_id}/appointments/open"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            logger.info(f"Making appointment slots request to: {url}")
            logger.info(f"Search parameters: {search_params}")
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.get(url, params=search_params, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully retrieved appointment slots: {result}")
                    
                    # Return the appointments list
                    appointments = result.get("appointments", [])
                    return appointments
                else:
                    logger.error(f"Failed to get appointment slots: {response.status_code} - {response.text}")
                    raise Exception(f"Appointment slots request failed with status {response.status_code}: {response.text}")
                    
        except Exception as e:
            logger.error(f"Error getting appointment slots: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    async def book_appointment_slot(self, appointment_id: str, booking_data: Dict) -> Dict:
        """
        Book an appointment slot by confirming it.
        Uses form-encoded data as required by Athena Health API.
        
        Args:
            appointment_id: ID of the appointment slot to book
            booking_data: Dictionary containing provider, patient and appointment type info
            
        Returns:
            Dictionary with booking result
        """
        try:
            logger.info(f"Booking appointment slot {appointment_id} with data: {booking_data}")
            
            # Get access token
            token = await self.get_access_token()
            
            # Prepare the booking request
            url = f"{self.base_url}/{self.practice_id}/appointments/{appointment_id}"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            logger.info(f"Making appointment booking request to: {url}")
            logger.info(f"Booking data: {booking_data}")
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.put(url, data=booking_data, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully booked appointment: {result}")
                    
                    # Handle case where Athena returns a list
                    if isinstance(result, list) and len(result) > 0:
                        return result[0]  # Return first appointment from list
                    elif isinstance(result, dict):
                        return result
                    else:
                        return {"appointmentid": appointment_id, "status": "booked"}
                else:
                    logger.error(f"Failed to book appointment: {response.status_code} - {response.text}")
                    raise Exception(f"Appointment booking failed with status {response.status_code}: {response.text}")
                    
        except Exception as e:
            logger.error(f"Error booking appointment: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise

    def get_appointment_type_id(self, providerid: str, is_new_patient: bool) -> str:
        """
        Get appointment type ID based on provider and patient status.
        
        Args:
            providerid: Provider ID (7, 8 for Physical Therapy; 5, 2 for Office Visit)
            is_new_patient: True if new patient, False if existing patient
            
        Returns:
            Appointment type ID as string
        """
        # Physical Therapy providers (7, 8)
        if providerid in ["7", "8"]:
            if is_new_patient:
                return "181"  # PHYSICAL THERAPY NEW
            else:
                return "161"  # PHYSICAL THERAPY Established
        
        # Office Visit providers (5, 2)
        elif providerid in ["5", "2"]:
            if is_new_patient:
                return "2"   # OFFICE VISIT NEW
            else:
                return "3"   # OFFICE VISIT ESTABLISHED
        
        # Default fallback
        else:
            if is_new_patient:
                return "2"   # Default to OFFICE VISIT NEW
            else:
                return "3"   # Default to OFFICE VISIT ESTABLISHED

    def get_appointment_type_name(self, providerid: str, is_new_patient: bool) -> str:
        """
        Get appointment type name based on provider and patient status.
        
        Args:
            providerid: Provider ID (7, 8 for Physical Therapy; 5, 2 for Office Visit)
            is_new_patient: True if new patient, False if existing patient
            
        Returns:
            Appointment type name
        """
        # Physical Therapy providers (7, 8)
        if providerid in ["7", "8"]:
            if is_new_patient:
                return "PHYSICAL THERAPY NEW"
            else:
                return "PHYSICAL THERAPY Established"
        
        # Office Visit providers (5, 2)
        elif providerid in ["5", "2"]:
            if is_new_patient:
                return "OFFICE VISIT NEW"
            else:
                return "OFFICE VISIT ESTABLISHED"
        
        # Default fallback
        else:
            if is_new_patient:
                return "OFFICE VISIT NEW"
            else:
                return "OFFICE VISIT ESTABLISHED"
    
    async def reschedule_appointment(
        self,
        appointment_id: str,
        new_appointment_id: str,
        patient_id: str,
        appointment_cancel_reason_id: Optional[int] = None,
        ignore_schedulable_permission: bool = True,
        no_patient_case: bool = False,
        reason_id: Optional[int] = None,
        reschedule_reason: Optional[str] = None
    ) -> Dict:
        """
        Reschedule an existing appointment to a new timeslot.
        
        Args:
            appointment_id: ID of the currently scheduled appointment to reschedule
            new_appointment_id: ID of the new appointment slot
            patient_id: The athenaNet patient ID (required)
            appointment_cancel_reason_id: Optional cancel reason ID for the original appointment
            ignore_schedulable_permission: Allow booking regardless of web settings (default: True)
            no_patient_case: Bypass patient case creation for new patients (default: False)
            reason_id: Optional appointment reason ID (uses original if not provided)
            reschedule_reason: Optional text explanation why the appointment is being rescheduled
            
        Returns:
            Dictionary with rescheduled appointment details
        """
        try:
            logger.info(f"Rescheduling appointment {appointment_id} to {new_appointment_id} for patient {patient_id}")
            
            # Get access token
            token = await self.get_access_token()
            
            # Prepare the reschedule request
            url = f"{self.base_url}/{self.practice_id}/appointments/{appointment_id}/reschedule"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            # Prepare reschedule data according to Athena API specification
            reschedule_data = {
                "patientid": patient_id,  # Required
                "newappointmentid": new_appointment_id  # Required
            }
            
            # Add optional parameters if provided
            if appointment_cancel_reason_id is not None:
                reschedule_data["appointmentcancelreasonid"] = str(appointment_cancel_reason_id)
            
            if ignore_schedulable_permission:
                reschedule_data["ignoreschedulablepermission"] = "true"
            else:
                reschedule_data["ignoreschedulablepermission"] = "false"
            
            if no_patient_case:
                reschedule_data["nopatientcase"] = "true"
            else:
                reschedule_data["nopatientcase"] = "false"
            
            if reason_id is not None:
                reschedule_data["reasonid"] = str(reason_id)
            
            if reschedule_reason:
                reschedule_data["reschedulereason"] = reschedule_reason
            
            logger.info(f"Making appointment reschedule request to: {url}")
            logger.info(f"Reschedule data: {reschedule_data}")
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.put(url, data=reschedule_data, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully rescheduled appointment: {result}")
                    return result
                else:
                    logger.error(f"Failed to reschedule appointment: {response.status_code} - {response.text}")
                    raise Exception(f"Appointment reschedule failed with status {response.status_code}: {response.text}")
                    
        except Exception as e:
            logger.error(f"Error rescheduling appointment: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise
    
    async def get_appointment_notes(
        self,
        appointment_id: str,
        show_deleted: bool = False,
        limit: int = 1500,
        offset: int = 0
    ) -> List[Dict]:
        """
        Get appointment notes for a specific appointment.
        This is used to retrieve clinical notes and instructions for pre/post-operative questions.
        
        Args:
            appointment_id: ID of the appointment to get notes for
            show_deleted: Include deleted notes in results (default: False)
            limit: Number of entries to return (default: 1500, max: 5000)
            offset: Starting point of entries; 0-indexed (default: 0)
            
        Returns:
            List of appointment notes with details
        """
        try:
            logger.info(f"Getting appointment notes for appointment {appointment_id}")
            
            # Get access token
            token = await self.get_access_token()
            
            # Prepare the request
            url = f"{self.base_url}/{self.practice_id}/appointments/{appointment_id}/notes"
            
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            # Prepare query parameters
            params = {
                'limit': min(limit, 5000),  # Cap at max 5000
                'offset': offset
            }
            
            if show_deleted:
                params['showdeleted'] = 'true'
            
            logger.info(f"Making appointment notes request to: {url}")
            logger.info(f"Parameters: {params}")
            
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
                response = await client.get(url, params=params, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    logger.info(f"Successfully retrieved appointment notes: {len(result.get('notes', []))} notes found")
                    
                    # Return the notes list
                    notes = result.get("notes", [])
                    return notes
                else:
                    logger.error(f"Failed to get appointment notes: {response.status_code} - {response.text}")
                    raise Exception(f"Appointment notes request failed with status {response.status_code}: {response.text}")
                    
        except Exception as e:
            logger.error(f"Error getting appointment notes: {str(e)}")
            import traceback
            logger.error(f"Full traceback: {traceback.format_exc()}")
            raise


import sys
import os
import logging
import asyncio
import httpx
import csv
from httpx import Timeout
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from pydantic import BaseModel

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.medofficehq.core.config import settings
from app.medofficehq.services.athena_service import AthenaService

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MissingSlipsRequest(BaseModel):
    """Request model for Missing Slips Filter"""
    start_date: Optional[str] = None  # MM/DD/YYYY format
    end_date: Optional[str] = None    # MM/DD/YYYY format

class MissingSlipsResponse(BaseModel):
    """Response model for Missing Slips Filter"""
    success: bool
    message: str
    total_appointments: int
    missing_slips_count: int
    appointments: List[Dict]
    csv_filename: Optional[str] = None
    details: Optional[dict] = None

class MissingSlipsFilter:
    """
    Filter to identify appointments that are missing slips.
    """
    
    def __init__(self):
        """Initialize the missing slips filter"""
        self.name = "Missing Slips Filter"
        self.version = "1.0"
        
        # Get production credentials (this is a production-only backend)
        credentials = environment_manager.get_athena_credentials(AthenaEnvironment.PRODUCTION)
        
        # API configuration
        self.base_url = credentials["base_url"]
        self.practice_id = credentials["practice_id"]
        
        # Initialize AthenaService with production credentials
        self.athena_service = AthenaService(
            client_id=credentials["client_id"],
            client_secret=credentials["client_secret"],
            practice_id=credentials["practice_id"],
            base_url=credentials["base_url"],
            environment="production"
        )
        
        logger.info(f"Initialized {self.name} v{self.version}")
    
    async def get_missing_slips_appointments(self, start_date: str = None, end_date: str = None) -> MissingSlipsResponse:
        """
        Get appointments that are missing slips for the last 90 days by default
        
        Args:
            start_date: Start date in MM/DD/YYYY format (optional, defaults to 90 days ago)
            end_date: End date in MM/DD/YYYY format (optional, defaults to today)
            
        Returns:
            MissingSlipsResponse with appointments missing slips
        """
        try:
            token = await self.athena_service.get_access_token()
            
            # If no dates provided, use last 90 days by default
            if not start_date or not end_date:
                end_date_obj = datetime.now()
                start_date_obj = end_date_obj - timedelta(days=90)
                print(f"Using default date range: Last 90 days ({start_date_obj.strftime('%m/%d/%Y')} to {end_date_obj.strftime('%m/%d/%Y')})")
            else:
                # Convert dates to the format expected by Athena API
                start_date_obj = datetime.strptime(start_date, "%m/%d/%Y")
                end_date_obj = datetime.strptime(end_date, "%m/%d/%Y")
            
            missing_slips_appointments = []
            total_appointments_processed = 0
            
            # Fetch appointments month by month
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
                
                print(f"Fetching appointments from {month_start_str} to {month_end_str}")
                
                url = f"{self.base_url}/{self.practice_id}/appointments/booked"
                params = {
                    'startdate': month_start_str,
                    'enddate': month_end_str,
                    'departmentid': '1',
                    'showpatientdetail': 'true',
                    'showinsurance': 'true',
                    'showclaimdetail': 'true',
                    'showexpectedprocedurecodes': 'true'
                }
                
                headers = {
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json'
                }
                
                # Use longer timeout for large date ranges (180 seconds)
                async with httpx.AsyncClient(timeout=Timeout(180.0)) as client:
                    try:
                        response = await client.get(url, params=params, headers=headers)
                        
                        if response.status_code == 200:
                            data = response.json()
                            if 'appointments' in data:
                                print(f"Found {len(data['appointments'])} appointments for this month")
                                total_appointments_processed += len(data['appointments'])
                                
                                # Filter for missing slips
                                for appointment in data['appointments']:
                                    if self._is_missing_slip(appointment):
                                        missing_slips_appointments.append(appointment)
                                        print(f"Found missing slip: Appointment {appointment.get('appointmentid', 'N/A')}")
                            else:
                                print(f"No appointments found for this month")
                        else:
                            print(f"API error: {response.status_code}")
                            print(f"Response: {response.text}")
                    except Exception as e:
                        print(f"Error fetching data for {month_start_str} to {month_end_str}: {str(e)}")
                    
                    # Add small delay to avoid rate limiting
                    await asyncio.sleep(0.5)
                
                # Move to next month
                current_date = next_month
            
            print(f"Found {len(missing_slips_appointments)} appointments missing slips")
            
            # Export to CSV
            csv_filename = None
            if missing_slips_appointments:
                csv_filename = self.export_missing_slips_to_csv(missing_slips_appointments)
            
            return MissingSlipsResponse(
                success=True,
                message=f"Missing slips analysis completed. Found {len(missing_slips_appointments)} appointments missing slips.",
                total_appointments=total_appointments_processed,
                missing_slips_count=len(missing_slips_appointments),
                appointments=missing_slips_appointments,
                csv_filename=csv_filename,
                details={
                    "date_range": f"{start_date_obj.strftime('%m/%d/%Y')} to {end_date_obj.strftime('%m/%d/%Y')}",
                    "total_appointments_processed": total_appointments_processed,
                    "missing_slips_percentage": round((len(missing_slips_appointments) / total_appointments_processed * 100), 2) if total_appointments_processed > 0 else 0
                }
            )
            
        except Exception as e:
            logger.error(f"Error fetching missing slips appointments: {e}")
            import traceback
            print(f"Full error details: {traceback.format_exc()}")
            return MissingSlipsResponse(
                success=False,
                message=f"Error during analysis: {str(e)}",
                total_appointments=0,
                missing_slips_count=0,
                appointments=[],
                csv_filename=None,
                details={"error": str(e)}
            )
    
    def _is_missing_slip(self, appointment: Dict) -> bool:
        """
        Check if an appointment is missing a slip
        
        Args:
            appointment: Appointment data
            
        Returns:
            True if appointment is missing slip, False otherwise
        """
        # Check if appointment has claims
        if 'claims' not in appointment or not appointment['claims']:
            return True
        
        # Check if any claim has procedures
        for claim in appointment['claims']:
            if 'procedures' in claim and claim['procedures']:
                # If there are procedures, appointment is not missing slip
                return False
        
        # If we get here, appointment has claims but no procedures
        return True
    
    def export_missing_slips_to_csv(self, missing_slips: List[Dict], filename: Optional[str] = None) -> str:
        """
        Export missing slips data to CSV file
        
        Args:
            missing_slips: List of appointments missing slips
            filename: Optional filename for export
            
        Returns:
            Path to the exported file
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"missing_slips_{timestamp}.csv"
        
        if not missing_slips:
            print("No missing slips to export")
            return ""
        
        fieldnames = [
            'appointment_id', 'patient_id', 'patient_name', 'appointment_date', 
            'appointment_type', 'encounter_state', 'encounter_status', 'encounter_id',
            'charge_entry_not_required', 'department_id', 'provider_id', 
            'insurance_provider', 'insurance_member_id', 'claims_count',
            'scheduled_datetime', 'checkin_datetime', 'checkout_datetime'
        ]
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for appointment in missing_slips:
                    # Get patient info
                    patient_info = appointment.get('patient', {})
                    
                    # Get insurance info
                    insurances = appointment.get('insurances', [])
                    primary_insurance = insurances[0] if insurances else {}
                    
                    # Get claims info
                    claims = appointment.get('claims', [])
                    
                    # Create detailed record
                    missing_slip_info = {
                        'appointment_id': appointment.get('appointmentid', ''),
                        'patient_id': appointment.get('patientid', ''),
                        'patient_name': f"{patient_info.get('firstname', '')} {patient_info.get('lastname', '')}",
                        'appointment_date': appointment.get('date', ''),
                        'appointment_type': appointment.get('appointmenttype', ''),
                        'encounter_state': appointment.get('encounterstate', ''),
                        'encounter_status': appointment.get('encounterstatus', ''),
                        'encounter_id': appointment.get('encounterid', ''),
                        'charge_entry_not_required': appointment.get('chargeentrynotrequired', False),
                        'department_id': appointment.get('departmentid', ''),
                        'provider_id': appointment.get('providerid', ''),
                        'insurance_provider': primary_insurance.get('insurancepayername', ''),
                        'insurance_member_id': primary_insurance.get('insuranceidnumber', ''),
                        'claims_count': len(claims),
                        'scheduled_datetime': appointment.get('scheduleddatetime', ''),
                        'checkin_datetime': appointment.get('checkindatetime', ''),
                        'checkout_datetime': appointment.get('checkoutdatetime', '')
                    }
                    
                    writer.writerow(missing_slip_info)
            
            print(f"Missing slips exported successfully to {filename}")
            print(f"Total records exported: {len(missing_slips)}")
            return filename
            
        except Exception as e:
            print(f"Error exporting to CSV: {e}")
            return ""

# Global instance for use by other modules
missing_slips_filter = MissingSlipsFilter()

async def main():
    """Main function for standalone testing"""
    print(f"Finding appointments missing slips for last 90 days (default)")
    
    # Test with default 90 days
    response = await missing_slips_filter.get_missing_slips_appointments()
    
    print(f"\nResults:")
    print(f"Success: {response.success}")
    print(f"Message: {response.message}")
    print(f"Total appointments processed: {response.total_appointments}")
    print(f"Missing slips count: {response.missing_slips_count}")
    
    if response.appointments:
        print("\nSample appointments:")
        for i, appointment in enumerate(response.appointments[:5]):  # Show first 5
            print(f"{i+1}. Appointment ID: {appointment.get('appointmentid', 'N/A')}")
            print(f"   Patient: {appointment.get('patientname', 'N/A')}")
            print(f"   Date: {appointment.get('date', 'N/A')}")
        
        if response.csv_filename:
            print(f"\nCSV exported to: {response.csv_filename}")

if __name__ == "__main__":
    asyncio.run(main()) 
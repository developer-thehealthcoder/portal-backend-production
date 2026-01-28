"""
Hold Records Filter

This module filters appointments to find those that have hold records.
Used by automation rules to identify appointments with HOLD status.

Author: Your Name
Date: 2025-01-07
Version: 1.0
"""

import sys
import os
import logging
import asyncio
import httpx
import csv
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional
from httpx import Timeout
from pydantic import BaseModel

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.medofficehq.core.config import settings
from app.medofficehq.services.athena_service import AthenaService

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class HoldRecordsRequest(BaseModel):
    """Request model for Hold Records Filter"""
    start_date: str  # MM/DD/YYYY format
    end_date: str    # MM/DD/YYYY format

class HoldRecordsResponse(BaseModel):
    """Response model for Hold Records Filter"""
    success: bool
    message: str
    total_appointments: int
    hold_records_count: int
    appointments: List[Dict]
    csv_filename: Optional[str] = None
    details: Optional[dict] = None

class HoldRecordsFilter:
    """
    Filter to identify appointments that have hold records.
    """
    
    def __init__(self):
        """Initialize the hold records filter"""
        self.name = "Hold Records Filter"
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
    
    async def get_departments(self, token: str) -> List[str]:
        """
        Get all department IDs for the practice
        
        Args:
            token: Access token for API calls
            
        Returns:
            List of department IDs
        """
        try:
            url = f"{self.base_url}/{self.practice_id}/departments"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            async with httpx.AsyncClient(timeout=Timeout(60.0)) as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    departments = data.get('departments', [])
                    department_ids = [dept.get('departmentid') for dept in departments if dept.get('departmentid')]
                    
                    print(f"Found {len(department_ids)} departments: {department_ids}")
                    return department_ids
                else:
                    print(f"Error fetching departments: {response.status_code}")
                    return ['1']  # Fallback to department 1
                    
        except Exception as e:
            print(f"Error fetching departments: {str(e)}")
            return ['1']  # Fallback to department 1
    
    async def get_hold_records_appointments(self, start_date: str, end_date: str) -> HoldRecordsResponse:
        """
        Get appointments that have hold records for the given date range across all departments
        
        Args:
            start_date: Start date in MM/DD/YYYY format
            end_date: End date in MM/DD/YYYY format
            
        Returns:
            HoldRecordsResponse with appointments having hold records
        """
        try:
            token = await self.athena_service.get_access_token()
            
            # Get all departments first
            department_ids = await self.get_departments(token)
            
            # Convert dates to the format expected by Athena API
            start_date_obj = datetime.strptime(start_date, "%m/%d/%Y")
            end_date_obj = datetime.strptime(end_date, "%m/%d/%Y")
            
            hold_records_appointments = []
            total_appointments_processed = 0
            
            # Fetch appointments for each department, month by month
            for department_id in department_ids:
                print(f"Processing Department ID: {department_id}")
                
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
                    
                    print(f"Fetching appointments from {month_start_str} to {month_end_str} for Department {department_id}")
                    
                    url = f"{self.base_url}/{self.practice_id}/appointments/booked"
                    params = {
                        'startdate': month_start_str,
                        'enddate': month_end_str,
                        'departmentid': department_id,
                        'showpatientdetail': 'true',
                        'showinsurance': 'true',
                        'showclaimdetail': 'true',
                        'showexpectedprocedurecodes': 'true'
                    }
                    
                    print(f"URL: {url}")
                    print(f"Params: {params}")
                    
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
                                    print(f"Found {len(data['appointments'])} appointments for this month in Department {department_id}")
                                    total_appointments_processed += len(data['appointments'])
                                    # Filter for appointments with hold records
                                    for appointment in data['appointments']:
                                        # Enhanced debugging: Show ALL appointments with any balance
                                        if 'claims' in appointment and appointment['claims']:
                                            for claim in appointment['claims']:
                                                if claim.get('balance') and float(claim.get('balance', 0)) > 0:
                                                    print(f"Appointment {appointment.get('appointmentid', 'N/A')} has balance: {claim.get('balance')}")
                                                    print(f"Claim status: {claim.get('status')}")
                                                    if 'primaryinsurancepayer' in claim:
                                                        print(f"Primary insurance status: {claim['primaryinsurancepayer'].get('status')}")
                                                    else:
                                                        print(f"No primary insurance payer found")
                                                    
                                                    # Check if this would be detected as hold record
                                                    is_hold = self._has_hold_record(appointment)
                                                    print(f"Would be detected as hold: {is_hold}")
                                                    
                                                    if not is_hold:
                                                        print(f"MISSED - Full claim structure: {claim}")
                                                    break
                                        
                                        # Original logic
                                        if self._has_hold_record(appointment):
                                            hold_records_appointments.append(appointment)
                                            print(f"Found hold record: Appointment {appointment.get('appointmentid', 'N/A')} in Department {department_id}")
                                else:
                                    print(f"No appointments found for this month in Department {department_id}")
                            else:
                                print(f"API error: {response.status_code}")
                                print(f"Response: {response.text}")
                        except Exception as e:
                            print(f"Error fetching data for {month_start_str} to {month_end_str} in Department {department_id}: {str(e)}")
                        
                        # Add small delay to avoid rate limiting
                        await asyncio.sleep(0.5)
                    
                    # Move to next month
                    current_date = next_month
                
                # Reset current_date for next department
                current_date = start_date_obj
            
            print(f"Found {len(hold_records_appointments)} appointments with hold records across all departments")
            print(f"Total appointments processed: {total_appointments_processed}")
            print(f"Hold records found: {len(hold_records_appointments)}")
            
            # Export to CSV
            csv_filename = None
            if hold_records_appointments:
                csv_filename = self.export_hold_records_to_csv(hold_records_appointments)
            
            return HoldRecordsResponse(
                success=True,
                message=f"Hold records analysis completed. Found {len(hold_records_appointments)} appointments with hold records.",
                total_appointments=total_appointments_processed,
                hold_records_count=len(hold_records_appointments),
                appointments=hold_records_appointments,
                csv_filename=csv_filename,
                details={
                    "date_range": f"{start_date} to {end_date}",
                    "total_appointments_processed": total_appointments_processed,
                    "hold_records_percentage": round((len(hold_records_appointments) / total_appointments_processed * 100), 2) if total_appointments_processed > 0 else 0,
                    "departments_processed": len(department_ids)
                }
            )
            
        except Exception as e:
            logger.error(f"Error fetching hold records appointments: {e}")
            import traceback
            print(f"Full error details: {traceback.format_exc()}")
            return HoldRecordsResponse(
                success=False,
                message=f"Error during analysis: {str(e)}",
                total_appointments=0,
                hold_records_count=0,
                appointments=[],
                csv_filename=None,
                details={"error": str(e)}
            )
    
    def _has_hold_record(self, appointment: Dict) -> bool:
        """
        Check if an appointment has a hold record
        
        Args:
            appointment: Appointment data
            
        Returns:
            True if appointment has hold record, False otherwise
        """
        # Check if appointment has claims
        if 'claims' not in appointment or not appointment['claims']:
            return False
        
        # Check each claim for hold status
        for claim in appointment['claims']:
            # Check primary insurance payer status
            if 'primaryinsurancepayer' in claim:
                primary_insurance = claim['primaryinsurancepayer']
                if primary_insurance.get('status') == 'HOLD':
                    return True
            
            # Check if claim itself has hold status
            if claim.get('status') == 'HOLD':
                return True
            
            # Check for other possible hold indicators
            # Check if claim has any balance (outstanding amount)
            if claim.get('balance') and float(claim.get('balance', 0)) > 0:
                # This might be a hold record - let's check further
                if claim.get('status') in ['PENDING', 'SUBMITTED', 'REJECTED']:
                    return True
                
                # Also check if there's any balance regardless of status
                # This catches cases where balance > 0 but status might be different
                return True
        
        return False
    
    def export_hold_records_to_csv(self, hold_records: List[Dict], filename: Optional[str] = None) -> str:
        """
        Export hold records data to CSV file
        
        Args:
            hold_records: List of appointments with hold records
            filename: Optional filename for export
            
        Returns:
            Path to the exported file
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"hold_records_{timestamp}.csv"
        
        if not hold_records:
            print("No hold records to export")
            return ""
        
        fieldnames = [
            'appointment_id', 'patient_id', 'patient_name', 'appointment_date', 
            'appointment_type', 'encounter_state', 'encounter_status', 'encounter_id',
            'charge_entry_not_required', 'department_id', 'provider_id', 
            'insurance_provider', 'insurance_member_id', 'hold_status', 
            'primary_insurance_package_id', 'balance', 'primary_patient_insurance_id',
            'claims_count', 'scheduled_datetime', 'checkin_datetime', 'checkout_datetime'
        ]
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for appointment in hold_records:
                    # Get patient info
                    patient_info = appointment.get('patient', {})
                    
                    # Get insurance info
                    insurances = appointment.get('insurances', [])
                    primary_insurance = insurances[0] if insurances else {}
                    
                    # Get claims info
                    claims = appointment.get('claims', [])
                    
                    # Find hold record details
                    hold_status = "N/A"
                    primary_insurance_package_id = "N/A"
                    balance = "N/A"
                    primary_patient_insurance_id = "N/A"
                    
                    for claim in claims:
                        if 'primaryinsurancepayer' in claim:
                            primary_payer = claim['primaryinsurancepayer']
                            if primary_payer.get('status') == 'HOLD':
                                hold_status = primary_payer.get('status', 'HOLD')
                                primary_insurance_package_id = primary_payer.get('primaryinsurancepackageid', 'N/A')
                                balance = primary_payer.get('balance', 'N/A')
                                primary_patient_insurance_id = primary_payer.get('primarypatientinsuranceid', 'N/A')
                                break
                        elif claim.get('status') == 'HOLD':
                            hold_status = 'HOLD'
                            break
                    
                    # Create detailed record
                    hold_record_info = {
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
                        'hold_status': hold_status,
                        'primary_insurance_package_id': primary_insurance_package_id,
                        'balance': balance,
                        'primary_patient_insurance_id': primary_patient_insurance_id,
                        'claims_count': len(claims),
                        'scheduled_datetime': appointment.get('scheduleddatetime', ''),
                        'checkin_datetime': appointment.get('checkindatetime', ''),
                        'checkout_datetime': appointment.get('checkoutdatetime', '')
                    }
                    
                    writer.writerow(hold_record_info)
            
            print(f"Hold records exported successfully to {filename}")
            print(f"Total records exported: {len(hold_records)}")
            return filename
            
        except Exception as e:
            print(f"Error exporting to CSV: {e}")
            return ""

# Global instance for use by other modules
hold_records_filter = HoldRecordsFilter()

async def main():
    """Main function for standalone testing"""
    start_date = "11/01/2024"  # Updated to match user's requirement
    end_date = "06/01/2025"  # Current date as end date
    
    print(f"Finding appointments with hold records from {start_date} to {end_date}")
    
    response = await hold_records_filter.get_hold_records_appointments(start_date, end_date)
    
    print(f"\nResults:")
    print(f"Total appointments with hold records: {len(response.appointments)}")
    
    if response.appointments:
        print("\nSample appointments:")
        for i, appointment in enumerate(response.appointments[:5]):  # Show first 5
            print(f"{i+1}. Appointment ID: {appointment.get('appointmentid', 'N/A')}")
            print(f"   Patient: {appointment.get('patientname', 'N/A')}")
            print(f"   Date: {appointment.get('date', 'N/A')}")
            
            # Show hold details
            claims = appointment.get('claims', [])
            for claim in claims:
                if 'primaryinsurancepayer' in claim:
                    primary_payer = claim['primaryinsurancepayer']
                    if primary_payer.get('status') == 'HOLD':
                        print(f"   Hold Status: {primary_payer.get('status')}")
                        print(f"   Balance: {primary_payer.get('balance')}")
                        print(f"   Package ID: {primary_payer.get('primaryinsurancepackageid')}")
                        break
        
        # Export to CSV
        if response.csv_filename:
            print(f"\nCSV exported to: {response.csv_filename}")

if __name__ == "__main__":
    asyncio.run(main()) 
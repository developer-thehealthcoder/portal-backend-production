"""
Test Script: Check for JR3490 Procedure Code in Missing Slips

This script:
1. Gets all missing slips appointments
2. For each appointment, fetches procedure codes from services API
3. Checks if JR3490 procedure code is present
4. Generates CSV with results

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
from datetime import datetime
from typing import Dict, List, Optional
from httpx import Timeout

# Add the parent directory to the path so we can import from app
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from app.core.config import settings
    from app.services.athena_service import AthenaService
    from rules.filters.missing_slips_filter import missing_slips_filter
except ImportError as e:
    print(f"Import error: {e}")
    # Fallback for when running directly
    import os
    from pydantic_settings import BaseSettings
    
    class Settings(BaseSettings):
        API_V1_STR: str = "/api/v1"
        PROJECT_NAME: str = "Athena Health API Integration"
        ATHENA_API_BASE_URL: str = "https://api.platform.athenahealth.com/v1"
        ATHENA_PRACTICE_ID: str = os.getenv("ATHENA_PRACTICE_ID", "")
        ATHENA_Client_ID: str = os.getenv("ATHENA_Client_ID", "")
        ATHENA_Client_Secret: str = os.getenv("ATHENA_Client_Secret", "")
        
        class Config:
            env_file = ".env"
            case_sensitive = True
    
    settings = Settings()

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class JR3490TestScript:
    """
    Test script to check for JR3490 procedure code in missing slips
    """
    
    def __init__(self):
        """Initialize the test script"""
        self.name = "JR3490 Test Script"
        self.version = "1.0"
        
        # API configuration
        self.base_url = settings.ATHENA_API_BASE_URL
        self.practice_id = settings.ATHENA_PRACTICE_ID
        
        # Initialize AthenaService for API calls
        self.athena_service = AthenaService()
        
        # Target procedure code to search for
        self.target_procedure_code = "JR3490"
        
        logger.info(f"Initialized {self.name} v{self.version}")
    
    async def get_missing_slips_appointments(self, start_date: str, end_date: str) -> List[Dict]:
        """
        Get all missing slips appointments using the existing filter
        
        Args:
            start_date: Start date in MM/DD/YYYY format
            end_date: End date in MM/DD/YYYY format
            
        Returns:
            List of appointments missing slips
        """
        try:
            print(f"🔍 Getting missing slips appointments from {start_date} to {end_date}")
            appointments = await missing_slips_filter.get_missing_slips_appointments(start_date, end_date)
            print(f"✅ Found {len(appointments)} missing slips appointments")
            return appointments
        except Exception as e:
            logger.error(f"Error getting missing slips appointments: {e}")
            return []
    
    async def get_encounter_services(self, encounter_id: str, token: str) -> List[Dict]:
        """
        Get procedure codes for a specific encounter
        
        Args:
            encounter_id: Encounter ID
            token: Access token for API calls
            
        Returns:
            List of procedures for the encounter
        """
        try:
            url = f"{self.base_url}/{self.practice_id}/encounter/{encounter_id}/services"
            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }
            
            async with httpx.AsyncClient(timeout=Timeout(30.0)) as client:
                response = await client.get(url, headers=headers)
                
                if response.status_code == 200:
                    data = response.json()
                    procedures = data.get('procedures', [])
                    print(f"    📋 Found {len(procedures)} procedures for encounter {encounter_id}")
                    return procedures
                else:
                    print(f"    ❌ API error for encounter {encounter_id}: {response.status_code}")
                    return []
                    
        except Exception as e:
            print(f"    ❌ Error fetching services for encounter {encounter_id}: {str(e)}")
            return []
    
    def check_for_jr3490(self, procedures: List[Dict]) -> bool:
        """
        Check if JR3490 procedure code is present in the procedures list
        
        Args:
            procedures: List of procedure dictionaries
            
        Returns:
            True if JR3490 is found, False otherwise
        """
        for procedure in procedures:
            procedure_code = procedure.get('procedurecode', '')
            if self.target_procedure_code in procedure_code:
                print(f"    ✅ Found {self.target_procedure_code} in procedure: {procedure_code}")
                return True
        
        return False
    
    async def process_missing_slips_for_jr3490(self, start_date: str, end_date: str) -> List[Dict]:
        """
        Process all missing slips and check for JR3490 procedure code
        
        Args:
            start_date: Start date in MM/DD/YYYY format
            end_date: End date in MM/DD/YYYY format
            
        Returns:
            List of appointments with JR3490 check results
        """
        try:
            # Get missing slips appointments
            missing_slips = await self.get_missing_slips_appointments(start_date, end_date)
            
            if not missing_slips:
                print("❌ No missing slips appointments found")
                return []
            
            # Get access token
            token = await self.athena_service.get_access_token()
            
            results = []
            total_processed = 0
            
            print(f"\n🔍 Checking {len(missing_slips)} appointments for {self.target_procedure_code}...")
            
            for appointment in missing_slips:
                appointment_id = appointment.get('appointmentid', 'N/A')
                encounter_id = appointment.get('encounterid', '')
                
                print(f"\n📋 Processing Appointment {appointment_id} (Encounter: {encounter_id})")
                
                has_jr3490 = False
                procedures_found = []
                
                if encounter_id:
                    # Get procedures for this encounter
                    procedures = await self.get_encounter_services(encounter_id, token)
                    procedures_found = procedures
                    
                    # Check for JR3490
                    has_jr3490 = self.check_for_jr3490(procedures)
                    
                    if has_jr3490:
                        print(f"    ✅ Appointment {appointment_id} has {self.target_procedure_code}")
                    else:
                        print(f"    ❌ Appointment {appointment_id} does not have {self.target_procedure_code}")
                else:
                    print(f"    ⚠️  No encounter ID found for appointment {appointment_id}")
                
                # Create result record
                result = {
                    'appointment_id': appointment_id,
                    'encounter_id': encounter_id,
                    'patient_id': appointment.get('patientid', ''),
                    'patient_name': appointment.get('patientname', ''),
                    'appointment_date': appointment.get('date', ''),
                    'department_id': appointment.get('departmentid', ''),
                    'has_jr3490': has_jr3490,
                    'procedures_count': len(procedures_found),
                    'procedures_list': ', '.join([p.get('procedurecode', '') for p in procedures_found])
                }
                
                results.append(result)
                total_processed += 1
                
                # Add small delay to avoid rate limiting
                await asyncio.sleep(0.5)
            
            print(f"\n✅ Processed {total_processed} appointments")
            return results
            
        except Exception as e:
            logger.error(f"Error processing missing slips for JR3490: {e}")
            import traceback
            print(f"❌ Full error details: {traceback.format_exc()}")
            return []
    
    def export_results_to_csv(self, results: List[Dict], filename: Optional[str] = None) -> str:
        """
        Export results to CSV file
        
        Args:
            results: List of result dictionaries
            filename: Optional filename for export
            
        Returns:
            Path to the exported file
        """
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"jr3490_test_results_{timestamp}.csv"
        
        if not results:
            print("No results to export")
            return ""
        
        fieldnames = [
            'appointment_id', 'encounter_id', 'patient_id', 'patient_name', 
            'appointment_date', 'department_id', 'has_jr3490', 'procedures_count',
            'procedures_list'
        ]
        
        try:
            with open(filename, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                writer.writeheader()
                
                for result in results:
                    writer.writerow(result)
            
            print(f"✅ Results exported successfully to {filename}")
            print(f"📄 Total records exported: {len(results)}")
            return filename
            
        except Exception as e:
            print(f"❌ Error exporting to CSV: {e}")
            return ""

# Global instance for use by other modules
jr3490_test_script = JR3490TestScript()

async def main():
    """Main function for standalone testing"""
    start_date = "03/05/2025"
    end_date = "05/07/2025"
    
    print(f"🔍 Testing for JR3490 procedure code in missing slips from {start_date} to {end_date}")
    
    results = await jr3490_test_script.process_missing_slips_for_jr3490(start_date, end_date)
    
    print(f"\n📋 Results:")
    print(f"Total appointments processed: {len(results)}")
    
    if results:
        # Count results
        with_jr3490 = sum(1 for r in results if r['has_jr3490'])
        without_jr3490 = len(results) - with_jr3490
        
        print(f"Appointments with JR3490: {with_jr3490}")
        print(f"Appointments without JR3490: {without_jr3490}")
        
        print("\nSample results:")
        for i, result in enumerate(results[:5]):  # Show first 5
            print(f"{i+1}. Appointment ID: {result['appointment_id']}")
            print(f"   Patient: {result['patient_name']}")
            print(f"   Date: {result['appointment_date']}")
            print(f"   Has JR3490: {result['has_jr3490']}")
            print(f"   Procedures count: {result['procedures_count']}")
        
        # Export to CSV
        csv_filename = jr3490_test_script.export_results_to_csv(results)
        if csv_filename:
            print(f"\n📄 CSV exported to: {csv_filename}")

if __name__ == "__main__":
    asyncio.run(main()) 
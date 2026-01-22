"""
Filter API Endpoints

This module provides API endpoints for various filters including:
- Missing Slips Filter
- Hold Records Filter

Author: Adil
Date: 2025-01-07
Version: 1.0
"""

from fastapi import APIRouter, HTTPException
from typing import List, Dict, Optional
from pydantic import BaseModel

# Import filter classes
from app.medofficehq.rules.filters.missing_slips_filter import MissingSlipsFilter, MissingSlipsRequest, MissingSlipsResponse
from app.medofficehq.rules.filters.hold_records_filter import HoldRecordsFilter, HoldRecordsRequest, HoldRecordsResponse

# Create router
router = APIRouter()

# Initialize filter instances
missing_slips_filter = MissingSlipsFilter()
hold_records_filter = HoldRecordsFilter()

# New Pydantic models for filter list API
class FilterInfo(BaseModel):
    """Information about a specific filter"""
    filter_id: str
    name: str
    description: str
    endpoint: str
    request_model: str
    response_model: str
    parameters: List[Dict[str, str]]  # List of parameter descriptions

class AvailableFiltersResponse(BaseModel):
    """Response model for available filters"""
    success: bool
    message: str
    filters: List[FilterInfo]

@router.get("/list", response_model=AvailableFiltersResponse)
async def get_available_filters():
    """
    Get list of all available filters
    """
    try:
        filters = [
            FilterInfo(
                filter_id="missing-slips",
                name="Missing Slips Filter",
                description="Identifies appointments that are missing charge slips. Looks for appointments with encounter status not CLOSED, charge entry required, and no claims or no procedures in claims. Defaults to last 90 days if no date range provided.",
                endpoint="/filters/missing-slips",
                request_model="MissingSlipsRequest",
                response_model="MissingSlipsResponse",
                parameters=[
                    {
                        "name": "start_date",
                        "type": "string (optional)",
                        "format": "MM/DD/YYYY",
                        "description": "Start date for filter range. If not provided, defaults to 90 days ago."
                    },
                    {
                        "name": "end_date", 
                        "type": "string (optional)",
                        "format": "MM/DD/YYYY", 
                        "description": "End date for filter range. If not provided, defaults to today."
                    }
                ]
            ),
            FilterInfo(
                filter_id="hold-records",
                name="Hold Records Filter",
                description="Identifies appointments that have hold records. Looks for appointments with claims that have HOLD status, pending status, or outstanding balances.",
                endpoint="/filters/hold-records",
                request_model="HoldRecordsRequest",
                response_model="HoldRecordsResponse",
                parameters=[
                    {
                        "name": "start_date",
                        "type": "string (required)",
                        "format": "MM/DD/YYYY",
                        "description": "Start date for filter range."
                    },
                    {
                        "name": "end_date",
                        "type": "string (required)", 
                        "format": "MM/DD/YYYY",
                        "description": "End date for filter range."
                    }
                ]
            )
        ]
        
        return AvailableFiltersResponse(
            success=True,
            message=f"Found {len(filters)} available filters",
            filters=filters
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/missing-slips", response_model=MissingSlipsResponse)
async def get_missing_slips(request: MissingSlipsRequest):
    """
    Get appointments that are missing slips
    
    Args:
        request: MissingSlipsRequest with optional start_date and end_date
        
    Returns:
        MissingSlipsResponse with appointments missing slips
    """
    try:
        print("Missing Slips Filter API called")
        print(f"Request: start_date={request.start_date}, end_date={request.end_date}")
        
        # Call the filter
        response = await missing_slips_filter.get_missing_slips_appointments(
            start_date=request.start_date,
            end_date=request.end_date
        )
        
        print(f"Filter completed: {response.success}")
        print(f"Message: {response.message}")
        print(f"Total appointments: {response.total_appointments}")
        print(f"Missing slips: {response.missing_slips_count}")
        
        return response
        
    except Exception as e:
        print(f"Error in missing slips API: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing missing slips filter: {str(e)}")

@router.post("/hold-records", response_model=HoldRecordsResponse)
async def get_hold_records(request: HoldRecordsRequest):
    """
    Get appointments that have hold records
    
    Args:
        request: HoldRecordsRequest with start_date and end_date
        
    Returns:
        HoldRecordsResponse with appointments having hold records
    """
    try:
        print("Hold Records Filter API called")
        print(f"Request: start_date={request.start_date}, end_date={request.end_date}")
        
        # Call the filter
        response = await hold_records_filter.get_hold_records_appointments(
            start_date=request.start_date,
            end_date=request.end_date
        )
        
        print(f"Filter completed: {response.success}")
        print(f"Message: {response.message}")
        print(f"Total appointments: {response.total_appointments}")
        print(f"Hold records: {response.hold_records_count}")
        
        return response
        
    except Exception as e:
        print(f"Error in hold records API: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing hold records filter: {str(e)}")

@router.get("/missing-slips/test")
async def test_missing_slips():
    """
    Test endpoint for missing slips filter (uses default 90 days)
    """
    try:
        print("Testing Missing Slips Filter with default 90 days")
        
        response = await missing_slips_filter.get_missing_slips_appointments()
        
        return {
            "success": response.success,
            "message": response.message,
            "total_appointments": response.total_appointments,
            "missing_slips_count": response.missing_slips_count,
            "csv_filename": response.csv_filename,
            "details": response.details
        }
        
    except Exception as e:
        print(f"Error in missing slips test: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error testing missing slips filter: {str(e)}")

@router.get("/hold-records/test")
async def test_hold_records():
    """
    Test endpoint for hold records filter (uses sample date range)
    """
    try:
        print("Testing Hold Records Filter with sample date range")
        
        # Use a sample date range for testing
        start_date = "11/01/2024"
        end_date = "06/01/2025"
        
        response = await hold_records_filter.get_hold_records_appointments(
            start_date=start_date,
            end_date=end_date
        )
        
        return {
            "success": response.success,
            "message": response.message,
            "total_appointments": response.total_appointments,
            "hold_records_count": response.hold_records_count,
            "csv_filename": response.csv_filename,
            "details": response.details
        }
        
    except Exception as e:
        print(f"Error in hold records test: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error testing hold records filter: {str(e)}") 
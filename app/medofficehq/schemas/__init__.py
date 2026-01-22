"""
Schema definitions for the application.

This module contains Pydantic models for data validation and serialization.
"""

from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime

class Department(BaseModel):
    """Department model"""
    departmentid: str
    name: str
    providerlist: Optional[str] = None
    showclaimtracker: Optional[str] = None
    showexpectedprocedurecodes: Optional[str] = None

class Appointment(BaseModel):
    """Appointment model with enhanced details"""
    appointmentid: str
    patientid: str
    date: str
    starttime: str
    endtime: Optional[str] = None
    appointmenttype: str
    departmentid: str
    providerid: Optional[str] = None
    encounterstate: Optional[str] = None
    encounterstatus: Optional[str] = None
    encounterid: Optional[str] = None
    chargeentrynotrequired: Optional[bool] = None
    scheduleddatetime: Optional[str] = None
    checkindatetime: Optional[str] = None
    checkoutdatetime: Optional[str] = None
    
    # Enhanced fields from showpatientdetail=true
    patient: Optional[Dict] = None
    
    # Enhanced fields from showinsurance=true
    insurances: Optional[List[Dict]] = None
    
    # Enhanced fields from showclaimdetail=true
    claims: Optional[List[Dict]] = None
    
    # Additional fields that might be present
    copay: Optional[float] = None
    appointmentstatus: Optional[str] = None
    visitid: Optional[str] = None
    duration: Optional[int] = None
    appointmentcopay: Optional[Dict] = None

class PatientInfo(BaseModel):
    """Patient information model"""
    patientid: str
    firstname: str
    lastname: str
    dob: Optional[str] = None
    sex: Optional[str] = None
    homephone: Optional[str] = None
    mobilephone: Optional[str] = None
    email: Optional[str] = None

class Insurance(BaseModel):
    """Insurance model"""
    insurancepayername: str
    insuranceidnumber: Optional[str] = None
    insurancepackageid: Optional[str] = None
    status: Optional[str] = None
    balance: Optional[str] = None

class Procedure(BaseModel):
    """Procedure model"""
    procedureid: str
    procedurecode: str
    proceduredescription: Optional[str] = None
    units: Optional[int] = None
    charges: Optional[float] = None
    modifiers: Optional[List[str]] = None

class Diagnosis(BaseModel):
    """Diagnosis model"""
    diagnosisid: str
    icd10code: str
    description: Optional[str] = None
    primary: Optional[bool] = None

# Export all models
__all__ = [
    'Department',
    'Appointment', 
    'PatientInfo',
    'Insurance',
    'Procedure',
    'Diagnosis'
]

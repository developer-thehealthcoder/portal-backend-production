from pydantic import BaseModel
from typing import Optional, List
from datetime import date

class PatientListResponse(BaseModel):
    patient_id: str
    first_name: str
    last_name: str
    dob: str
    appointment_id: str
    department_id: str

class CPTCode(BaseModel):
    code: str
    units: int
    billable: bool

class Diagnosis(BaseModel):
    code: str
    description: str

class Encounter(BaseModel):
    encounter_id: str
    date: str
    cpt_codes: List[CPTCode]
    diagnoses: List[Diagnosis]

class PatientDetailResponse(BaseModel):
    patient_id: str
    first_name: str
    last_name: str
    dob: str
    appointment_id: str
    department_id: str
    encounter_id: str
    encounter_date: str
    cpt_codes: List[str]
    diagnosis_codes: List[str]
    encounters: Optional[List[Encounter]] = None 
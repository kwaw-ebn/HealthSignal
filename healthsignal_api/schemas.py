from datetime import date, datetime
from typing import Literal
from pydantic import BaseModel, Field, model_validator

class ScreeningRequest(BaseModel):
    patient_code: str = Field(min_length=2, max_length=64)
    visit_date: date
    region: str = ""; district: str = ""; community: str = ""; facility: str = ""
    age: int = Field(ge=0, le=120)
    sex: Literal["Female", "Male", "Other", "Unknown"]
    pregnant: bool = False
    disease: Literal["hypertension", "diabetes", "malaria", "tb"]
    systolic_1: int | None = Field(default=None, ge=40, le=300)
    diastolic_1: int | None = Field(default=None, ge=20, le=200)
    systolic_2: int | None = Field(default=None, ge=40, le=300)
    diastolic_2: int | None = Field(default=None, ge=20, le=200)
    pulse: int | None = Field(default=None, ge=20, le=250)
    weight_kg: float | None = Field(default=None, gt=0, le=400)
    height_cm: float | None = Field(default=None, gt=30, le=250)
    glucose_type: Literal["Not tested", "FBS", "RBS"] = "Not tested"
    glucose_mmol_l: float | None = Field(default=None, ge=0, le=50)
    temperature_c: float | None = Field(default=None, ge=30, le=45)
    fever_or_history: bool = False
    malaria_test: Literal["Not done", "RDT", "Microscopy"] = "Not done"
    malaria_result: Literal["Not available", "Negative", "Positive"] = "Not available"
    cough_two_weeks: bool = False; tb_contact: bool = False; night_sweats: bool = False
    unexplained_weight_loss: bool = False; family_history: bool = False; previous_diagnosis: bool = False
    referred: bool = False
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    @model_validator(mode="after")
    def checks(self):
        if self.glucose_type != "Not tested" and self.glucose_mmol_l is None: raise ValueError("Enter the measured glucose result.")
        if self.malaria_result != "Not available" and self.malaria_test == "Not done": raise ValueError("Select the malaria test performed.")
        return self

class ScreeningResult(BaseModel):
    screening_id: str; disease: str
    risk_level: Literal["Low", "Moderate", "High", "Urgent"]
    classification: str; recommendation: str; score: float
    bmi: float | None = None; disclaimer: str; created_at: datetime

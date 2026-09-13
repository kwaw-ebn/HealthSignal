from dataclasses import dataclass
from .schemas import ScreeningRequest

@dataclass
class Decision:
    risk: str; classification: str; recommendation: str; score: float; bmi: float | None = None

def _bmi(d): return round(d.weight_kg / ((d.height_cm / 100) ** 2), 1) if d.weight_kg and d.height_cm else None

def screen(d: ScreeningRequest) -> Decision:
    bmi = _bmi(d)
    if d.disease == "hypertension":
        readings = [(s, x) for s, x in [(d.systolic_1,d.diastolic_1),(d.systolic_2,d.diastolic_2)] if s and x]
        if not readings: return Decision("Moderate","Blood pressure not measured","Take and record two valid blood pressure readings, then repeat screening.",.4,bmi)
        sbp=sum(x[0] for x in readings)/len(readings); dbp=sum(x[1] for x in readings)/len(readings)
        if sbp>=180 or dbp>=120: return Decision("Urgent","Very high blood pressure screening result","Arrange immediate clinical assessment. Do not use this result alone as a diagnosis.",1,bmi)
        if sbp>=140 or dbp>=90: return Decision("High","High blood pressure screening result","Refer for clinical assessment and confirmation according to local protocol.",.8,bmi)
        if sbp>=130 or dbp>=85: return Decision("Moderate","Elevated blood pressure screening result","Repeat measurement and arrange routine clinical follow up.",.55,bmi)
        return Decision("Low","Blood pressure within screening range","Continue routine screening. Clinical review may still be required when other risks are present.",.2,bmi)
    if d.disease == "diabetes":
        if d.glucose_mmol_l is None:
            risk="Moderate" if d.family_history or d.previous_diagnosis else "Low"
            return Decision(risk,"No current glucose measurement","Perform an appropriate glucose test and follow local confirmation protocol.",.45 if risk=="Moderate" else .2,bmi)
        high=(d.glucose_type=="FBS" and d.glucose_mmol_l>=7) or (d.glucose_type=="RBS" and d.glucose_mmol_l>=11.1)
        borderline=(d.glucose_type=="FBS" and d.glucose_mmol_l>=6.1) or (d.glucose_type=="RBS" and d.glucose_mmol_l>=7.8)
        if high: return Decision("High","Raised glucose screening result","Refer for clinical assessment and confirmatory testing. A single screening value is not a diagnosis.",.85,bmi)
        if borderline: return Decision("Moderate","Borderline glucose screening result","Arrange repeat or confirmatory testing and routine clinical review.",.55,bmi)
        return Decision("Low","Glucose within screening range","Continue routine risk assessment and screening as clinically indicated.",.2,bmi)
    if d.disease == "malaria":
        if d.malaria_result=="Positive": return Decision("High",f"Positive {d.malaria_test} result recorded","Send for clinical management according to the current Ghana malaria protocol.",.9,bmi)
        febrile=d.fever_or_history or (d.temperature_c is not None and d.temperature_c>=37.5)
        if febrile and d.malaria_result=="Negative": return Decision("Moderate","Febrile illness with negative malaria test","Refer for assessment of other causes of fever; do not classify every fever as malaria.",.5,bmi)
        if febrile:
            priority=d.pregnant or d.age<5
            return Decision("High" if priority else "Moderate","Suspected malaria requiring testing","Perform RDT or microscopy before treatment and assess for danger signs.",.7 if priority else .55,bmi)
        return Decision("Low","No malaria screening trigger recorded","Continue routine assessment; test when fever or clinical suspicion is present.",.15,bmi)
    if d.disease == "tb":
        triggers=sum([d.cough_two_weeks,d.tb_contact,d.night_sweats,d.unexplained_weight_loss])
        if d.cough_two_weeks or triggers>=2: return Decision("High","Presumptive TB screening result","Refer for diagnostic investigation using the approved TB testing pathway.",min(.95,.55+triggers*.1),bmi)
        if triggers==1: return Decision("Moderate","One TB screening risk factor recorded","Complete clinical TB screening and consider diagnostic investigation.",.4,bmi)
        return Decision("Low","No TB screening trigger recorded","Continue routine screening based on exposure and clinical history.",.15,bmi)
    label=d.disease.replace("_"," ").title()
    return Decision("Moderate",f"{label} assessment recorded",f"Complete the approved {label} assessment and follow the current clinical or public health protocol. This module requires medical review before decision rules are activated.",.4,bmi)

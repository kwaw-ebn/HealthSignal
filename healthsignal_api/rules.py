from dataclasses import dataclass
from .schemas import ScreeningRequest

@dataclass
class Decision:
    risk: str; classification: str; recommendation: str; score: float; bmi: float | None = None

def _bmi(d): return round(d.weight_kg / ((d.height_cm / 100) ** 2), 1) if d.weight_kg and d.height_cm else None

def priority(level,label,recommendation,score,bmi=None):
    names={"Low":"Routine","Moderate":"Needs assessment","High":"High priority","Urgent":"Immediate referral"}
    return Decision(level,f"{names[level]}: {label}",recommendation+" This is a screening priority, not a diagnosis.",score,bmi)

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
            elevated_priority=d.pregnant or d.age<5
            return Decision("High" if elevated_priority else "Moderate","Suspected malaria requiring testing","Perform RDT or microscopy before treatment and assess for danger signs.",.7 if elevated_priority else .55,bmi)
        return Decision("Low","No malaria screening trigger recorded","Continue routine assessment; test when fever or clinical suspicion is present.",.15,bmi)
    if d.disease == "tb":
        triggers=sum([d.cough_two_weeks,d.tb_contact,d.night_sweats,d.unexplained_weight_loss])
        if d.cough_two_weeks or triggers>=2: return Decision("High","Presumptive TB screening result","Refer for diagnostic investigation using the approved TB testing pathway.",min(.95,.55+triggers*.1),bmi)
        if triggers==1: return Decision("Moderate","One TB screening risk factor recorded","Complete clinical TB screening and consider diagnostic investigation.",.4,bmi)
        return Decision("Low","No TB screening trigger recorded","Continue routine screening based on exposure and clinical history.",.15,bmi)
    if d.disease=="maternal_risk":
        if d.maternal_warning_signs or d.reduced_fetal_movement or (d.systolic_1 and d.systolic_1>=160) or (d.diastolic_1 and d.diastolic_1>=110): return priority("Urgent","maternal warning indicator recorded","Arrange immediate assessment using the approved maternal referral pathway.",.95,bmi)
        if d.multiple_pregnancy or d.previous_caesarean or d.age<18 or d.age>=35 or (d.haemoglobin_g_dl is not None and d.haemoglobin_g_dl<7): return priority("High","maternal risk factor recorded","Arrange prompt clinician review and confirm the referral plan.",.8,bmi)
        if d.gestational_age_weeks is None or d.anc_visits is None or d.systolic_1 is None: return priority("Moderate","maternal assessment incomplete","Complete gestational age, ANC and blood pressure assessment.",.5,bmi)
        return priority("Low","no priority maternal indicator recorded","Continue routine antenatal care and reassess at scheduled contacts.",.2,bmi)
    if d.disease=="childhood_malnutrition":
        if d.bilateral_oedema or (d.muac_cm is not None and d.muac_cm<11.5): return priority("Urgent","severe nutrition screening indicator","Refer immediately for assessment under the approved nutrition protocol.",.95,bmi)
        if (d.muac_cm is not None and d.muac_cm<12.5) or d.feeding_problem: return priority("High","nutrition risk indicator recorded","Arrange prompt nutrition assessment, counselling and follow up.",.8,bmi)
        if d.muac_cm is None or d.weight_kg is None or d.height_cm is None: return priority("Moderate","nutrition measurements incomplete","Complete age appropriate anthropometry and feeding assessment.",.5,bmi)
        return priority("Low","no priority nutrition indicator recorded","Continue growth monitoring and age appropriate feeding assessment.",.2,bmi)
    if d.disease=="anaemia_pregnancy":
        if d.haemoglobin_g_dl is not None and d.haemoglobin_g_dl<7: return priority("Urgent","very low haemoglobin screening result","Arrange immediate clinical assessment and confirm management under local protocol.",.95,bmi)
        if d.haemoglobin_g_dl is not None and d.haemoglobin_g_dl<11: return priority("High","low haemoglobin screening result","Arrange prompt clinical review and assessment of contributing factors.",.8,bmi)
        if d.haemoglobin_g_dl is None or d.anaemia_symptoms: return priority("Moderate","anaemia assessment requires completion","Measure haemoglobin and review symptoms, supplementation and malaria status.",.5,bmi)
        return priority("Low","no priority anaemia indicator recorded","Continue routine ANC monitoring under the approved schedule.",.2,bmi)
    if d.disease=="hiv_linkage":
        if d.hiv_result_category in {"Reactive","Positive confirmed"}: return priority("High","HIV testing or linkage action required","Follow the approved confirmatory testing and confidential linkage pathway promptly.",.85,bmi)
        if d.test_offered and d.hiv_result_category in {"Pending","Not tested"}: return priority("Moderate","HIV testing pathway incomplete","Complete consented testing or document the appropriate follow up.",.5,bmi)
        return priority("Low","HIV testing and linkage status recorded","Continue confidential services according to the approved national pathway.",.2,bmi)
    if d.disease=="cholera_diarrhoea":
        if d.dehydration_level=="Severe": return priority("Urgent","severe dehydration indicator","Arrange immediate clinical assessment and notification according to outbreak protocol.",.95,bmi)
        if (d.stool_count_24h or 0)>=3 or d.disease_test_result=="Positive": return priority("High","acute diarrhoeal disease signal","Arrange prompt assessment, specimen pathway and public health notification as indicated.",.8,bmi)
        if d.stool_count_24h is None: return priority("Moderate","diarrhoea assessment incomplete","Record stool frequency, duration and dehydration assessment.",.5,bmi)
        return priority("Low","no priority diarrhoeal indicator recorded","Continue assessment and prevention counselling.",.2,bmi)
    if d.disease=="measles":
        if d.rash_present and d.fever_or_history: return priority("High","fever and rash signal","Isolate as locally directed and notify for prompt case investigation and specimen assessment.",.85,bmi)
        if d.rash_present or d.contact_history: return priority("Moderate","measles assessment required","Complete fever, rash, vaccination, exposure and specimen assessment.",.5,bmi)
        return priority("Low","no priority measles indicator recorded","Continue routine surveillance and vaccination status review.",.2,bmi)
    if d.disease=="meningitis":
        if d.altered_consciousness or (d.fever_or_history and d.neck_stiffness): return priority("Urgent","meningitis warning indicator","Arrange immediate clinical assessment and notification using the approved pathway.",.98,bmi)
        if d.fever_or_history or d.contact_history: return priority("High","meningitis assessment required","Arrange prompt clinician assessment and complete the investigation pathway.",.8,bmi)
        return priority("Low","no priority meningitis indicator recorded","Continue routine surveillance and reassess if warning indicators develop.",.2,bmi)
    if d.disease=="acute_respiratory_infection":
        if (d.oxygen_saturation is not None and d.oxygen_saturation<90) or d.altered_consciousness: return priority("Urgent","severe respiratory warning indicator","Arrange immediate clinical assessment.",.98,bmi)
        if d.breathing_difficulty or (d.oxygen_saturation is not None and d.oxygen_saturation<94): return priority("High","respiratory priority indicator","Arrange prompt clinical assessment using the age appropriate respiratory protocol.",.82,bmi)
        if d.cough_present or d.fever_or_history: return priority("Moderate","respiratory assessment required","Review respiratory rate, temperature, oxygen saturation and other warning indicators.",.5,bmi)
        return priority("Low","no priority respiratory indicator recorded","Continue routine assessment.",.2,bmi)
    if d.disease=="hepatitis":
        if d.disease_test_result=="Positive": return priority("High","positive hepatitis test recorded","Arrange confirmatory clinical review and linkage under the approved hepatitis pathway.",.85,bmi)
        if d.jaundice_present or d.hepatitis_exposure: return priority("Moderate","hepatitis assessment required","Complete exposure, symptom and laboratory assessment.",.5,bmi)
        return priority("Low","no priority hepatitis indicator recorded","Continue risk assessment and prevention counselling.",.2,bmi)
    if d.disease=="mental_health":
        if d.urgent_safety_concern: return priority("Urgent","urgent wellbeing concern recorded","Follow the approved safeguarding and urgent clinical assessment pathway.",.98,bmi)
        if d.questionnaire_risk=="Severe" or d.functional_impairment: return priority("High","high wellbeing screening priority","Arrange prompt review by an appropriately trained professional.",.82,bmi)
        if d.questionnaire_risk in {"Mild","Moderate"} or d.questionnaire_score is None: return priority("Moderate","wellbeing assessment or follow up required","Review the validated tool result and arrange appropriate support or follow up.",.5,bmi)
        return priority("Low","routine wellbeing follow up","Continue supportive monitoring according to the selected validated tool.",.2,bmi)
    if d.disease=="other_ncd":
        level={"Routine":"Low","Needs assessment":"Moderate","High priority":"High","Immediate referral":"Urgent"}.get(d.ncd_reported_priority,"Moderate")
        return priority(level,d.ncd_condition or "other NCD assessment", "Have an authorized clinician verify the condition specific measurement and action plan.",.4 if level=="Moderate" else .8 if level=="High" else .95 if level=="Urgent" else .2,bmi)
    label=d.disease.replace("_"," ").title()
    return Decision("Moderate",f"{label} assessment recorded",f"Complete the approved {label} assessment and follow the current clinical or public health protocol. This module requires medical review before decision rules are activated.",.4,bmi)

import os
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, Integer, LargeBinary, String, Text, create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./healthsignal.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

class Base(DeclarativeBase): pass

class Screening(Base):
    __tablename__ = "screenings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    screening_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    visit_date: Mapped[str] = mapped_column(String(10), index=True)
    region: Mapped[str] = mapped_column(String(100), default="")
    district: Mapped[str] = mapped_column(String(100), index=True, default="")
    community: Mapped[str] = mapped_column(String(100), index=True, default="")
    facility: Mapped[str] = mapped_column(String(150), default="")
    age: Mapped[int] = mapped_column(Integer)
    sex: Mapped[str] = mapped_column(String(20))
    pregnant: Mapped[bool] = mapped_column(Boolean, default=False)
    disease: Mapped[str] = mapped_column(String(40), index=True)
    risk_level: Mapped[str] = mapped_column(String(20), index=True)
    classification: Mapped[str] = mapped_column(String(120))
    recommendation: Mapped[str] = mapped_column(Text)
    score: Mapped[float] = mapped_column(Float, default=0)
    inputs_json: Mapped[str] = mapped_column(Text)
    referred: Mapped[bool] = mapped_column(Boolean, default=False)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    case_status: Mapped[str] = mapped_column(String(30), default="suspected", index=True)
    outcome: Mapped[str | None] = mapped_column(String(120), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

class Patient(Base):
    __tablename__ = "patients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    patient_code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    sex: Mapped[str] = mapped_column(String(20))
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)
    approximate_age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    home_community: Mapped[str | None] = mapped_column(String(120), nullable=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Encounter(Base):
    __tablename__ = "encounters"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    encounter_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    screening_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    visit_date: Mapped[str] = mapped_column(String(10), index=True)
    facility: Mapped[str | None] = mapped_column(String(160), nullable=True)
    community: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    temperature_c: Mapped[float | None] = mapped_column(Float, nullable=True)
    pulse: Mapped[int | None] = mapped_column(Integer, nullable=True)
    respiratory_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    oxygen_saturation: Mapped[float | None] = mapped_column(Float, nullable=True)
    systolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diastolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weight_kg: Mapped[float | None] = mapped_column(Float, nullable=True)
    height_cm: Mapped[float | None] = mapped_column(Float, nullable=True)
    bmi: Mapped[float | None] = mapped_column(Float, nullable=True)
    pregnant: Mapped[bool] = mapped_column(Boolean, default=False)
    symptoms_json: Mapped[str] = mapped_column(Text, default="[]")
    notes: Mapped[str] = mapped_column(Text, default="")
    outcome: Mapped[str | None] = mapped_column(String(120), nullable=True)
    follow_up_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    completion_status: Mapped[str] = mapped_column(String(30), default="complete", index=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class LaboratoryTest(Base):
    __tablename__ = "laboratory_tests"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    test_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    encounter_id: Mapped[str] = mapped_column(String(36), index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    test_name: Mapped[str] = mapped_column(String(100), index=True)
    result: Mapped[str] = mapped_column(String(120))
    result_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    result_status: Mapped[str] = mapped_column(String(30), default="available")
    tested_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    created_by: Mapped[str] = mapped_column(String(80))

class Attachment(Base):
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    attachment_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    encounter_id: Mapped[str] = mapped_column(String(36), index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    filename: Mapped[str] = mapped_column(String(180))
    content_type: Mapped[str] = mapped_column(String(80))
    content: Mapped[bytes] = mapped_column(LargeBinary)
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    email: Mapped[str | None] = mapped_column(String(180), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str | None] = mapped_column(String(40), nullable=True)
    staff_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    facility: Mapped[str | None] = mapped_column(String(160), nullable=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True)
    region: Mapped[str | None] = mapped_column(String(120), nullable=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[str] = mapped_column(String(30), default="approved", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    terms_accepted: Mapped[bool] = mapped_column(Boolean, default=False)
    force_password_change: Mapped[bool] = mapped_column(Boolean, default=False)
    failed_login_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(80), index=True)
    target_type: Mapped[str] = mapped_column(String(50))
    target_id: Mapped[str] = mapped_column(String(100), index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class Referral(Base):
    __tablename__ = "referrals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referral_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    screening_id: Mapped[str] = mapped_column(String(36), index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    destination: Mapped[str] = mapped_column(String(160))
    reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="Pending", index=True)
    due_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ReviewCase(Base):
    __tablename__ = "review_cases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    screening_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    encounter_id: Mapped[str] = mapped_column(String(36), index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    disease: Mapped[str] = mapped_column(String(50), index=True)
    district: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    facility: Mapped[str | None] = mapped_column(String(160), nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="routine", index=True)
    status: Mapped[str] = mapped_column(String(30), default="awaiting_review", index=True)
    flag_reasons_json: Mapped[str] = mapped_column(Text, default="[]")
    assigned_to: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    reviewer_classification: Mapped[str | None] = mapped_column(String(30), nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    follow_up_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ReviewEvent(Base):
    __tablename__ = "review_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    review_id: Mapped[str] = mapped_column(String(36), index=True)
    actor: Mapped[str] = mapped_column(String(80), index=True)
    action: Mapped[str] = mapped_column(String(80))
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class Facility(Base):
    __tablename__ = "facilities"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    facility_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(160), unique=True, index=True)
    facility_type: Mapped[str] = mapped_column(String(60), default="Hospital")
    district: Mapped[str] = mapped_column(String(120), index=True)
    region: Mapped[str] = mapped_column(String(120), index=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    allowed_radius_m: Mapped[int] = mapped_column(Integer, default=250)
    geofence_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class CareEpisode(Base):
    __tablename__ = "care_episodes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    episode_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    facility: Mapped[str] = mapped_column(String(160), index=True)
    visit_date: Mapped[str] = mapped_column(String(10), index=True)
    visit_type: Mapped[str] = mapped_column(String(40), default="OPD")
    status: Mapped[str] = mapped_column(String(30), default="registered", index=True)
    chief_complaint: Mapped[str] = mapped_column(Text, default="")
    assigned_department: Mapped[str] = mapped_column(String(60), default="OPD", index=True)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class CareEvent(Base):
    __tablename__ = "care_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    episode_id: Mapped[str] = mapped_column(String(36), index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    facility: Mapped[str] = mapped_column(String(160), index=True)
    department: Mapped[str] = mapped_column(String(60), index=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    summary: Mapped[str] = mapped_column(Text)
    clinical_data_json: Mapped[str] = mapped_column(Text, default="{}")
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class MedicationOrder(Base):
    __tablename__ = "medication_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    episode_id: Mapped[str] = mapped_column(String(36), index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    facility: Mapped[str] = mapped_column(String(160), index=True)
    medicine: Mapped[str] = mapped_column(String(160))
    instructions: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="prescribed", index=True)
    prescribed_by: Mapped[str] = mapped_column(String(80))
    dispensed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    dispensed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class WardAdmission(Base):
    __tablename__ = "ward_admissions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    admission_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    episode_id: Mapped[str] = mapped_column(String(36), index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    facility: Mapped[str] = mapped_column(String(160), index=True)
    ward: Mapped[str] = mapped_column(String(80), index=True)
    bed_number: Mapped[str | None] = mapped_column(String(30), nullable=True)
    admission_reason: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="admitted", index=True)
    admitted_by: Mapped[str] = mapped_column(String(80))
    discharge_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    admitted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    discharged_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class AncVisit(Base):
    __tablename__ = "anc_visits"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anc_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    episode_id: Mapped[str] = mapped_column(String(36), index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    facility: Mapped[str] = mapped_column(String(160), index=True)
    gestational_age_weeks: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gravida: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    systolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    diastolic: Mapped[int | None] = mapped_column(Integer, nullable=True)
    haemoglobin_g_dl: Mapped[float | None] = mapped_column(Float, nullable=True)
    fetal_heart_rate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    danger_signs: Mapped[str] = mapped_column(Text, default="")
    plan: Mapped[str] = mapped_column(Text)
    next_visit_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    recorded_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class InventoryItem(Base):
    __tablename__ = "inventory_items"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    facility: Mapped[str] = mapped_column(String(160), index=True)
    item_name: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    reorder_level: Mapped[int] = mapped_column(Integer, default=0)
    unit: Mapped[str] = mapped_column(String(40), default="unit")
    batch_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    expiry_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    updated_by: Mapped[str] = mapped_column(String(80))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class RevenueTransaction(Base):
    __tablename__ = "revenue_transactions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    receipt_number: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    episode_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    patient_code: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    facility: Mapped[str] = mapped_column(String(160), index=True)
    service: Mapped[str] = mapped_column(String(160), index=True)
    amount: Mapped[float] = mapped_column(Float)
    payment_method: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="paid", index=True)
    collected_by: Mapped[str] = mapped_column(String(80))
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class InsuranceClaim(Base):
    __tablename__ = "insurance_claims"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    episode_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    facility: Mapped[str] = mapped_column(String(160), index=True)
    member_number: Mapped[str] = mapped_column(String(80), index=True)
    ccc_number: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    surname: Mapped[str] = mapped_column(String(120), default="")
    other_names: Mapped[str] = mapped_column(String(180), default="")
    gender: Mapped[str] = mapped_column(String(20), default="Not recorded")
    date_of_birth: Mapped[str | None] = mapped_column(String(10), nullable=True)
    folder_number: Mapped[str | None] = mapped_column(String(80), nullable=True)
    attendance_type: Mapped[str] = mapped_column(String(40), default="Emergency/Acute Episode")
    specialty: Mapped[str | None] = mapped_column(String(20), nullable=True)
    service_outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    referring_facility: Mapped[str | None] = mapped_column(String(160), nullable=True)
    referral_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    physician_name_id: Mapped[str | None] = mapped_column(String(160), nullable=True)
    pre_authorization_codes: Mapped[str | None] = mapped_column(Text, nullable=True)
    principal_gdrg: Mapped[str | None] = mapped_column(String(80), nullable=True)
    manual_entries_json: Mapped[str] = mapped_column(Text, default="[]")
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    validation_json: Mapped[str] = mapped_column(Text, default="[]")
    created_by: Mapped[str] = mapped_column(String(80))
    reviewed_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class NetworkReferral(Base):
    __tablename__ = "network_referrals"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referral_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    episode_id: Mapped[str] = mapped_column(String(36), index=True)
    patient_code: Mapped[str] = mapped_column(String(64), index=True)
    source_facility: Mapped[str] = mapped_column(String(160), index=True)
    destination_facility: Mapped[str] = mapped_column(String(160), index=True)
    access_code_hash: Mapped[str] = mapped_column(String(64))
    reason: Mapped[str] = mapped_column(Text)
    urgency: Mapped[str] = mapped_column(String(20), default="routine", index=True)
    clinical_summary: Mapped[str] = mapped_column(Text)
    receiving_department: Mapped[str] = mapped_column(String(60), default="Consulting Room")
    consent_type: Mapped[str] = mapped_column(String(40), default="patient")
    consent_scope_json: Mapped[str] = mapped_column(Text, default='["care_summary"]')
    consent_recorded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    consent_revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    access_count: Mapped[int] = mapped_column(Integer, default=0)
    last_accessed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="sent", index=True)
    consent_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    accepted_by: Mapped[str | None] = mapped_column(String(80), nullable=True)
    accepted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    created_by: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class NetworkReferralEvent(Base):
    __tablename__ = "network_referral_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    referral_id: Mapped[str] = mapped_column(String(36), index=True)
    actor: Mapped[str] = mapped_column(String(80), index=True)
    facility: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(50))
    details: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class ReferralAccessGrant(Base):
    __tablename__ = "referral_access_grants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grant_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    referral_id: Mapped[str] = mapped_column(String(36), index=True)
    username: Mapped[str] = mapped_column(String(80), index=True)
    facility: Mapped[str] = mapped_column(String(160), index=True)
    department: Mapped[str] = mapped_column(String(60))
    purpose: Mapped[str] = mapped_column(String(80))
    access_reason: Mapped[str] = mapped_column(Text)
    emergency: Mapped[bool] = mapped_column(Boolean, default=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

class LocationAccessGrant(Base):
    __tablename__ = "location_access_grants"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    grant_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(80), index=True)
    facility: Mapped[str] = mapped_column(String(160), index=True)
    latitude: Mapped[float] = mapped_column(Float)
    longitude: Mapped[float] = mapped_column(Float)
    accuracy_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    distance_m: Mapped[float] = mapped_column(Float)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

def init_db():
    Base.metadata.create_all(bind=engine)
    # create_all does not add columns to an existing table. This small, additive
    # migration keeps early HealthSignal installations compatible.
    columns={c["name"] for c in inspect(engine).get_columns("users")}
    additions={
        "email":"VARCHAR(180)", "phone":"VARCHAR(40)", "staff_id":"VARCHAR(80)",
        "facility":"VARCHAR(160)", "district":"VARCHAR(120)", "region":"VARCHAR(120)",
        "status":"VARCHAR(30) DEFAULT 'approved'", "terms_accepted":"BOOLEAN DEFAULT FALSE",
        "force_password_change":"BOOLEAN DEFAULT FALSE", "failed_login_attempts":"INTEGER DEFAULT 0",
        "locked_until":"TIMESTAMP", "last_login":"TIMESTAMP", "reviewed_by":"VARCHAR(80)",
        "reviewed_at":"TIMESTAMP"
    }
    with engine.begin() as conn:
        for name,sql_type in additions.items():
            if name not in columns:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {name} {sql_type}"))
        conn.execute(text("UPDATE users SET role='field_officer' WHERE role='field_worker'"))
    screening_columns={c["name"] for c in inspect(engine).get_columns("screenings")}
    screening_additions={"updated_at":"TIMESTAMP","created_by":"VARCHAR(80)","case_status":"VARCHAR(30) DEFAULT 'suspected'","outcome":"VARCHAR(120)","archived":"BOOLEAN DEFAULT FALSE"}
    with engine.begin() as conn:
        for name,sql_type in screening_additions.items():
            if name not in screening_columns:
                conn.execute(text(f"ALTER TABLE screenings ADD COLUMN {name} {sql_type}"))
    if inspect(engine).has_table("facilities"):
        facility_columns={c["name"] for c in inspect(engine).get_columns("facilities")}
        facility_additions={"latitude":"FLOAT","longitude":"FLOAT","allowed_radius_m":"INTEGER DEFAULT 250","geofence_enabled":"BOOLEAN DEFAULT FALSE"}
        with engine.begin() as conn:
            for name,sql_type in facility_additions.items():
                if name not in facility_columns:
                    conn.execute(text(f"ALTER TABLE facilities ADD COLUMN {name} {sql_type}"))
    if inspect(engine).has_table("network_referrals"):
        referral_columns={c["name"] for c in inspect(engine).get_columns("network_referrals")}
        referral_additions={
            "receiving_department":"VARCHAR(60) DEFAULT 'Consulting Room'",
            "consent_type":"VARCHAR(40) DEFAULT 'patient'",
            "consent_scope_json":"TEXT DEFAULT '[\"care_summary\"]'",
            "consent_recorded_at":"TIMESTAMP", "consent_revoked_at":"TIMESTAMP",
            "access_count":"INTEGER DEFAULT 0", "last_accessed_at":"TIMESTAMP"
        }
        with engine.begin() as conn:
            for name,sql_type in referral_additions.items():
                if name not in referral_columns:
                    conn.execute(text(f"ALTER TABLE network_referrals ADD COLUMN {name} {sql_type}"))
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

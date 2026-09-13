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
    screening_columns={c["name"] for c in inspect(engine).get_columns("screenings")}
    screening_additions={"updated_at":"TIMESTAMP","created_by":"VARCHAR(80)","case_status":"VARCHAR(30) DEFAULT 'suspected'","outcome":"VARCHAR(120)","archived":"BOOLEAN DEFAULT FALSE"}
    with engine.begin() as conn:
        for name,sql_type in screening_additions.items():
            if name not in screening_columns:
                conn.execute(text(f"ALTER TABLE screenings ADD COLUMN {name} {sql_type}"))
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

import os
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, inspect, text
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
def get_db():
    db = SessionLocal()
    try: yield db
    finally: db.close()

"""SQLAlchemy ORM models for all database tables."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Session(Base):
    __tablename__ = "sessions"

    id = Column(String, primary_key=True, default=_new_id)
    name = Column(String, nullable=False)
    tax_year = Column(Integer, nullable=False)
    status = Column(String, nullable=False, default="in_progress")
    current_step = Column(String, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    tax_profile = relationship("TaxProfile", back_populates="session", uselist=False, cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="session", cascade="all, delete-orphan")
    chat_messages = relationship("ChatMessage", back_populates="session", cascade="all, delete-orphan")
    chat_summaries = relationship("ChatSummary", back_populates="session", cascade="all, delete-orphan")
    calculation_results = relationship("CalculationResult", back_populates="session", cascade="all, delete-orphan")


class TaxProfile(Base):
    __tablename__ = "tax_profiles"

    id = Column(String, primary_key=True, default=_new_id)
    session_id = Column(String, ForeignKey("sessions.id"), unique=True, nullable=False)
    filing_status = Column(String, nullable=True)
    state_of_residence = Column(String, nullable=True)
    num_dependents = Column(Integer, default=0)
    profile_data = Column(Text, default="{}")  # JSON blob
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)

    session = relationship("Session", back_populates="tax_profile")


class Document(Base):
    __tablename__ = "documents"

    id = Column(String, primary_key=True, default=_new_id)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    doc_type = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    ocr_text = Column(Text, nullable=True)
    extracted_data = Column(Text, default="{}")  # JSON blob
    confidence_score = Column(Float, nullable=True)
    needs_review = Column(Boolean, default=False)
    created_at = Column(DateTime, default=_utcnow)

    session = relationship("Session", back_populates="documents")


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    role = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    step_id = Column(String, nullable=True)
    token_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=_utcnow)

    session = relationship("Session", back_populates="chat_messages")


class ChatSummary(Base):
    __tablename__ = "chat_summaries"

    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    summary_text = Column(Text, nullable=False)
    messages_start_id = Column(Integer, nullable=False)
    messages_end_id = Column(Integer, nullable=False)
    created_at = Column(DateTime, default=_utcnow)

    session = relationship("Session", back_populates="chat_summaries")


class CalculationResult(Base):
    __tablename__ = "calculation_results"

    id = Column(String, primary_key=True, default=_new_id)
    session_id = Column(String, ForeignKey("sessions.id"), nullable=False)
    calc_type = Column(String, nullable=False)
    engine_used = Column(String, nullable=False)
    input_snapshot = Column(Text, default="{}")  # JSON blob
    result_data = Column(Text, default="{}")  # JSON blob
    warnings = Column(Text, default="[]")  # JSON array
    created_at = Column(DateTime, default=_utcnow)

    session = relationship("Session", back_populates="calculation_results")

"""Test fixtures: in-memory DB, mock LLM, sample profiles."""

import json
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from ai_tax_prep.core.tax_profile import (
    Dependent,
    Income,
    Payments,
    PersonalInfo,
    SelfEmploymentIncome,
    TaxProfile,
    W2Income,
)
from ai_tax_prep.db.models import Base


@pytest.fixture
def in_memory_db():
    """Create an in-memory SQLite database for testing."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


@pytest.fixture
def sample_profile_single():
    """A simple single filer with W-2 income."""
    return TaxProfile(
        tax_year=2025,
        personal_info=PersonalInfo(
            first_name="Jane",
            last_name="Doe",
            age=30,
            filing_status="single",
            state_of_residence="CA",
        ),
        income=Income(
            w2s=[
                W2Income(
                    employer_name="Acme Corp",
                    wages=75000,
                    federal_withholding=10000,
                    state="CA",
                    state_wages=75000,
                    state_withholding=3000,
                )
            ],
        ),
        payments=Payments(
            federal_withholding=10000,
            state_withholding=3000,
        ),
    )


@pytest.fixture
def sample_profile_married_with_dependents():
    """Married filing jointly with kids and self-employment."""
    return TaxProfile(
        tax_year=2025,
        personal_info=PersonalInfo(
            first_name="John",
            last_name="Smith",
            age=40,
            filing_status="married_filing_jointly",
            state_of_residence="TX",
            dependents=[
                Dependent(name="Alice Smith", relationship="daughter", age=8),
                Dependent(name="Bob Smith", relationship="son", age=5),
            ],
        ),
        income=Income(
            w2s=[
                W2Income(employer_name="BigCo", wages=120000, federal_withholding=20000, state="TX"),
            ],
            self_employment=[
                SelfEmploymentIncome(business_name="Side Hustle LLC", gross_income=30000, expenses=5000),
            ],
        ),
        payments=Payments(
            federal_withholding=20000,
            estimated_federal_payments=3000,
        ),
    )


@pytest.fixture
def sample_profile_zero_income():
    """Profile with no income — edge case."""
    return TaxProfile(
        tax_year=2025,
        personal_info=PersonalInfo(
            first_name="Empty",
            last_name="Profile",
            age=25,
            filing_status="single",
            state_of_residence="NY",
        ),
    )


@pytest.fixture
def mock_llm_response():
    """Factory for mock LLM responses."""
    def _make(content="Mock response", json_content=None):
        mock = MagicMock()
        if json_content:
            mock.chat.return_value = json.dumps(json_content)
            mock.chat_json.return_value = json_content
        else:
            mock.chat.return_value = content
        mock.chat_stream.return_value = iter([content])
        mock.count_tokens.return_value = len(content) // 4
        return mock
    return _make

"""Session lifecycle management — create, resume, list."""

import json
from typing import Optional

from ai_tax_prep.core.tax_profile import TaxProfile
from ai_tax_prep.db.database import get_session_factory, init_db
from ai_tax_prep.db.models import Session
from ai_tax_prep.db.repository import SessionRepository, TaxProfileRepository


class SessionManager:
    def __init__(self):
        init_db()
        self._factory = get_session_factory()

    def _get_db(self):
        return self._factory()

    def create_session(self, name: str, tax_year: int = 2025) -> Session:
        db = self._get_db()
        try:
            repo = SessionRepository(db)
            existing = repo.get_by_name(name)
            if existing:
                raise ValueError(f"Session '{name}' already exists. Use a different name.")
            return repo.create(name=name, tax_year=tax_year)
        finally:
            db.close()

    def list_sessions(self, status: Optional[str] = None) -> list[Session]:
        db = self._get_db()
        try:
            repo = SessionRepository(db)
            return repo.list_all(status=status)
        finally:
            db.close()

    def get_session(self, session_id: str) -> Optional[Session]:
        db = self._get_db()
        try:
            repo = SessionRepository(db)
            return repo.get(session_id)
        finally:
            db.close()

    def get_session_by_name(self, name: str) -> Optional[Session]:
        db = self._get_db()
        try:
            repo = SessionRepository(db)
            return repo.get_by_name(name)
        finally:
            db.close()

    def delete_session(self, session_id: str) -> bool:
        db = self._get_db()
        try:
            repo = SessionRepository(db)
            return repo.delete(session_id)
        finally:
            db.close()

    def get_tax_profile(self, session_id: str) -> TaxProfile:
        db = self._get_db()
        try:
            repo = TaxProfileRepository(db)
            db_profile = repo.get_by_session(session_id)
            if db_profile and db_profile.profile_data:
                try:
                    return TaxProfile.from_json(db_profile.profile_data)
                except Exception:
                    return TaxProfile()
            return TaxProfile()
        finally:
            db.close()

    def save_tax_profile(self, session_id: str, profile: TaxProfile) -> None:
        db = self._get_db()
        try:
            repo = TaxProfileRepository(db)
            db_profile = repo.get_by_session(session_id)
            if db_profile:
                db_profile.profile_data = profile.to_json()
                db_profile.filing_status = profile.personal_info.filing_status
                db_profile.state_of_residence = profile.personal_info.state_of_residence
                db_profile.num_dependents = len(profile.personal_info.dependents)
                db.commit()
        finally:
            db.close()

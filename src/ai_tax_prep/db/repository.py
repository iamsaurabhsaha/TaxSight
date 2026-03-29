"""CRUD operations for sessions and tax profiles."""

import json
from datetime import UTC, datetime

from sqlalchemy.orm import Session as DbSession

from ai_tax_prep.db.models import (
    ChatMessage,
    ChatSummary,
    Session,
    TaxProfile,
)


class SessionRepository:
    def __init__(self, db: DbSession):
        self.db = db

    def create(self, name: str, tax_year: int) -> Session:
        session = Session(name=name, tax_year=tax_year)
        self.db.add(session)
        self.db.flush()
        profile = TaxProfile(session_id=session.id)
        self.db.add(profile)
        self.db.commit()
        self.db.refresh(session)
        return session

    def get(self, session_id: str) -> Session | None:
        return self.db.query(Session).filter(Session.id == session_id).first()

    def get_by_name(self, name: str) -> Session | None:
        return self.db.query(Session).filter(Session.name == name).first()

    def list_all(self, status: str | None = None) -> list[Session]:
        query = self.db.query(Session).order_by(Session.updated_at.desc())
        if status:
            query = query.filter(Session.status == status)
        return query.all()

    def update_step(self, session_id: str, step: str) -> None:
        session = self.get(session_id)
        if session:
            session.current_step = step
            session.updated_at = datetime.now(UTC)
            self.db.commit()

    def update_status(self, session_id: str, status: str) -> None:
        session = self.get(session_id)
        if session:
            session.status = status
            session.updated_at = datetime.now(UTC)
            self.db.commit()

    def delete(self, session_id: str) -> bool:
        session = self.get(session_id)
        if session:
            self.db.delete(session)
            self.db.commit()
            return True
        return False


class TaxProfileRepository:
    def __init__(self, db: DbSession):
        self.db = db

    def get_by_session(self, session_id: str) -> TaxProfile | None:
        return (
            self.db.query(TaxProfile)
            .filter(TaxProfile.session_id == session_id)
            .first()
        )

    def update_profile_data(self, session_id: str, data: dict) -> None:
        profile = self.get_by_session(session_id)
        if profile:
            existing = json.loads(profile.profile_data or "{}")
            existing.update(data)
            profile.profile_data = json.dumps(existing)
            profile.updated_at = datetime.now(UTC)
            self.db.commit()

    def set_filing_status(self, session_id: str, status: str) -> None:
        profile = self.get_by_session(session_id)
        if profile:
            profile.filing_status = status
            self.db.commit()

    def set_state(self, session_id: str, state: str) -> None:
        profile = self.get_by_session(session_id)
        if profile:
            profile.state_of_residence = state
            self.db.commit()


class ChatRepository:
    def __init__(self, db: DbSession):
        self.db = db

    def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        step_id: str | None = None,
        token_count: int = 0,
    ) -> ChatMessage:
        msg = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            step_id=step_id,
            token_count=token_count,
        )
        self.db.add(msg)
        self.db.commit()
        self.db.refresh(msg)
        return msg

    def get_messages(
        self, session_id: str, limit: int | None = None
    ) -> list[ChatMessage]:
        query = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id.asc())
        )
        if limit:
            query = query.limit(limit)
        return query.all()

    def get_total_tokens(self, session_id: str) -> int:
        messages = self.get_messages(session_id)
        return sum(m.token_count for m in messages)

    def add_summary(
        self,
        session_id: str,
        summary_text: str,
        start_id: int,
        end_id: int,
    ) -> ChatSummary:
        summary = ChatSummary(
            session_id=session_id,
            summary_text=summary_text,
            messages_start_id=start_id,
            messages_end_id=end_id,
        )
        self.db.add(summary)
        self.db.commit()
        return summary

    def get_latest_summary(self, session_id: str) -> ChatSummary | None:
        return (
            self.db.query(ChatSummary)
            .filter(ChatSummary.session_id == session_id)
            .order_by(ChatSummary.id.desc())
            .first()
        )

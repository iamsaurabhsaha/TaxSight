"""Chat context management — token tracking, auto-summarization, checkpointing."""


from ai_tax_prep.config.settings import get_settings
from ai_tax_prep.db.database import get_session_factory, init_db
from ai_tax_prep.db.repository import ChatRepository
from ai_tax_prep.llm.client import LLMClient


class ContextManager:
    """Manages chat context window — tracks tokens, auto-summarizes before overflow."""

    def __init__(self, session_id: str, llm: LLMClient | None = None):
        self.session_id = session_id
        self.settings = get_settings()
        self.llm = llm or LLMClient()
        init_db()
        self._db_factory = get_session_factory()

    def _get_db(self):
        return self._db_factory()

    def get_context_messages(self) -> list[dict]:
        """Get the current context window — summary + recent messages."""
        db = self._get_db()
        try:
            repo = ChatRepository(db)

            # Check for existing summary
            summary = repo.get_latest_summary(self.session_id)
            messages = repo.get_messages(self.session_id)

            result = []

            if summary:
                # Start with summary as a system-level context
                result.append({
                    "role": "system",
                    "content": f"Summary of earlier conversation:\n{summary.summary_text}",
                })
                # Only include messages after the summary
                messages = [m for m in messages if m.id > summary.messages_end_id]

            # Add remaining messages
            for msg in messages:
                result.append({"role": msg.role, "content": msg.content})

            return result
        finally:
            db.close()

    def check_and_summarize(self) -> bool:
        """Check if context is approaching the limit and summarize if needed.

        Returns True if summarization was performed.
        """
        db = self._get_db()
        try:
            repo = ChatRepository(db)
            total_tokens = repo.get_total_tokens(self.session_id)
            threshold = self.settings.max_context_tokens * self.settings.context_summarize_threshold

            if total_tokens < threshold:
                return False

            # Get messages to summarize
            messages = repo.get_messages(self.session_id)
            if len(messages) < 10:
                return False

            # Keep the last 5 messages, summarize the rest
            to_summarize = messages[:-5]
            if not to_summarize:
                return False

            # Check for existing summary to build upon
            latest_summary = repo.get_latest_summary(self.session_id)
            existing_context = ""
            if latest_summary:
                existing_context = f"Previous summary: {latest_summary.summary_text}\n\n"
                to_summarize = [m for m in to_summarize if m.id > latest_summary.messages_end_id]
                if not to_summarize:
                    return False

            # Build summarization prompt
            conversation_text = "\n".join(
                f"{m.role}: {m.content}" for m in to_summarize
            )

            prompt = f"""{existing_context}Summarize this tax preparation conversation. Focus on:
1. Key facts collected (filing status, income amounts, deductions, etc.)
2. Decisions made by the user
3. Important context for continuing the conversation
4. Any concerns or flags raised

Keep it concise but complete — this summary replaces the original messages.

Conversation:
{conversation_text}"""

            summary_messages = [
                {"role": "system", "content": "You summarize tax preparation conversations accurately and concisely."},
                {"role": "user", "content": prompt},
            ]

            summary_text = self.llm.chat(summary_messages, temperature=0.1)

            # Save summary
            repo.add_summary(
                session_id=self.session_id,
                summary_text=summary_text,
                start_id=to_summarize[0].id,
                end_id=to_summarize[-1].id,
            )

            return True
        finally:
            db.close()

    def get_token_usage(self) -> dict:
        """Get current token usage stats."""
        db = self._get_db()
        try:
            repo = ChatRepository(db)
            total_tokens = repo.get_total_tokens(self.session_id)
            messages = repo.get_messages(self.session_id)
            summary = repo.get_latest_summary(self.session_id)

            return {
                "total_tokens": total_tokens,
                "message_count": len(messages),
                "max_tokens": self.settings.max_context_tokens,
                "usage_pct": (total_tokens / self.settings.max_context_tokens * 100)
                if self.settings.max_context_tokens
                else 0,
                "has_summary": summary is not None,
                "threshold_pct": self.settings.context_summarize_threshold * 100,
            }
        finally:
            db.close()

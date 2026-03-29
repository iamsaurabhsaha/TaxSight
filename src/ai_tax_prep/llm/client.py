"""LiteLLM wrapper with BYOK key management and structured output support."""

import json
import os
import re
from typing import Optional

import litellm

from ai_tax_prep.config.settings import Settings, get_settings

# Suppress litellm logging noise
litellm.suppress_debug_info = True


class LLMClient:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self._configure_env()

    def _configure_env(self) -> None:
        if self.settings.llm_provider == "anthropic" and self.settings.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = self.settings.anthropic_api_key
        elif self.settings.llm_provider == "openai" and self.settings.openai_api_key:
            os.environ["OPENAI_API_KEY"] = self.settings.openai_api_key
        elif self.settings.llm_provider == "gemini" and self.settings.gemini_api_key:
            os.environ["GEMINI_API_KEY"] = self.settings.gemini_api_key

        if self.settings.llm_provider == "ollama":
            os.environ["OLLAMA_API_BASE"] = self.settings.ollama_base_url

    def chat(
        self,
        messages: list[dict],
        json_mode: bool = False,
        temperature: float = 0.3,
    ) -> str:
        kwargs = {
            "model": self.settings.resolved_model,
            "messages": messages,
            "temperature": temperature,
        }

        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}

        response = litellm.completion(**kwargs)
        return response.choices[0].message.content

    def chat_stream(
        self,
        messages: list[dict],
        temperature: float = 0.3,
    ):
        kwargs = {
            "model": self.settings.resolved_model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }

        response = litellm.completion(**kwargs)
        for chunk in response:
            delta = chunk.choices[0].delta
            if delta and delta.content:
                yield delta.content

    def chat_json(
        self,
        messages: list[dict],
        temperature: float = 0.2,
    ) -> dict:
        content = self.chat(messages, json_mode=True, temperature=temperature)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            # Fallback: extract JSON from markdown code block
            match = re.search(r"```(?:json)?\s*([\s\S]*?)```", content)
            if match:
                return json.loads(match.group(1).strip())
            raise ValueError(f"Could not parse JSON from LLM response: {content[:200]}")

    def count_tokens(self, text: str) -> int:
        try:
            import tiktoken

            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            # Rough estimate: ~4 chars per token
            return len(text) // 4

    def test_connection(self) -> dict:
        try:
            response = self.chat(
                messages=[{"role": "user", "content": "Say 'connected' in one word."}],
                temperature=0.0,
            )
            return {"status": "ok", "provider": self.settings.llm_provider, "response": response}
        except Exception as e:
            return {"status": "error", "provider": self.settings.llm_provider, "error": str(e)}

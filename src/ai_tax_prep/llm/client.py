"""LiteLLM wrapper with BYOK key management, retry logic, and structured output support."""

import json
import logging
import os
import re
import time

import litellm

from ai_tax_prep.config.settings import Settings, get_settings

# Suppress litellm logging noise
litellm.suppress_debug_info = True

logger = logging.getLogger("ai_tax_prep.llm")

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


class LLMError(Exception):
    """Raised when LLM call fails after retries."""
    pass


class LLMClient:
    def __init__(self, settings: Settings | None = None):
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

    def _call_with_retry(self, fn, *args, **kwargs):
        """Call a function with retry logic for transient failures."""
        last_error = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return fn(*args, **kwargs)
            except Exception as e:
                last_error = e
                error_str = str(e).lower()

                # Don't retry on auth errors or bad requests
                if any(term in error_str for term in ["api key", "authentication", "unauthorized", "invalid_api_key"]):
                    raise LLMError(
                        f"Authentication failed for {self.settings.llm_provider}. "
                        f"Please check your API key. Error: {e}"
                    )

                if "rate_limit" in error_str or "429" in error_str:
                    wait = RETRY_DELAY_SECONDS * attempt
                    logger.warning(f"Rate limited, waiting {wait}s before retry {attempt}/{MAX_RETRIES}")
                    time.sleep(wait)
                    continue

                if attempt < MAX_RETRIES:
                    logger.warning(f"LLM call failed (attempt {attempt}/{MAX_RETRIES}): {e}")
                    time.sleep(RETRY_DELAY_SECONDS)
                    continue

        raise LLMError(f"LLM call failed after {MAX_RETRIES} attempts. Last error: {last_error}")

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

        def _do_call():
            response = litellm.completion(**kwargs)
            return response.choices[0].message.content

        return self._call_with_retry(_do_call)

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

        try:
            response = litellm.completion(**kwargs)
            for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error(f"Stream error: {e}")
            raise LLMError(f"Streaming failed: {e}")

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
                try:
                    return json.loads(match.group(1).strip())
                except json.JSONDecodeError:
                    pass
            # Last resort: try to find any JSON object in the response
            match = re.search(r"\{[\s\S]*\}", content)
            if match:
                try:
                    return json.loads(match.group(0))
                except json.JSONDecodeError:
                    pass
            raise ValueError(f"Could not parse JSON from LLM response: {content[:200]}")

    def count_tokens(self, text: str) -> int:
        try:
            import tiktoken
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
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

    def check_provider_available(self) -> dict:
        """Check if the configured provider is available and has a valid key."""
        provider = self.settings.llm_provider
        issues = []

        if provider == "ollama":
            try:
                import httpx
                r = httpx.get(self.settings.ollama_base_url, timeout=5.0)
                if r.status_code != 200:
                    issues.append(f"Ollama not responding at {self.settings.ollama_base_url}")
            except Exception:
                issues.append(f"Cannot connect to Ollama at {self.settings.ollama_base_url}. Is it running?")
        else:
            if not self.settings.api_key:
                issues.append(
                    f"No API key set for {provider}. "
                    f"Set it in .env or as environment variable."
                )

        return {"provider": provider, "issues": issues, "ok": len(issues) == 0}

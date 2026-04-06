from __future__ import annotations

import json
import logging
from urllib import error, request

from quant_system.config import AIConfig


LOGGER = logging.getLogger(__name__)


class AIService:
    def __init__(self, config: AIConfig) -> None:
        self.config = config

    @property
    def available(self) -> bool:
        return self.config.enabled and self.config.provider in {"openai", "openrouter"} and bool(self.config.api_key)

    def _build_request(self, prompt: str) -> request.Request:
        base_url = self.config.api_base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {self.config.api_key}",
            "Content-Type": "application/json",
        }

        if self.config.provider == "openrouter":
            payload = {
                "model": self.config.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            }
            if self.config.openrouter_site_url:
                headers["HTTP-Referer"] = self.config.openrouter_site_url
            if self.config.openrouter_app_name:
                headers["X-Title"] = self.config.openrouter_app_name
            return request.Request(
                url=f"{base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )

        payload = {
            "model": self.config.model,
            "input": prompt,
        }
        return request.Request(
            url=f"{base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def _extract_text(self, body: dict) -> str | None:
        if self.config.provider == "openrouter":
            choices = body.get("choices", [])
            for choice in choices:
                message = choice.get("message", {})
                content = message.get("content", "")
                if isinstance(content, str) and content.strip():
                    return content.strip()
                if isinstance(content, list):
                    texts: list[str] = []
                    for item in content:
                        text = item.get("text") if isinstance(item, dict) else None
                        if text:
                            texts.append(text.strip())
                    combined = "\n".join(part for part in texts if part)
                    if combined:
                        return combined
            return None

        for item in body.get("output", []):
            if item.get("type") != "message":
                continue
            texts: list[str] = []
            for content in item.get("content", []):
                if content.get("type") == "output_text":
                    texts.append(content.get("text", ""))
            summary = "\n".join(part.strip() for part in texts if part.strip()).strip()
            if summary:
                return summary
        return None

    def _request_text(self, prompt: str) -> str | None:
        if not self.available:
            return None

        req = self._build_request(prompt)
        try:
            with request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.URLError as exc:
            LOGGER.warning("AI summary request failed: %s", exc)
            return None

        summary = self._extract_text(body)
        if summary:
            return summary
        LOGGER.warning("AI summary response contained no output text.")
        return None

    def summarize(self, prompt: str) -> str | None:
        return self._request_text(prompt)

    def answer(self, prompt: str) -> str | None:
        return self._request_text(prompt)

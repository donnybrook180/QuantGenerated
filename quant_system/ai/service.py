from __future__ import annotations

import json
import logging
from urllib import error, request

from quant_system.config import AIConfig, AIEndpointConfig


LOGGER = logging.getLogger(__name__)


def _describe_http_error(status_code: int, provider: str) -> str:
    if status_code == 401:
        if provider == "openrouter":
            return "Unauthorized: check AI_API_KEY/OPENROUTER_API_KEY, AI_PROVIDER=openrouter, and AI_API_BASE_URL."
        return "Unauthorized: check AI_API_KEY/OPENAI_API_KEY, AI_PROVIDER=openai, and AI_API_BASE_URL."
    if status_code == 403:
        if provider == "openrouter":
            return "Forbidden: the OpenRouter key is valid but blocked for this model or endpoint."
        return "Forbidden: the OpenAI key is valid but blocked for this model or endpoint."
    if status_code == 404:
        return "Not found: check the provider base URL and model name."
    if status_code == 429:
        return "Rate limited: the provider accepted the key but rejected the request volume."
    return f"HTTP {status_code}"


class AIService:
    def __init__(self, config: AIConfig) -> None:
        self.config = config

    @property
    def available(self) -> bool:
        return self.config.enabled and bool(self.config.endpoint_pool())

    def _build_request(self, endpoint: AIEndpointConfig, prompt: str) -> request.Request:
        base_url = endpoint.api_base_url.rstrip("/")
        headers = {
            "Authorization": f"Bearer {endpoint.api_key}",
            "Content-Type": "application/json",
        }

        if endpoint.provider == "openrouter":
            payload = {
                "model": endpoint.model,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            }
            if endpoint.openrouter_site_url:
                headers["HTTP-Referer"] = endpoint.openrouter_site_url
            if endpoint.openrouter_app_name:
                headers["X-Title"] = endpoint.openrouter_app_name
            return request.Request(
                url=f"{base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers=headers,
                method="POST",
            )

        payload = {
            "model": endpoint.model,
            "input": prompt,
        }
        return request.Request(
            url=f"{base_url}/responses",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

    def _extract_text(self, endpoint: AIEndpointConfig, body: dict) -> str | None:
        if endpoint.provider == "openrouter":
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

    def _request_text_for_endpoint(self, endpoint: AIEndpointConfig, prompt: str) -> tuple[str | None, bool]:
        req = self._build_request(endpoint, prompt)
        try:
            with request.urlopen(req, timeout=30) as response:
                body = json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            response_body = ""
            try:
                response_body = exc.read().decode("utf-8", errors="replace").strip()
            except Exception:
                response_body = ""
            detail = _describe_http_error(exc.code, endpoint.provider)
            if response_body:
                LOGGER.warning(
                    "AI request failed: %s | slot=%s provider=%s model=%s body=%s",
                    detail,
                    endpoint.slot_name,
                    endpoint.provider,
                    endpoint.model,
                    response_body,
                )
            else:
                LOGGER.warning(
                    "AI request failed: %s | slot=%s provider=%s model=%s",
                    detail,
                    endpoint.slot_name,
                    endpoint.provider,
                    endpoint.model,
                )
            return None, exc.code in {429, 500, 502, 503, 504}
        except error.URLError as exc:
            LOGGER.warning(
                "AI request failed: network/url error | slot=%s provider=%s model=%s base_url=%s error=%s",
                endpoint.slot_name,
                endpoint.provider,
                endpoint.model,
                endpoint.api_base_url,
                exc,
            )
            return None, True

        summary = self._extract_text(endpoint, body)
        if summary:
            LOGGER.info(
                "AI request succeeded | slot=%s provider=%s model=%s",
                endpoint.slot_name,
                endpoint.provider,
                endpoint.model,
            )
            return summary, False
        LOGGER.warning(
            "AI response contained no output text | slot=%s provider=%s model=%s body_keys=%s",
            endpoint.slot_name,
            endpoint.provider,
            endpoint.model,
            ",".join(sorted(body.keys())),
        )
        return None, True

    def _request_text(self, prompt: str) -> str | None:
        if not self.available:
            return None

        endpoints = self.config.endpoint_pool()
        for index, endpoint in enumerate(endpoints):
            text, retryable = self._request_text_for_endpoint(endpoint, prompt)
            if text is not None:
                return text
            if not retryable:
                continue
            if index < len(endpoints) - 1:
                LOGGER.info(
                    "AI fallback: moving from slot=%s to slot=%s",
                    endpoint.slot_name,
                    endpoints[index + 1].slot_name,
                )
        return None

    def summarize(self, prompt: str) -> str | None:
        return self._request_text(prompt)

    def answer(self, prompt: str) -> str | None:
        return self._request_text(prompt)

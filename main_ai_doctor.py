from __future__ import annotations

from quant_system.ai.service import AIService
from quant_system.config import SystemConfig


def main() -> int:
    config = SystemConfig()
    ai_config = config.ai
    service = AIService(ai_config)

    print("AI doctor")
    print(f"enabled: {ai_config.enabled}")
    print(f"provider: {ai_config.provider}")
    print(f"model: {ai_config.model}")
    print(f"base_url: {ai_config.api_base_url}")
    print(f"api_key_present: {bool(ai_config.api_key)}")
    if ai_config.provider == "openrouter":
        print(f"openrouter_site_url: {ai_config.openrouter_site_url or 'not set'}")
        print(f"openrouter_app_name: {ai_config.openrouter_app_name or 'not set'}")

    if not ai_config.enabled:
        print("status: AI is disabled")
        return 1
    if not ai_config.api_key:
        print("status: missing API key")
        return 1
    if ai_config.provider not in {"openai", "openrouter"}:
        print(f"status: unsupported provider '{ai_config.provider}'")
        return 1

    prompt = "Reply with exactly: OK"
    response = service.answer(prompt)
    if response is None:
        print("status: request failed")
        return 1

    print("status: request succeeded")
    print(f"response: {response.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

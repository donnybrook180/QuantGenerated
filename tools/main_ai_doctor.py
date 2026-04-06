from __future__ import annotations

import _bootstrap  # noqa: F401

from quant_system.ai.service import AIService
from quant_system.config import SystemConfig


def _mask_key(value: str) -> str:
    if len(value) <= 10:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def main() -> int:
    config = SystemConfig()
    ai_config = config.ai
    service = AIService(ai_config)
    endpoints = ai_config.endpoint_pool()

    print("AI doctor")
    print(f"enabled: {ai_config.enabled}")
    print(f"configured_slots: {len(endpoints)}")
    for endpoint in endpoints:
        print(
            f"- slot={endpoint.slot_name} provider={endpoint.provider} model={endpoint.model} "
            f"base_url={endpoint.api_base_url} api_key={_mask_key(endpoint.api_key)}"
        )

    if not ai_config.enabled:
        print("status: AI is disabled")
        return 1
    if not endpoints:
        print("status: missing API key")
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

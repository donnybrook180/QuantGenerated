from __future__ import annotations

import sys

from quant_system.ai.chat import ExperimentChat
from quant_system.config import SystemConfig


def main() -> int:
    config = SystemConfig()
    profiles = list(config.instrument.active_profiles)
    question = " ".join(sys.argv[1:]).strip()
    if not question:
        print("Usage: .\\.venv\\Scripts\\python.exe main_ai_chat.py <question>")
        return 1

    chat = ExperimentChat(config.ai.experiment_database_path, config.ai)
    answer = chat.ask(question, profiles)
    print("Question:")
    print(answer.question)
    print("")
    print("Answer:")
    print(answer.answer)
    print("")
    print("Profiles:")
    print(", ".join(profiles))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

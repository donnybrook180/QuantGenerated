from __future__ import annotations


def build_analysis_prompt(profile_name: str, local_summary: str, next_experiments: list[str]) -> str:
    suggestions = "\n".join(f"- {item}" for item in next_experiments)
    return (
        f"You are reviewing a trading research profile named '{profile_name}'. "
        "Use the local analysis below to produce a concise research note. "
        "Do not invent metrics that are not present.\n\n"
        "Local analysis:\n"
        f"{local_summary}\n\n"
        "Recommended next experiments:\n"
        f"{suggestions}\n\n"
        "Return:\n"
        "1. A short plain-language diagnosis.\n"
        "2. The highest-value next experiment.\n"
        "3. One warning about overfitting or sample quality if relevant."
    )


def build_chat_prompt(question: str, context: str, local_answer: str) -> str:
    return (
        "You are answering a question about a local trading research system. "
        "Use only the supplied context and local answer draft. "
        "Do not invent metrics, runs, or conclusions that are not present.\n\n"
        f"Question:\n{question}\n\n"
        f"Context:\n{context}\n\n"
        f"Local answer draft:\n{local_answer}\n\n"
        "Return a concise final answer in plain language. "
        "Prefer direct comparison and mention sample size limits when relevant."
    )

from __future__ import annotations

from dataclasses import dataclass

from quant_system.ai.context_builder import build_experiment_context
from quant_system.ai.prompts import build_chat_prompt
from quant_system.ai.service import AIService
from quant_system.ai.storage import ExperimentStore
from quant_system.config import AIConfig


@dataclass(slots=True)
class ChatAnswer:
    question: str
    answer: str
    context: str


class ExperimentChat:
    def __init__(self, database_path: str, ai_config: AIConfig) -> None:
        self.store = ExperimentStore(database_path)
        self.ai_config = ai_config
        self.ai_service = AIService(ai_config)

    def ask(self, question: str, profiles: list[str]) -> ChatAnswer:
        normalized = question.lower()
        if "vergelijk" in normalized or "compare" in normalized:
            answer, context = self._compare_profiles(profiles)
        elif "beste" in normalized or "best" in normalized:
            answer, context = self._best_profile(profiles)
        elif "experiment" in normalized or "next" in normalized or "volgende" in normalized:
            answer, context = self._next_experiments(profiles)
        else:
            answer, context = self._profile_snapshot(profiles)

        if self.ai_service.available:
            prompt = build_chat_prompt(question, context[: self.ai_config.max_context_chars], answer)
            enriched = self.ai_service.answer(prompt)
            if enriched:
                answer = enriched
        return ChatAnswer(question=question, answer=answer, context=context)

    def _profile_snapshot(self, profiles: list[str]) -> tuple[str, str]:
        contexts: list[str] = []
        lines: list[str] = []
        for profile in profiles:
            recent = self.store.list_recent_experiments(profile, limit=3)
            best = self.store.get_best_experiment(profile)
            contexts.append(build_experiment_context(profile, recent, best))
            if best is None:
                lines.append(f"{profile}: geen experiment history beschikbaar.")
                continue
            lines.append(
                f"{profile}: beste run heeft pnl {best.realized_pnl:.2f}, profit factor {best.profit_factor:.2f}, "
                f"{best.closed_trades} closed trades en drawdown {best.max_drawdown_pct:.2f}%."
            )
        return "\n".join(lines), "\n\n".join(contexts)

    def _best_profile(self, profiles: list[str]) -> tuple[str, str]:
        ranked = []
        contexts: list[str] = []
        for profile in profiles:
            best = self.store.get_best_experiment(profile)
            recent = self.store.list_recent_experiments(profile, limit=3)
            contexts.append(build_experiment_context(profile, recent, best))
            if best is not None:
                ranked.append((profile, best))
        if not ranked:
            return "Er is nog geen experiment history beschikbaar.", "\n\n".join(contexts)
        ranked.sort(key=lambda item: (item[1].realized_pnl, item[1].profit_factor, item[1].closed_trades), reverse=True)
        winner_profile, winner = ranked[0]
        answer = (
            f"Op basis van de beste geregistreerde run staat {winner_profile} nu bovenaan met pnl {winner.realized_pnl:.2f}, "
            f"profit factor {winner.profit_factor:.2f}, {winner.closed_trades} closed trades en drawdown {winner.max_drawdown_pct:.2f}%. "
            "Let wel op de sample size voordat je hier live conclusies aan hangt."
        )
        return answer, "\n\n".join(contexts)

    def _compare_profiles(self, profiles: list[str]) -> tuple[str, str]:
        contexts: list[str] = []
        comparisons: list[str] = []
        snapshots = []
        for profile in profiles:
            best = self.store.get_best_experiment(profile)
            recent = self.store.list_recent_experiments(profile, limit=3)
            contexts.append(build_experiment_context(profile, recent, best))
            if best is not None:
                snapshots.append((profile, best))
        if len(snapshots) < 2:
            return "Er zijn nog niet genoeg profielen met experiment history om te vergelijken.", "\n\n".join(contexts)
        snapshots.sort(key=lambda item: (item[1].realized_pnl, item[1].profit_factor), reverse=True)
        for profile, snap in snapshots:
            comparisons.append(
                f"{profile}: pnl {snap.realized_pnl:.2f}, pf {snap.profit_factor:.2f}, "
                f"closed trades {snap.closed_trades}, drawdown {snap.max_drawdown_pct:.2f}%"
            )
        leader = snapshots[0]
        answer = (
            "Vergelijking op basis van de beste geregistreerde run:\n"
            + "\n".join(comparisons)
            + "\n"
            + f"Beste profiel nu: {leader[0]}. Beoordeel dit wel samen met de sample size."
        )
        return answer, "\n\n".join(contexts)

    def _next_experiments(self, profiles: list[str]) -> tuple[str, str]:
        contexts: list[str] = []
        lines: list[str] = []
        for profile in profiles:
            current, previous = self.store.compare_latest_runs(profile)
            best = self.store.get_best_experiment(profile)
            recent = self.store.list_recent_experiments(profile, limit=3)
            contexts.append(build_experiment_context(profile, recent, best))
            if current is None:
                lines.append(f"{profile}: nog geen runs beschikbaar.")
                continue
            if previous is None:
                lines.append(f"{profile}: eerst meer runs verzamelen voordat experiment-prioritering zinvol is.")
                continue
            if current.realized_pnl < previous.realized_pnl:
                lines.append(f"{profile}: laatste wijziging verslechterde de run; eerst terug naar de vorige betere iteratie.")
            elif current.closed_trades < 5:
                lines.append(f"{profile}: edge lijkt mogelijk positief, maar sample is te klein; vergroot evaluatie of trade count veilig.")
            else:
                lines.append(f"{profile}: focus op de zwakste exitbucket of uurfilter uit de laatste artifacts.")
        return "\n".join(lines), "\n\n".join(contexts)

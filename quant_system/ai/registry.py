from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path

from quant_system.ai.models import AgentRegistryRecord, ProfileArtifacts


def _load_rows(path: Path | None) -> list[dict[str, str]]:
    if path is None or not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _profit_factor(pnls: list[float]) -> float:
    gross_profit = sum(pnl for pnl in pnls if pnl > 0)
    gross_loss = abs(sum(pnl for pnl in pnls if pnl < 0))
    if gross_loss == 0:
        return gross_profit if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _win_rate(pnls: list[float]) -> float:
    if not pnls:
        return 0.0
    wins = sum(1 for pnl in pnls if pnl > 0)
    return wins / len(pnls) * 100.0


def _verdict(realized_pnl: float, closed_trades: int, profit_factor: float, source_type: str) -> tuple[str, str]:
    if closed_trades <= 0:
        return "idle", f"No closed trades yet for {source_type}; keep it in observation only."
    if realized_pnl > 0 and profit_factor >= 1.2 and closed_trades >= 3:
        return "promising", "Promote this agent for deeper validation and parameter refinement."
    if realized_pnl > 0 and profit_factor >= 1.0:
        return "needs_retest", "Edge is positive but sample is thin; increase evaluation sample size."
    if closed_trades < 3:
        return "needs_retest", "Sample is too small to reject; retest on more history."
    return "rejected", "Do not prioritize this agent until the entry or exit logic is redesigned."


def build_agent_registry_records(profile_name: str, artifacts: ProfileArtifacts) -> list[AgentRegistryRecord]:
    trade_rows = _load_rows(artifacts.trade_log)
    shadow_rows = _load_rows(artifacts.shadow_log)
    records: list[AgentRegistryRecord] = []

    grouped_trade_pnls: dict[str, list[float]] = defaultdict(list)
    trade_data_sources: dict[str, str] = defaultdict(lambda: "duckdb_cache")
    for row in trade_rows:
        agent_name = row.get("entry_reason", "unknown")
        pnl = float(row.get("pnl", "0") or 0.0)
        grouped_trade_pnls[agent_name].append(pnl)

    for agent_name, pnls in grouped_trade_pnls.items():
        pf = _profit_factor(pnls)
        win_rate = _win_rate(pnls)
        verdict, action = _verdict(sum(pnls), len(pnls), pf, "realized")
        records.append(
            AgentRegistryRecord(
                profile_name=profile_name,
                agent_name=agent_name,
                source_type="realized",
                realized_pnl=sum(pnls),
                closed_trades=len(pnls),
                win_rate_pct=win_rate,
                profit_factor=pf,
                max_drawdown_pct=0.0,
                data_source=trade_data_sources[agent_name],
                verdict=verdict,
                recommended_action=action,
            )
        )

    for row in shadow_rows:
        agent_name = row.get("setup_name", "unknown")
        realized_pnl = float(row.get("realized_pnl", "0") or 0.0)
        closed_trades = int(float(row.get("closed_trades", "0") or 0.0))
        win_rate_pct = float(row.get("win_rate_pct", "0") or 0.0)
        profit_factor = float(row.get("profit_factor", "0") or 0.0)
        max_drawdown_pct = float(row.get("max_drawdown_pct", "0") or 0.0)
        data_source = row.get("data_source", "unknown") or "unknown"
        verdict, action = _verdict(realized_pnl, closed_trades, profit_factor, "shadow")
        records.append(
            AgentRegistryRecord(
                profile_name=profile_name,
                agent_name=agent_name,
                source_type="shadow",
                realized_pnl=realized_pnl,
                closed_trades=closed_trades,
                win_rate_pct=win_rate_pct,
                profit_factor=profit_factor,
                max_drawdown_pct=max_drawdown_pct,
                data_source=data_source,
                verdict=verdict,
                recommended_action=action,
            )
        )

    return records


def render_agent_registry(records: list[AgentRegistryRecord], profile_name: str) -> str:
    lines = [f"Profile: {profile_name}", "Agent registry", ""]
    if not records:
        lines.append("No agent records available yet.")
        return "\n".join(lines)

    ranked = sorted(
        records,
        key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades),
        reverse=True,
    )
    for record in ranked:
        lines.append(
            f"{record.agent_name} [{record.source_type}]: pnl={record.realized_pnl:.2f} "
            f"closed={record.closed_trades} pf={record.profit_factor:.2f} "
            f"win_rate={record.win_rate_pct:.2f}% verdict={record.verdict} "
            f"data_source={record.data_source}"
        )
        lines.append(f"action: {record.recommended_action}")
    return "\n".join(lines)


def render_agent_catalog(profile_name: str, rows: list[dict[str, object]]) -> str:
    lines = [f"Profile: {profile_name}", "Agent catalog", ""]
    if not rows:
        lines.append("No catalog entries available yet.")
        return "\n".join(lines)

    for row in rows:
        lines.append(
            f"{row['agent_name']} [{row['lifecycle_scope']}]: status={row['status']} "
            f"active={row['is_active']} class={row['class_name']}"
        )
        if row.get("variant_label"):
            lines.append(
                f"variant: {row['variant_label']} timeframe={row.get('timeframe_label', '')} session={row.get('session_label', '')}"
            )
        lines.append(f"path: {row['code_path']}")
        lines.append(f"description: {row['description']}")
        lines.append(
            f"version_id={row['last_version_id']} evaluation_id={row['last_evaluation_id']} "
            f"first_seen={row['first_seen_at']} last_seen={row['last_seen_at']}"
        )
    return "\n".join(lines)

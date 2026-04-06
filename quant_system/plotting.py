from __future__ import annotations

import csv
from pathlib import Path

ARTIFACTS_DIR = Path("artifacts")


def _safe_name(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "_" for ch in value).strip("_")


def _load_trade_pnls(path: str) -> list[float]:
    trade_path = Path(path)
    if not trade_path.exists():
        return []
    with trade_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return [float(row["pnl"]) for row in reader if row.get("pnl")]


def _equity_curve(pnls: list[float]) -> list[float]:
    equity = 0.0
    curve: list[float] = []
    for pnl in pnls:
        equity += pnl
        curve.append(equity)
    return curve


def plot_symbol_research(symbol: str, rows) -> list[Path]:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ModuleNotFoundError:
        return []

    ARTIFACTS_DIR.mkdir(exist_ok=True)
    slug = _safe_name(symbol)
    ranked = sorted(rows, key=lambda item: (item.realized_pnl, item.profit_factor, item.closed_trades), reverse=True)
    top = ranked[:8]
    paths: list[Path] = []

    if top:
        ranking_path = ARTIFACTS_DIR / f"{slug}_candidate_ranking.png"
        fig, ax = plt.subplots(figsize=(12, 6))
        labels = [row.name[:36] for row in top]
        values = [row.realized_pnl for row in top]
        colors = ["#1f7a1f" if value >= 0 else "#b22222" for value in values]
        ax.barh(labels[::-1], values[::-1], color=colors[::-1])
        ax.set_title(f"{symbol} Candidate PnL Ranking")
        ax.set_xlabel("Realized PnL")
        fig.tight_layout()
        fig.savefig(ranking_path, dpi=150)
        plt.close(fig)
        paths.append(ranking_path)

        scatter_path = ARTIFACTS_DIR / f"{slug}_validation_test_scatter.png"
        fig, ax = plt.subplots(figsize=(8, 6))
        x = [row.validation_pnl for row in top]
        y = [row.test_pnl for row in top]
        sizes = [max(row.walk_forward_pass_rate_pct, 10.0) * 4 for row in top]
        colors = [row.profit_factor for row in top]
        scatter = ax.scatter(x, y, s=sizes, c=colors, cmap="viridis", alpha=0.8, edgecolors="black", linewidths=0.5)
        for row in top:
            ax.annotate(row.name[:20], (row.validation_pnl, row.test_pnl), fontsize=7, alpha=0.8)
        ax.axhline(0.0, color="gray", linewidth=1)
        ax.axvline(0.0, color="gray", linewidth=1)
        ax.set_title(f"{symbol} Validation vs Test")
        ax.set_xlabel("Validation PnL")
        ax.set_ylabel("Test PnL")
        fig.colorbar(scatter, ax=ax, label="Profit factor")
        fig.tight_layout()
        fig.savefig(scatter_path, dpi=150)
        plt.close(fig)
        paths.append(scatter_path)

        regime_path = ARTIFACTS_DIR / f"{slug}_regimes.png"
        fig, ax = plt.subplots(figsize=(12, 6))
        labels = [row.name[:24] for row in top[:6]]
        best_values = [row.best_regime_pnl for row in top[:6]]
        worst_values = [row.worst_regime_pnl for row in top[:6]]
        positions = list(range(len(labels)))
        ax.bar([pos - 0.2 for pos in positions], best_values, width=0.4, label="Best regime", color="#2b8cbe")
        ax.bar([pos + 0.2 for pos in positions], worst_values, width=0.4, label="Worst regime", color="#de2d26")
        ax.set_xticks(positions)
        ax.set_xticklabels(labels, rotation=25, ha="right")
        ax.set_title(f"{symbol} Regime Contribution")
        ax.set_ylabel("PnL")
        ax.legend()
        fig.tight_layout()
        fig.savefig(regime_path, dpi=150)
        plt.close(fig)
        paths.append(regime_path)

        best = top[0]
        trade_pnls = _load_trade_pnls(best.trade_log_path)
        if trade_pnls:
            equity_path = ARTIFACTS_DIR / f"{slug}_best_candidate_equity.png"
            fig, ax = plt.subplots(figsize=(12, 5))
            ax.plot(_equity_curve(trade_pnls), color="#1f4e79", linewidth=2)
            ax.set_title(f"{symbol} Equity Curve: {best.name}")
            ax.set_xlabel("Closed trade number")
            ax.set_ylabel("Cumulative PnL")
            ax.axhline(0.0, color="gray", linewidth=1)
            fig.tight_layout()
            fig.savefig(equity_path, dpi=150)
            plt.close(fig)
            paths.append(equity_path)

    return paths

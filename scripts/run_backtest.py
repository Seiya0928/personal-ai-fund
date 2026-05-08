"""SQLite に保存済みの Public API データで複数戦略をバックテストする。"""
import sys
import datetime
from itertools import product
from pathlib import Path
from typing import Optional
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.storage.sqlite_store import SQLiteStore
from src.strategies.moving_average import MovingAverageCross
from src.strategies.dca import DollarCostAveragingStrategy
from src.strategies.dip_buy import DipBuyStrategy
from src.backtest.runner import BacktestRunner, BacktestResult
from src.utils.logger import get_logger

log = get_logger("run_backtest")
ROOT = Path(__file__).resolve().parents[1]

SYMBOL = "BTC_JPY"
INITIAL_CAPITAL = 100_000
INTERVALS = ("1day", "1hour")
FEE_BPS = 12.0
SPREAD_BPS = 5.0
B_BASELINE_CONFIG = {
    "dip_threshold_pct": 3.0,
    "take_profit_pct": 5.0,
    "stop_loss_pct": 10.0,
    "max_holding_days": 90.0,
    "max_position_ratio": 0.35,
    "cooldown_days": 10.0,
}
B_GRID_OPTIONS = {
    "dip_threshold_pct": [3.0, 5.0, 7.0, 10.0],
    "take_profit_pct": [5.0, 7.5, 10.0],
    "stop_loss_pct": [7.5, 10.0, 12.5, 15.0],
    "max_holding_days": [30.0, 60.0, 90.0, 180.0],
    "max_position_ratio": [0.05, 0.10, 0.15],
    "cooldown_days": [3.0, 7.0, 14.0, 30.0],
}
FILTER_SEARCH_BASES = [
    {
        "name": "seed_return",
        "params": {
            "dip_threshold_pct": 3.0,
            "take_profit_pct": 10.0,
            "stop_loss_pct": 12.5,
            "max_holding_days": 90.0,
            "max_position_ratio": 0.15,
            "cooldown_days": 14.0,
        },
    },
    {
        "name": "seed_safe",
        "params": {
            "dip_threshold_pct": 5.0,
            "take_profit_pct": 5.0,
            "stop_loss_pct": 7.5,
            "max_holding_days": 30.0,
            "max_position_ratio": 0.05,
            "cooldown_days": 30.0,
        },
    },
]
FILTER_SEARCH_OPTIONS = {
    "min_drop_from_recent_high_pct": [0.0, 10.0, 15.0, 20.0],
    "recent_high_lookback_days": [14, 30, 60, 90],
    "trend_filter": [False, True],
    "volatility_filter": ["none", "high_only", "exclude_extreme_high"],
    "min_days_between_entries": [7.0, 14.0, 30.0, 60.0],
}


def _required_rows(strategy_name: str, interval: str) -> int:
    if strategy_name == "移動平均クロス":
        return 73 if interval == "1hour" else 21
    return 2


def _beats_or_is_much_safer(excess_return: float, drawdown_diff: float) -> bool:
    return excess_return > 0 or drawdown_diff <= -10.0


def _iter_b_grid_configs() -> list[dict]:
    keys = list(B_GRID_OPTIONS.keys())
    configs = []
    for values in product(*(B_GRID_OPTIONS[key] for key in keys)):
        params = dict(zip(keys, values))
        label = (
            f"B-grid d{params['dip_threshold_pct']:g}"
            f"_tp{params['take_profit_pct']:g}"
            f"_sl{params['stop_loss_pct']:g}"
            f"_h{params['max_holding_days']:g}"
            f"_p{params['max_position_ratio']:.2f}"
            f"_cd{params['cooldown_days']:g}"
        )
        configs.append({"name": label, "params": params})
    return configs


def _iter_filtered_b_configs() -> list[dict]:
    keys = list(FILTER_SEARCH_OPTIONS.keys())
    configs = []
    for base in FILTER_SEARCH_BASES:
        for values in product(*(FILTER_SEARCH_OPTIONS[key] for key in keys)):
            params = dict(base["params"])
            params.update(dict(zip(keys, values)))
            label = (
                f"{base['name']}"
                f"_drop{params['min_drop_from_recent_high_pct']:g}"
                f"_rh{params['recent_high_lookback_days']}"
                f"_trend{int(params['trend_filter'])}"
                f"_vol{params['volatility_filter']}"
                f"_gap{params['min_days_between_entries']:g}"
            )
            configs.append({
                "name": label,
                "params": params,
                "base_name": base["name"],
            })
    return configs


def _status_result(
    name: str,
    interval: str,
    rows: list[dict],
    status: str,
    reason: str = "",
    result: Optional[BacktestResult] = None,
) -> dict:
    return {
        "name": name,
        "interval": interval,
        "rows": rows,
        "status": status,
        "reason": reason,
        "result": result,
        "benchmark": None,
        "excess_return_vs_benchmark": None,
        "drawdown_diff_vs_benchmark": None,
        "benchmark_verdict": None,
        "warnings": [],
        "comment": "",
        "evaluation": None,
        "provisional_score": None,
        "live_evaluation": None,
        "live_failed_checks": [],
        "live_score": None,
        "near_live_candidate": False,
        "params": None,
        "group": "main",
        "base_name": None,
    }


def _period_days(rows: list[dict]) -> float:
    if len(rows) <= 1:
        return 1 / 24
    first_ts = pd.to_datetime(pd.to_numeric(rows[0]["timestamp"]), unit="ms", utc=True)
    last_ts = pd.to_datetime(pd.to_numeric(rows[-1]["timestamp"]), unit="ms", utc=True)
    return max((last_ts - first_ts).total_seconds() / 86400, 1 / 24)


def _annualized_return(final_capital: float, initial_capital: float, period_days: float) -> float:
    years = period_days / 365.25
    if years <= 0 or initial_capital <= 0:
        return 0.0
    return ((final_capital / initial_capital) ** (1 / years) - 1) * 100


def _compute_buy_and_hold(rows: list[dict]) -> dict:
    first_price = float(rows[0]["close"])
    last_price = float(rows[-1]["close"])
    buy_price = first_price * (1 + SPREAD_BPS / 10_000)
    qty = INITIAL_CAPITAL / (buy_price * (1 + FEE_BPS / 10_000))
    invested = qty * buy_price * (1 + FEE_BPS / 10_000)

    peak = 0.0
    max_dd = 0.0
    for row in rows:
        equity = qty * float(row["close"])
        peak = max(peak, equity)
        dd = (peak - equity) / peak * 100 if peak > 0 else 0.0
        max_dd = max(max_dd, dd)

    final_capital = qty * last_price
    total_return = (final_capital - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    period_days = _period_days(rows)
    annualized = _annualized_return(final_capital, INITIAL_CAPITAL, period_days)
    return {
        "initial_capital": INITIAL_CAPITAL,
        "invested_capital": invested,
        "final_capital": round(final_capital, 0),
        "total_return_pct": round(total_return, 2),
        "annualized_return_pct": round(annualized, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "period_days": round(period_days, 1),
    }


def _evaluate_entry(entry: dict):
    if entry["status"] != "OK" or entry["result"] is None or entry["benchmark"] is None:
        return

    result = entry["result"]
    benchmark = entry["benchmark"]
    excess_return = result.total_return_pct - benchmark["total_return_pct"]
    dd_diff = result.max_drawdown_pct - benchmark["max_drawdown_pct"]
    entry["excess_return_vs_benchmark"] = round(excess_return, 2)
    entry["drawdown_diff_vs_benchmark"] = round(dd_diff, 2)
    entry["benchmark_verdict"] = "Buy & Holdに勝った" if excess_return > 0 else "Buy & Holdに負けた"

    warnings = []
    if result.max_drawdown_pct > 50:
        warnings.append("DD過大")
    if result.win_rate_pct == 100.0:
        warnings.append("未実現損失・損切り未考慮の可能性あり")
    if entry["interval"] == "1hour":
        warnings.append("1hour戦略はコスト負けしやすい")
    entry["warnings"] = warnings
    entry["comment"] = " / ".join(warnings) if warnings else "特記事項なし"
    entry["provisional_score"] = round(
        excess_return
        + min(result.total_return_pct, 30)
        - max(result.max_drawdown_pct - 25, 0) * 0.6
        - max(result.average_holding_days - 90, 0) * 0.03
        - max(result.capital_utilization_rate_pct - 50, 0) * 0.1
        - result.stop_loss_count * 0.5
        + min(result.trade_count, 30) * 0.1,
        2,
    )

    if result.max_drawdown_pct > 50:
        entry["evaluation"] = "Reject"
        return
    if excess_return <= 0 and dd_diff > -10:
        entry["evaluation"] = "Reject"
        return
    if entry["interval"] == "1hour" and result.total_return_pct < 10:
        entry["evaluation"] = "Reject"
        return

    candidate_ok = (
        result.total_return_pct > 10
        and _beats_or_is_much_safer(excess_return, dd_diff)
        and result.trade_count >= 10
        and result.period_days >= 365
        and result.max_drawdown_pct <= 50
        and result.annualized_return_pct > 0
        and result.max_holding_days <= 365
        and result.average_holding_days <= 180
        and result.capital_utilization_rate_pct <= 70
        and result.max_portfolio_unrealized_drawdown_pct <= 35
        and not (entry["interval"] == "1hour" and result.period_days < 365)
        and result.win_rate_pct < 100.0
    )
    if candidate_ok:
        entry["evaluation"] = "Candidate"
        return

    if result.win_rate_pct == 100.0 and _beats_or_is_much_safer(excess_return, dd_diff) and result.max_drawdown_pct <= 50:
        entry["evaluation"] = "Watch"
        return

    if entry["interval"] == "1hour" and result.period_days < 365:
        entry["evaluation"] = "Watch"
        return

    if _beats_or_is_much_safer(excess_return, dd_diff) and result.annualized_return_pct > 0 and result.max_drawdown_pct <= 50:
        entry["evaluation"] = "Watch"
    else:
        entry["evaluation"] = "Reject"


def _evaluate_live_entry(entry: dict):
    if entry["status"] != "OK" or entry["result"] is None:
        entry["live_evaluation"] = "LiveReject"
        entry["live_failed_checks"] = ["not_ok"]
        entry["live_score"] = float("inf")
        entry["near_live_candidate"] = False
        return

    result = entry["result"]
    failed_checks = []
    checks = [
        ("max_dd", result.max_drawdown_pct <= 15),
        ("portfolio_unrealized_dd", result.max_portfolio_unrealized_drawdown_pct <= 8),
        ("max_hold", result.max_holding_days <= 90),
        ("avg_hold", result.average_holding_days <= 30),
        ("utilization", result.capital_utilization_rate_pct <= 25),
        ("trades", result.trade_count <= 250),
        ("stop_loss", result.stop_loss_count <= 40),
        ("annualized", result.annualized_return_pct >= 5),
    ]
    for label, ok in checks:
        if not ok:
            failed_checks.append(label)

    if entry["interval"] != "1day":
        failed_checks.append("reference_only_interval")

    if entry["interval"] != "1day" or result.annualized_return_pct < 3 or len(failed_checks) >= 3:
        entry["live_evaluation"] = "LiveReject"
    elif len(failed_checks) <= 2:
        entry["live_evaluation"] = "LiveWatch"
    else:
        entry["live_evaluation"] = "LiveReject"

    if not failed_checks and entry["interval"] == "1day":
        entry["live_evaluation"] = "LiveCandidate"

    entry["live_failed_checks"] = failed_checks
    near_live_checks = [
        result.max_drawdown_pct <= 15,
        result.max_portfolio_unrealized_drawdown_pct <= 8,
        result.max_holding_days <= 90,
        result.average_holding_days <= 30,
        result.capital_utilization_rate_pct <= 25,
        result.trade_count <= 365,
        result.stop_loss_count <= 60,
        result.annualized_return_pct >= 5,
        entry["interval"] == "1day",
    ]
    entry["near_live_candidate"] = all(near_live_checks)
    entry["live_score"] = (
        result.max_drawdown_pct,
        result.max_portfolio_unrealized_drawdown_pct,
        result.trade_count,
        result.stop_loss_count,
        result.average_holding_days,
        -result.annualized_return_pct,
        -result.return_per_max_drawdown,
        -result.return_per_holding_day,
        -(entry["excess_return_vs_benchmark"] or -999.0),
    )


def _select_provisional_candidate(results: list[dict]) -> Optional[dict]:
    eligible = [entry for entry in results if entry["status"] == "OK" and entry["evaluation"] in {"Candidate", "Watch"}]
    if not eligible:
        return None

    def sort_key(entry: dict):
        result = entry["result"]
        tier = 0 if entry["evaluation"] == "Candidate" else 1
        hour_penalty = 1 if entry["interval"] == "1hour" else 0
        return (
            tier,
            hour_penalty,
            -(entry["provisional_score"] or 0.0),
            -result.total_return_pct,
            result.max_drawdown_pct,
        )

    return sorted(eligible, key=sort_key)[0]


def _rank_operational_candidates(results: list[dict]) -> list[dict]:
    ranked = [entry for entry in results if entry["status"] == "OK" and entry["result"] is not None]

    def sort_key(entry: dict):
        result = entry["result"]
        evaluation_bias = {"Candidate": 0, "Watch": 1, "Reject": 2}.get(entry["evaluation"], 3)
        return (
            evaluation_bias,
            -(entry["excess_return_vs_benchmark"] or -999.0),
            result.max_drawdown_pct,
            result.average_holding_days,
            result.capital_utilization_rate_pct,
            result.stop_loss_count,
            -result.annualized_return_pct,
        )

    return sorted(ranked, key=sort_key)


def _rank_live_candidates(grid_results: list[dict]) -> list[dict]:
    eligible = [entry for entry in grid_results if entry["status"] == "OK" and entry["result"] is not None]

    def sort_key(entry: dict):
        live_bias = {"LiveCandidate": 0, "LiveWatch": 1, "LiveReject": 2}.get(entry["live_evaluation"], 3)
        result = entry["result"]
        return (
            live_bias,
            result.max_drawdown_pct,
            result.max_portfolio_unrealized_drawdown_pct,
            result.trade_count,
            result.stop_loss_count,
            result.average_holding_days,
            -result.annualized_return_pct,
            -result.return_per_max_drawdown,
            -result.return_per_holding_day,
            -(entry["excess_return_vs_benchmark"] or -999.0),
        )

    return sorted(eligible, key=sort_key)


def _find_baseline_entry(results: list[dict], name: str, interval: str) -> Optional[dict]:
    for entry in results:
        if entry["name"] == name and entry["interval"] == interval and entry["status"] == "OK":
            return entry
    return None


def _summarize_live_counts(grid_results: list[dict]) -> dict:
    counts = {"LiveCandidate": 0, "LiveWatch": 0, "LiveReject": 0, "NearLiveCandidate": 0}
    for entry in grid_results:
        label = entry.get("live_evaluation")
        if label in counts:
            counts[label] += 1
        if entry.get("near_live_candidate"):
            counts["NearLiveCandidate"] += 1
    return counts


def _market_regime_counts(entry: dict) -> dict:
    result = entry["result"]
    regimes = {
        "2021_uptrend": 0,
        "2022_downtrend": 0,
        "2023_recovery": 0,
        "2024_uptrend": 0,
        "2025_onward": 0,
    }
    for trade in result.trades:
        ts = trade.get("entry_timestamp")
        if ts is None:
            continue
        year = pd.Timestamp(ts).year
        if year == 2021:
            regimes["2021_uptrend"] += 1
        elif year == 2022:
            regimes["2022_downtrend"] += 1
        elif year == 2023:
            regimes["2023_recovery"] += 1
        elif year == 2024:
            regimes["2024_uptrend"] += 1
        elif year >= 2025:
            regimes["2025_onward"] += 1
    return regimes


def _format_result(entry: dict) -> str:
    name = entry["name"]
    interval = entry["interval"]
    rows = entry["rows"]
    status = entry["status"]
    result = entry["result"]
    if status != "OK":
        return f"- {name} [{interval}] {status}: {entry['reason']}"

    return (
        f"- {name} [{interval}] 件数={len(rows)} "
        f"最終資産=¥{result.final_capital:,.0f} "
        f"総リターン={result.total_return_pct:+.2f}% "
        f"対B&H={entry['excess_return_vs_benchmark']:+.2f}% "
        f"年率={result.annualized_return_pct:+.2f}% "
        f"最大DD={result.max_drawdown_pct:.2f}% "
        f"勝率={result.win_rate_pct:.2f}% "
        f"取引数={result.trade_count} "
        f"評価={entry['evaluation']}"
    )


def _save_markdown(results: list[dict], grid_results: list[dict], filtered_results: list[dict]) -> Path:
    reports_dir = ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    path = reports_dir / f"backtest_{date_str}.md"
    provisional = _select_provisional_candidate(results)
    ranking = _rank_operational_candidates(results)
    live_ranking = _rank_live_candidates(grid_results)
    live_counts = _summarize_live_counts(grid_results)
    filtered_live_ranking = _rank_live_candidates(filtered_results)
    filtered_live_counts = _summarize_live_counts(filtered_results)
    baseline_b = _find_baseline_entry(results, "急落時のみ買い B", "1day")
    previous_top = live_ranking[0] if live_ranking else None
    filtered_top = filtered_live_ranking[0] if filtered_live_ranking else None
    balanced = filtered_live_ranking[0] if filtered_live_ranking else None
    high_return_many_trades = [
        entry for entry in filtered_live_ranking
        if entry["result"].annualized_return_pct >= 5 and entry["result"].trade_count > 250
    ][:5]
    low_return_safe = [
        entry for entry in filtered_live_ranking
        if entry["result"].annualized_return_pct < 5
        and entry["result"].max_drawdown_pct <= 10
        and entry["result"].max_portfolio_unrealized_drawdown_pct <= 5
        and entry["result"].trade_count <= 150
    ][:5]
    improved_vs_b = []
    filtered_improved_vs_b = []
    if baseline_b is not None:
        base = baseline_b["result"]
        for entry in live_ranking:
            result = entry["result"]
            if (
                result.max_drawdown_pct <= base.max_drawdown_pct
                and result.max_portfolio_unrealized_drawdown_pct <= base.max_portfolio_unrealized_drawdown_pct
                and result.trade_count <= base.trade_count
                and result.stop_loss_count <= base.stop_loss_count
                and result.annualized_return_pct >= max(base.annualized_return_pct - 2.0, 5.0)
            ):
                improved_vs_b.append(entry)
        improved_vs_b = improved_vs_b[:10]
        for entry in filtered_live_ranking:
            result = entry["result"]
            if (
                result.max_drawdown_pct <= base.max_drawdown_pct
                and result.max_portfolio_unrealized_drawdown_pct <= base.max_portfolio_unrealized_drawdown_pct
                and result.trade_count <= base.trade_count
                and result.stop_loss_count <= base.stop_loss_count
                and result.annualized_return_pct >= max(base.annualized_return_pct - 2.0, 5.0)
            ):
                filtered_improved_vs_b.append(entry)
        filtered_improved_vs_b = filtered_improved_vs_b[:10]

    lines = [
        "# Backtest Report",
        "",
        f"- Symbol: {SYMBOL}",
        f"- Initial capital: ¥{INITIAL_CAPITAL:,.0f}",
        f"- Cost assumptions: fee 12bps, spread 5bps",
        "- Unrealized DD note: 旧100%表示は、退出後に残った極小BTC残高をピーク建玉と比較していたバグです。現在は position と portfolio を分離して集計しています。",
        f"- B-grid search size: {len(grid_results)}",
        f"- Filtered search size: {len(filtered_results)}",
        "",
        "## 実運用判断",
        "",
    ]

    if provisional is None:
        lines += [
            "- 暫定実運用候補: なし",
            "- 理由: Candidate / Watch 条件を満たす戦略がありません。",
        ]
    else:
        result = provisional["result"]
        lines += [
            f"- 暫定実運用候補: {provisional['name']} / {provisional['interval']} ({provisional['evaluation']})",
            f"- 判定理由: 総リターン {result.total_return_pct:+.2f}%, 対B&H {provisional['excess_return_vs_benchmark']:+.2f}%, 最大DD {result.max_drawdown_pct:.2f}%, 期間 {result.period_days:.1f}日",
        ]

    lines += [
        "",
        "## B派生グリッド探索サマリー",
        "",
        f"- LiveCandidate: {live_counts['LiveCandidate']}",
        f"- LiveWatch: {live_counts['LiveWatch']}",
        f"- LiveReject: {live_counts['LiveReject']}",
        f"- 準LiveCandidate: {live_counts['NearLiveCandidate']}",
    ]

    if baseline_b is not None:
        base = baseline_b["result"]
        lines += [
            "",
            "### B現状",
            "",
            f"- Baseline config: {B_BASELINE_CONFIG}",
            f"- Annualized: {base.annualized_return_pct:+.2f}%",
            f"- Max DD: {base.max_drawdown_pct:.2f}%",
            f"- Portfolio Unrealized DD: {base.max_portfolio_unrealized_drawdown_pct:.2f}%",
            f"- Trades: {base.trade_count}",
            f"- Stop Loss: {base.stop_loss_count}",
            f"- Avg Hold: {base.average_holding_days:.1f}d",
            f"- Live label: {baseline_b['live_evaluation']}",
        ]

    lines += [
        "",
        "## フィルター追加版サマリー",
        "",
        f"- LiveCandidate: {filtered_live_counts['LiveCandidate']}",
        f"- LiveWatch: {filtered_live_counts['LiveWatch']}",
        f"- LiveReject: {filtered_live_counts['LiveReject']}",
        f"- 準LiveCandidate: {filtered_live_counts['NearLiveCandidate']}",
    ]

    if previous_top is not None:
        prev = previous_top["result"]
        lines += [
            "",
            "### 前回ランキング上位",
            "",
            f"- Name: {previous_top['name']}",
            f"- Live: {previous_top['live_evaluation']}",
            f"- Annualized: {prev.annualized_return_pct:+.2f}%",
            f"- Max DD: {prev.max_drawdown_pct:.2f}%",
            f"- Trades: {prev.trade_count}",
            f"- Stop Loss: {prev.stop_loss_count}",
        ]

    lines += [
        "",
        "## B派生グリッド比較表",
        "",
        "| Rank | Name | Live | Annualized | Max DD | Portfolio Unrealized DD | Trades | Stop Loss | Avg Hold | Utilization | Return/DD | Return/Hold Day | Excess vs B&H |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for rank, entry in enumerate(live_ranking[:40], start=1):
        result = entry["result"]
        lines.append(
            f"| {rank} | {entry['name']} | {entry['live_evaluation']} | {result.annualized_return_pct:+.2f}% | "
            f"{result.max_drawdown_pct:.2f}% | {result.max_portfolio_unrealized_drawdown_pct:.2f}% | "
            f"{result.trade_count} | {result.stop_loss_count} | {result.average_holding_days:.1f}d | "
            f"{result.capital_utilization_rate_pct:.2f}% | {result.return_per_max_drawdown:.4f} | "
            f"{result.return_per_holding_day:.4f} | {entry['excess_return_vs_benchmark']:+.2f}% |"
        )

    lines += [
        "",
        "## フィルター追加版の比較表",
        "",
        "| Rank | Name | Base | Live | NearLive | Annualized | Max DD | Portfolio Unrealized DD | Trades | Stop Loss | Avg Hold | Utilization | Excess vs B&H |",
        "|---:|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for rank, entry in enumerate(filtered_live_ranking[:40], start=1):
        result = entry["result"]
        lines.append(
            f"| {rank} | {entry['name']} | {entry.get('base_name')} | {entry['live_evaluation']} | "
            f"{'Yes' if entry.get('near_live_candidate') else 'No'} | {result.annualized_return_pct:+.2f}% | "
            f"{result.max_drawdown_pct:.2f}% | {result.max_portfolio_unrealized_drawdown_pct:.2f}% | "
            f"{result.trade_count} | {result.stop_loss_count} | {result.average_holding_days:.1f}d | "
            f"{result.capital_utilization_rate_pct:.2f}% | {entry['excess_return_vs_benchmark']:+.2f}% |"
        )

    lines += [
        "",
        "## 実運用向きランキング上位10",
        "",
        "| Rank | Name | Live | Max DD | Portfolio Unrealized DD | Trades | Stop Losses | Avg Hold | Annualized | Return/DD | Excess vs B&H |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    for rank, entry in enumerate(filtered_live_ranking[:10], start=1):
        result = entry["result"]
        lines.append(
            f"| {rank} | {entry['name']} | {entry['live_evaluation']} | {result.max_drawdown_pct:.2f}% | "
            f"{result.max_portfolio_unrealized_drawdown_pct:.2f}% | {result.trade_count} | {result.stop_loss_count} | "
            f"{result.average_holding_days:.1f}d | {result.annualized_return_pct:+.2f}% | {result.return_per_max_drawdown:.4f} | "
            f"{entry['excess_return_vs_benchmark']:+.2f}% |"
        )

    lines += [
        "",
        "## 旧Bとの比較",
        "",
    ]

    if filtered_improved_vs_b:
        lines += [
            "| Name | Live | Annualized Δ | Max DD Δ | Portfolio Unrealized DD Δ | Trades Δ | Stop Loss Δ | Avg Hold Δ |",
            "|---|---|---:|---:|---:|---:|---:|---:|",
        ]
        for entry in filtered_improved_vs_b:
            result = entry["result"]
            base = baseline_b["result"]
            lines.append(
                f"| {entry['name']} | {entry['live_evaluation']} | {result.annualized_return_pct - base.annualized_return_pct:+.2f}pt | "
                f"{result.max_drawdown_pct - base.max_drawdown_pct:+.2f}pt | "
                f"{result.max_portfolio_unrealized_drawdown_pct - base.max_portfolio_unrealized_drawdown_pct:+.2f}pt | "
                f"{result.trade_count - base.trade_count:+d} | {result.stop_loss_count - base.stop_loss_count:+d} | "
                f"{result.average_holding_days - base.average_holding_days:+.1f}d |"
            )
    else:
        lines.append("- B現状を明確に上回る候補はありません。")

    lines += [
        "",
        "## 前回ランキング上位との比較",
        "",
    ]
    if previous_top is not None and filtered_top is not None:
        prev = previous_top["result"]
        curr = filtered_top["result"]
        lines += [
            f"- 前回上位: {previous_top['name']} ({previous_top['live_evaluation']})",
            f"- 今回上位: {filtered_top['name']} ({filtered_top['live_evaluation']})",
            f"- Annualized Δ: {curr.annualized_return_pct - prev.annualized_return_pct:+.2f}pt",
            f"- Max DD Δ: {curr.max_drawdown_pct - prev.max_drawdown_pct:+.2f}pt",
            f"- Trades Δ: {curr.trade_count - prev.trade_count:+d}",
            f"- Stop Loss Δ: {curr.stop_loss_count - prev.stop_loss_count:+d}",
        ]
    else:
        lines.append("- 比較対象なし")

    lines += [
        "",
        "## リターンは高いがトレード回数が多すぎる候補",
        "",
    ]
    if high_return_many_trades:
        for entry in high_return_many_trades:
            result = entry["result"]
            lines.append(
                f"- {entry['name']}: Annualized {result.annualized_return_pct:+.2f}%, Trades {result.trade_count}, Stop Loss {result.stop_loss_count}, Live {entry['live_evaluation']}"
            )
    else:
        lines.append("- 該当なし")

    lines += [
        "",
        "## リターンは低いが安全性が高い候補",
        "",
    ]
    if low_return_safe:
        for entry in low_return_safe:
            result = entry["result"]
            lines.append(
                f"- {entry['name']}: Annualized {result.annualized_return_pct:+.2f}%, Max DD {result.max_drawdown_pct:.2f}%, Portfolio Unrealized DD {result.max_portfolio_unrealized_drawdown_pct:.2f}%, Trades {result.trade_count}"
            )
    else:
        lines.append("- 該当なし")

    lines += [
        "",
        "## 最もバランスが良い候補",
        "",
    ]
    if balanced is not None:
        result = balanced["result"]
        regime_counts = _market_regime_counts(balanced)
        lines += [
            f"- Name: {balanced['name']}",
            f"- Live: {balanced['live_evaluation']}",
            f"- Params: {balanced.get('params')}",
            f"- Annualized: {result.annualized_return_pct:+.2f}%",
            f"- Max DD: {result.max_drawdown_pct:.2f}%",
            f"- Portfolio Unrealized DD: {result.max_portfolio_unrealized_drawdown_pct:.2f}%",
            f"- Trades: {result.trade_count}",
            f"- Stop Loss: {result.stop_loss_count}",
            f"- Avg Hold: {result.average_holding_days:.1f}d",
            "",
            "### なぜTradesが減った/減らなかったのか",
            "",
            f"- 直近高値からの下落条件: {balanced['params'].get('min_drop_from_recent_high_pct')}%",
            f"- 直近高値参照期間: {balanced['params'].get('recent_high_lookback_days')}日",
            f"- トレンドフィルター: {balanced['params'].get('trend_filter')}",
            f"- ボラティリティフィルター: {balanced['params'].get('volatility_filter')}",
            f"- 追加エントリー間隔: {balanced['params'].get('min_days_between_entries')}日",
            f"- 分析: Trades {result.trade_count} なので、フィルターで小さい急落を多少抑えても、主因の dip_threshold が低いままでシグナル頻度はまだ高いです。",
            "",
            "### 取引日が集中した相場局面",
            "",
            f"- 2021上昇局面: {regime_counts['2021_uptrend']}",
            f"- 2022下落局面: {regime_counts['2022_downtrend']}",
            f"- 2023回復局面: {regime_counts['2023_recovery']}",
            f"- 2024上昇局面: {regime_counts['2024_uptrend']}",
            f"- 2025以降: {regime_counts['2025_onward']}",
        ]
    else:
        lines.append("- 該当なし")

    lines += [
        "",
        "## Results",
        "",
        "| Strategy | Timeframe | Status | Final | Total Return | B&H Return | Excess vs B&H | Annualized | Max DD | Position Unrealized DD | Portfolio Unrealized DD | Return/DD | Return/Hold Day | Max Hold | Avg Hold | Locked Days | Utilization | Losses | Stop Loss | Timeout | DD vs B&H | Win Rate | Trades | Evaluation | Notes |",
        "|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|",
    ]

    for entry in results:
        name = entry["name"]
        interval = entry["interval"]
        rows = entry["rows"]
        status = entry["status"]
        result = entry["result"]
        if status == "OK" and result is not None and entry["benchmark"] is not None:
            benchmark = entry["benchmark"]
            notes = [entry["benchmark_verdict"]]
            if entry["warnings"]:
                notes.extend(entry["warnings"])
            lines.append(
                f"| {name} | {interval} | {status} | ¥{result.final_capital:,.0f} | "
                f"{result.total_return_pct:+.2f}% | {benchmark['total_return_pct']:+.2f}% | "
                f"{entry['excess_return_vs_benchmark']:+.2f}% | {result.annualized_return_pct:+.2f}% | "
                f"{result.max_drawdown_pct:.2f}% | {result.max_position_unrealized_drawdown_pct:.2f}% | {result.max_portfolio_unrealized_drawdown_pct:.2f}% | "
                f"{result.return_per_max_drawdown:.4f} | {result.return_per_holding_day:.4f} | "
                f"{result.max_holding_days:.1f}d | {result.average_holding_days:.1f}d | {result.max_capital_locked_days:.1f}d | "
                f"{result.capital_utilization_rate_pct:.2f}% | {result.realized_loss_count} | {result.stop_loss_count} | {result.timeout_exit_count} | "
                f"{entry['drawdown_diff_vs_benchmark']:+.2f}pt | {result.win_rate_pct:.2f}% | {result.trade_count} | {entry['evaluation']} | {' / '.join(notes)} |"
            )
        else:
            lines.append(
                f"| {name} | {interval} | {status} | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | - | {entry['reason']} |"
            )

    lines += [
        "",
        "## Details",
        "",
    ]

    for entry in results:
        name = entry["name"]
        interval = entry["interval"]
        rows = entry["rows"]
        status = entry["status"]
        result = entry["result"]
        lines += [f"### {name} / {interval}", "", f"- Status: {status}", f"- Data points: {len(rows)}"]
        if status == "OK" and result is not None:
            benchmark = entry["benchmark"]
            lines += [
                f"- Period days: {result.period_days}",
                f"- Final capital: ¥{result.final_capital:,.0f}",
                f"- Total return: {result.total_return_pct:+.2f}%",
                f"- Annualized return: {result.annualized_return_pct:+.2f}%",
                f"- Max drawdown: {result.max_drawdown_pct:.2f}%",
                f"- Max position unrealized drawdown: {result.max_position_unrealized_drawdown_pct:.2f}%",
                f"- Max portfolio unrealized drawdown: {result.max_portfolio_unrealized_drawdown_pct:.2f}%",
                f"- Return per max drawdown: {result.return_per_max_drawdown:.4f}",
                f"- Return per holding day: {result.return_per_holding_day:.4f}",
                f"- Max holding days: {result.max_holding_days}",
                f"- Average holding days: {result.average_holding_days}",
                f"- Max capital locked days: {result.max_capital_locked_days}",
                f"- Capital utilization rate: {result.capital_utilization_rate_pct:.2f}%",
                f"- Realized loss count: {result.realized_loss_count}",
                f"- Stop loss count: {result.stop_loss_count}",
                f"- Timeout exit count: {result.timeout_exit_count}",
                f"- Win rate: {result.win_rate_pct:.2f}%",
                f"- Closed trades: {result.trade_count}",
                f"- Executions: {result.execution_count}",
                f"- Average PnL: ¥{result.average_pnl_jpy:,.0f}",
                f"- Total PnL: ¥{result.total_pnl_jpy:,.0f}",
                f"- Benchmark final capital: ¥{benchmark['final_capital']:,.0f}",
                f"- Benchmark total return: {benchmark['total_return_pct']:+.2f}%",
                f"- Benchmark annualized return: {benchmark['annualized_return_pct']:+.2f}%",
                f"- Benchmark max drawdown: {benchmark['max_drawdown_pct']:.2f}%",
                f"- Excess return vs benchmark: {entry['excess_return_vs_benchmark']:+.2f}%",
                f"- Drawdown diff vs benchmark: {entry['drawdown_diff_vs_benchmark']:+.2f}pt",
                f"- Benchmark verdict: {entry['benchmark_verdict']}",
                f"- Evaluation: {entry['evaluation']}",
                f"- Live evaluation: {entry['live_evaluation']}",
                f"- Live failed checks: {', '.join(entry['live_failed_checks']) if entry['live_failed_checks'] else 'none'}",
                f"- Notes: {entry['comment']}",
                "",
            ]
        else:
            lines += [
                f"- Reason: {entry['reason']}",
                "",
            ]

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def main():
    store = SQLiteStore()
    results: list[dict] = []
    grid_results: list[dict] = []
    filtered_results: list[dict] = []

    strategy_factories = [
        ("定時積立", lambda interval: DollarCostAveragingStrategy(
            amount_jpy=2_000.0 if interval == "1day" else 500.0,
            every_n_bars=1 if interval == "1day" else 24,
        )),
        ("移動平均クロス", lambda interval: MovingAverageCross(
            short=5 if interval == "1day" else 24,
            long=20 if interval == "1day" else 72,
        )),
        ("急落時のみ買い A", lambda interval: DipBuyStrategy(
            dip_threshold_pct=3.0 if interval == "1day" else 1.5,
            take_profit_pct=5.0,
            stop_loss_pct=None,
            max_holding_days=None,
            max_position_ratio=0.45 if interval == "1day" else 0.30,
            cooldown_days=7.0 if interval == "1day" else 3.0,
        )),
        ("急落時のみ買い B", lambda interval: DipBuyStrategy(
            dip_threshold_pct=3.0 if interval == "1day" else 1.5,
            take_profit_pct=5.0,
            stop_loss_pct=10.0,
            max_holding_days=90.0 if interval == "1day" else 21.0,
            max_position_ratio=0.35 if interval == "1day" else 0.25,
            cooldown_days=10.0 if interval == "1day" else 5.0,
        )),
        ("急落時のみ買い C", lambda interval: DipBuyStrategy(
            dip_threshold_pct=4.0 if interval == "1day" else 2.0,
            take_profit_pct=10.0,
            stop_loss_pct=15.0,
            max_holding_days=180.0 if interval == "1day" else 45.0,
            max_position_ratio=0.30 if interval == "1day" else 0.20,
            cooldown_days=14.0 if interval == "1day" else 7.0,
        )),
        ("急落時のみ買い D", lambda interval: DipBuyStrategy(
            dip_threshold_pct=5.0 if interval == "1day" else 2.5,
            take_profit_pct=15.0,
            stop_loss_pct=20.0,
            max_holding_days=365.0 if interval == "1day" else 90.0,
            max_position_ratio=0.25 if interval == "1day" else 0.15,
            cooldown_days=21.0 if interval == "1day" else 10.0,
        )),
    ]

    for interval in INTERVALS:
        rows = store.load_ohlcv(SYMBOL, interval, limit=3000 if interval == "1hour" else 1500)
        benchmark = _compute_buy_and_hold(rows) if rows else None
        if not rows:
            results.append(_status_result(
                name="全戦略",
                interval=interval,
                rows=[],
                status="SKIPPED",
                reason="保存済みデータがありません。先に fetch_btc_price.py を実行してください。",
            ))
            log.warning(f"データ不足のためスキップ: {SYMBOL} {interval}")
            continue

        for name, factory in strategy_factories:
            minimum_rows = _required_rows(name, interval)
            if len(rows) < minimum_rows:
                entry = _status_result(
                    name=name,
                    interval=interval,
                    rows=rows,
                    status="SKIPPED",
                    reason=f"データ不足（必要: {minimum_rows}件以上 / 実データ: {len(rows)}件）",
                )
                results.append(entry)
                print(_format_result(entry))
                continue

            try:
                strategy = factory(interval)
                df = strategy.generate_signals(rows)
                runner = BacktestRunner(initial_capital=INITIAL_CAPITAL)
                result = runner.run(df)
                entry = _status_result(
                    name=name,
                    interval=interval,
                    rows=rows,
                    status="OK",
                    result=result,
                )
            except ValueError as e:
                entry = _status_result(
                    name=name,
                    interval=interval,
                    rows=rows,
                    status="SKIPPED",
                    reason=str(e),
                )
            except Exception as e:
                entry = _status_result(
                    name=name,
                    interval=interval,
                    rows=rows,
                    status="ERROR",
                    reason=str(e),
                )
            entry["benchmark"] = benchmark
            _evaluate_entry(entry)
            _evaluate_live_entry(entry)
            results.append(entry)
            print(_format_result(entry))

        if interval == "1day":
            for grid_config in _iter_b_grid_configs():
                try:
                    strategy = DipBuyStrategy(**grid_config["params"])
                    df = strategy.generate_signals(rows)
                    runner = BacktestRunner(initial_capital=INITIAL_CAPITAL)
                    result = runner.run(df)
                    entry = _status_result(
                        name=grid_config["name"],
                        interval=interval,
                        rows=rows,
                        status="OK",
                        result=result,
                    )
                except ValueError as e:
                    entry = _status_result(
                        name=grid_config["name"],
                        interval=interval,
                        rows=rows,
                        status="SKIPPED",
                        reason=str(e),
                    )
                except Exception as e:
                    entry = _status_result(
                        name=grid_config["name"],
                        interval=interval,
                        rows=rows,
                        status="ERROR",
                        reason=str(e),
                    )
                entry["benchmark"] = benchmark
                entry["params"] = grid_config["params"]
                entry["group"] = "b_grid"
                _evaluate_entry(entry)
                _evaluate_live_entry(entry)
                grid_results.append(entry)

            for filtered_config in _iter_filtered_b_configs():
                try:
                    strategy = DipBuyStrategy(**filtered_config["params"])
                    df = strategy.generate_signals(rows)
                    runner = BacktestRunner(initial_capital=INITIAL_CAPITAL)
                    result = runner.run(df)
                    entry = _status_result(
                        name=filtered_config["name"],
                        interval=interval,
                        rows=rows,
                        status="OK",
                        result=result,
                    )
                except ValueError as e:
                    entry = _status_result(
                        name=filtered_config["name"],
                        interval=interval,
                        rows=rows,
                        status="SKIPPED",
                        reason=str(e),
                    )
                except Exception as e:
                    entry = _status_result(
                        name=filtered_config["name"],
                        interval=interval,
                        rows=rows,
                        status="ERROR",
                        reason=str(e),
                    )
                entry["benchmark"] = benchmark
                entry["params"] = filtered_config["params"]
                entry["group"] = "filtered_b"
                entry["base_name"] = filtered_config["base_name"]
                _evaluate_entry(entry)
                _evaluate_live_entry(entry)
                filtered_results.append(entry)

    report_path = _save_markdown(results, grid_results, filtered_results)
    log.info(f"バックテストレポート保存: {report_path}")
    return report_path


if __name__ == "__main__":
    main()

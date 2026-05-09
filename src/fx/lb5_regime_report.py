"""
lb=5 regime_filter 診断レポート生成モジュール
実注文なし・研究用のみ
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from src.fx.fx_backtest import FXBacktestResult

JST = ZoneInfo("Asia/Tokyo")

# 評価する8パターン
# 注: "up_excluded" と "down+range" は同一フィルタ条件（確認用）
REGIME_PATTERNS: list[tuple[str, Optional[list[str]]]] = [
    ("all",            None),
    ("uptrend",        ["uptrend"]),
    ("downtrend",      ["downtrend"]),
    ("range",          ["range"]),
    ("down+range",     ["downtrend", "range"]),
    ("up+range",       ["uptrend",   "range"]),
    ("up_excluded",    ["downtrend", "range"]),   # 上昇除外（= down+range と同一）
    ("range_excluded", ["uptrend",   "downtrend"]),  # レンジ除外
]

# 採用フィルター（VALベース・testは最終確認のみ）
MIN_VAL_TRADES = 10           # regime フィルタで減少するため緩和
MIN_VAL_PF = 1.0              # PF > 1.0
MAX_VAL_MDD = 15.0            # % 最大DD許容値
D1_DIFF_PF_THRESHOLD = 0.30   # resample/direct PF 差分の上限


# ---------------------------------------------------------------------------
# BUY/SELL 別メトリクス計算
# ---------------------------------------------------------------------------

def _side_metrics(trades: list[dict], side: str) -> dict:
    """trades の中から LONG/SHORT を絞り込んでメトリクスを計算。"""
    filtered = [t for t in trades if t.get("side") == side]
    n = len(filtered)
    if n == 0:
        return {"count": 0, "win_rate": 0.0, "profit_factor": float("inf"), "expectancy": 0.0}
    wins = [t for t in filtered if t.get("pnl_jpy", 0.0) > 0]
    gross_profit = sum(t["pnl_jpy"] for t in filtered if t["pnl_jpy"] > 0)
    gross_loss = abs(sum(t["pnl_jpy"] for t in filtered if t["pnl_jpy"] <= 0))
    pf = gross_profit / gross_loss if gross_loss > 0 else float("inf")
    return {
        "count": n,
        "win_rate": round(len(wins) / n, 4),
        "profit_factor": round(pf, 4),
        "expectancy": round(sum(t["pnl_jpy"] for t in filtered) / n, 2),
    }


# ---------------------------------------------------------------------------
# 月別損益フォーマット
# ---------------------------------------------------------------------------

def _format_monthly(monthly: dict) -> list[str]:
    if not monthly:
        return ["  - データなし"]
    return [f"  - {ym}: {v:+.2f}%" for ym, v in sorted(monthly.items())]


def _monthly_dependence_flag(monthly: dict) -> str:
    """1〜2ヶ月だけに利益が集中していないかチェック。"""
    if not monthly:
        return "n/a"
    positive = {ym: v for ym, v in monthly.items() if v > 0}
    if not positive:
        return "利益月なし"
    total_pos = sum(positive.values())
    if len(positive) <= 2:
        return f"⚠️ 利益が {len(positive)} ヶ月に集中"
    # 上位2ヶ月が利益の80%超
    top2 = sorted(positive.values(), reverse=True)[:2]
    if total_pos > 0 and sum(top2) / total_pos > 0.8:
        return f"⚠️ 上位2ヶ月で利益の{sum(top2)/total_pos*100:.0f}%"
    return "分散"


# ---------------------------------------------------------------------------
# 単一 FXBacktestResult の詳細行テキスト
# ---------------------------------------------------------------------------

def _result_detail_lines(label: str, r: FXBacktestResult) -> list[str]:
    long_m = _side_metrics(r.trades, "LONG")
    short_m = _side_metrics(r.trades, "SHORT")
    lines = [
        f"  [{label}]",
        f"  取引数: {r.trade_count}  (BUY={r.buy_count}, SELL={r.sell_count})",
        f"  勝率: {r.win_rate*100:.1f}%  PF: {r.profit_factor:.4f}  期待値: {r.expectancy:+,.0f}円",
        f"  総収益率: {r.total_return_pct:+.2f}%  MDD: {r.max_drawdown_pct:.2f}%  連敗: {r.max_losing_streak}",
        f"  MFE: {r.avg_mfe_pips:.1f}pips  MAE: {r.avg_mae_pips:.1f}pips  半TP失敗: {r.failed_after_half_tp_count}",
        f"  BUY({long_m['count']}): WR={long_m['win_rate']*100:.1f}% PF={long_m['profit_factor']:.3f}  "
        f"SELL({short_m['count']}): WR={short_m['win_rate']*100:.1f}% PF={short_m['profit_factor']:.3f}",
        "  月別損益:",
        *_format_monthly(r.monthly_returns),
        f"  月別依存度: {_monthly_dependence_flag(r.monthly_returns)}",
    ]
    return lines


# ---------------------------------------------------------------------------
# 採用判断
# ---------------------------------------------------------------------------

def _evaluate_pattern(
    pattern: str,
    res_resample: dict,
    res_direct: dict,
) -> str:
    """
    "採用候補" / "保留" / "棄却" を返す。
    testは最終確認のみ・採用判断に使わない。
    """
    for src_key, res in [("resample", res_resample), ("direct", res_direct)]:
        vr = res["val"]
        if vr.trade_count < MIN_VAL_TRADES:
            return f"棄却（{src_key} val_trades={vr.trade_count} < {MIN_VAL_TRADES}）"
        if vr.profit_factor < MIN_VAL_PF:
            return f"棄却（{src_key} val_pf={vr.profit_factor:.3f} < {MIN_VAL_PF}）"
        if vr.max_drawdown_pct > MAX_VAL_MDD:
            return f"棄却（{src_key} val_mdd={vr.max_drawdown_pct:.1f}% > {MAX_VAL_MDD}%）"

    # resample/direct PF 差分チェック
    res_val_pf = res_resample["val"].profit_factor
    dir_val_pf = res_direct["val"].profit_factor
    diff = abs(res_val_pf - dir_val_pf)
    if res_val_pf != float("inf") and dir_val_pf != float("inf") and diff > D1_DIFF_PF_THRESHOLD:
        return f"保留（resample/direct PF 差 {diff:.3f} > {D1_DIFF_PF_THRESHOLD}）"

    # 両方 PF > 1.1 → 採用候補
    if res_val_pf > 1.1 and dir_val_pf > 1.1:
        return "採用候補"
    # 片方のみ > 1.1 → 保留
    return "保留"


# ---------------------------------------------------------------------------
# サマリーテーブル行
# ---------------------------------------------------------------------------

def _summary_row(pattern: str, res: dict) -> str:
    tr = res["train"]
    vr = res["val"]
    te = res["test"]
    return (
        f"| {pattern:<14} | {tr.trade_count:>5} | {tr.profit_factor:>7.3f}"
        f" | {vr.trade_count:>5} | {vr.profit_factor:>7.3f} | {vr.max_drawdown_pct:>6.2f}%"
        f" | {te.trade_count:>5} | {te.profit_factor:>7.3f} |"
    )


# ---------------------------------------------------------------------------
# レポート全体生成
# ---------------------------------------------------------------------------

def render_lb5_regime_report(
    results_resample: dict[str, dict],   # pattern -> {train, val, test}
    results_direct: dict[str, dict],
    target_params: dict,
    generated_at: datetime,
) -> str:
    gen_jst = generated_at.astimezone(JST)
    today = gen_jst.strftime("%Y-%m-%d")

    lines: list[str] = [
        f"# USD/JPY H1/D1 lb=5 regime_filter 診断レポート",
        f"生成日時: {gen_jst.strftime('%Y-%m-%d %H:%M')} JST",
        "",
        "> **注**: 実注文APIは使用していません（研究・診断のみ）",
        "> test 結果はパラメータ選定に使用しない。最終確認のみ。",
        "",
        "## 診断条件",
        "",
        "| パラメータ | 値 |",
        "|-----------|-----|",
    ]
    for k, v in target_params.items():
        lines.append(f"| {k} | {v} |")
    lines.append("")

    # サマリーテーブル
    tbl_header = "| パターン       | TR取引 | TR_PF  | VA取引 | VA_PF  | VA_MDD | TE取引 | TE_PF  |"
    tbl_sep    = "|----------------|--------|--------|--------|--------|--------|--------|--------|"

    for src_label, results in [("resample D1", results_resample), ("direct D1", results_direct)]:
        lines += [
            f"## サマリーテーブル（{src_label}）",
            "",
            tbl_header,
            tbl_sep,
        ]
        for pat, _ in REGIME_PATTERNS:
            if pat in results:
                lines.append(_summary_row(pat, results[pat]))
        lines.append("")

    # resample vs direct 差分
    lines += [
        "## resample / direct D1 VAL PF 差分",
        "",
        "| パターン       | resample_val_pf | direct_val_pf | 差分 | 一致度 |",
        "|----------------|-----------------|---------------|------|--------|",
    ]
    for pat, _ in REGIME_PATTERNS:
        if pat not in results_resample or pat not in results_direct:
            continue
        r_pf = results_resample[pat]["val"].profit_factor
        d_pf = results_direct[pat]["val"].profit_factor
        if r_pf == float("inf") or d_pf == float("inf"):
            diff_str = "n/a"
            consistent = "n/a"
        else:
            diff = abs(r_pf - d_pf)
            diff_str = f"{diff:.3f}"
            consistent = "✅" if diff <= D1_DIFF_PF_THRESHOLD else "⚠️"
        lines.append(f"| {pat:<14} | {r_pf:>15.3f} | {d_pf:>13.3f} | {diff_str:>4} | {consistent} |")
    lines.append("")

    # 採用判断
    lines += ["## 採用判断（VALベース・test未使用）", ""]
    adopt = []
    hold = []
    reject = []
    for pat, _ in REGIME_PATTERNS:
        if pat not in results_resample or pat not in results_direct:
            continue
        verdict = _evaluate_pattern(pat, results_resample[pat], results_direct[pat])
        if verdict.startswith("採用"):
            adopt.append((pat, verdict))
        elif verdict.startswith("保留"):
            hold.append((pat, verdict))
        else:
            reject.append((pat, verdict))

    lines += ["### 採用候補", ""]
    if adopt:
        for pat, v in adopt:
            lines.append(f"- **{pat}**: {v}")
    else:
        lines.append("- なし")
    lines.append("")

    lines += ["### 保留", ""]
    if hold:
        for pat, v in hold:
            lines.append(f"- **{pat}**: {v}")
    else:
        lines.append("- なし")
    lines.append("")

    lines += ["### 棄却", ""]
    if reject:
        for pat, v in reject:
            lines.append(f"- **{pat}**: {v}")
    else:
        lines.append("- なし")
    lines.append("")

    # パターン詳細
    for src_label, results in [("resample D1", results_resample), ("direct D1", results_direct)]:
        lines += [f"## 各パターン詳細（{src_label}）", ""]
        for pat, flt in REGIME_PATTERNS:
            if pat not in results:
                continue
            flt_str = str(flt) if flt else "None（全環境）"
            if pat == "up_excluded":
                flt_str += "  ← 上昇除外。下降+レンジと同一フィルタ（確認用）"
            lines += [
                f"### {pat}",
                f"- filter: {flt_str}",
                "",
            ]
            res = results[pat]
            lines += _result_detail_lines("TRAIN", res["train"])
            lines.append("")
            lines += _result_detail_lines("VAL  ", res["val"])
            lines.append("")
            lines += _result_detail_lines("TEST ", res["test"])
            lines.append("")
            # VAL BUY/SELL 評価コメント
            vr = res["val"]
            if vr.trade_count > 0:
                buy_only = vr.sell_count == 0 and vr.buy_count > 0
                sell_only = vr.buy_count == 0 and vr.sell_count > 0
                if buy_only:
                    lines.append("  ⚠️ VAL: BUYのみ（偏り）")
                elif sell_only:
                    lines.append("  ⚠️ VAL: SELLのみ（偏り）")
            lines.append("")

    # 注記
    lines += [
        "## 注記",
        "",
        "- up_excluded と down+range は同一フィルタ条件（両方向からの確認用）",
        "- val_trades が少ないパターンは統計的信頼性が低い",
        "- test 結果はリスク参照のみ、採用根拠に使用しない",
        "- 月別依存度: 特定1〜2ヶ月の利益が全体の80%超の場合は信頼性が低い",
        "- 実注文APIは一切使用していない",
        "",
    ]

    return "\n".join(lines).rstrip() + "\n"

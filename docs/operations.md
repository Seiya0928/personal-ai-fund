# Operations Guide

普段の運用・確認手順と、スクリプトの役割一覧。

---

## 現在の運用フェーズ（2026-05-20 時点）

| 対象 | フェーズ | ステータス | 自動実行時刻 |
|------|---------|-----------|-------------|
| **BTC** | 自動監視フェーズ（Phase 1） | `BUY_WATCH` — 監視のみ | 09:00 / 15:00 / 22:00 JST |
| **FX** | 自動監視フェーズ（Phase 1） | `FX_WATCH` — 監視のみ | 00:00 / 06:00 / 12:00 JST |
| **日本株** | スクリーニングフェーズ（Phase 1） | `JP_STOCK_WATCH/CANDIDATE` — 候補抽出のみ | **平日 15:45 JST** |
| **競艇** | データ収集完了待ち | — | — |

**現在できること / できないこと**

- ✅ health check で状態確認する
- ✅ ログ・レポートを読む
- ✅ proposal 一覧・dry-run 記録を読む
- ✅ 日本株スクリーニング結果を確認する（`JP_STOCK_WATCH` はチャート確認のみ）
- ❌ `BUY_WATCH` / `FX_WATCH` で手動購入しない
- ❌ `BUY_WATCH` / `FX_WATCH` で注文案を作らない
- ❌ `JP_STOCK_CANDIDATE` でも実注文しない（候補確認のみ）
- ❌ 実注文は **まだ禁止**（Phase 3 以降まで）
- ❌ `DRY_RUN=false` / `READ_ONLY=false` にしない
- ❌ `live_order_once.py` を実行しない

---

## CANDIDATE が出た時の手順

### BTC で `BUY_CANDIDATE` が出た場合

```bash
# 1. health check で現在状態を確認する
./venv/bin/python scripts/check_btc_alert_health.py

# 2. レポートで詳細を確認する
cat reports/btc_jpy_dip_alert_$(date +%Y%m%d).md

# 3. 注文案を確認する
./venv/bin/python scripts/list_order_proposals.py

# 4. dry-run 注文記録を作る（実注文ではない）
./venv/bin/python scripts/dry_run_order_from_proposal.py --proposal-id <ID>
# → プロンプトに "RECORD DRY RUN ORDER" を入力

# 5. dry-run 記録を確認する
./venv/bin/python scripts/list_dry_run_orders.py
```

> ⛔ ステップ 4 を終えても**実注文は絶対にしない**。

### FX で `FX_CANDIDATE` が出た場合

```bash
# 1. health check で現在状態を確認する
./venv/bin/python scripts/check_fx_signal_health.py

# 2. レポートで詳細を確認する（直近のレポートを確認）
ls -lt reports/ | head -5

# 3. FX 注文案を確認する
./venv/bin/python scripts/list_fx_order_proposals.py

# 4. dry-run 注文記録を作る（実注文ではない）
./venv/bin/python scripts/record_fx_dry_run_order.py --proposal-id <ID>
# → プロンプトに "RECORD DRY RUN ORDER" を入力

# 5. dry-run 記録を確認する
./venv/bin/python scripts/list_dry_run_orders.py
```

> ⛔ ステップ 4 を終えても**実注文は絶対にしない**。

> 将来 `BUY_CANDIDATE` から実運用へ進む条件・手順・禁止事項の詳細は → **[live_trading_readiness.md](live_trading_readiness.md)**

---

## 触ってよいコマンド / 触らないコマンド

### ✅ 触ってよいコマンド

```bash
# 状態確認
./venv/bin/python scripts/check_btc_alert_health.py
./venv/bin/python scripts/check_fx_signal_health.py
./venv/bin/python scripts/check_jp_stock_screener_health.py  # 日本株

# ログ確認
tail -80 logs/btc_dip_alert_$(date +%Y%m%d).log
tail -80 logs/fx_usdjpy_launchd.log
tail -80 logs/jp_stock_screener_launchd.log                  # 日本株 launchd ログ

# 日本株スクリーニングレポートを確認
cat reports/jp_stock_screener_$(date +%Y%m%d).md

# シグナル・提案・paper trade の閲覧
./venv/bin/python scripts/list_signal_history.py
./venv/bin/python scripts/list_order_proposals.py
./venv/bin/python scripts/list_fx_order_proposals.py
./venv/bin/python scripts/list_paper_trades.py
./venv/bin/python scripts/list_dry_run_orders.py

# CANDIDATE 時のみ dry-run 注文記録（上記「CANDIDATE が出た時の手順」参照）
./venv/bin/python scripts/dry_run_order_from_proposal.py --proposal-id <ID>
./venv/bin/python scripts/record_fx_dry_run_order.py --proposal-id <ID>
```

### ❌ 触らないコマンド

| コマンド / 操作 | 理由 |
|----------------|------|
| `scripts/live_order_once.py` | 実注文経路。Phase 4 以降まで使わない |
| `DRY_RUN=false` に変更 | 実注文が有効になる |
| `READ_ONLY=false` に変更 | 実注文が有効になる |
| GMO / FX Private API 注文送信 | 実注文経路 |
| `BUY_WATCH` / `FX_WATCH` での手動購入 | CANDIDATE 条件を満たしていない |
| `scripts/run_fx_usdjpy_signal.py` | 旧版スクリプト。launchd には使われていない |

---

## Mac スリープと常時稼働環境

- **現段階**（watch-only / paper trade / dry-run）は Mac launchd で許容する
- Mac スリープ中の実行取りこぼしは、watch-only 段階では**許容**する（ログに `WARNING: missed expected run` として記録される）
- **実注文に進む前**（Phase 3 移行時）には Mac launchd から VPS 等の常時稼働環境へ移行すること
- 理由：エントリー機会損失より、**保有中の利確・損切り・timeout exit を逃すリスクの方が大きい**ため

移行先の候補と手順は [docs/roadmap.md](roadmap.md) の Phase 3 を参照。

---

## スクリプト分類

### A. 自動実行（launchd）

普段は手動で実行しない。Mac が起動・非スリープ中に自動実行される。

| スクリプト | launchd ラベル | 実行時刻（JST） |
|-----------|--------------|----------------|
| `scripts/run_daily_btc_alert.sh` | `com.personal-ai-fund.btc-alert` | 09:00 / 15:00 / 22:00（毎日） |
| `scripts/run_fx_daily.py` | `com.personal-ai-fund.fx-usdjpy-signal` | 00:00 / 06:00 / 12:00（毎日） |
| `scripts/run_jp_stock_screener.py` | `com.personal-ai-fund.jp-stock-screener` | **15:45（平日月〜金のみ）** |

**日本株スクリーナー自動実行の注意事項：**
- 東証クローズ直後（15:00）の 15:45 JST に実行し、当日終値ベースで翌日の候補を抽出する
- Mac がスリープ中は実行されない。逃した分は補完されない（watch-only 段階では許容）
- 実注文なし。`JP_STOCK_WATCH` はチャート確認のみ。`JP_STOCK_CANDIDATE` でも実注文しない
- 実注文前（Phase 3 移行時）には VPS 等の常時稼働環境へ移行すること

> **注意**: Mac がスリープ中の時間帯は実行されない。逃した分は自動補完されない。
> watch-only / paper trade 段階では許容。実注文前には VPS 等の常時稼働環境へ移行すること。

---

### B. 手動確認（health check）

自動実行が正常に動いているか確認するときだけ実行する。

```bash
cd /Users/apple/personal-ai-fund

# BTC の状態確認
./venv/bin/python scripts/check_btc_alert_health.py

# FX の状態確認
./venv/bin/python scripts/check_fx_signal_health.py

# 日本株スクリーナーの状態確認
./venv/bin/python scripts/check_jp_stock_screener_health.py
```

### C. 日本株スクリーナー（任意実行）

平日 15:45 の自動実行に加え、任意のタイミングで手動実行できる。

```bash
# 手動でスクリーニングを実行する
./venv/bin/python scripts/run_jp_stock_screener.py

# 当日レポートを確認する
cat reports/jp_stock_screener_$(date +%Y%m%d).md

# launchd ログを確認する
tail -50 logs/jp_stock_screener_launchd.log
```

> ⛔ `JP_STOCK_CANDIDATE` が出た場合でも**実注文しない**。チャート・出来高・板を人間が確認するだけ。

---

### C. 研究・集計（手動・不定期）

シグナル評価・FX Watch Candidate まとめ・日次レポートの手動生成。

```bash
# FX Watch Candidate シグナル評価 + Daily Personal Report 生成
./venv/bin/python scripts/run_daily_personal_report.py --save-watch-signal --evaluate-watch-signals
```

---

### D. 旧版・非推奨（Legacy）

> ⚠️ **原則実行しない。** 現在の launchd では使用されていない旧バージョン。

| スクリプト | 理由 |
|-----------|------|
| `scripts/run_fx_usdjpy_signal.py` | FX統合版（`run_fx_daily.py`）に移行済み。launchd の呼び出し先から除外されている。削除予定だが現時点では残存。 |

---

## ログ確認

```bash
# BTC ログ
tail -80 logs/btc_dip_alert_$(date +%Y%m%d).log
tail -80 logs/launchd_btc_alert.stdout.log
tail -80 logs/launchd_btc_alert.stderr.log

# FX ログ
tail -80 logs/fx_usdjpy_launchd.log
tail -80 logs/fx_usdjpy_launchd_err.log
```

---

## launchd 設定メモ

### BTC: `com.personal-ai-fund.btc-alert`

- plist: `~/Library/LaunchAgents/com.personal-ai-fund.btc-alert.plist`
- 実行スクリプト: `scripts/run_daily_btc_alert.sh`
- 実行時刻（JST）: 09:00 / 15:00 / 22:00
- 環境変数: `DRY_RUN=true` / `READ_ONLY=true`

```bash
# 状態確認
launchctl list | grep btc-alert

# 再読み込み
launchctl unload ~/Library/LaunchAgents/com.personal-ai-fund.btc-alert.plist
launchctl load   ~/Library/LaunchAgents/com.personal-ai-fund.btc-alert.plist
```

### FX: `com.personal-ai-fund.fx-usdjpy-signal`

- plist: `~/Library/LaunchAgents/com.personal-ai-fund.fx-usdjpy-signal.plist`
- 実行スクリプト: `scripts/run_fx_daily.py`
- 実行時刻（JST）: 00:00 / 06:00 / 12:00
- 環境変数: `DRY_RUN=true` / `READ_ONLY=true`

```bash
# 状態確認
launchctl list | grep fx-usdjpy

# 再読み込み
launchctl unload ~/Library/LaunchAgents/com.personal-ai-fund.fx-usdjpy-signal.plist
launchctl load   ~/Library/LaunchAgents/com.personal-ai-fund.fx-usdjpy-signal.plist
```

---

## シグナルステータスとアクション方針

### BTC シグナル

| ステータス | 意味 | アクション |
|-----------|------|-----------|
| `BUY_SKIP` | 買い条件不足。観測記録のみ。 | 何もしない |
| `BUY_WATCH` | 買い候補に近い監視状態。 | 通知を確認する。注文案は作らない |
| `BUY_CANDIDATE` | 買い条件成立。注文案が生成される。 | `list_order_proposals.py` で確認 → dry-run 記録へ |
| `TAKE_PROFIT_CANDIDATE` | 利確候補。SELL 注文案が生成される。 | 同上 |
| `STOP_LOSS_CANDIDATE` | 損切り候補。SELL 注文案が生成される。 | 同上 |
| `TIMEOUT_EXIT_CANDIDATE` | 最大保有日数到達。SELL 注文案が生成される。 | 同上 |

### FX シグナル

| ステータス | 意味 | アクション |
|-----------|------|-----------|
| `FX_SKIP` | 条件不足。記録のみ。 | 何もしない |
| `FX_WATCH` | 監視中。注文案は作らない。 | 何もしない |
| `FX_CANDIDATE` | エントリー候補。注文案が生成される。 | `list_fx_order_proposals.py` で確認 → dry-run 記録へ |
| `FX_TAKE_PROFIT_CANDIDATE` | 保有中ポジションの利確候補。 | dry-run 決済記録を作る |
| `FX_STOP_LOSS_CANDIDATE` | 保有中ポジションの損切り候補。 | dry-run 損切り記録を優先 |
| `FX_TIMEOUT_EXIT_CANDIDATE` | 保有期限切れ候補。 | dry-run 決済記録を作る |
| `FX_STALE_INVALID` | 市場データが古く判断無効。 | health check を確認 |

### CANDIDATE が出たときだけ行う操作

```bash
# BTC
./venv/bin/python scripts/list_order_proposals.py
./venv/bin/python scripts/dry_run_order_from_proposal.py --proposal-id <ID>
# → "RECORD DRY RUN ORDER" を入力

# FX
./venv/bin/python scripts/list_fx_order_proposals.py
./venv/bin/python scripts/record_fx_dry_run_order.py --proposal-id <ID>
# → "RECORD DRY RUN ORDER" を入力
```

> **実注文はまだしない。** `DRY_RUN=true` / `READ_ONLY=true` を常に維持すること。

---

## 安全フラグの確認

```bash
# 緊急停止（全取引を即停止）
echo "手動停止" > STOP_TRADING

# 停止解除
rm STOP_TRADING

# 現在の設定確認
cat .env | grep -E "DRY_RUN|READ_ONLY"
```

DRY_RUN / READ_ONLY は `.env` で管理する。デフォルトは両方 `true`。
変更する場合は [README の安全な段階移行](../README.md#4-安全な段階移行) を必ず参照すること。

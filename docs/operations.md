# Operations Guide

普段の運用・確認手順と、スクリプトの役割一覧。

---

## スクリプト分類

### A. 自動実行（launchd）

普段は手動で実行しない。Mac が起動・非スリープ中に自動実行される。

| スクリプト | launchd ラベル | 実行時刻（JST） |
|-----------|--------------|----------------|
| `scripts/run_daily_btc_alert.sh` | `com.personal-ai-fund.btc-alert` | 09:00 / 15:00 / 22:00 |
| `scripts/run_fx_daily.py` | `com.personal-ai-fund.fx-usdjpy-signal` | 00:00 / 06:00 / 12:00 |

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
```

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

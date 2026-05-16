# Roadmap — personal-ai-fund

実運用までのフェーズ定義と、各フェーズの完了条件。

> **現在地: Phase 1（Watch-only）**

---

## Phase 1: Watch-only（現在）

**目的**: 自動監視システムの安定稼働確認。CANDIDATE 発生パターンの観察。

### やること

- BTC / FX の定時実行を launchd で自動化する（済）
- `BUY_WATCH` / `FX_WATCH` の発生パターンを記録する
- `CANDIDATE` 発生を待つ
- health check で取りこぼしを記録する（WARNING として扱う）
- Mac スリープによる実行取りこぼしを**許容**する

### やらないこと

- 実注文しない
- `DRY_RUN=false` にしない
- `BUY_WATCH` / `FX_WATCH` で proposal を作らない

### 完了条件

- BTC / FX とも `BUY_CANDIDATE` / `FX_CANDIDATE` が少なくとも 1 回発生した
- health check が `Status: OK` または `Status: WARNING` で安定稼働している
- signal_history に 30 件以上蓄積されている

---

## Phase 2: Paper trade / dry-run（次のフェーズ）

**目的**: `CANDIDATE` 発生時の proposal → dry-run 注文記録フローを通し、TP/SL/TIMEOUT の有効性を検証する。

### やること

- `CANDIDATE` 発生時に proposal を確認する
- `dry_run_order_from_proposal.py` / `record_fx_dry_run_order.py` で dry-run 注文記録を作る
- paper trade の TP/SL/TIMEOUT 達成率を `report_paper_performance.py` で評価する
- 3 ルール（Conservative / Current / Wide）の成績を比較する

### やらないこと

- 実注文しない
- `live_order_once.py` を実行しない
- `BUY_WATCH` / `FX_WATCH` で dry-run 記録を作らない

### 完了条件

- dry-run 注文記録が BTC / FX 合わせて 3 件以上ある
- paper trade で 1 件以上クローズ済み（TP/SL/TIMEOUT いずれか）
- 勝てないルールの判定ができている

---

## Phase 3: 極小ロット実運用準備

**目的**: Mac 依存を解消し、実注文に耐えるインフラを整える。

### やること

- **常時稼働環境（VPS 等）へ移行する**（Mac launchd から切り替え）
  - 理由：保有中の利確・損切り・timeout exit を Mac スリープで逃すリスクを排除
- GMO APIキー権限を確認する（現物取引のみ・出金権限なし）
- 最小ロット（BTC: 0.0001 BTC 程度）を確認する
- 最大損失額の設定を見直す（`src/risk/risk_config.py`）
- `STOP_TRADING` キルスイッチの動作を再確認する
- `pre_live_checklist.py` を全項目パスする
- `rehearse_gmo_spot_order.py` でリハーサルを通す

### やらないこと

- まだ実注文しない
- `live_order_once.py` を実行しない

### 完了条件

- VPS 等で launchd または cron が安定稼働している
- `pre_live_checklist.py` が ALL OK
- `rehearse_gmo_spot_order.py` が成功する
- GMO 口座に入金済み（¥10,000 程度）

---

## Phase 4: 極小ロット実運用

**目的**: 実運用摩擦（APIエラー・約定ズレ・通知タイミング）を最小リスクで測定する。収益目的ではない。

### やること

- **明示的な人間の承認後のみ** `live_order_once.py` を実行する
- 初回は ¥1,000 以下の指値注文のみ
- 発注後に GMO 管理画面で注文状態を確認する
- `post_trade_report.py` でレポートを生成・確認する
- 実運用摩擦（エラー率・約定率・ログ精度）を記録する

### やらないこと

- スケールアップしない（Phase 4 中は最小ロット固定）
- 自動ループ発注・cron 登録しない
- 収益を目的とした大口エントリーをしない

### 完了条件

- 実発注 → 約定 → レポート生成 → GMO 管理画面確認 のフローが 1 往復完了
- エラーなし・残高整合あり
- 実運用摩擦のメモが完成している

---

## 参考：重要スクリプトとフェーズの対応

| スクリプト | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
|-----------|:-------:|:-------:|:-------:|:-------:|
| `check_btc_alert_health.py` | ✅ | ✅ | ✅ | ✅ |
| `check_fx_signal_health.py` | ✅ | ✅ | ✅ | ✅ |
| `list_order_proposals.py` | 閲覧のみ | ✅ | ✅ | ✅ |
| `dry_run_order_from_proposal.py` | ❌ | ✅ | ✅ | ✅ |
| `report_paper_performance.py` | ❌ | ✅ | ✅ | ✅ |
| `pre_live_checklist.py` | ❌ | ❌ | ✅ | ✅ |
| `rehearse_gmo_spot_order.py` | ❌ | ❌ | ✅ | ✅ |
| `live_order_once.py` | ❌ | ❌ | ❌ | ✅（明示承認後） |

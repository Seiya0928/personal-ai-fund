# Live Trading Readiness

> **現段階では実注文しない。このドキュメントは「将来進む条件」を明文化したものであり、今すぐ実行する手順書ではない。**

---

## 現在の原則

- 現段階では**実注文しない**。
- `BUY_WATCH` では**絶対に買わない**。通知は確認するだけ。
- 実運用候補は **BTC のみ**（FX・競艇はまだ paper/検証段階）。
- `live_order_once.py` は実行しない。`DRY_RUN=false` / `READ_ONLY=false` にしない。

---

## 極小ロット実運用へ進める最低条件

以下の **すべてを満たしていること** が必須。一つでも欠けたら進まない。

| # | 条件 | 確認方法 |
|---|------|---------|
| 1 | 実データで `BUY_CANDIDATE` が出ている | `check_btc_alert_health.py` の signal 欄 |
| 2 | health check が `OK` または `Current state: OK` | `check_btc_alert_health.py` の出力 |
| 3 | market data stale level が `fresh` | health check の market_data 欄 |
| 4 | order proposal が生成されている | `list_order_proposals.py` |
| 5 | paper trade が生成されている | `list_paper_trades.py` |
| 6 | dry-run 注文記録が正常に作成できる | `dry_run_order_from_proposal.py` が異常なく完了 |
| 7 | `STOP_TRADING` が inactive | health check / ログ確認 |
| 8 | duplicate guard が有効（二重注文防止） | ログで guard 動作確認 |
| 9 | **人間による manual approval が実施済み**（自動実行不可） | 本人が内容を読んで承認 |
| 10 | 最大損失額が明確（`max_loss_jpy` が確認できる） | proposal の `max_loss_jpy` フィールド |
| 11 | `stop_loss` / `take_profit` / `timeout` が明確 | proposal の各フィールド |
| 12 | 常時稼働環境の準備が整っている（Mac スリープ問題の解決） | VPS 等の稼働確認 → [roadmap.md](roadmap.md) Phase 3 参照 |

---

## 初回実弾の制限

初回実弾は**収益目的ではない**。目的は「実運用の摩擦を実際のコストで計測すること」。

| 項目 | 制限 |
|------|------|
| 最大損失 | **100〜500 円以内** |
| ポジションサイズ | 取引所が許す**最小単位** |
| 注文頻度 | **1 日 1 回まで** |
| 連敗時 | **即停止**（損失問わず）|
| 承認方式 | **手動確認なしで注文しない** |

---

## 絶対禁止

以下は状況にかかわらず禁止。例外なし。

- `BUY_WATCH` で買わない
- stale warning / invalid 状態で買わない
- proposal なしで買わない
- paper trade なしで買わない
- `STOP_TRADING` 中に買わない
- 感情で成行注文しない（FOMO・損取り）
- 損切り（`stop_loss`）を消さない・広げない
- ポジションサイズを初回より上げない
- `DRY_RUN=false` / `READ_ONLY=false` を安易に設定しない

---

## `BUY_CANDIDATE` が出た時の確認手順

> ⛔ この手順を全て完了しても、**実注文は行わない**（まだ Phase 1）。  
> 将来 Phase 3 に進んだ後、改めてこの手順を踏んで human approval を経て初めて実注文可能。

```bash
# 1. health check で現在状態を確認する
./venv/bin/python scripts/check_btc_alert_health.py
#   → Status: OK / Current state: OK を確認
#   → market stale level: fresh を確認
#   → STOP_TRADING が inactive を確認

# 2. 最新レポートを確認する
cat reports/btc_jpy_dip_alert_$(date +%Y%m%d).md

# 3. order proposal を確認する（stop_loss / take_profit / max_loss_jpy を読む）
./venv/bin/python scripts/list_order_proposals.py

# 4. paper trade を確認する
./venv/bin/python scripts/list_paper_trades.py

# 5. dry-run 注文記録を作成する（実注文ではない）
./venv/bin/python scripts/dry_run_order_from_proposal.py --proposal-id <ID>
#   → プロンプトに "RECORD DRY RUN ORDER" と入力
#   → 記録が正常に作成されたことを確認する

# 6. dry-run 記録を確認する
./venv/bin/python scripts/list_dry_run_orders.py

# 7. max_loss_jpy が 100〜500 円以内かを確認する

# 8. 上記全て OK なら「進めるか」を人間が判断する
#    → Phase 1 現在: ここで終了。実注文しない。
#    → Phase 3 移行後: 承認して初めて実注文フローへ
```

---

## 実運用前に残っている課題

以下が未解決のまま実注文フローに進むことは禁止。

| 課題 | 状態 | 備考 |
|------|------|------|
| GMO API キー権限確認（Private API） | 未確認 | 口座開設審査完了後 |
| 最小注文数量の確認 | 未確認 | GMO コイン BTC 最小単位 |
| 手数料・スプレッドの確認 | 未確認 | `max_loss_jpy` 計算に必要 |
| 常時稼働環境（VPS 等）の準備 | 未着手 | Mac スリープ問題の解決 |
| 実注文ログ保存設計 | 未着手 | 証跡・事後検証のため |
| 決済側の監視体制確認 | 未着手 | take_profit / stop_loss / timeout の自動実行 |
| 緊急停止手順の確認 | 未着手 | 手動での即時全決済フロー |

> これらの課題は [docs/roadmap.md](roadmap.md) の **Phase 3 — 実運用前準備** で対処する。

---

## フェーズ対応表

| フェーズ | このドキュメントとの関係 |
|---------|----------------------|
| Phase 1（現在）Watch-only | このドキュメントの条件を **読むだけ**。実注文不可。 |
| Phase 2 Paper trade / dry-run | 条件 1〜8 を継続チェック。dry-run を積み重ねる。 |
| Phase 3 実運用前準備 | 上記「残っている課題」を全て解決する。 |
| Phase 4 極小ロット実運用 | 全条件を満たし、manual approval を経て初回実弾。 |

---

*最終更新: 2026-05-19*

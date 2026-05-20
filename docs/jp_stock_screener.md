# 日本株スクリーニング bot

> **このツールは研究用スクリーニングのみ。実注文・証券API発注は一切行わない。**

---

## 目的

毎朝または任意実行で「今日見るべき日本株候補」を抽出する研究用ツール。

- **デイトレ自動売買ではない**: 候補を提示するだけで、売買は人間が判断する
- **実注文しない**: 証券会社 API への発注・注文送信は含まない
- **無料データ**: yfinance (Yahoo Finance の遅延データ) を使用
- **将来拡張向け**: BTC/FX bot と同じ SKIP/WATCH/CANDIDATE の思想に準拠

---

## ステータス定義

| ステータス | 意味 | アクション |
|-----------|------|-----------|
| `JP_STOCK_SKIP` | 候補外・特徴なし | 何もしない。記録のみ。 |
| `JP_STOCK_WATCH` | 要注目・条件に近い | チャート確認のみ。手動売買しない。 |
| `JP_STOCK_CANDIDATE` | 今日見る価値が高い候補 | チャート・出来高・板を**人間が確認**する。実注文しない。 |

---

## 触ってよいコマンド

```bash
# スクリーニング実行（毎朝 or 任意）
./venv/bin/python scripts/run_jp_stock_screener.py

# メール送信付きで実行（SMTP 設定済みの場合）
./venv/bin/python scripts/run_jp_stock_screener.py --send-email

# 送信せずにメール本文プレビューを CLI に出力する
./venv/bin/python scripts/run_jp_stock_screener.py --dry-run-notify

# ヘルスチェック
./venv/bin/python scripts/check_jp_stock_screener_health.py

# 直近レポートを確認
ls -lt reports/jp_stock_screener_*.md | head -5
cat reports/jp_stock_screener_$(date +%Y%m%d).md

# 履歴を確認
cat state/jp_stock_screening_history.json | python3 -m json.tool | tail -50
```

---

## 初期スクリーニング条件

### JP_STOCK_CANDIDATE（高優先候補）

以下のいずれかを満たす場合:

| 条件 | 閾値 |
|------|------|
| ギャップアップ候補 | 前日比 **+2.0%以上** かつ 出来高比 **1.5x以上** かつ 売買代金 **¥5億以上** |
| 急落リバウンド候補 | 前日比 **-5.0%以下** かつ 出来高比 **2.0x以上** かつ 売買代金 **¥5億以上** |

### JP_STOCK_WATCH（監視対象）

以下のいずれかを満たす場合:

| 条件 | 閾値 |
|------|------|
| モメンタム | 前日比 **+1.0%以上** かつ 出来高比 **1.2x以上** かつ 売買代金 **¥1億以上** |
| 出来高急増 | 出来高比 **2.0x以上** かつ 売買代金 **¥2億以上**（価格変動小） |
| 急落監視 | 前日比 **-3.0%以下** かつ 出来高比 **1.5x以上** かつ 売買代金 **¥2億以上** |

### 自動スキップ条件

- データが **stale**（4日以上古い）
- **データ取得失敗**（yfinance エラー）

---

## データ取得

- **データソース**: yfinance (Yahoo Finance)
- **遅延**: 15分以上の遅延あり（リアルタイムではない）
- **対象**: 東証上場の代表銘柄 65 銘柄（`src/jp_stocks/fetcher.py` の `STOCK_UNIVERSE`）
- **取得期間**: 直近 35 日分（20日平均出来高算出のため）
- **stale 判定**: データ日付が 4 日以上前の場合

> **注意**: 無料データは欠損・遅延・取得失敗がある。研究用として扱うこと。

---

## メール通知

launchd 自動実行は `--send-email` 付きで動くため、SMTP を設定すれば毎平日 15:45 に結果が届く。

### SMTP 設定（`.env`）

```dotenv
ALERT_EMAIL_SMTP_HOST=smtp.gmail.com
ALERT_EMAIL_SMTP_PORT=587
ALERT_EMAIL_USERNAME=your@gmail.com
ALERT_EMAIL_PASSWORD=app-password
ALERT_EMAIL_FROM=your@gmail.com
ALERT_EMAIL_TO=recipient@example.com
```

### 件名フォーマット

| 状況 | 件名 |
|------|------|
| CANDIDATE あり | `【JP Stock Screener】候補あり: CANDIDATE=N WATCH=M` |
| WATCH のみ | `【JP Stock Screener】監視銘柄あり: WATCH=M` |
| 候補なし | `【JP Stock Screener】候補なし` |

### メール本文

- 実行日時・データ取得元・銘柄数
- CANDIDATE 一覧（最大 10 件、現在値・出来高比・理由）
- WATCH 一覧（最大 10 件）
- Next Action セクション
- **必須免責事項**: 「実注文は行いません。これは研究用スクリーニング通知です。」

### SMTP 未設定の場合

設定なしで `--send-email` を渡すとスキップ（エラーにならない）。  
`--dry-run-notify` なら CLI にプレビューだけ出力する。

---

## ファイル構成

```
src/jp_stocks/
  __init__.py          ← モジュール宣言（実注文なし宣言）
  models.py            ← データクラス: StockQuote, ScreeningSignal, ScreeningResult
  fetcher.py           ← yfinance データ取得 + STOCK_UNIVERSE（65銘柄）
  screener.py          ← スクリーニングロジック
  signal_history.py    ← JSON 履歴保存（state/jp_stock_screening_history.json）
  reporter.py          ← Markdown レポート生成
  health.py            ← ヘルスチェック
  notifier.py          ← メール通知（build_subject / build_body / send_screening_email）

scripts/
  run_jp_stock_screener.py          ← メインエントリーポイント（--send-email / --dry-run-notify）
  check_jp_stock_screener_health.py ← ヘルスチェック

state/
  jp_stock_screening_history.json   ← 実行履歴 (最大 90 エントリ)

reports/
  jp_stock_screener_YYYYMMDD.md     ← 日次レポート

tests/
  test_jp_stock_screener.py   ← スクリーニング条件テスト
  test_jp_stock_reporter.py   ← レポート生成テスト
  test_jp_stock_health.py     ← ヘルスチェックテスト
  test_jp_stock_safety.py     ← 安全性テスト（実注文なし確認）
  test_jp_stock_notifier.py   ← メール通知テスト（27 テスト）
```

---

## 日本株から始める理由

| 理由 | 詳細 |
|------|------|
| 取引時間が明確 | 9:00〜15:00 JST（前場 9:00〜11:30 / 後場 12:30〜15:00） |
| 情報取得のしやすさ | yfinance の `.T` サフィックスで即座にアクセス可能 |
| BTC bot との連続性 | GMO コインで BTC を監視中。同じインフラを共有しやすい |
| 為替リスクなし | 円建て取引のため複雑な為替ヘッジが不要 |
| 証拠金制度の理解しやすさ | 現物株から入ることで仕組みを学習しやすい |

米国株は将来拡張の対象だが、為替・時差・規制の複雑さがあるため後回しにする。

---

## 安全設計

- `DRY_RUN=true` が前提（証券 API 発注を呼ばない）
- `READ_ONLY=true` が前提（書き込みは state/ と reports/ のみ）
- 全 `.py` ファイルの冒頭に `# 実注文なし・研究用スクリーニングのみ` を記載
- `test_jp_stock_safety.py` で禁止文字列の混入を自動検出

---

## 将来の拡張

| フェーズ | 内容 |
|---------|------|
| **現在** | 65 銘柄の日次スクリーニング・CANDIDATE 通知 |
| Phase 2 | 銘柄ユニバースを JPX 全上場銘柄に拡大（JPX 公開データ活用） |
| Phase 2 | 財務指標スクリーニング追加（PER・PBR・ROE・増収率） |
| Phase 2 | paper trade 記録（JP_STOCK_CANDIDATE が出た時の仮想エントリー） |
| Phase 3 | kabuステーション API 等によるリアルタイムデータ対応 |
| Phase 3 | 前場中の分足データによるイントラデイ監視 |
| Phase 4 | 証券 API を通じた小口実注文（別途安全設計が必要） |

> Phase 4 は本ドキュメントの外。`docs/live_trading_readiness.md` を参照。

---

## よくあるエラー

### `yfinance がインストールされていません`
```bash
./venv/bin/pip install yfinance
```

### `データが少なすぎます (rows=0)`
東証が休場（祝日・年末年始）の場合、または銘柄コードが誤っている場合。

### `stale` 警告が出る
週末・祝日をまたいでいると stale 判定されることがある。  
月曜日の午前中に実行すれば金曜日のデータで正常動作する（差分 3 日 < 閾値 4 日）。

---

*最終更新: 2026-05-20*

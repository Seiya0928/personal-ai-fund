# personal-ai-fund

GMOコイン Public API を使った自分専用AIファンドの初期プロジェクト。
口座開設審査待ちの間に、**認証不要のPublic APIだけ**でデータ収集・保存・バックテスト・レポート生成を動かす。

## Daily Operations

> 詳細は [docs/operations.md](docs/operations.md) を参照。

### 基本方針

普段は手動実行しない。BTC と FX は launchd で自動実行される。手動で見るのは health check のみ。

### 自動実行（launchd）

| 対象 | スクリプト | 実行時刻（JST） |
|------|-----------|----------------|
| BTC | `scripts/run_daily_btc_alert.sh` | 09:00 / 15:00 / 22:00 |
| FX | `scripts/run_fx_daily.py` | 00:00 / 06:00 / 12:00 |

Mac がスリープ中は実行されない。watch-only / paper trade 段階では許容。実注文前には VPS 等の常時稼働環境へ移行すること（→ [移行方針](#常時稼働環境への移行方針)）。

### 状態確認（手動）

```bash
cd /Users/apple/personal-ai-fund
./venv/bin/python scripts/check_btc_alert_health.py
./venv/bin/python scripts/check_fx_signal_health.py
```

### ログ確認

```bash
tail -80 logs/btc_dip_alert_$(date +%Y%m%d).log
tail -80 logs/fx_usdjpy_launchd.log
```

### Daily Personal Report（研究・集計）

```bash
./venv/bin/python scripts/run_daily_personal_report.py --save-watch-signal --evaluate-watch-signals
```

### Legacy スクリプト

> ⚠️ `scripts/run_fx_usdjpy_signal.py` は旧FXシグナル処理。現在の launchd では **使用されていない**。原則実行しない。

---

## 構成

```
personal-ai-fund/
  src/
    brokers/        # GMO / IBKR など将来のブローカー層
    storage/        # SQLite保存・CSVエクスポート
    strategies/     # 移動平均クロス戦略
    backtest/       # バックテストエンジン
    reports/        # デイリーレポート生成
    risk/           # リスク管理・安全装置
    utils/          # ロガー
  scripts/          # 実行エントリーポイント
  tests/            # pytest
  data/             # DB・CSV（git管理外）
  logs/             # ログファイル（git管理外）
```

## セットアップ

```bash
cd personal-ai-fund
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## 使い方

### 1. BTC/JPY価格を取得・保存

```bash
python scripts/fetch_btc_price.py
```

- GMOコイン Public APIからticker（現在価格）と1時間足OHLCVを取得
- SQLite（`data/fund.db`）に保存（重複は自動スキップ）
- `data/BTC_JPY_1hour.csv` にエクスポート

### 2. バックテスト実行

```bash
python scripts/run_backtest.py
```

- SQLiteのOHLCVデータで移動平均クロス戦略（MA5 × MA20）を検証
- 総リターン・勝率・最大ドローダウン・取引回数・最終資産額を出力

### 3. デイリーレポート生成

```bash
python scripts/generate_report.py
```

- 現在価格・1時間変化率・売買シグナルをテキスト出力

### 4. 仮注文シミュレーション（実発注なし）

```bash
python scripts/simulate_order.py
```

- リスクチェックを全通過したらSQLiteに仮注文ログを記録（発注はしない）
- 2回目以降は「本日注文回数上限」でブロックされることを確認できる

### 5. Private API 接続確認（口座開通後）

```bash
python scripts/check_private_api_connection.py
```

- `.env` に設定したAPIキーで残高取得のみ実行（発注・キャンセルは一切しない）
- `DRY_RUN=true` のままでは「モードで実行中」と表示されAPI通信はスキップ
- 実際に接続確認するには `.env` で `DRY_RUN=false` + `READ_ONLY=true` に変更
- ✅ 接続成功 → 円残高・BTC残高が表示される
- ❌ 失敗 → APIキーの誤り・IP制限・API権限未設定の可能性

### 6. Discord通知設定

1. Discord で Webhook URL を作成する
2. `.env` または環境変数に `DISCORD_WEBHOOK_URL` を設定する
3. 疎通確認は `./venv/bin/python scripts/run_btc_dip_alert.py --test-discord` を実行する
4. 通常運用は `./venv/bin/python scripts/run_btc_dip_alert.py --send-discord`
5. 通常通知は `should_notify=true` のときだけ送信される

### 7. Gmail通知設定

1. Googleアカウントで 2 段階認証を有効化する
2. Google のアプリパスワードを発行する
3. `.env` または環境変数に SMTP 設定を入れる
   - `ALERT_EMAIL_SMTP_HOST=smtp.gmail.com`
   - `ALERT_EMAIL_SMTP_PORT=587`
   - `ALERT_EMAIL_USERNAME=送信元Gmailアドレス`
   - `ALERT_EMAIL_PASSWORD=Googleアプリパスワード`
   - `ALERT_EMAIL_FROM=送信元Gmailアドレス`
   - `ALERT_EMAIL_TO=受信先Gmailアドレス`
4. 疎通確認は `./venv/bin/python scripts/run_btc_dip_alert.py --test-email` を実行する
5. 通常運用は `./venv/bin/python scripts/run_btc_dip_alert.py --send-email --markdown --send-daily-summary`
6. 通常通知は `should_notify=true` のときだけ送信される
7. 日次サマリーは 22:00 実行時だけ Gmail 送信される

### 8. BTC/JPYアラートの定時実行

Gmail通知テストが成功している前提で、ローカルMacでは `launchd` を使って 1日3回 `09:00 / 15:00 / 22:00` に実行できる。

1. `.env` に SMTP 設定を保存する
2. 手動実行で確認する

```bash
bash scripts/run_daily_btc_alert.sh
```

3. `docs/launchd_btc_alert.example.plist` を参考に、必要ならユーザー名やパスを調整する
4. plist を `~/Library/LaunchAgents/com.personal-ai-fund.btc-alert.plist` に配置する
5. 初回または更新後に読み込む

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.personal-ai-fund.btc-alert.plist
```

6. すぐ試す

```bash
launchctl kickstart -k gui/$(id -u)/com.personal-ai-fund.btc-alert
```

7. 停止する

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.personal-ai-fund.btc-alert.plist
```

8. 既に `~/Library/LaunchAgents/com.personal-ai-fund.btc-alert.plist` を配置済みなら、設定反映は次でやる

```bash
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.personal-ai-fund.btc-alert.plist
cp docs/launchd_btc_alert.example.plist ~/Library/LaunchAgents/com.personal-ai-fund.btc-alert.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.personal-ai-fund.btc-alert.plist
launchctl kickstart -k gui/$(id -u)/com.personal-ai-fund.btc-alert
launchctl list | grep personal-ai-fund
```

9. ログを確認する

```bash
tail -n 50 logs/btc_dip_alert_$(date +%Y%m%d).log
tail -n 50 logs/launchd_btc_alert.stdout.log
tail -n 50 logs/launchd_btc_alert.stderr.log
```

- 通常通知は `should_notify=true` の重要イベント時だけ Gmail 送信される
- `BUY_SKIP` 継続ならメールは送られず、Markdown レポートだけ更新される
- 実発注は行わない

### 9. 手動ポジション登録と売り判断

1. 買い通知が来たら、GMO などで手動購入する
2. 購入後に手動ポジションを登録する

```bash
./venv/bin/python scripts/add_manual_position.py \
  --symbol BTC_JPY \
  --entry-price 12000000 \
  --entry-date 2026-04-29 \
  --position-size 0.001 \
  --note "BUY_CANDIDATE通知後に手動購入"
```

3. 登録済みポジションを確認する

```bash
./venv/bin/python scripts/list_manual_positions.py
```

4. 以後は定時実行で利確候補 / 損切り候補 / 最大保有日数到達 / 継続保有を判定する
5. 売却したら終了登録する

```bash
./venv/bin/python scripts/close_manual_position.py \
  --id btc_20260429_001 \
  --exit-price 13200000 \
  --exit-date 2026-05-10 \
  --reason TAKE_PROFIT
```

- 実発注は行わない
- まずは通知と記録だけで運用する
- `BTC_JPY` の open position は 1 件運用を前提とする
- 複数 open position がある場合は合算せず、最新の 1 件だけを判定対象にして警告を出す

### 10. BTC BUY_WATCH と手動確認用の注文案

- `BUY_SKIP` は通常の観測記録で、買い候補ラインまでの距離と trend_filter の不足分を確認する
- `BUY_WATCH` は買い候補に近い監視状態として記録・通知するが、BUY 注文案は生成しない
- `BUY_WATCH` 通知は同日1回までを基本とし、通知本文に WATCH 理由とまだ買わない理由を含める
- `BUY_CANDIDATE` でのみ BUY 注文案を生成する
- `TAKE_PROFIT_CANDIDATE` / `STOP_LOSS_CANDIDATE` / `TIMEOUT_EXIT_CANDIDATE` では SELL 注文案を生成する
- 注文案は `state/order_proposals.json` に保存する
- 戦略・通知・表示上の `symbol` は `BTC_JPY` のまま使う
- GMO Private API の現物注文 body では `BTC_JPY` ではなく `BTC` を使う
- GMO サポート回答を受けて、現物注文用 symbol mapping を追加した
- `BTC_JPY` をそのまま現物注文に送ると `ERR-5127` などの制限エラーになる可能性がある
- 実発注は行わない
- `send_to_exchange=false` / `requires_manual_confirmation=true` を固定にする
- すべての注文案に `stop_loss` / `take_profit` / `max_loss_jpy` / `rationale` / `invalidation_conditions` を保存する
- 実行候補として扱う前に、共通の手動承認付き実行ゲートで安全条件を確認する

```bash
./venv/bin/python scripts/run_btc_dip_alert.py --notify-preview --markdown --proposal-jpy 1000
./venv/bin/python scripts/list_order_proposals.py
./venv/bin/python scripts/mark_order_proposal.py --id proposal_id --status ignored --note "見送り"
```

- `manually_executed` にしても実ポジションは自動登録しない
- 実際に手動購入した場合は、別途 `add_manual_position.py` で登録する

### 11. 半自動発注 DRY_RUN フロー

- これは実発注ではない
- 注文案から `state/dry_run_orders.json` に DRY_RUN 注文記録を作るだけ
- GMO API へ送信しない
- 実発注に進む前の安全な中間段階
- `READ_ONLY=true` / `DRY_RUN=true` を維持する
- 通常利用では承認フレーズ `RECORD DRY RUN ORDER` を手入力する
- `--yes-i-understand-dry-run-only` はテスト・CI 用
- 同じ proposal、または同じ `source_signal_id` / `symbol` / `side` / `price` の dry-run 注文記録は重複保存しない
- `STOP_TRADING` が存在する場合は dry-run 注文記録も停止する

```bash
./venv/bin/python scripts/list_order_proposals.py
./venv/bin/python scripts/dry_run_order_from_proposal.py --proposal-id proposal_id
# RECORD DRY RUN ORDER と入力
./venv/bin/python scripts/list_dry_run_orders.py
```

`dry_run_order_from_proposal.py` は次を確認してから記録する。

- `DRY_RUN=true`
- `READ_ONLY=true`
- `proposal.status=proposed`
- `proposal.source_status` が `BUY_CANDIDATE` / 利確候補 / 損切り候補 / timeout候補
- `proposal.send_to_exchange=false`
- `proposal.requires_manual_confirmation=true`
- `stop_loss` / `take_profit` / `max_loss_jpy` / 根拠 / 無効条件が入っている
- `STOP_TRADING` が存在しない
- GMO 注文 body の `symbol` が `BTC` などの現物 symbol
- `side` が `BUY` または `SELL`
- `execution_type` が `LIMIT`
- `size` が GMO 最小数量以上
- `price` が整数円

成功すると元の注文案は `status=dry_run_recorded` になり、`note=DRY_RUN order recorded. No exchange order sent.` が入る。

### 12. シグナル履歴と paper trade

- `state/signal_history.json` にシグナル履歴を保存する
- `state/paper_trades.json` に注文案ベースの仮想トレードを保存する
- signal_history は通知の有無に関係なく、各定時実行ごとに保存される
- `BUY_SKIP` もフォワードテスト用の観測データとして signal_history に保存される
- `paper_trades` は BUY 注文案が出た時だけ作られる
- paper trade は実売買ではなく、通知や注文案の有効性を後から検証するための記録
- BUY 注文案が出た場合、次の 3 ルールを同時に比較する
  - `Conservative`: 利確 `+5%` / 損切り `-7.5%` / 最大保有 `30日`
  - `Current`: 利確 `+10%` / 損切り `-12.5%` / 最大保有 `90日`
  - `Wide`: 利確 `+15%` / 損切り `-15%` / 最大保有 `180日`
- 3日、30日、90日などの節目で成績を見て、勝てないルールは捨てる

```bash
./venv/bin/python scripts/list_signal_history.py
./venv/bin/python scripts/list_paper_trades.py
./venv/bin/python scripts/list_paper_trades.py --status open
./venv/bin/python scripts/list_paper_trades.py --status closed --rule Current
./venv/bin/python scripts/report_paper_performance.py
```

### 13. 日次サマリーメール

- 重要通知は従来通り `should_notify=true` のときだけ送信する
- `--send-daily-summary` を付けると、22:00 実行時だけ正常稼働サマリーを Gmail 送信する
- daily summary は `BUY_SKIP` でも送信対象になる
- 09:00 / 15:00 実行では daily summary は送信しない
- `state/daily_summary_state.json` に送信済み日付を保存し、同じ日付には重複送信しない
- `--force-daily-summary` は時刻・重複判定を無視して preview / 送信対象にする
- `--dry-run-notify` は送信せず本文 preview だけ表示する
- daily summary は通知確認用であり、実発注は行わず、投資助言ではない

```bash
./venv/bin/python scripts/run_btc_dip_alert.py --send-daily-summary --dry-run-notify
./venv/bin/python scripts/run_btc_dip_alert.py --force-daily-summary --dry-run-notify
```

### 14. GMO現物注文 symbol 修正後のリハーサル

- GMO サポート回答により、現物注文 body の `symbol` は `BTC_JPY` ではなく `BTC` を使う
- 戦略・表示・通知・注文案の内部 `symbol` は引き続き `BTC_JPY`
- 実発注前に必ず次のリハーサルを実行する

```bash
./venv/bin/python scripts/rehearse_gmo_spot_order.py
```

- このリハーサルでは注文送信しない
- `order_body.symbol` が `BTC` になっていることを確認する
- `DRY_RUN: true` / `READ_ONLY: true` / `send_to_exchange: false` を確認する
- 実発注はまだ行わない

### 13. 稼働確認 health check

定時実行が正常に動いていて通知不要だったのか、異常で通知が来ていないのかを確認する。

```bash
./venv/bin/python scripts/check_btc_alert_health.py
```

- 今日の `logs/btc_dip_alert_YYYYMMDD.log` を見る
- 最後の `run_daily_btc_alert start`
- 最後の `exit_code`
- `Buy status`
- `Should notify`
- `Email sent`
- `Email skipped reason`
- `Markdown report saved`
- その時点までに期待される `09:00 / 15:00 / 22:00` 実行が揃っているか

## APIキー設定手順（口座開通後）

### 1. GMOコインでAPIキーを発行

1. GMOコイン管理画面 → API設定 → 新規APIキー作成
2. 権限：**「現物取引（BTC/JPY）」のみ有効**にする（信用取引は有効にしない）
3. IPアドレス制限：設定推奨（自宅のIPアドレスを登録）

### 2. .env に設定

```bash
cp .env.example .env
# .env を編集して GMO_API_KEY と GMO_API_SECRET を記入
```

**絶対にやってはいけないこと:**
- `.env` を git にコミットする（`.gitignore` で除外済みだが要注意）
- APIキー・シークレットをターミナルに直接入力して履歴に残す
- `READ_ONLY=false` と `DRY_RUN=false` を同時に設定する（必ず段階的に）

### 3. 接続確認

```bash
# DRY_RUN=false, READ_ONLY=true に変更してから実行
python scripts/check_private_api_connection.py
```

### 4. 安全な段階移行

```
DRY_RUN=true  READ_ONLY=true  → デフォルト（何もしない）
DRY_RUN=false READ_ONLY=true  → API接続確認のみ（発注不可）← まずここから
DRY_RUN=false READ_ONLY=false → 実発注可能 ← 十分テスト後のみ
```

## 口座開通前にやる安全確認

口座が開通し Private API を実装する前に、以下を必ず確認してください。

### リスク設定（`src/risk/risk_config.py`）

| 設定 | デフォルト値 | 説明 |
|---|---|---|
| `DRY_RUN` | `true` | **false にしない限り実発注は絶対に起きない** |
| `max_order_amount_jpy` | ¥1,000 | 1回あたり最大注文額 |
| `max_daily_orders` | 1回 | 1日あたり最大注文回数 |
| `max_daily_loss_jpy` | ¥300 | 1日最大損失額 |
| `max_position_value_jpy` | ¥3,000 | 最大保有BTC評価額 |
| 許可シンボル | BTC_JPY のみ | ETH等は全ブロック |
| 許可注文タイプ | LIMIT のみ | 成行（MARKET）は全ブロック |
| レバレッジ | 禁止 | 現物BTC/JPYのみ |

### 緊急停止（KILL SWITCH）

```bash
# 全取引を即停止する（ファイルを置くだけ）
echo "手動停止" > STOP_TRADING

# 再開する場合
rm STOP_TRADING
```

### 安全確認チェックリスト

口座開通後・Private API実装前に以下をすべて確認すること：

**基本安全確認（口座開通前）**
- [ ] `pytest tests/ -v` が全通過している
- [ ] `DRY_RUN=true` のまま `simulate_order.py` が正常動作している
- [ ] STOP_TRADINGファイルを置いたとき注文がブロックされる
- [ ] 1001円の注文がブロックされる
- [ ] 成行注文（MARKET）がブロックされる
- [ ] BTC_JPY以外のシンボルがブロックされる
- [ ] 1日2回目の注文がブロックされる

**APIキー安全確認（口座開通後）**
- [ ] `.env` に `GMO_API_KEY` と `GMO_API_SECRET` が設定されている
- [ ] `.env` が `.gitignore` に含まれている（`git status` で `.env` が出ないこと）
- [ ] `READ_ONLY=true` のまま `check_private_api_connection.py` が成功する
- [ ] `READ_ONLY=true` のとき `place_order` が `ReadOnlyViolationError` で止まる（pytestで確認済み）
- [ ] ログ出力にAPIシークレットが含まれていない（pytestで確認済み）
- [ ] 実発注前に `DRY_RUN=false READ_ONLY=false` の両方変更が必要なことを理解している

## 実発注前チェック手順（口座開通後の正式手順）

実発注に進むときは、**必ずこの順番で**実行すること。順番を飛ばさない。

### ステップ 1: 口座開通 & APIキー作成

1. GMOコインの口座審査が通ったことを確認
2. GMOコイン管理画面 → API設定 → 新規APIキー作成
3. 権限：**「現物取引（BTC/JPY）」のみ有効**　**「出金」は絶対に有効にしない**
4. `.env` に `GMO_API_KEY` と `GMO_API_SECRET` を記入

### ステップ 2: READ_ONLY=true で残高取得確認

```bash
# .env: DRY_RUN=false, READ_ONLY=true に変更してから実行
python scripts/check_private_api_connection.py
```

→ 円残高と BTC 残高が表示されれば OK

### ステップ 3: 入金

GMOコインへの入金（¥10,000 程度）を確認する。

### ステップ 4: 発注前チェックリスト

```bash
# .env に WITHDRAWAL_API_DISABLED=confirmed を追記してから実行
python scripts/pre_live_checklist.py
```

**ALL OK が出るまで次に進まない。**

チェック内容（14項目）:
- DRY_RUN=false / READ_ONLY=false に変更済みか
- STOP_TRADING ファイルがないか
- APIキーが設定されているか
- 出金権限なしを手動確認済みか（`WITHDRAWAL_API_DISABLED=confirmed`）
- 最大注文額 ≤ ¥1,000
- 最大日次注文 ≤ 1回
- 成行注文が無効か
- 許可シンボルが BTC_JPY のみか
- 注文タイプが LIMIT のみか
- DB 接続 OK
- ログ書き込み OK
- 未処理注文がないか

### ステップ 5: 発注リハーサル

```bash
python scripts/rehearse_live_order.py
```

→ 実際の注文は送信せずに、発注フロー全体をシミュレーション  
→ SQLite の `rehearsals` テーブルに記録される  
→ 最後に「これはリハーサルです」と表示されれば OK

### ステップ 6: 初回実発注

リハーサルが成功したら、`.env` を `READ_ONLY=false` に変更する。

**初回実発注は必ず `live_order_once.py` のみ使用すること。**

```bash
python scripts/live_order_once.py
```

`ERR-5127 This operation is restricted` が出た場合の確認項目:
- APIキーに注文権限があるか
- IP制限に引っかかっていないか
- GMO管理画面に追加確認や取引制限の案内が出ていないか

**重要なルール:**
- `live_order_once.py` は1回実行したら終了する（ループしない）
- 自動ループ・定期実行・cron 登録は禁止
- 初回は ¥1,000 以下の指値注文のみ
- 成行（MARKET）・レバレッジは禁止
- 発注前に端末で承認フレーズを入力する手動承認ゲートがある
- 承認フレーズを入力しない限り、発注リクエストは絶対に送信されない
- 発注後は GMOコインの管理画面でも注文を確認すること

**手動承認ゲートの仕組み:**

```
[live_order_once.py 実行]
  ↓
[チェックリスト 14項目確認]
  ↓
[リスクチェック]
  ↓
[端末に注文予定内容を表示]
  ↓
「EXECUTE LIVE ORDER」を正確に入力 ← ここで止まる
  ↓ (入力が違う or タイムアウト or 非対話環境)
  → 発注せず終了（安全）
  ↓ (フレーズ一致)
[GMO API へ発注リクエスト送信]
  ↓
[約定監視]
```

```
DRY_RUN=true  READ_ONLY=true  → デフォルト（何もしない）
DRY_RUN=false READ_ONLY=true  → API接続確認のみ（発注不可） ← ステップ2
DRY_RUN=false READ_ONLY=false → 実発注可能（手動承認ゲートあり） ← ステップ6以降のみ
```

### 初回実発注後の確認（必須）

`live_order_once.py` が終了すると自動的に `reports/post_trade_YYYYMMDD_HHMMSS.md` が生成される。

```bash
# レポートを手動で再生成する場合
python scripts/post_trade_report.py
```

レポートには以下が含まれる:
- 注文ID・ステータス・約定価格・約定数量
- 発注前後の残高・BTC保有量変化
- API残高との一致確認（DRY_RUN=false 時）
- エラー有無
- **次回発注可否（OK / NG）**

**次回発注可否 NG の条件:**
| 条件 | 対応 |
|---|---|
| OPEN 注文が残っている | `watch_orders` が終わるまで待つ |
| 注文ステータスが未確定 | GMOコイン管理画面で確認 |
| API残高とローカルがズレ | 手動で差異を確認してから再発注 |
| エラーが発生 | ログを確認して原因を解消 |
| STOP_TRADING が存在 | `rm STOP_TRADING` で解除 |
| 本日約定回数が上限 | 翌日に持ち越す |

**禁止事項:**
- 次回発注可否 NG のまま 2回目の発注を行うこと
- 初回実発注後 24時間以内の自動ループ発注
- `live_order_once.py` 以外のスクリプトで実発注すること（現時点）

## テスト

```bash
pytest tests/ -v
```

## 今後の拡張予定

- [ ] GMOコイン Private API（口座開設後）で実発注（DRY_RUN=falseに変更してから）
- [ ] IBKR API連携（海外市場）
- [ ] 戦略の追加（RSI、ボリンジャーバンドなど）

## FX USD/JPY シグナル検証（研究用）

> ⚠️ **FXは研究用シグナルのみ。実注文なし。**
> このモジュールは絶対に実注文APIを呼びません。
> `DRY_RUN=true` / `READ_ONLY=true` の環境でのみ実行してください。
> 現時点では注文送信用アダプタを接続せず、シグナル生成・保存・レポート作成・注文提案保存だけを行います。

### シグナル生成

> ⚠️ **Deprecated / Legacy**: `run_fx_usdjpy_signal.py` は旧バージョン。現在の launchd は `scripts/run_fx_daily.py` を使用している。通常はこのスクリプトを直接実行しない。

```bash
# 旧版（原則使わない）
python scripts/run_fx_usdjpy_signal.py

# 現行版（launchd が自動実行）
DRY_RUN=true READ_ONLY=true ./venv/bin/python scripts/run_fx_daily.py
```

- 価格データ不足、スプレッド過大、価格スナップショット異常、重要指標前後は `SKIP`
- 同一 `signal_id` はDB側で重複保存されません
- 実注文API、`order_executor`、`live_order_once.py` は使いません

### FX 注文提案

- `BUY` / `SELL` シグナルだけ `state/fx_order_proposals.json` に注文提案を保存する
- `WATCH` / `SKIP` では注文提案を作らない
- 注文提案は `send_to_exchange=false` / `requires_manual_confirmation=true`
- すべての注文提案に想定損切り、利確、最大損失、根拠、無効条件を入れる
- FXの実注文アダプタは未実装。現段階では提案保存までで、実行対象にしない
- 実行に進める場合も、必ず手動承認フレーズと共通実行ゲートを通す設計にする

```bash
python scripts/list_fx_order_proposals.py
```

## Daily Proposal Report

BTC の DRY_RUN 注文記録と FX USD/JPY の注文提案を横断して、当日の提案を Markdown で確認できます。これは確認用レポートであり、実注文API、注文送信アダプタ、実発注スクリプトは使いません。

```bash
DRY_RUN=true READ_ONLY=true ./venv/bin/python scripts/list_all_order_proposals.py
```

- 出力先: `reports/daily_order_proposals_YYYYMMDD.md`
- 読み込み元: `state/dry_run_orders.json`, `state/order_proposals.json`, `state/fx_order_proposals.json`
- 表示項目: `asset`, `side`, `status`, `entry_price`, `stop_loss`, `take_profit`, `max_loss_jpy`, `rationale`, `invalidation_conditions`, `created_at`
- `未承認` / `承認済み` / `無効` / `SKIP相当` に分類する
- `max_loss_jpy` の合計を表示する
- `DRY_RUN=true` / `READ_ONLY=true` でない場合は停止する
- `STOP_TRADING=true` または `STOP_TRADING` ファイルがある場合、全提案は実行禁止として明記する

### シグナル一覧
```bash
python scripts/list_fx_signals.py
```

### 定期実行

#### macOS launchd（推奨）
```bash
cp infra/com.personal-ai-fund.fx-usdjpy-signal.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.personal-ai-fund.fx-usdjpy-signal.plist
# 停止する場合
launchctl unload ~/Library/LaunchAgents/com.personal-ai-fund.fx-usdjpy-signal.plist
```

#### GitHub Actions
`.github/workflows/fx_usdjpy_signal.yml` を push すれば自動実行されます。
手動実行: Actions タブ → fx_usdjpy_signal → Run workflow

#### 重複実行時の挙動
同じ `signal_id`（= `usdjpy_{timestamp}_{action}`）は2回保存されません。

## Polymarket

Polymarket 関連は情報分析のみです。注文提案、手動承認付き実行ゲート、DRY_RUN注文記録、実注文の対象にはしません。
重複の場合 `save()` が `False` を返してスキップし、エラーにはなりません。

## FX Watch Candidate daily workflow

> ⚠️ **観察専用・実注文なし。** OrderProposal化・DRY_RUN注文化・実発注はしません。

### 初回セットアップ

```bash
# 長期 H1/D1 データを取得する（初回のみ）
python scripts/fetch_fx_ohlcv_longterm.py
```

### 日次実行（推奨）

```bash
# シグナル生成 + 保存 + 過去シグナル評価 + Daily Personal Report 生成
python scripts/run_daily_personal_report.py --save-watch-signal --evaluate-watch-signals
```

### 個別コマンド

```bash
# シグナル確認のみ（保存なし）
python scripts/run_fx_watch_candidate.py

# シグナル保存
python scripts/run_fx_watch_candidate.py --save

# 過去シグナル評価（48本タイムアウト）
python scripts/evaluate_fx_watch_signals.py --timeout-bars 48 --save

# Daily Personal Report のみ生成（シグナル新規生成・保存なし）
python scripts/run_daily_personal_report.py

# 特定日付のレポート生成
python scripts/run_daily_personal_report.py --report-date 20260509
```

### ワークフロー概要

```
1. fetch_fx_ohlcv_longterm.py   — 長期データ取得（週1回程度）
2. run_daily_personal_report.py — 日次実行（毎朝）
   ├── FX Watch Candidate シグナル生成
   ├── --save-watch-signal → state/fx_watch_signals.json に保存
   ├── --evaluate-watch-signals → 過去 open シグナルをTP/SL判定
   └── reports/daily_personal_report_YYYYMMDD.md を生成
```

### 出力ファイル

| ファイル | 内容 |
|----------|------|
| `state/fx_watch_signals.json` | シグナル履歴 + 評価結果 |
| `reports/daily_personal_report_YYYYMMDD.md` | 日次レポート |
| `reports/fx_watch_candidate_evaluation_YYYYMMDD.md` | 評価詳細レポート |

## 常時稼働環境への移行方針

- **現段階**（watch-only / paper trade / dry-run）は Mac launchd で運用する。
- 実データで `BUY_CANDIDATE` / `FX_CANDIDATE` が出始め、dry-run注文記録を安定取得したくなった段階で **VPS移行を検討する**。
- 極小ロットでも実注文に進む前には、Macスリープ依存をやめ、VPS等の常時稼働環境へ移行する。

**理由**: エントリー機会損失より、保有中の**利確・損切り・timeout exitを逃すリスクの方が大きいため**。

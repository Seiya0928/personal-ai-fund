"""
gmo_private_adapter.py — GMOコイン Private API ラッパー。

APIレスポンスを内部フォーマット（dict）に正規化してから返す。
呼び出し側は GMO 固有のフィールド名を意識しなくていい。

認証方式: HMAC-SHA256
  signature = HMAC-SHA256(timestamp + method + path + body, api_secret)
  headers:
    API-KEY: api_key
    API-TIMESTAMP: unix_ms
    API-SIGN: signature

DRY_RUN=true のとき place_order / cancel_order はモック応答を返す。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Optional

import requests

from src.execution.gmo_symbols import to_gmo_spot_symbol
from src.utils.logger import get_logger

log = get_logger(__name__)

PRIVATE_BASE = "https://api.coin.z.com/private"
PRIVATE_API_VERSION = "/v1"
MAX_RETRIES = 3
RETRY_WAIT = 2


# ---------------------------------------------------------------------------
# 正規化データクラス（dict で返す）
# ---------------------------------------------------------------------------

def _normalize_balance(raw: dict) -> dict:
    """
    APIレスポンス例:
      {"symbol": "JPY",  "amount": "500000", "available": "480000"}
      {"symbol": "BTC",  "amount": "0.001",  "available": "0.001"}
    → {"jpy": float, "btc": float, "btc_available": float}
    """
    result = {"jpy": 0.0, "btc": 0.0, "btc_available": 0.0}
    for item in raw.get("data", []):
        sym = item.get("symbol", "")
        amount = float(item.get("amount", 0))
        available = float(item.get("available", 0))
        if sym == "JPY":
            result["jpy"] = amount
        elif sym == "BTC":
            result["btc"] = amount
            result["btc_available"] = available
    return result


def _normalize_position(raw: dict, symbol: str = "BTC_JPY") -> dict:
    """
    GMOコインの現物ポジションは「残高」ベース。
    position_side: BUY-only（現物）
    → {"symbol": str, "btc_held": float, "avg_price": float}
    """
    # 現物の場合、ポジションは assets エンドポイントで取得済みの btc を使う
    # ここでは open_positions エンドポイントがある場合の変換を定義
    items = raw.get("data", {})
    if isinstance(items, list):
        for item in items:
            if item.get("symbol") == symbol:
                return {
                    "symbol": symbol,
                    "btc_held": float(item.get("openQuantity", 0)),
                    "avg_price": float(item.get("averageOpenPrice", 0)),
                }
    return {"symbol": symbol, "btc_held": 0.0, "avg_price": 0.0}


def _normalize_order(raw_order: dict) -> dict:
    """
    APIレスポンス例:
      {"orderId": "123", "symbol": "BTC_JPY", "side": "BUY",
       "executedSize": "0.001", "price": "5000000",
       "status": "FILLED", "timestamp": "2024-01-01T00:00:00.000Z"}
    → 内部フォーマット
    """
    status_map = {
        "WAITING": "OPEN",
        "ORDERED": "OPEN",
        "MODIFYING": "OPEN",
        "CANCELLING": "OPEN",
        "CANCELED": "CANCELLED",
        "EXECUTED": "FILLED",
        "EXPIRED": "EXPIRED",
    }
    raw_status = raw_order.get("status", "")
    return {
        "order_id": str(raw_order.get("orderId", "")),
        "symbol": raw_order.get("symbol", ""),
        "side": raw_order.get("side", ""),
        "order_type": raw_order.get("executionType", "LIMIT"),
        "price": float(raw_order.get("price", 0)),
        "quantity": float(raw_order.get("size", 0)),
        "executed_quantity": float(raw_order.get("executedSize", 0)),
        "status": status_map.get(raw_status, raw_status),
        "timestamp": raw_order.get("timestamp", ""),
    }


def _normalize_execution(raw_ex: dict) -> dict:
    """
    約定履歴の正規化。
    → {"execution_id", "order_id", "symbol", "side", "price", "quantity", "timestamp"}
    """
    return {
        "execution_id": str(raw_ex.get("executionId", "")),
        "order_id": str(raw_ex.get("orderId", "")),
        "symbol": raw_ex.get("symbol", ""),
        "side": raw_ex.get("side", ""),
        "price": float(raw_ex.get("price", 0)),
        "quantity": float(raw_ex.get("size", 0)),
        "timestamp": raw_ex.get("timestamp", ""),
    }


# ---------------------------------------------------------------------------
# Private API クライアント
# ---------------------------------------------------------------------------

class ReadOnlyViolationError(Exception):
    """READ_ONLY モードで発注・キャンセル系を呼んだときに送出する。"""


class MissingAPIKeyError(Exception):
    """APIキーまたはシークレットが未設定のときに送出する。"""


class GMOPrivateAPIError(Exception):
    """GMO Private API のエラー。"""

    def __init__(self, status_code: int | str, message: str):
        self.status_code = str(status_code)
        self.message = message
        super().__init__(f"{self.status_code} {self.message}")


class GMOPrivateAdapter:
    """
    GMOコイン Private API のラッパー。
    レスポンスはすべて正規化して返す。

    DRY_RUN=true   : place_order / cancel_order はモック応答を返し HTTP 送信しない
    READ_ONLY=true : place_order / cancel_order を呼ぶと ReadOnlyViolationError を送出
                     残高取得・注文一覧・約定履歴のみ許可
    """

    def __init__(
        self,
        api_key: str,
        api_secret: str,
        dry_run: bool = True,
        read_only: bool = True,
    ):
        self.api_key = api_key
        self.api_secret = api_secret
        self.dry_run = dry_run
        self.read_only = read_only

    def _guard_write(self, method_name: str):
        """発注・キャンセル系メソッドの先頭で呼ぶ。READ_ONLY=true なら例外。"""
        if self.read_only:
            raise ReadOnlyViolationError(
                f"READ_ONLY=true のため '{method_name}' は実行できません。"
                f" .env の READ_ONLY=false に変更してから再度実行してください。"
            )

    def _versioned_path(self, path: str) -> str:
        """署名対象と実リクエストで共通の version 付き path を返す。"""
        normalized_path = path if path.startswith("/") else f"/{path}"
        if normalized_path.startswith(PRIVATE_API_VERSION + "/"):
            return normalized_path
        return f"{PRIVATE_API_VERSION}{normalized_path}"

    def _serialize_body(self, body: Optional[dict]) -> str:
        """署名対象・送信 payload 用の JSON 文字列を返す。GET は空文字。"""
        if body is None:
            return ""
        return json.dumps(body, separators=(",", ":"), ensure_ascii=False)

    def _build_signature_payload(self, method: str, path: str, body: str = "") -> tuple[str, str]:
        """署名に使う timestamp と payload を返す。"""
        timestamp = str(int(time.time() * 1000))
        signature_payload = timestamp + method.upper() + path + body
        return timestamp, signature_payload

    # ------------------------------------------------------------------
    # 認証ヘッダー生成
    # ------------------------------------------------------------------

    def _headers(self, method: str, path: str, body: str = "") -> dict:
        ts, msg = self._build_signature_payload(method, path, body)
        sign = hmac.new(
            self.api_secret.encode(), msg.encode(), hashlib.sha256
        ).hexdigest()
        return {
            "API-KEY": self.api_key,
            "API-TIMESTAMP": ts,
            "API-SIGN": sign,
            "Content-Type": "application/json",
        }

    def _normalize_order_symbol(self, symbol: str) -> str:
        """
        内部シンボルを GMO API 用シンボルへ変換する。
        現物注文では BTC_JPY のような価格ペアではなく、BTC のような現物銘柄シンボルを使う。
        """
        return to_gmo_spot_symbol(symbol)

    def _build_order_body(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
    ) -> dict:
        """GMO /v1/order 用の request body を組み立てる。"""
        api_symbol = self._normalize_order_symbol(symbol)
        return {
            "symbol": api_symbol,
            "side": side,
            "executionType": order_type,
            "price": str(int(price)),
            "size": f"{quantity:.8f}",
        }

    # ------------------------------------------------------------------
    # HTTP ラッパー
    # ------------------------------------------------------------------

    def _raise_for_api_error(self, data: dict):
        status = data.get("status")
        if status == 0:
            return
        messages = data.get("messages") or []
        first_message = messages[0] if messages else {}
        message_code = first_message.get("message_code") or status
        message_text = first_message.get("message_string") or str(data)
        raise GMOPrivateAPIError(message_code, message_text)

    def _should_retry(self, error: Exception) -> bool:
        if isinstance(error, GMOPrivateAPIError):
            return False
        if isinstance(error, requests.Timeout):
            return True
        if isinstance(error, requests.ConnectionError):
            return True
        if isinstance(error, requests.HTTPError):
            response = error.response
            if response is not None and 500 <= response.status_code < 600:
                return True
            return False
        return False

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        versioned_path = self._versioned_path(path)
        url = PRIVATE_BASE + versioned_path
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                headers = self._headers("GET", versioned_path, "")
                resp = requests.get(url, headers=headers, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                self._raise_for_api_error(data)
                return data
            except Exception as e:
                if not self._should_retry(e):
                    log.error(f"[Private GET] 即時失敗: {versioned_path}: {e}")
                    raise
                log.warning(f"[Private GET] リトライ {attempt}/{MAX_RETRIES} {versioned_path}: {e}")
                if attempt == MAX_RETRIES:
                    log.error(f"[Private GET] 失敗: {versioned_path}")
                    raise
                time.sleep(RETRY_WAIT * attempt)

    def _post(self, path: str, body: dict) -> dict:
        versioned_path = self._versioned_path(path)
        url = PRIVATE_BASE + versioned_path
        body_str = self._serialize_body(body)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                headers = self._headers("POST", versioned_path, body_str)
                resp = requests.post(url, headers=headers, data=body_str, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                self._raise_for_api_error(data)
                return data
            except Exception as e:
                if not self._should_retry(e):
                    log.error(f"[Private POST] 即時失敗: {versioned_path}: {e}")
                    raise
                log.warning(f"[Private POST] リトライ {attempt}/{MAX_RETRIES} {versioned_path}: {e}")
                if attempt == MAX_RETRIES:
                    log.error(f"[Private POST] 失敗: {versioned_path}")
                    raise
                time.sleep(RETRY_WAIT * attempt)

    def _delete(self, path: str, body: dict) -> dict:
        versioned_path = self._versioned_path(path)
        url = PRIVATE_BASE + versioned_path
        body_str = self._serialize_body(body)
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                headers = self._headers("DELETE", versioned_path, body_str)
                resp = requests.delete(url, headers=headers, data=body_str, timeout=10)
                resp.raise_for_status()
                data = resp.json()
                self._raise_for_api_error(data)
                return data
            except Exception as e:
                if not self._should_retry(e):
                    log.error(f"[Private DELETE] 即時失敗: {versioned_path}: {e}")
                    raise
                log.warning(f"[Private DELETE] リトライ {attempt}/{MAX_RETRIES} {versioned_path}: {e}")
                if attempt == MAX_RETRIES:
                    log.error(f"[Private DELETE] 失敗: {versioned_path}")
                    raise
                time.sleep(RETRY_WAIT * attempt)

    # ------------------------------------------------------------------
    # 残高・ポジション
    # ------------------------------------------------------------------

    def get_balance(self) -> dict:
        """円残高・BTC残高を正規化して返す。"""
        raw = self._get("/account/assets")
        result = _normalize_balance(raw)
        log.info(f"残高同期: JPY=¥{result['jpy']:,.0f} BTC={result['btc']:.8f}")
        return result

    def get_positions(self, symbol: str = "BTC_JPY") -> dict:
        """
        現物の場合は保有BTC = get_balance()["btc"] と同じ。
        レバレッジ口座がある場合は /openPositions を使う。
        現物専用のためここでは balance から取得する。
        """
        balance = self.get_balance()
        pos = {
            "symbol": symbol,
            "btc_held": balance["btc"],
            "avg_price": 0.0,  # 現物APIでは平均取得単価は返ってこない
        }
        log.info(f"ポジション同期: {symbol} btc_held={pos['btc_held']:.8f}")
        return pos

    def get_executions_today(self, symbol: str = "BTC_JPY") -> list[dict]:
        """本日の約定履歴を正規化して返す。"""
        raw = self._get("/latestExecutions", params={"symbol": symbol, "count": "100"})
        items = raw.get("data", {}).get("list", [])
        result = [_normalize_execution(ex) for ex in items]
        log.info(f"約定履歴取得: {len(result)}件 ({symbol})")
        return result

    # ------------------------------------------------------------------
    # 注文
    # ------------------------------------------------------------------

    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
    ) -> dict:
        """
        指値注文を発注する。
        DRY_RUN=true のとき実際には送信せずモック応答を返す。
        → {"order_id": str, "symbol": str, "side": str, ...}
        """
        self._guard_write("place_order")

        if self.dry_run:
            mock_id = f"dry_{uuid.uuid4().hex[:8]}"
            log.info(f"[DRY_RUN] モック発注: {symbol} {side} {quantity:.8f} @ ¥{price:,.0f} → id={mock_id}")
            return {
                "order_id": mock_id,
                "symbol": symbol,
                "side": side,
                "order_type": order_type,
                "price": price,
                "quantity": quantity,
                "executed_quantity": 0.0,
                "status": "OPEN",
                "timestamp": "",
            }

        body = self._build_order_body(symbol, side, order_type, price, quantity)
        log.info(
            "注文リクエスト準備: symbol=%s side=%s executionType=%s price=%s size=%s",
            body["symbol"], body["side"], body["executionType"], body["price"], body["size"]
        )
        raw = self._post("/order", body)
        order_id = str(raw.get("data", ""))
        log.info(f"発注完了: {symbol} {side} {quantity:.8f} @ ¥{price:,.0f} → order_id={order_id}")
        return {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "order_type": order_type,
            "price": price,
            "quantity": quantity,
            "executed_quantity": 0.0,
            "status": "OPEN",
            "timestamp": "",
        }

    def get_order(self, order_id: str) -> dict:
        """注文IDで注文状態を取得して正規化して返す。"""
        if self.dry_run:
            # DRY_RUNでは即FILLED扱い（監視テスト用）
            log.info(f"[DRY_RUN] モック注文状態: order_id={order_id} → FILLED")
            return {
                "order_id": order_id,
                "symbol": "BTC_JPY",
                "side": "BUY",
                "order_type": "LIMIT",
                "price": 0.0,
                "quantity": 0.0,
                "executed_quantity": 0.0,
                "status": "FILLED",
                "timestamp": "",
            }
        raw = self._get("/orders", params={"orderId": order_id})
        items = raw.get("data", {}).get("list", [])
        if not items:
            raise ValueError(f"注文が見つかりません: {order_id}")
        return _normalize_order(items[0])

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        """注文をキャンセルする。成功したら True を返す。"""
        self._guard_write("cancel_order")

        if self.dry_run:
            log.info(f"[DRY_RUN] モックキャンセル: order_id={order_id}")
            return True
        try:
            self._delete("/order", {"orderId": int(order_id), "symbol": symbol})
            log.info(f"キャンセル完了: order_id={order_id}")
            return True
        except Exception as e:
            log.error(f"キャンセル失敗: order_id={order_id}: {e}")
            return False


# ---------------------------------------------------------------------------
# ファクトリ関数
# ---------------------------------------------------------------------------

def load_adapter_from_env() -> "GMOPrivateAdapter":
    """
    .env から設定を読み込んで GMOPrivateAdapter を返す。
    APIキーが未設定の場合は MissingAPIKeyError を送出して安全停止する。
    ログに APIキー・シークレットは絶対に出力しない。
    """
    import os
    from dotenv import load_dotenv
    load_dotenv()

    api_key = os.getenv("GMO_API_KEY", "").strip()
    api_secret = os.getenv("GMO_API_SECRET", "").strip()
    dry_run = os.getenv("DRY_RUN", "true").lower() not in ("false", "0", "no")
    read_only = os.getenv("READ_ONLY", "true").lower() not in ("false", "0", "no")

    if not api_key:
        raise MissingAPIKeyError(
            "GMO_API_KEY が .env に設定されていません。"
            " .env.example を参考に設定してください。"
        )
    if not api_secret:
        raise MissingAPIKeyError(
            "GMO_API_SECRET が .env に設定されていません。"
            " .env.example を参考に設定してください。"
        )

    # キーの存在だけ確認（値は絶対にログに出さない）
    log.info(
        f"GMOPrivateAdapter 初期化: "
        f"api_key=***{api_key[-4:]} "
        f"dry_run={dry_run} read_only={read_only}"
    )

    return GMOPrivateAdapter(
        api_key=api_key,
        api_secret=api_secret,
        dry_run=dry_run,
        read_only=read_only,
    )

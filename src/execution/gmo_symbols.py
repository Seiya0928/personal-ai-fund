from __future__ import annotations


_SPOT_SYMBOL_MAP = {
    "BTC_JPY": "BTC",
    "ETH_JPY": "ETH",
    "XRP_JPY": "XRP",
    "BTC": "BTC",
    "ETH": "ETH",
    "XRP": "XRP",
}


def to_gmo_spot_symbol(symbol: str) -> str:
    """
    戦略・表示用シンボルを GMO 現物注文 API 用シンボルへ変換する。

    例:
    - BTC_JPY -> BTC
    - ETH_JPY -> ETH
    - XRP_JPY -> XRP
    - BTC -> BTC
    """
    if not symbol or not isinstance(symbol, str):
        raise ValueError("symbol must be a non-empty string")
    try:
        return _SPOT_SYMBOL_MAP[symbol]
    except KeyError as exc:
        raise ValueError(f"unsupported GMO spot symbol: {symbol}") from exc

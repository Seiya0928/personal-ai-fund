import pandas as pd
from dataclasses import dataclass
from typing import Optional
from src.utils.logger import get_logger

log = get_logger(__name__)


@dataclass
class BacktestResult:
    initial_capital: float
    final_capital: float
    total_return_pct: float
    annualized_return_pct: float
    win_rate_pct: float
    max_drawdown_pct: float
    max_position_unrealized_drawdown_pct: float
    max_portfolio_unrealized_drawdown_pct: float
    max_unrealized_drawdown_pct: float
    max_holding_days: float
    average_holding_days: float
    capital_utilization_rate_pct: float
    return_per_max_drawdown: float
    return_per_holding_day: float
    max_capital_locked_days: float
    realized_loss_count: int
    stop_loss_count: int
    timeout_exit_count: int
    trade_count: int
    execution_count: int
    average_pnl_jpy: float
    total_pnl_jpy: float
    period_days: float
    trades: list[dict]
    assumptions: dict


class BacktestRunner:
    """
    シグナルDataFrameを受け取り、コスト込みのバックテスト結果を計算する。
    """

    def __init__(
        self,
        initial_capital: float = 100_000,
        fee_bps: float = 12.0,
        spread_bps: float = 5.0,
    ):
        self.initial_capital = initial_capital
        self.fee_rate = fee_bps / 10_000
        self.spread_rate = spread_bps / 10_000

    def _buy(self, price: float, spend_total: float, cash: float, btc: float, lots: list[dict], timestamp) -> tuple[float, float, Optional[dict]]:
        if spend_total <= 0 or cash <= 0:
            return cash, btc, None
        spend_total = min(spend_total, cash)
        execution_price = price * (1 + self.spread_rate)
        quantity = spend_total / (execution_price * (1 + self.fee_rate))
        if quantity <= 0:
            return cash, btc, None
        fee = quantity * execution_price * self.fee_rate
        gross = quantity * execution_price
        total_spend = gross + fee
        cash -= total_spend
        btc += quantity
        lots.append({
            "quantity": quantity,
            "cost_total": total_spend,
            "entry_price": execution_price,
            "timestamp": timestamp,
        })
        return cash, btc, {
            "side": "BUY",
            "price": execution_price,
            "quantity": quantity,
            "fee": fee,
            "gross": gross,
            "timestamp": timestamp,
        }

    def _sell(
        self,
        price: float,
        quantity: float,
        cash: float,
        btc: float,
        lots: list[dict],
        timestamp,
        exit_reason: Optional[str] = None,
    ) -> tuple[float, float, list[dict], Optional[dict]]:
        if quantity <= 0 or btc <= 0:
            return cash, btc, [], None
        quantity = min(quantity, btc)
        execution_price = price * (1 - self.spread_rate)
        gross = quantity * execution_price
        fee = gross * self.fee_rate
        net_proceeds = gross - fee
        cash += net_proceeds
        btc -= quantity
        if abs(btc) <= 1e-12:
            btc = 0.0

        closed = []
        qty_left = quantity
        while qty_left > 1e-12 and lots:
            lot = lots[0]
            take_qty = min(qty_left, lot["quantity"])
            cost_basis = lot["cost_total"] * (take_qty / lot["quantity"])
            proceeds = net_proceeds * (take_qty / quantity)
            pnl = proceeds - cost_basis
            closed.append({
                "entry": lot["entry_price"],
                "exit": execution_price,
                "pnl": pnl,
                "quantity": take_qty,
                "holding_days": (timestamp - lot["timestamp"]).total_seconds() / 86400,
                "exit_reason": exit_reason or "SELL",
                "entry_timestamp": lot["timestamp"],
                "exit_timestamp": timestamp,
            })
            lot["quantity"] -= take_qty
            lot["cost_total"] -= cost_basis
            qty_left -= take_qty
            if lot["quantity"] <= 1e-12:
                lots.pop(0)

        return cash, btc, closed, {
            "side": "SELL",
            "price": execution_price,
            "quantity": quantity,
            "fee": fee,
            "gross": gross,
            "timestamp": timestamp,
        }

    def run(self, df: pd.DataFrame) -> BacktestResult:
        df = df.copy()
        if not pd.api.types.is_datetime64_any_dtype(df["timestamp"]):
            df["timestamp"] = pd.to_datetime(pd.to_numeric(df["timestamp"]), unit="ms", utc=True)
        else:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.sort_values("timestamp").reset_index(drop=True)
        capital = self.initial_capital
        btc = 0.0
        lots: list[dict] = []
        trades: list[dict] = []
        execution_count = 0
        equity_curve = []
        holding_days_samples: list[float] = []
        utilization_samples: list[float] = []
        capital_locked_days: list[float] = []
        max_position_unrealized_dd = 0.0
        max_portfolio_unrealized_dd = 0.0
        current_lock_start = None

        has_target = "target_position" in df.columns
        has_contribution = "contribution_jpy" in df.columns

        for _, row in df.iterrows():
            price = row["close"]
            timestamp = row["timestamp"]
            exit_reason = row.get("exit_reason")
            if pd.isna(exit_reason):
                exit_reason = None

            if has_contribution and float(row.get("contribution_jpy", 0.0) or 0.0) > 0:
                capital, btc, execution = self._buy(
                    price=price,
                    spend_total=float(row["contribution_jpy"]),
                    cash=capital,
                    btc=btc,
                    lots=lots,
                    timestamp=timestamp,
                )
                if execution:
                    execution_count += 1

            if has_target and pd.notna(row.get("target_position")):
                target_position = float(row["target_position"])
                equity_mid = capital + btc * price
                desired_value = equity_mid * target_position
                current_value = btc * price
                diff = desired_value - current_value

                if diff > 1e-9:
                    capital, btc, execution = self._buy(
                        price=price,
                        spend_total=diff,
                        cash=capital,
                        btc=btc,
                        lots=lots,
                        timestamp=timestamp,
                    )
                    if execution:
                        execution_count += 1
                elif diff < -1e-9:
                    sell_qty = min(btc, abs(diff) / price)
                    capital, btc, closed_trades, execution = self._sell(
                        price=price,
                        quantity=sell_qty,
                        cash=capital,
                        btc=btc,
                        lots=lots,
                        timestamp=timestamp,
                        exit_reason=exit_reason,
                    )
                    if execution:
                        execution_count += 1
                        trades.extend(closed_trades)
                        holding_days_samples.extend(trade["holding_days"] for trade in closed_trades)

            open_value = btc * price
            open_cost_basis = sum(lot["cost_total"] for lot in lots)
            unrealized_loss = max(open_cost_basis - open_value, 0.0)
            if btc > 0 and current_lock_start is None:
                current_lock_start = timestamp
            elif btc <= 1e-12 and current_lock_start is not None:
                capital_locked_days.append((timestamp - current_lock_start).total_seconds() / 86400)
                current_lock_start = None

            total_equity = capital + open_value
            equity_curve.append(total_equity)
            utilization = (open_value / total_equity * 100) if total_equity > 0 else 0.0
            utilization_samples.append(utilization)

            if open_cost_basis > 0:
                position_unrealized_dd = unrealized_loss / open_cost_basis * 100
                max_position_unrealized_dd = max(max_position_unrealized_dd, position_unrealized_dd)
            if total_equity > 0:
                portfolio_unrealized_dd = unrealized_loss / total_equity * 100
                max_portfolio_unrealized_dd = max(max_portfolio_unrealized_dd, portfolio_unrealized_dd)

        if btc > 0:
            capital, btc, closed_trades, execution = self._sell(
                price=float(df.iloc[-1]["close"]),
                quantity=btc,
                cash=capital,
                btc=btc,
                lots=lots,
                timestamp=df.iloc[-1]["timestamp"],
                exit_reason="FORCE_EXIT",
            )
            if execution:
                execution_count += 1
                trades.extend(closed_trades)
                holding_days_samples.extend(trade["holding_days"] for trade in closed_trades)
            equity_curve[-1] = capital
        if current_lock_start is not None:
            capital_locked_days.append((df.iloc[-1]["timestamp"] - current_lock_start).total_seconds() / 86400)

        total_return = (capital - self.initial_capital) / self.initial_capital * 100 if self.initial_capital else 0.0
        win_trades = [t for t in trades if t["pnl"] > 0]
        win_rate = len(win_trades) / len(trades) * 100 if trades else 0.0

        max_dd = 0.0
        peak = equity_curve[0] if equity_curve else self.initial_capital
        for value in equity_curve:
            peak = max(peak, value)
            dd = (peak - value) / peak * 100 if peak > 0 else 0.0
            if dd > max_dd:
                max_dd = dd

        period_days = max(
            (df.iloc[-1]["timestamp"] - df.iloc[0]["timestamp"]).total_seconds() / 86400,
            1 / 24,
        ) if len(df) > 1 else 1 / 24
        years = period_days / 365.25
        annualized = ((capital / self.initial_capital) ** (1 / years) - 1) * 100 if years > 0 and self.initial_capital > 0 else 0.0
        avg_pnl = sum(t["pnl"] for t in trades) / len(trades) if trades else 0.0
        max_holding_days = max(holding_days_samples) if holding_days_samples else 0.0
        avg_holding_days = sum(holding_days_samples) / len(holding_days_samples) if holding_days_samples else 0.0
        capital_utilization = sum(utilization_samples) / len(utilization_samples) if utilization_samples else 0.0
        max_capital_locked_days = max(capital_locked_days) if capital_locked_days else 0.0
        realized_loss_count = sum(1 for trade in trades if trade["pnl"] < 0)
        stop_loss_count = sum(1 for trade in trades if trade.get("exit_reason") == "STOP_LOSS")
        timeout_exit_count = sum(1 for trade in trades if trade.get("exit_reason") == "TIMEOUT_EXIT")
        return_per_max_drawdown = total_return / max_dd if max_dd > 0 else 0.0
        return_per_holding_day = total_return / avg_holding_days if avg_holding_days > 0 else 0.0

        return BacktestResult(
            initial_capital=self.initial_capital,
            final_capital=round(capital, 0),
            total_return_pct=round(total_return, 2),
            annualized_return_pct=round(annualized, 2),
            win_rate_pct=round(win_rate, 2),
            max_drawdown_pct=round(max_dd, 2),
            max_position_unrealized_drawdown_pct=round(max_position_unrealized_dd, 2),
            max_portfolio_unrealized_drawdown_pct=round(max_portfolio_unrealized_dd, 2),
            max_unrealized_drawdown_pct=round(max_portfolio_unrealized_dd, 2),
            max_holding_days=round(max_holding_days, 1),
            average_holding_days=round(avg_holding_days, 1),
            capital_utilization_rate_pct=round(capital_utilization, 2),
            return_per_max_drawdown=round(return_per_max_drawdown, 4),
            return_per_holding_day=round(return_per_holding_day, 4),
            max_capital_locked_days=round(max_capital_locked_days, 1),
            realized_loss_count=realized_loss_count,
            stop_loss_count=stop_loss_count,
            timeout_exit_count=timeout_exit_count,
            trade_count=len(trades),
            execution_count=execution_count,
            average_pnl_jpy=round(avg_pnl, 0),
            total_pnl_jpy=round(capital - self.initial_capital, 0),
            period_days=round(period_days, 1),
            trades=trades,
            assumptions={
                "fee_bps": self.fee_rate * 10_000,
                "spread_bps": self.spread_rate * 10_000,
            },
        )

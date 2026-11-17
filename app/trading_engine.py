"""ALP read-only analysis and paper-trading engine.

This module has no exchange-order functionality and makes no network requests.
It accepts public market candles supplied by the caller and performs local
calculations only. All trading simulations are long-only spot simulations.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Iterable, Optional, Sequence
import math
import time


DEFAULT_STARTING_CASH = Decimal("100.00")
DEFAULT_RISK_BUDGET = Decimal("1.00")
DEFAULT_FEE_RATE = Decimal("0.0025")  # 0.25% per side
INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1h": 3_600_000,
    "2h": 7_200_000,
    "4h": 14_400_000,
    "6h": 21_600_000,
    "8h": 28_800_000,
    "12h": 43_200_000,
    "1d": 86_400_000,
    "1w": 604_800_000,
}


@dataclass(frozen=True)
class Candle:
    timestamp_ms: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class PositionPlan:
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    quantity: Decimal
    notional_eur: Decimal
    entry_fee_eur: Decimal
    estimated_exit_fee_eur: Decimal
    estimated_loss_eur: Decimal
    risk_budget_eur: Decimal


@dataclass
class PaperPosition:
    market: str
    entry_price: Decimal
    stop_price: Decimal
    target_price: Decimal
    quantity: Decimal
    entry_fee_eur: Decimal
    opened_at_ms: int


@dataclass(frozen=True)
class ClosedTrade:
    market: str
    entry_price: Decimal
    exit_price: Decimal
    quantity: Decimal
    entry_fee_eur: Decimal
    exit_fee_eur: Decimal
    gross_pnl_eur: Decimal
    net_pnl_eur: Decimal
    closed_at_ms: int


def _finite_float(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Ungültiger Wert für {field}.") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} muss endlich sein.")
    return number


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"Ungültiger Wert für {field}.") from exc
    if not result.is_finite():
        raise ValueError(f"{field} muss endlich sein.")
    return result


def parse_bitvavo_candles(raw_candles: Iterable[Sequence[Any]]) -> list[Candle]:
    """Parse Bitvavo [timestamp, open, high, low, close, volume] rows."""
    candles: list[Candle] = []
    for index, row in enumerate(raw_candles):
        if not isinstance(row, (list, tuple)) or len(row) < 6:
            raise ValueError(f"Kerze {index} hat nicht mindestens 6 Felder.")
        try:
            timestamp_ms = int(row[0])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Ungültiger Zeitstempel in Kerze {index}.") from exc
        if timestamp_ms < 0:
            raise ValueError(f"Negativer Zeitstempel in Kerze {index}.")
        open_price = _finite_float(row[1], "open")
        high = _finite_float(row[2], "high")
        low = _finite_float(row[3], "low")
        close = _finite_float(row[4], "close")
        volume = _finite_float(row[5], "volume")
        if min(open_price, high, low, close) <= 0:
            raise ValueError(f"Kurse müssen in Kerze {index} positiv sein.")
        if volume < 0 or high < max(open_price, close, low) or low > min(open_price, close, high):
            raise ValueError(f"Inkonsistente OHLCV-Daten in Kerze {index}.")
        candles.append(Candle(timestamp_ms, open_price, high, low, close, volume))
    candles.sort(key=lambda candle: candle.timestamp_ms)
    # Duplicate timestamps can distort indicators; retain the last row for each timestamp.
    unique: dict[int, Candle] = {c.timestamp_ms: c for c in candles}
    return [unique[key] for key in sorted(unique)]


def completed_candles(candles: Sequence[Candle], interval: str, now_ms: Optional[int] = None) -> list[Candle]:
    """Exclude a still-forming last candle so signals use closed bars only."""
    if interval not in INTERVAL_MS:
        raise ValueError("Nicht unterstütztes Zeitintervall.")
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    duration = INTERVAL_MS[interval]
    return [c for c in candles if c.timestamp_ms + duration <= now]


def ema(values: Sequence[float], period: int) -> list[Optional[float]]:
    if period < 1:
        raise ValueError("EMA-Periode muss mindestens 1 sein.")
    result: list[Optional[float]] = [None] * len(values)
    if len(values) < period:
        return result
    seed = sum(values[:period]) / period
    result[period - 1] = seed
    multiplier = 2.0 / (period + 1.0)
    previous = seed
    for index in range(period, len(values)):
        previous = (values[index] - previous) * multiplier + previous
        result[index] = previous
    return result


def rsi(values: Sequence[float], period: int = 14) -> list[Optional[float]]:
    if period < 1:
        raise ValueError("RSI-Periode muss mindestens 1 sein.")
    result: list[Optional[float]] = [None] * len(values)
    if len(values) <= period:
        return result
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(values[:-1], values[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def value(gain: float, loss: float) -> float:
        if gain == 0 and loss == 0:
            return 50.0
        if loss == 0:
            return 100.0
        relative_strength = gain / loss
        return 100.0 - (100.0 / (1.0 + relative_strength))

    result[period] = value(avg_gain, avg_loss)
    for index in range(period + 1, len(values)):
        avg_gain = ((avg_gain * (period - 1)) + gains[index - 1]) / period
        avg_loss = ((avg_loss * (period - 1)) + losses[index - 1]) / period
        result[index] = value(avg_gain, avg_loss)
    return result


def macd(
    values: Sequence[float], fast_period: int = 12, slow_period: int = 26, signal_period: int = 9
) -> dict[str, list[Optional[float]]]:
    if fast_period < 1 or slow_period <= fast_period or signal_period < 1:
        raise ValueError("MACD-Perioden sind ungültig.")
    fast = ema(values, fast_period)
    slow = ema(values, slow_period)
    line: list[Optional[float]] = [None] * len(values)
    valid_values: list[float] = []
    valid_start = slow_period - 1
    for index in range(valid_start, len(values)):
        if fast[index] is not None and slow[index] is not None:
            value = fast[index] - slow[index]
            line[index] = value
            valid_values.append(value)
    signal_valid = ema(valid_values, signal_period)
    signal: list[Optional[float]] = [None] * len(values)
    histogram: list[Optional[float]] = [None] * len(values)
    for offset, value in enumerate(signal_valid):
        index = valid_start + offset
        signal[index] = value
        if value is not None and line[index] is not None:
            histogram[index] = line[index] - value
    return {"macd": line, "signal": signal, "histogram": histogram}


def analyze_candles(
    raw_or_parsed_candles: Iterable[Sequence[Any]] | Sequence[Candle],
    market: str = "BTC-EUR",
    interval: str = "1h",
    now_ms: Optional[int] = None,
    minimum_bars: int = 200,
) -> dict[str, Any]:
    """Return a deterministic long-only spot setup assessment; never places orders."""
    items = list(raw_or_parsed_candles)
    if not items:
        raise ValueError("Keine Kerzendaten vorhanden.")
    if isinstance(items[0], Candle):
        parsed = sorted(items, key=lambda c: c.timestamp_ms)
    else:
        parsed = parse_bitvavo_candles(items)  # type: ignore[arg-type]
    closed = completed_candles(parsed, interval, now_ms)
    if len(closed) < minimum_bars:
        return {
            "market": market,
            "interval": interval,
            "status": "insufficient_data",
            "bars_available": len(closed),
            "bars_required": minimum_bars,
            "signal": "WAIT",
            "reason": f"Für EMA 200 werden mindestens {minimum_bars} abgeschlossene Kerzen benötigt.",
            "mode": "read-only / paper trading only",
            "real_orders_enabled": False,
        }

    closes = [c.close for c in closed]
    ema20 = ema(closes, 20)[-1]
    ema50 = ema(closes, 50)[-1]
    ema200 = ema(closes, 200)[-1]
    rsi14 = rsi(closes, 14)[-1]
    macd_values = macd(closes)
    macd_line = macd_values["macd"][-1]
    macd_signal = macd_values["signal"][-1]
    macd_histogram = macd_values["histogram"][-1]
    last = closed[-1]
    volume_window = [c.volume for c in closed[-21:-1]]
    average_volume = sum(volume_window) / len(volume_window) if volume_window else 0.0
    volume_ratio = last.volume / average_volume if average_volume > 0 else None
    range_window = closed[-50:]
    recent_floor = min(c.low for c in range_window)
    recent_ceiling = max(c.high for c in range_window)

    bullish_trend = bool(ema20 and ema50 and ema200 and ema20 > ema50 > ema200 and last.close > ema20)
    momentum_ok = bool(rsi14 is not None and 50.0 <= rsi14 < 70.0)
    macd_ok = bool(macd_line is not None and macd_signal is not None and macd_line > macd_signal and macd_line > 0)
    volume_ok = bool(volume_ratio is not None and volume_ratio >= 1.0)
    exit_warning = bool(
        (ema50 is not None and last.close < ema50)
        or (macd_line is not None and macd_signal is not None and rsi14 is not None
            and macd_line < macd_signal and rsi14 < 45.0)
    )

    if exit_warning:
        signal = "EXIT_WARNING"
        reason = "Mindestens ein technischer Exit-Filter ist aktiv; bestehende Paper-Position prüfen."
    elif bullish_trend and momentum_ok and macd_ok and volume_ok:
        signal = "PAPER_ENTRY_CANDIDATE"
        reason = "Trend-, Momentum-, MACD- und Volumenfilter sind gleichzeitig erfüllt. Kein Orderauftrag."
    else:
        signal = "WAIT"
        failed = []
        if not bullish_trend: failed.append("Trendfilter")
        if not momentum_ok: failed.append("RSI-Momentum")
        if not macd_ok: failed.append("MACD-Bestätigung")
        if not volume_ok: failed.append("Volumenbestätigung")
        reason = "Nicht alle Einstiegskriterien erfüllt: " + ", ".join(failed) + "."

    return {
        "market": market,
        "interval": interval,
        "status": "ok",
        "as_of_ms": last.timestamp_ms,
        "bars_available": len(closed),
        "last_close": last.close,
        "indicators": {
            "ema20": ema20,
            "ema50": ema50,
            "ema200": ema200,
            "rsi14": rsi14,
            "macd": macd_line,
            "macd_signal": macd_signal,
            "macd_histogram": macd_histogram,
            "volume_ratio_20": volume_ratio,
        },
        "recent_50_bar_range": {"low": recent_floor, "high": recent_ceiling},
        "checks": {
            "bullish_trend": bullish_trend,
            "rsi_momentum": momentum_ok,
            "macd_confirmation": macd_ok,
            "volume_confirmation": volume_ok,
            "exit_warning": exit_warning,
        },
        "signal": signal,
        "reason": reason,
        "mode": "read-only / paper trading only",
        "real_orders_enabled": False,
        "leverage_enabled": False,
    }


def build_position_plan(
    entry_price: Any,
    stop_price: Any,
    equity_eur: Any = DEFAULT_STARTING_CASH,
    risk_budget_eur: Any = DEFAULT_RISK_BUDGET,
    fee_rate: Any = DEFAULT_FEE_RATE,
    reward_risk_ratio: Any = Decimal("2.0"),
    available_cash_eur: Optional[Any] = None,
) -> PositionPlan:
    """Calculate a long-only spot size, including estimated entry and exit fees."""
    entry = _decimal(entry_price, "entry_price")
    stop = _decimal(stop_price, "stop_price")
    equity = _decimal(equity_eur, "equity_eur")
    risk = _decimal(risk_budget_eur, "risk_budget_eur")
    fee = _decimal(fee_rate, "fee_rate")
    rr = _decimal(reward_risk_ratio, "reward_risk_ratio")
    cash = equity if available_cash_eur is None else _decimal(available_cash_eur, "available_cash_eur")

    if entry <= 0 or stop <= 0 or stop >= entry:
        raise ValueError("Für einen Long-Spot-Plan muss 0 < Stop-Loss < Einstieg gelten.")
    if equity <= 0 or cash <= 0 or risk <= 0 or risk > equity:
        raise ValueError("Kapital und Risikobudget müssen positiv sein; Risiko darf Kapital nicht überschreiten.")
    if fee < 0 or fee >= Decimal("0.1"):
        raise ValueError("Gebührensatz muss zwischen 0 und 10 % je Seite liegen.")
    if rr <= 0:
        raise ValueError("Chance-Risiko-Verhältnis muss positiv sein.")

    # Planned loss includes price movement plus both-side fees.
    loss_per_unit = (entry - stop) + (entry * fee) + (stop * fee)
    quantity_by_risk = risk / loss_per_unit
    quantity_by_cash = cash / (entry * (Decimal("1") + fee))
    quantity = min(quantity_by_risk, quantity_by_cash).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
    if quantity <= 0:
        raise ValueError("Mit dem verfügbaren Kapital ist keine positive Positionsgröße möglich.")

    target = entry + ((entry - stop) * rr)
    notional = quantity * entry
    entry_fee = notional * fee
    exit_fee = quantity * stop * fee
    estimated_loss = quantity * loss_per_unit
    return PositionPlan(
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        quantity=quantity,
        notional_eur=notional,
        entry_fee_eur=entry_fee,
        estimated_exit_fee_eur=exit_fee,
        estimated_loss_eur=estimated_loss,
        risk_budget_eur=risk,
    )


class PaperTrader:
    """In-memory paper portfolio. No network, API keys, or exchange orders."""

    def __init__(self, starting_cash_eur: Any = DEFAULT_STARTING_CASH, fee_rate: Any = DEFAULT_FEE_RATE):
        self.cash_eur = _decimal(starting_cash_eur, "starting_cash_eur")
        self.starting_cash_eur = self.cash_eur
        self.fee_rate = _decimal(fee_rate, "fee_rate")
        if self.cash_eur <= 0:
            raise ValueError("Startkapital muss positiv sein.")
        if self.fee_rate < 0 or self.fee_rate >= Decimal("0.1"):
            raise ValueError("Gebührensatz muss zwischen 0 und 10 % je Seite liegen.")
        self.position: Optional[PaperPosition] = None
        self.closed_trades: list[ClosedTrade] = []
        self.realized_pnl_eur = Decimal("0")

    def open_long(
        self,
        market: str,
        entry_price: Any,
        stop_price: Any,
        risk_budget_eur: Any = DEFAULT_RISK_BUDGET,
        reward_risk_ratio: Any = Decimal("2.0"),
        timestamp_ms: Optional[int] = None,
    ) -> PositionPlan:
        if self.position is not None:
            raise ValueError("Es ist bereits eine Paper-Position offen.")
        plan = build_position_plan(
            entry_price=entry_price,
            stop_price=stop_price,
            equity_eur=self.cash_eur,
            risk_budget_eur=risk_budget_eur,
            fee_rate=self.fee_rate,
            reward_risk_ratio=reward_risk_ratio,
            available_cash_eur=self.cash_eur,
        )
        debit = plan.notional_eur + plan.entry_fee_eur
        if debit > self.cash_eur:
            raise ValueError("Nicht genügend Paper-Cash inklusive Einstiegsgebühr.")
        self.cash_eur -= debit
        self.position = PaperPosition(
            market=market,
            entry_price=plan.entry_price,
            stop_price=plan.stop_price,
            target_price=plan.target_price,
            quantity=plan.quantity,
            entry_fee_eur=plan.entry_fee_eur,
            opened_at_ms=int(time.time() * 1000) if timestamp_ms is None else int(timestamp_ms),
        )
        return plan

    def mark_to_market(self, mark_price: Any) -> dict[str, Decimal]:
        price = _decimal(mark_price, "mark_price")
        if price <= 0:
            raise ValueError("Marktpreis muss positiv sein.")
        market_value = Decimal("0")
        estimated_exit_fee = Decimal("0")
        unrealized_net = Decimal("0")
        if self.position is not None:
            market_value = self.position.quantity * price
            estimated_exit_fee = market_value * self.fee_rate
            unrealized_net = (
                self.position.quantity * (price - self.position.entry_price)
                - self.position.entry_fee_eur
                - estimated_exit_fee
            )
        equity = self.cash_eur + market_value - estimated_exit_fee
        return {
            "cash_eur": self.cash_eur,
            "market_value_eur": market_value,
            "estimated_exit_fee_eur": estimated_exit_fee,
            "unrealized_net_pnl_eur": unrealized_net,
            "realized_pnl_eur": self.realized_pnl_eur,
            "equity_eur": equity,
        }

    def close_position(self, exit_price: Any, timestamp_ms: Optional[int] = None) -> ClosedTrade:
        if self.position is None:
            raise ValueError("Keine offene Paper-Position vorhanden.")
        price = _decimal(exit_price, "exit_price")
        if price <= 0:
            raise ValueError("Ausstiegspreis muss positiv sein.")
        position = self.position
        gross_proceeds = position.quantity * price
        exit_fee = gross_proceeds * self.fee_rate
        self.cash_eur += gross_proceeds - exit_fee
        gross_pnl = position.quantity * (price - position.entry_price)
        net_pnl = gross_pnl - position.entry_fee_eur - exit_fee
        trade = ClosedTrade(
            market=position.market,
            entry_price=position.entry_price,
            exit_price=price,
            quantity=position.quantity,
            entry_fee_eur=position.entry_fee_eur,
            exit_fee_eur=exit_fee,
            gross_pnl_eur=gross_pnl,
            net_pnl_eur=net_pnl,
            closed_at_ms=int(time.time() * 1000) if timestamp_ms is None else int(timestamp_ms),
        )
        self.closed_trades.append(trade)
        self.realized_pnl_eur += net_pnl
        self.position = None
        return trade

    def evaluate_exit(self, mark_price: Any, timestamp_ms: Optional[int] = None) -> Optional[ClosedTrade]:
        """Close a simulated long if the supplied price reaches stop or target.

        This is a paper-only check on a supplied market price; it does not monitor
        the market in the background and does not model slippage or price gaps.
        """
        if self.position is None:
            return None
        price = _decimal(mark_price, "mark_price")
        if price <= 0:
            raise ValueError("Marktpreis muss positiv sein.")
        if price <= self.position.stop_price or price >= self.position.target_price:
            return self.close_position(price, timestamp_ms=timestamp_ms)
        return None

    def performance_summary(self) -> dict[str, Any]:
        trade_count = len(self.closed_trades)
        wins = [t for t in self.closed_trades if t.net_pnl_eur > 0]
        losses = [t for t in self.closed_trades if t.net_pnl_eur < 0]
        gross_wins = sum((t.net_pnl_eur for t in wins), Decimal("0"))
        gross_losses = -sum((t.net_pnl_eur for t in losses), Decimal("0"))
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else None
        cumulative = self.starting_cash_eur
        peak = cumulative
        max_drawdown = Decimal("0")
        for trade in self.closed_trades:
            cumulative += trade.net_pnl_eur
            peak = max(peak, cumulative)
            max_drawdown = max(max_drawdown, peak - cumulative)
        total_fees = sum(
            (t.entry_fee_eur + t.exit_fee_eur for t in self.closed_trades),
            Decimal("0"),
        )
        return {
            "starting_cash_eur": self.starting_cash_eur,
            "cash_eur": self.cash_eur,
            "realized_pnl_eur": self.realized_pnl_eur,
            "return_pct": (self.realized_pnl_eur / self.starting_cash_eur * Decimal("100")),
            "closed_trade_count": trade_count,
            "win_rate_pct": (Decimal(len(wins)) / Decimal(trade_count) * Decimal("100")) if trade_count else None,
            "profit_factor": profit_factor,
            "total_fees_eur": total_fees,
            "max_drawdown_eur": max_drawdown,
            "max_drawdown_pct_of_peak": (max_drawdown / peak * Decimal("100")) if peak > 0 else Decimal("0"),
            "mode": "paper trading only",
            "real_orders_enabled": False,
            "leverage_enabled": False,
        }

    def snapshot(self, mark_price: Optional[Any] = None) -> dict[str, Any]:
        if self.position is not None and mark_price is None:
            raise ValueError("Für eine offene Position muss ein Markpreis angegeben werden.")
        if mark_price is None:
            equity = self.cash_eur
            unrealized = Decimal("0")
        else:
            marked = self.mark_to_market(mark_price)
            equity = marked["equity_eur"]
            unrealized = marked["unrealized_net_pnl_eur"]
        return {
            "cash_eur": self.cash_eur,
            "equity_eur": equity,
            "realized_pnl_eur": self.realized_pnl_eur,
            "unrealized_net_pnl_eur": unrealized,
            "open_position": asdict(self.position) if self.position else None,
            "closed_trade_count": len(self.closed_trades),
            "mode": "paper trading only",
            "real_orders_enabled": False,
            "leverage_enabled": False,
        }

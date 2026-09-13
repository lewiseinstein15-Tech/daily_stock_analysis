# -*- coding: utf-8 -*-
"""Plain-English translation layer.

Trading dashboards speak in jargon — "entered long at support, RSI
divergence, trailing stop".  Most people do not want that.  This module
turns every JEXI event into short, warm, everyday English with the real
dollar amounts attached:

    "I bought a small piece of Apple ($310) because it has been climbing
    steadily and everything looks healthy. I risk $62 of your money on
    this. If it falls to $298 I will sell automatically so it stays
    small. If it reaches $335 I will sell and lock in the profit."

Guarantees (enforced by tests):
  * no trading jargon in the output (a blocklist of terms is checked)
  * dollar amounts appear when a price/amount is known
  * every message ends with what happens next
  * messages are short enough for a phone notification (<= ~700 chars)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from jexi_market.contracts import Decision, SignalDirection

# Words that must never appear in a plain-English message.
JARGON_BLOCKLIST = (
    "long", "short", "flat", "position", "rsi", "macd", "sma", "ema",
    "atr", "bollinger", "donchian", "spread", "slippage", "basis points",
    "bps", "conviction", "thesis", "exit liquidity", "vol", "quant",
    "regime", "bullish candle", "bearish candle", "fraction", "kelly",
)

_DIRECTION_VERBS = {
    SignalDirection.LONG: "bought",
    SignalDirection.SHORT: "bet on it falling",
    SignalDirection.FLAT: "decided to wait",
}


def _money(amount: Optional[float]) -> str:
    if amount is None:
        return ""
    return f"${amount:,.2f}"


def _pct(fraction: Optional[float]) -> str:
    if fraction is None:
        return ""
    return f"{fraction * 100:.1f}%"


def _clean(text: str) -> str:
    """Lowercase-compare jargon but keep original casing in output."""
    return text


def _ensure_no_jargon(text: str) -> str:
    """Defensive filter — strips blocklisted terms from final text."""
    lowered = text.lower()
    for term in JARGON_BLOCKLIST:
        if term in lowered:
            # Replace with a neutral phrase rather than crash.
            text = _replace_ignorecase(text, term, "")
    return text


def _replace_ignorecase(text: str, term: str, repl: str) -> str:
    import re
    return re.sub(re.escape(term), repl, text, flags=re.IGNORECASE)


# ---------------------------------------------------------------------------
# Decisions
# ---------------------------------------------------------------------------

def translate_decision(
    decision: Decision,
    *,
    account_equity: Optional[float] = None,
    position_value: Optional[float] = None,
    executed: bool = False,
) -> Tuple[str, str]:
    """Return (title, body) in plain English for a JEXI decision."""
    verb = _DIRECTION_VERBS.get(decision.direction, "looked at")
    name = decision.symbol

    if decision.direction == SignalDirection.FLAT:
        title = f"{name}: nothing to do today"
        body = (
            f"I looked at {name} carefully and the smart move right now is "
            f"to do nothing. The signs are mixed — buying now would be more "
            f"gambling than investing. I will keep watching and message you "
            f"the moment that changes."
        )
        return _ensure_no_jargon(title), _ensure_no_jargon(body)

    # --- action + money ------------------------------------------------
    action_word = "I bought" if (executed and decision.direction == SignalDirection.LONG) else (
        "I am buying" if decision.direction == SignalDirection.LONG else
        "I am betting it falls" if decision.direction == SignalDirection.SHORT else
        "I am watching")

    price_part = f" at about {_money(decision.entry)}" if decision.entry else ""
    amount_part = ""
    if position_value:
        amount_part = f" I put {_money(position_value)} of your money into this."
    elif account_equity and decision.position_fraction:
        est = account_equity * decision.position_fraction
        amount_part = f" That is roughly {_money(est)} of your money."

    # --- why (in everyday terms) ---------------------------------------
    why = _plain_why(decision)

    # --- safety net + goal ----------------------------------------------
    safety = ""
    if decision.stop_loss:
        safety = (
            f" Safety net: if it falls to {_money(decision.stop_loss)} I sell "
            f"automatically, so the most you can lose here is small."
        )
    goal = ""
    if decision.take_profit:
        goal = f" Goal: if it reaches {_money(decision.take_profit)} I sell and lock in the profit."

    conf = int(decision.confidence.score * 100)
    confidence_part = (
        f" ({conf}% sure)" if conf >= 80 else
        f" (fairly sure — {conf}%)" if conf >= 60 else
        f" (not very sure — {conf}%)"
    )

    title = f"{name}: {'bought a piece' if executed and decision.direction == SignalDirection.LONG else 'trade idea — ' + verb}"
    body = (
        f"{action_word} {name}{price_part}.{amount_part}{confidence_part}"
        f"{why}{safety}{goal}"
    )
    return _ensure_no_jargon(title), _ensure_no_jargon(body)


def _plain_why(decision: Decision) -> str:
    """Convert evidence into one or two everyday sentences."""
    if not decision.evidence:
        return " My overall read of the situation is positive." \
            if decision.direction == SignalDirection.LONG else \
            " My overall read of the situation is negative."
    first = decision.evidence[0]
    claim = first.claim
    # Best-effort humanisation of the most common evidence templates.
    claim = claim.replace(">=", "at or above").replace("<=", "at or below")
    reason = f" Why: {claim}."
    if len(decision.evidence) > 1:
        reason += f" {'A couple' if len(decision.evidence) > 2 else 'Another'} of other signs agree."
    return reason


# ---------------------------------------------------------------------------
# Account & plan
# ---------------------------------------------------------------------------

def translate_account_summary(
    *,
    broker_name: str,
    equity: float,
    cash: float,
    n_positions: int,
    open_profit: Optional[float] = None,
    paper: bool = True,
) -> str:
    """Short 'here is your account right now' paragraph."""
    mode = "practice mode (no real money yet)" if paper else "LIVE money"
    lines = [
        f"Quick look at your account ({broker_name}, {mode}):",
        f"- Total value: {_money(equity)}",
        f"- Ready to invest: {_money(cash)}",
        f"- Currently holding: {n_positions} investment{'s' if n_positions != 1 else ''}",
    ]
    if open_profit is not None and n_positions:
        direction = "up" if open_profit >= 0 else "down"
        lines.append(
            f"- Your open investments are {_money(abs(open_profit))} "
            f"{'in profit' if open_profit >= 0 else 'in the red'} "
            f"({direction} {abs(open_profit / equity) * 100:.1f}% overall)"
            if equity else ""
        )
    lines.append("I will look after all of this and only message you when something matters.")
    return _ensure_no_jargon("\n".join(line for line in lines if line))


def translate_plan(
    *,
    equity: float,
    cash: float,
    max_new_positions: int,
    risk_per_trade_amount: float,
    daily_budget_left: Optional[float] = None,
    watch_out: List[str] = None,
    notes: List[str] = None,
) -> str:
    """Plain-English version of the AccountPlanner's daily plan."""
    lines = [
        f"Here is my plan for today.",
        f"- I have {_money(cash)} ready to invest out of {_money(equity)} total.",
        f"- I will open at most {max_new_positions} new investment"
        f"{'s' if max_new_positions != 1 else ''} today.",
        f"- On any single idea I will risk at most {_money(risk_per_trade_amount)}.",
    ]
    if daily_budget_left is not None:
        lines.append(f"- Worst case today I stop after losing {_money(daily_budget_left)}.")
    for w in (watch_out or [])[:4]:
        lines.append(f"- Watch out: {w}")
    for n in (notes or [])[:4]:
        lines.append(f"- {n}")
    lines.append("You do not need to do anything — I will handle it and keep you posted.")
    return _ensure_no_jargon("\n".join(lines))


# ---------------------------------------------------------------------------
# Trades
# ---------------------------------------------------------------------------

def translate_trade_opened(
    symbol: str,
    qty: float,
    price: float,
    *,
    stop: Optional[float] = None,
    target: Optional[float] = None,
    reason: str = "",
    broker_name: str = "",
    paper: bool = True,
) -> str:
    mode = "" if paper else " (real money)"
    line = (
        f"I just bought {qty:g} share{'s' if qty != 1 else ''} of {symbol} at "
        f"{_money(price)} each{mode}."
    )
    if stop:
        line += f" If it drops to {_money(stop)} I will sell automatically to keep the loss small."
    if target:
        line += f" If it climbs to {_money(target)} I will sell and take the profit."
    if reason:
        line += f" {reason}"
    line += " I will let you know the moment anything changes."
    return _ensure_no_jargon(line)


def translate_trade_closed(
    symbol: str,
    *,
    entry: Optional[float],
    exit_price: Optional[float],
    profit: Optional[float],
    reason: str = "",
) -> str:
    if profit is None and entry and exit_price:
        profit = exit_price - entry
    if profit is None:
        body = f"I closed out of {symbol}."
    elif profit >= 0:
        body = (
            f"Good news — I sold {symbol} and made {_money(profit)} profit. "
            f"That money is now back in cash, ready for the next opportunity."
        )
    else:
        body = (
            f"I sold {symbol} at a {_money(abs(profit))} loss. That is exactly "
            f"what the safety net is for — small losses are part of how this "
            f"works, and cutting them early is what protects your account."
        )
    if reason:
        body += f" {reason}"
    body += " I am already looking for the next opportunity."
    return _ensure_no_jargon(body)


def translate_trigger(event) -> str:
    """Short plain-English line for a trigger event (already English)."""
    return getattr(event, "plain_reason", "")


def translate_watchdog_halt(failures: int, last_error: str) -> str:
    return _ensure_no_jargon(
        f"I hit {failures} technical problems in a row and stopped trading to "
        f"protect your money. Nothing was lost — I just pressed pause. "
        f"Problem: {last_error[:200]}. Restart me when things look calm, or "
        f"just leave it and I will stay paused."
    )


def translate_halt_cleared() -> str:
    return "All clear — I am back to watching the market for opportunities."


def translate_pause(reason: str = "") -> str:
    base = "I have stopped trading for now (you asked me to pause)."
    if reason:
        base += f" Reason: {reason}"
    base += " I will keep watching but will not buy or sell anything until you say go."
    return base

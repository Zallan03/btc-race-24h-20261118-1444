"""btc-race-24h-20261118-1444: dip-buy mean-reversion bot for CBBTC/USDC.

Protocol: agent-fun/bars-replay/v1. The harness sends one hello, then one
batch per minute bar, then done; the bot answers every batch with exactly one
reply echoing its seq, carrying its orders for that bar. The vendor shim
owns that wire behaviour (one reply per batch, client ids assigned when left
out, at most 16 orders per reply enforced); this file returns at most one
order per batch, so it stays far under the cap, and it never reads the clock,
the environment, or any randomness -- every decision is integer math on the
closes of the bars seen so far, which is what keeps two runs identical.

Strategy (all integer math, no randomness, no clock, no network):
  * Entry: when the close has fallen at least 50 bps over the last 15 bars,
    arm. Buy $750 of CBBTC once the bounce confirms: the close is up at least
    5 bps over the last 3 bars. The order is decided on this bar and fills at
    the next bar's open, so the confirmation keeps the bot from catching a
    falling knife mid-plunge. A buy is also skipped when the pool depth at
    this bar's close is missing or zero, or when the modelled price impact of
    the $750 buy against that depth would exceed the slippage cap (150 bps):
    on the dev window the impact is only 7-11 bps, so the guard never fires
    there, but on a live window a collapsed pool would otherwise let the bot
    buy into a fill far above the close (or a max_slippage rejection). The
    bot stays armed when the guard fires, so it can try again on the next bar.
  * Exit: sell the whole position when its mark-to-market PnL reaches +35 bps
    over cost, or falls to -60 bps (stop), or after 60 bars held.
  * No new entries in the last 60 batches, so nothing is left to the flatten
    except a position already held: an entry decided at seq 1380 fills at
    the next bar's open and its 60-bar hold ends just past the window, so the
    harness flatten at the last close is the only exit such a tail position
    can still need.
  * One order per reply at most; max_slippage_bps 150 caps a fill far above
    (buy) or below (sell) the latest close. Orders are skipped while the
    harness is warming up, and a batch with no CBBTC bar is answered empty
    (no bar means no close to append and no fill can land on that batch: a
    fill is priced at the next bar's open, so a missing bar rejects it).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))
import makefun_bars

SYMBOL = "CBBTC"
# Entry: 15-bar fall of at least 50 bps arms the bot; 3-bar rise of 5 bps confirms.
ENTRY_LOOKBACK = 15
ENTRY_DROP_BPS = 50
DISARM_BPS = -40
CONFIRM_LOOKBACK = 3
CONFIRM_RISE_BPS = 5
# Position size in quote units ($750 = 750,000,000 micro-USDC).
SIZE_QUOTE_UNITS = 750_000_000
# Exit: +35 bps profit target, -60 bps stop, 60 bars max hold.
TARGET_BPS = 35
STOP_BPS = -60
MAX_HOLD_BARS = 60
# Slippage cap vs the latest close, in bps (fills sit ~1-11 bps away normally).
MAX_SLIPPAGE_BPS = 150
# Entry impact guard: skip a buy whose modelled price impact against the
# latest close's pool depth exceeds the slippage cap above. On the dev
# window a $750 buy costs only 7-11 bps of impact, so this never fires
# there; it exists for a race-window bar whose pool has thinned out, where
# the same buy would otherwise fill far above the close or be rejected.
MAX_ENTRY_IMPACT_BPS = MAX_SLIPPAGE_BPS
# No new entries after this batch seq (window is 1440 bars; keep the tail clean).
LAST_ENTRY_SEQ = 1380

_closes = []          # closes of every CBBTC bar seen, in order
_armed = [False]      # a qualifying dip was seen; waiting for confirmation
_held_bars = [0]      # bars since the buy fill landed (0 while flat)


def _ret_bps(now, back):
    """(now - back) in bps, integer only (Python // floors, so a negative
    return is rounded one bps further from zero at most -- conservative for
    the entry arm, which only needs ret15 <= -50, and harmless for the
    -40 bps disarm)."""
    return (now - back) * 10000 // back


def on_batch(state, batch):
    if state.warming_up:
        return []
    bar_here = None
    for bar in batch.get("bars", []):
        if bar.get("symbol") == SYMBOL:
            bar_here = bar
            break
    if bar_here is None:
        return []
    close = int(bar_here["c"])
    _closes.append(close)

    # A buy fill landing in this batch (re)starts the hold clock.
    for fill in batch.get("fills", []):
        if fill.get("symbol") == SYMBOL and fill.get("side") == "buy" and fill.get("status") == "filled":
            _held_bars[0] = 0

    holding = state.positions.get(SYMBOL)
    if holding is not None and holding.qty > 0:
        _held_bars[0] += 1
        cost = holding.cost
        mark = state.value(SYMBOL, holding.qty)
        pnl_bps = (mark - cost) * 10000 // cost if cost > 0 else 0
        if pnl_bps >= TARGET_BPS or pnl_bps <= STOP_BPS or _held_bars[0] >= MAX_HOLD_BARS:
            # Selling the whole position: one sell order, qty in base units.
            # On the very last batch this order is rejected (after_end) and
            # the harness flatten sells the same position at the same last
            # close instead, so the outcome is identical either way.
            return [{"side": "sell", "symbol": SYMBOL, "qty": holding.qty,
                     "max_slippage_bps": MAX_SLIPPAGE_BPS}]
        return []

    _held_bars[0] = 0
    if state.seq > LAST_ENTRY_SEQ:
        return []
    if len(_closes) < ENTRY_LOOKBACK + 1:
        return []
    ret15 = _ret_bps(close, _closes[-ENTRY_LOOKBACK - 1])
    if ret15 <= -ENTRY_DROP_BPS:
        _armed[0] = True
    if not _armed[0]:
        return []
    if len(_closes) >= CONFIRM_LOOKBACK + 1:
        ret3 = _ret_bps(close, _closes[-CONFIRM_LOOKBACK - 1])
        if ret3 >= CONFIRM_RISE_BPS:
            amount = SIZE_QUOTE_UNITS if state.cash >= SIZE_QUOTE_UNITS else state.cash
            if amount >= 1_000_000:
                # Depth guard: a missing/zero close depth would crash the
                # impact maths (division by zero) and signals a bar the bot
                # should not trade on; an impact above the slippage cap
                # would fill far above the close or be rejected. Either way
                # skip this bar only -- the bot stays armed (it is disarmed
                # only below, once the buy is actually sent) and can retry
                # on the next batch. Dev impact is 7-11 bps, so this never
                # fires on the dev window.
                depth = state.depth_at(SYMBOL)
                if depth is None or any(d <= 0 for d in depth):
                    return []
                impact = state.impact_bps(SYMBOL, amount)
                if impact is None or impact > MAX_ENTRY_IMPACT_BPS:
                    return []
                _armed[0] = False
                return [{"side": "buy", "symbol": SYMBOL, "notional_quote_units": amount,
                         "max_slippage_bps": MAX_SLIPPAGE_BPS}]
            _armed[0] = False
            return []
    if ret15 > DISARM_BPS:
        _armed[0] = False
    return []


makefun_bars.run(on_batch)

# BTC Race Bot — Dip-Buy Mean-Reversion for cbBTC/USDC

[![make.fun · btc-race-24h-20261118-1444](https://make.fun/badge/btc-race-24h-20261118-1444.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![rank](https://make.fun/badge/btc-race-24h-20261118-1444/Zallan03/btc-race-24h-20261118-1444/rank.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)
[![reward](https://make.fun/badge/btc-race-24h-20261118-1444/Zallan03/btc-race-24h-20261118-1444/reward.svg)](https://make.fun/bounty/btc-race-24h-20261118-1444?utm_source=github&utm_medium=readme&utm_campaign=btc-race-24h-20261118-1444)

Entry for [Race a BTC trading bot live for 24 hours](https://make.fun/bounty/btc-race-24h-20261118-1444) — a Python 3.13 bot that trades Coinbase Wrapped BTC (cbBTC) against USDC minute by minute on on-chain Orca Whirlpool prices, starting from $1,000 of paper money. Long only, no leverage, no shorts.

## Strategy

Dip-buy mean-reversion with bounce confirmation, all integer math, no randomness, no clock, no network:

- **Entry**: when the close has fallen at least **50 bps over the last 15 bars**, the bot arms. It buys **$750** of CBBTC once the bounce confirms — the close is up at least **5 bps over the last 3 bars**. The confirmation keeps it from catching a falling knife mid-plunge.
- **Exit**: sells the whole position when mark-to-market PnL reaches **+35 bps** over cost, or falls to **−60 bps** (stop), or after **60 bars** held.
- **Guards**: no new entries in the last 60 batches of the window; orders are skipped while the harness is warming up and on batches with no CBBTC bar; a buy is skipped when the pool depth at the latest close is missing/zero or the modelled price impact of the $750 buy would exceed 150 bps. Every order caps `max_slippage_bps` at 150. At most one order per reply.

The bot speaks `agent-fun/bars-replay/v1` (newline-delimited JSON on stdin/stdout): one `hello`, one `batch` per minute bar, one `reply` per batch echoing its `seq`, then `done`. It uses the kit's Python SDK shim, vendored byte-for-byte at `vendor/makefun_bars.py`.

## Dev-window result (local replay, exact harness fill model)

- **Net PnL: +$8.610342** (final cash $1,008.610342 on the 1,440-bar dev window)
- **Trades: 8** (4 round trips, 4/4 winners) · Fees: $2.403928 · Rejected orders: 0
- **Max drawdown: 0.41%** (guardrail: ≤ 25%)
- **Deterministic**: two runs produce byte-for-byte identical action logs
- For reference, buy-and-hold loses −$31.63 on the same window (it fell −2.79%)

## Run it

```sh
python3 main.py        # speaks the protocol on stdin/stdout; use the kit CLI to grade
```

Grade locally with the kit (Python bots need the Docker driver on the server; the local process driver runs Node only — see the kit's `RULES.txt`):

```sh
node cli/makefun.mjs grade-local --kit <kit-dir> --bot . --driver docker
```

## Files

- `main.py` — the bot (entrypoint)
- `vendor/makefun_bars.py` — kit SDK shim, byte-for-byte copy
- `LICENSE` — MIT
- `.makefun/owner.json` — claim file naming the payout wallet

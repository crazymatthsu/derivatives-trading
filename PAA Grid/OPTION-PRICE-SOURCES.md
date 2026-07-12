# Where Does the "Current Price" Come From? — Option Price Sources on a Sell-Side Desk

A design note answering: *for vanilla equity options on a sell-side firm,
does the current price come from a vendor (Activ, Bloomberg,
Reuters/Refinitiv) or is it calculated internally by the quant team — and
what are the official names of these prices?*

**Short answer: both — in a specific division of labor. Vendors give you the
underlying spot and the option quotes; your quant team gives you the price
you actually risk-manage on.**

## 1. Vendor / exchange prices (market-observable)

For US listed options, all quotes and trades flow through **OPRA** (Options
Price Reporting Authority) — the consolidated tape. Activ Financial,
Bloomberg (B-PIPE), and Refinitiv/LSEG (Elektron, formerly Reuters) are
redistributors of that same OPRA data, plus direct exchange feeds if you are
latency-sensitive. The named prices you get from them:

- **NBBO** (National Best Bid and Offer) — the consolidated best bid/ask
- **Last** (last trade price) — official but often stale for options; many
  strikes do not trade for hours
- **Mid / quote midpoint** — (bid + ask) / 2, the most common "current
  market price" proxy
- **Underlying spot** — the stock's consolidated last/mid, which is a
  *pricing input*, not the option price

The problem: listed option quotes are wide, stale on illiquid strikes, and
mutually inconsistent across the chain (mids can violate no-arbitrage). So
nobody scales a risk system directly off raw option mids.

## 2. Internal model prices (the quant team) — this is `CurrPrice`

The standard sell-side architecture: the quant/strats team **calibrates a
volatility surface** to the vendor quotes (fitting to NBBO mids of liquid
strikes, arbitrage-free smoothing across strikes and expiries — SVI-style
parameterizations are typical), and then *every* option, liquid or not, is
priced off that fitted surface. The official names for this price:

- **Theoretical price / "theo"** — the universal desk term
- **Model price / fair value** — same thing in more formal contexts
- **Mark / MTM mark** — once it is the number used for P&L

This is what feeds risk, intraday P&L, and PAA. It is smooth, consistent
across the whole chain, and updates continuously as spot ticks even when
quotes do not. In this project's engine
([02_paa_engine.py](deephaven-paa/02_paa_engine.py)),
`CurrPrice = bs_price(Spot, …, live vol)` is exactly this — a theo off a
marked surface; the `vol_live` table stands in for the quant team's fitted
surface.

## 3. End-of-day official prices — this is `PrevPrice`

For books and records, the anchor is the **exchange settlement price** (for
US equity options, the closing marks disseminated via OPRA/OCC; for index
options, exchange-published settlements). Desks typically use either the
settlement directly or an **EOD mark** off the end-of-day calibrated
surface, reconciled to settlements. Related official terms:

- **Settlement price / official closing price** — exchange-published
- **EOD mark / official mark / books-and-records mark** — what product
  control signs off
- **IPV** (Independent Price Verification) — product control's daily/monthly
  check of desk marks against vendor consensus; for OTC derivatives the
  consensus service is **Totem** (S&P Global / IHS Markit)

## Mapping to the PAA engine

| Engine column | Production source | Official name |
|---|---|---|
| `Spot` / `PrevSpot` | Vendor feed (Activ / B-PIPE / Elektron) | Underlying last/mid; official close |
| `vol_live` / `vol_prev` | Quant team's fitted surface (calibrated to OPRA quotes) | Marked vol surface |
| `CurrPrice` | Internal quant library off the live surface | Theoretical price ("theo") |
| `PrevPrice` | Exchange settlement or EOD surface mark | Settlement / official EOD mark |

Note that `PrevPrice` is the T-1 closing mark **of the option itself** —
not the underlying's close. The underlying's T-1 close is `PrevSpot`, an
*input* to the option mark. `ActualPnl = SODQty × Mult × (CurrPrice −
PrevPrice)` is the change in the option's value; the underlying's move
`DSpot = Spot − PrevSpot` produces option P&L only *through* the Greeks,
which is exactly what the attribution decomposes.

## The key discipline

`PrevPrice` must be the *official* T-1 mark, and `CurrPrice` must come from
the *same pricing model* that generated it (with updated inputs). If the
intraday theo model and the EOD marking model disagree, that disagreement
lands in unexplained P&L every morning — which is why the quant team owns
both, and why `vol_prev` should be the vol that reprices the official close
exactly.

## Related docs

- [PAA.md](PAA.md) — PAA methodology (Taylor explain, step reval, source data)
- [PAA-GRID.md](PAA-GRID.md) — PAA Grid formulas, tables, and conventions
- [RISK-GRID-VS-PAA-GRID.md](RISK-GRID-VS-PAA-GRID.md) — Risk Grid vs PAA Grid
- [TRADE-PNL-VS-COST-PNL.md](TRADE-PNL-VS-COST-PNL.md) — why trade P&L is marked from exec price
- [SOD-VS-LIVE-POSITION.md](SOD-VS-LIVE-POSITION.md) — which position snapshot each calculation uses
- [README.md](README.md) — project index, run order, data classification

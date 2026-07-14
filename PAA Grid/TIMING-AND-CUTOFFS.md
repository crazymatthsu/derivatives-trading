# Timing and Cut-offs — Snapshot Time vs Run Time vs Trade Time

A design note answering two related questions:

1. *Does the spot price used in risk/PAA need to be from the same time as
   the option price calculation, or is it the spot at the moment the P&L
   calculation runs?*
2. *If the snapshot is 30 minutes old and positions kept changing since,
   is that a problem?*

**Short answers:** (1) the spot must be from the same snapshot that priced
the options — the calculation's wall-clock run time is irrelevant; the
numbers are "as-of" the snapshot, not "as-of" the run. (2) Position churn
is mostly harmless: attribution is immune (SOD anchor), trade P&L needs a
cut-off aligned to the snapshot, and risk should take position updates in
real time without waiting for the next market snapshot.

---

## Part 1 — PAA is a function of two snapshots, not of "now"

Everything in the attribution is defined by two coherent market states:

- **T-1 close snapshot** → produced `PrevPrice` (and the Greeks)
- **T valuation snapshot** → produced `CurrPrice`

`DSpot` in `DeltaPnl = PosScale × Δ × DSpot` must be
`SpotUsed(T) − SpotUsed(T-1)` — the spots *inside those snapshots*, because
those generated the option price change being explained. Whether the P&L
batch runs at 16:05, 18:30, or 2am is invisible in the output: PAA is a
pure function of the snapshots, so running it later with the same inputs
gives identical numbers.

**Failure mode of "spot when the calculation happened":** marks generated
at 16:00:00 with spot 215.60; the P&L job runs at 16:00:45 and re-reads the
spot feed, getting 215.72. The left side of the attribution
(`CurrPrice − PrevPrice`) reflects a 215.60 world while the delta term uses
a 215.72 move — the 12-cent gap times delta lands in unexplained as pure
artifact (≈ 0.51 × 0.12 × 15,000 ≈ $920 of phantom residual on the traced
AAPL position). This is the asynchronous-ticks case of
[SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md): the valuation feed
publishes `(Mark, SpotUsed, SnapTime)` as one row, and the P&L job consumes
`SpotUsed` — never re-fetches.

**What "current" means:** the reported P&L is as-of the snapshot's
`SnapTime`, not the job's run time. A "live" PAA is just this done
frequently — each new coherent snapshot produces a new attribution. In the
Deephaven engine this is automatic: `CurrPrice` and `DSpot` derive from the
same `spot_live` row and update in the same graph cycle, so pricing time
and calculation time coincide tick by tick. The danger only exists in
architectures where marks and spot arrive on separate feeds and a batch
stitches them together.

**Risk: same rule, different sensitivity to staleness.**

- PAA cares about **coherence, not freshness**: a PAA on a 30-minute-old
  coherent snapshot is valid — it is the attribution as of 30 minutes ago;
  unexplained stays clean.
- Risk cares about **freshness too**: a 30-minute-old delta is internally
  consistent but describes a book the market has moved away from; acting
  on it mis-hedges by roughly gamma × the stale move. Live risk wants the
  most recent coherent snapshot, with `SnapTime` displayed so traders know
  its age.

---

## Part 2 — Position churn during a stale snapshot

The three consumers of position data have different sensitivities:

### PAA market-move attribution: immune by construction

The delta/gamma/vega/… terms scale by **SODQty, frozen all day** — that is
the point of the SOD anchor
([SOD-VS-LIVE-POSITION.md](SOD-VS-LIVE-POSITION.md)). Fills at 15:50 or
16:09 change nothing in those lines; a 30-minute-old snapshot just means
the attribution is "as of 15:45". No staleness interaction at all.

### PAA trade P&L: needs a trade cut-off aligned to the snapshot

`NewTradePnl = TradedQty × CurrPrice − TradedCost` marks fills against the
snapshot's `CurrPrice`. Including a fill executed *after* the snapshot
means marking a trade against a price from before it existed — market
drift between snap and fill shows up as fake execution edge or loss.

**The rule: a P&L as-of `T_snap` includes only executions with
`exec_time ≤ T_snap`.** The report has two clocks — market snapshot time
and trade cut-off — and they must be the same instant. Fills after the cut
belong to the next snapshot's P&L; nothing is lost, only correctly timed.

Production wrinkle: trades *booked late* (executed before the cut, entered
after) cannot retroactively change a signed report — they appear as a
"late trades / prior-day adjustment" line on the next report rather than a
restatement.

Note the asymmetry: a wrong spot corrupts **unexplained** (poisoning the
quality signal); a sloppy trade cut only mis-times **NewTradePnl** and
self-corrects at the next snapshot. Bad, but diagnosable and bounded.

### Risk: position updates should NOT wait for the market snapshot

Position is a **linear multiplier** on per-option Greeks — incorporating a
fill requires no pricing call: `PosDelta = CurrentQty × Δ` just needs the
new quantity. So live risk updates its two inputs on their natural
cadences:

- **Quantities: tick-by-tick.** Every fill flows immediately into
  `CurrentQty = SODQty + Σ fills`, against the latest available Greeks.
- **Greeks: on snapshot cadence.** Refreshed when the pricing service
  re-runs (seconds to minutes).

Fresh positions + 30-minute-old Greeks = positionally exact, only
market-stale (residual error ≈ gamma × untracked spot move — refresh
Greeks faster on gamma-heavy books). The reverse — fresh Greeks + stale
positions — is far more dangerous: the desk that bought 500
delta-equivalent ten minutes ago and doesn't see it is unhedged without
knowing. Deephaven gets this right by construction: `executions` is a live
table, so a position-aware risk grid re-aggregates on every fill within the
same update cycle, independently of when `spot_live` last ticked.

---

## Summary table

| Consumer | Position input | Market input | Staleness rule |
|---|---|---|---|
| PAA market-move terms | SODQty (frozen) | Two coherent snapshots (T-1 close, T snap) | Coherence only — age is just the "as-of" label |
| PAA trade P&L | Fills with `exec_time ≤ T_snap` | Same T snapshot | Trade cut-off = snapshot time; late bookings → adjustment line |
| Risk grid / hedging | Live `CurrentQty = SOD + fills`, tick-by-tick | Latest coherent snapshot | Positions never wait for market; Greeks as fresh as possible; show `SnapTime` |

**One-line discipline:** every report carries two timestamps — market
`SnapTime` and trade cut-off — kept equal; the calculator's wall clock
appears nowhere.

## Related docs

- [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md) — attribution inputs must equal mark-time inputs
- [SOD-VS-LIVE-POSITION.md](SOD-VS-LIVE-POSITION.md) — which position snapshot each calculation anchors on
- [TRADE-PNL-VS-COST-PNL.md](TRADE-PNL-VS-COST-PNL.md) — the NewTradePnl formula
- [GREEKS-OWNERSHIP.md](GREEKS-OWNERSHIP.md) — the EOD_OFFICIAL snapshot and published inputs
- [README.md](README.md) — project index

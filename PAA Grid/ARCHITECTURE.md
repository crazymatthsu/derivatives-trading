# Architecture — Teams, Data Sources, and Calculation Placement

Which teams provide which data sources, and where each calculation takes
place, to produce the PAA Grid and the Risk Grid.

## Diagram

An editable draw.io version of this diagram is in
[architecture.drawio](architecture.drawio) — open it at
[app.diagrams.net](https://app.diagrams.net) or with the draw.io desktop app
/ VS Code extension.

```mermaid
flowchart TD
    subgraph TEAMS["Data-providing teams"]
        MDT["Market data tech<br/>(Activ / B-PIPE / Elektron, OPRA)"]
        QUANT["Quant / strats<br/>(vol surface, pricing model)"]
        RATES["Rates & dividends team<br/>(curves, div/borrow yields)"]
        DESK["Trading desk OMS/EMS<br/>(orders, executions)"]
        OPS["Operations / middle office<br/>(SOD positions, security master)"]
        PC["Product control<br/>(T-1 official marks / settlements)"]
    end

    subgraph SRC["Deephaven keyed source tables — 01_paa_source_tables.py"]
        T_SPOT["spot_prev / spot_live"]
        T_FX["fx_prev / fx_live"]
        T_VOL["vol_prev / vol_live"]
        T_RATE["rates_prev / rates_live"]
        T_DIV["div_prev / div_live"]
        T_ORD["orders"]
        T_EXE["executions"]
        T_POS["book_position"]
        T_INS["instrument"]
    end

    MDT --> T_SPOT
    MDT --> T_FX
    QUANT --> T_VOL
    RATES --> T_RATE
    RATES --> T_DIV
    DESK --> T_ORD
    DESK --> T_EXE
    OPS --> T_POS
    OPS --> T_INS
    PC -. "T-1 snapshot side of every market table" .-> SRC

    subgraph CALC["Calculation layer"]
        ENG["02_paa_engine.py<br/>BS marks + Greeks, Taylor attribution, trade P&L"]
        ROLL["03_paa_rollups.py<br/>aggregation, summary stats, 5% check"]
        RG["04_risk_grid.py<br/>Greeks × spot ladder"]
        PG["05_paa_grid.py<br/>attribution × spot ladder"]
    end

    SRC --> ENG
    ENG --> ROLL
    ENG --> RG
    ENG --> PG
    T_POS -.-> RG
    T_POS -.-> PG
    T_EXE -.-> ENG

    subgraph OUT["Consumers"]
        PCOUT["Product control<br/>P&L sign-off"]
        TRD["Traders<br/>hedging decisions"]
        RM["Risk management<br/>model validation"]
    end

    ROLL --> PCOUT
    RG --> TRD
    PG --> RM
```

## Who provides which source table

| Team | Owns | Feeds tables |
|---|---|---|
| Market data technology | Vendor connectivity (Activ / Bloomberg B-PIPE / Refinitiv Elektron over OPRA) | `spot_live`, `fx_live` |
| Quant / strats | Fitted vol surface, pricing model — and the mark-time inputs (see [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md)) | `vol_live` (marked surface) |
| Rates & dividends (treasury / equity forwards) | Discount curves, dividend & borrow forecasts | `rates_live`, `div_live` |
| Trading desk (OMS/EMS) | Order and execution flow | `orders`, `executions` |
| Operations / middle office | Overnight batch, SOD reconciliation, security master | `book_position` (reconciled SOD), `instrument` |
| Product control | Official T-1 close marks / settlements | the `*_prev` snapshot side of every market table — the anchor `PrevPrice` must reprice exactly |

## Where each calculation runs

The key placement decision: in the demo scripts, Black-Scholes pricing and
Greeks run *inside* [02_paa_engine.py](deephaven-paa/02_paa_engine.py) in
Deephaven. In production at a sell-side firm, that box splits in two:

1. **Quant pricing service** — computes marks and Greeks. It owns the model,
   must produce numbers consistent with the official EOD marks, and
   publishes each mark **with its inputs as one row**:
   `(Mark, SpotUsed, VolUsed, RateUsed, DivUsed, SnapTime)`.
2. **Deephaven engine** — does what it is structurally best at: keyed joins,
   the Taylor attribution arithmetic, trade P&L from executions, the ladder
   cross-joins for both grids, and incremental roll-ups — all ticking.

Output routing:

- **Roll-ups + unexplained-breach check (03)** → product control (P&L
  sign-off, attribution quality monitoring)
- **Risk Grid (04)** → traders (hedging: "what is my delta if spot gaps 5%")
- **PAA Grid (05)** → risk management (model validation — it audits the risk
  grid's Greeks; see [RISK-GRID-VS-PAA-GRID.md](RISK-GRID-VS-PAA-GRID.md))

## Simplifications in the diagram

- Scripts 04 and 05 also read `book_position`, `fx_live`, and (for a
  live-position variant) `executions` directly from the source layer, not
  only through 02 — shown as dashed edges; the main flow line keeps the
  picture readable.
- The `orders` table is audit/context only — P&L consumes `executions`
  (see [TRADE-PNL-VS-COST-PNL.md](TRADE-PNL-VS-COST-PNL.md)).

## Related docs

- [PAA.md](PAA.md) — PAA methodology
- [PAA-GRID.md](PAA-GRID.md) — PAA Grid formulas and tables
- [RISK-GRID-VS-PAA-GRID.md](RISK-GRID-VS-PAA-GRID.md) — how the two grids relate
- [SOD-VS-LIVE-POSITION.md](SOD-VS-LIVE-POSITION.md) — position anchoring per calculation
- [OPTION-PRICE-SOURCES.md](OPTION-PRICE-SOURCES.md) — vendor vs internal prices
- [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md) — matching attribution inputs to mark-time inputs
- [README.md](README.md) — project index

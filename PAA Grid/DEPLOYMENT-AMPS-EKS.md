# Deployment — Deephaven on AWS EKS with AMPS as the Data Store

Design note covering three infrastructure decisions:

1. **Deephaven on EKS**: run as a **stateless single-replica Deployment
   (strategy: Recreate)** — not a StatefulSet, not a multi-replica
   ReplicaSet.
2. **AMPS (60East) on EC2** as the operational data store: all source
   teams publish to AMPS topics; Deephaven ingests via
   `sow_and_subscribe`.
3. **Consumers in two locations** — on-prem and another EKS namespace —
   served by two paths: direct Barrage/Web UI for interactive ticking
   clients, and AMPS **results topics** for decoupled fan-out.

The decisions reinforce each other: AMPS's State-of-the-World topics make
Deephaven's in-memory state instantly rebuildable (which makes the
stateless pod safe), and the same AMPS fabric distributes results back out
(which keeps the Deephaven engine's direct client count small).

---

## Part 1 — Deephaven on EKS: stateless Deployment, replicas = 1

### Why not a StatefulSet

A StatefulSet buys stable per-pod identity, ordered startup, and per-pod
PersistentVolumeClaims. This design needs none of them:

- **All durable state lives outside the pod.** T-1 EOD snapshots (official
  marks, Greeks, inputs) in S3/Parquet or a DB and on the `eod/official`
  AMPS topic; positions from the SOD recon; intraday market data and
  executions in AMPS. Nothing in the pod is the system of record.
- **Deephaven's in-memory state is derived, not owned.** The entire DAG —
  `inst_prev`, `paa`, both grids, roll-ups — is a deterministic function of
  the source feeds. A replacement pod rebuilds everything by re-subscribing.
  A PVC of yesterday's heap has nothing to contribute.
- Notebooks / app-mode scripts: bake into the image or mount via
  ConfigMap / git-sync — versioned deploys of the `deephaven-paa/` scripts,
  not pod-local files.

### Why not a ReplicaSet with N > 1

Replicas ≠ HA here. Deephaven Community does not cluster — each replica is
an independent engine with its own update graph, and Barrage/gRPC client
sessions are stateful and sticky. Two replicas behind one Service means a
client's subscription lands on pod A while the next request hits pod B,
which has never heard of that session. Round-robin load balancing is
actively broken for this workload.

**HA pattern instead — active-active twins:** two *separate* Deployments
(each replicas=1) with separate Services, both subscribing to the same AMPS
topics, computing identical tables. Clients (or a gateway) fail over by
reconnecting and re-subscribing. Because the DAG is deterministic from the
feeds, the twin's numbers match — the same property that lets
[paa-cal](paa-cal/README.md) reproduce the walkthrough exactly. Caveat:
keep nondeterminism out of the graph (the demo's random spot simulator is
exactly what production replaces with real feeds).

**Scaling axis:** one engine per desk/book scale-unit if the firm-wide book
outgrows one heap — partition by book using AMPS content filters
(`/book = 'DESK1'`), aggregate firm roll-ups downstream. Scale by
partitioning, not by replicas.

(Refinement: a *deliberate* replica pool with connection-affinity load
balancing and KEDA **is** viable for scaling read/query fan-out — see
Part 5. What stays forbidden is naive round-robin across replicas.)

### Deployment checklist

- `Deployment`, `replicas: 1`, `strategy: Recreate` — rolling update would
  briefly run two full-heap engines; Recreate makes cutover explicit (or
  blue/green via the twin).
- Memory-heavy node group, **Guaranteed QoS** (requests = limits), JVM heap
  sized to the book with headroom — the engine dies by OOM, not gracefully.
  PodDisruptionBudget + priority class so the autoscaler never evicts it
  mid-day.
- **Startup = rebuild**: app-mode script loads the T-1 snapshot, seeds
  `book_position` from recon, `sow_and_subscribe` to market topics,
  bookmark-replays executions from SOD. Readiness probe = "DAG built and
  caught up", not "port open" — otherwise clients connect to half-built
  tables.
- **Measure recovery time.** SOW rebuild is near-instant; executions replay
  is one day of fills. If ever too slow, checkpoint slow tables to Parquet
  in S3 on a schedule and recover as snapshot + txlog tail — recovery
  optimization, still not per-pod state.

---

## Part 2 — AMPS as the data store

AMPS's **SOW (State-of-the-World) topic** — a last-value cache per key plus
a subscription stream of updates — is the same abstraction as this
project's keyed source tables. The architecture maps one-to-one.

### Topic design

| Deephaven table | AMPS topic | SOW key | Publisher (team) |
|---|---|---|---|
| `instrument` | `refdata/instrument` | InstrumentId | Ops / security master |
| `book_position` | `positions/sod` | Book + InstrumentId | Ops (after SOD recon) |
| `spot_live` | `md/spot` | Underlying | Market data tech |
| `fx_live` | `md/fx` | Currency | Market data tech |
| `vol_live` | `md/vol` | InstrumentId | Quant surface service |
| `rates_live` / `div_live` | `md/rates` / `md/carry` | Currency / Underlying | Rates & dividends |
| Marks + Greeks feed | `val/greeks` | InstrumentId (+ SnapType) | Quant pricing service |
| T-1 snapshots (`*_prev`) | `eod/official` | InstrumentId + AsOfDate | Risk batch / product control |
| `executions` | `trades/executions` | — (event stream) | OMS |
| `orders` | `trades/orders` | OrderId | OMS |

### The three AMPS features that carry the load

- **`sow_and_subscribe`** — current state of every key, then deltas. This
  is `last_by` semantics at the messaging layer: the ingester gets a fully
  populated keyed table on connect. No replay-from-midnight for reference
  and market topics.
- **Transaction log + bookmark replay** — covers `executions`: subscribe
  from the SOD bookmark for every fill in order. Also how the trade
  cut-off of [TIMING-AND-CUTOFFS.md](TIMING-AND-CUTOFFS.md) is implemented
  for point-in-time rebuilds (replay to `exec_time ≤ T_snap`).
- **OOF (out-of-focus) messages** — notify when a key leaves the SOW
  (position purged, instrument delisted); the ingester translates these
  into row deletes.

### Two design rules from day one

1. **One message = one coherent row.** The quant service publishes
   `(mark, delta, gamma, …, spot_used, vol_used, snap_time, model_version)`
   as a single message on `val/greeks` — never marks and Greeks on separate
   topics. AMPS gives per-message atomicity, not cross-topic transactions,
   so the coherence requirement of
   [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md) must be packaged inside
   the message, per the [GREEKS-OWNERSHIP.md](GREEKS-OWNERSHIP.md) request
   spec.
2. **AMPS is the operational store, not the archive.** SOW holds current
   values per key; the transaction log is bounded by disk. The signed T-1
   official snapshots are also archived to S3/Parquet as the system of
   record; `eod/official` keyed by InstrumentId + AsOfDate gives a few days
   of lookback in the SOW itself. The EOD archive job is what makes txlog
   truncation safe.

### The Deephaven ingest adapter

Deephaven ships a Kafka ingester out of the box; for AMPS you write a small
adapter — an AMPS client (Python/Java) inside the Deephaven process:

```
per topic:  sow_and_subscribe → TablePublisher (blink table)
            → last_by(SOW key)          for SOW topics
            → append-only               for trades/executions
            OOF message → row delete
```

A well-trodden ~200-line pattern per message shape (JSON or NVFIX). It
slots exactly where script 01's simulators sit — same schemas and keys, so
scripts 02–05 are unchanged. Content filters (`/book = 'DESK1'`) do
server-side slicing if engines are later partitioned per desk.

### Appendix to Part 2 — topic types and the AMPS config

In AMPS, "topic type" is not declared per se: any topic can be published
to, and its behavior is defined by which config sections mention it —

- **`<SOW>` entry with keys** → last-value cache per key
  (`sow_and_subscribe` works): spot, vol, positions, greeks, …
- **`<TransactionLog>` coverage** → journaled to disk, enabling bookmark
  (replay) subscriptions: the event streams.
- **`<Queues>` entry** → competing-consumer, at-least-once delivery —
  **wrong here**: queues deliver each message to *one* consumer; every
  PAA engine needs *all* fills.

`trades/executions` is therefore a **plain transaction-logged topic with
no SOW entry**: an append-only event stream where history and ordering are
the point. "Last value per key" would be meaningless — executions are
never updated, only corrected via cancel/correct events, which are
themselves new events.

```xml
<AMPSConfig>
  <Name>amps-paa-primary</Name>

  <Transports>
    <Transport>
      <Name>json-tcp</Name>
      <Type>tcp</Type>
      <InetAddr>9007</InetAddr>
      <MessageType>json</MessageType>
      <Protocol>amps</Protocol>
    </Transport>
  </Transports>

  <!-- ========= event streams: journaled, NO SOW entry ========= -->
  <TransactionLog>
    <JournalDirectory>/amps/journal</JournalDirectory>
    <MinJournalSize>1GB</MinJournalSize>
    <Topic>
      <Name>trades/executions</Name>
      <MessageType>json</MessageType>
    </Topic>
    <Topic>
      <Name>trades/orders</Name>
      <MessageType>json</MessageType>
    </Topic>
    <!-- SOW topics are ALSO journaled: required for replication,
         and gives point-in-time replay of market data -->
    <Topic>
      <Name>md/.*</Name>            <!-- regex covers spot/fx/vol/rates/carry -->
      <MessageType>json</MessageType>
    </Topic>
    <Topic>
      <Name>val/greeks</Name>
      <MessageType>json</MessageType>
    </Topic>
    <Topic>
      <Name>positions/sod</Name>
      <MessageType>json</MessageType>
    </Topic>
    <Topic>
      <Name>eod/official</Name>
      <MessageType>json</MessageType>
    </Topic>
  </TransactionLog>

  <!-- ========= keyed last-value state: SOW topics ========= -->
  <SOW>
    <Topic>
      <Name>refdata/instrument</Name>
      <MessageType>json</MessageType>
      <Key>/instrument_id</Key>
      <FileName>/amps/sow/%n.sow</FileName>
    </Topic>
    <Topic>
      <Name>positions/sod</Name>
      <MessageType>json</MessageType>
      <Key>/book</Key>
      <Key>/instrument_id</Key>
      <FileName>/amps/sow/%n.sow</FileName>
    </Topic>
    <Topic>
      <Name>md/spot</Name>
      <MessageType>json</MessageType>
      <Key>/underlying</Key>
      <FileName>/amps/sow/%n.sow</FileName>
    </Topic>
    <Topic>
      <Name>val/greeks</Name>
      <MessageType>json</MessageType>
      <Key>/instrument_id</Key>
      <Key>/snap_type</Key>
      <FileName>/amps/sow/%n.sow</FileName>
    </Topic>
    <Topic>
      <Name>eod/official</Name>
      <MessageType>json</MessageType>
      <Key>/instrument_id</Key>
      <Key>/as_of_date</Key>
      <FileName>/amps/sow/%n.sow</FileName>
    </Topic>
    <!-- md/fx, md/vol, md/rates, md/carry declared the same way -->
    <!-- NOTE: trades/executions deliberately NOT here -->
  </SOW>
</AMPSConfig>
```

**Publisher side** (OMS — nothing special; use the AMPS publish store for
exactly-once sequencing across reconnects):

```python
client.publish("trades/executions",
    '{"exec_id":"EX-1","order_id":"ORD-1001","book":"DESK1",'
    '"instrument_id":"AAPL_C220_DEC26","side":"BUY","qty":15,'
    '"price":12.45,"exec_time":"2026-07-13T09:31:05"}')
```

**Ingester side** — bookmark subscription instead of `sow_and_subscribe`;
AMPS accepts an ISO timestamp bookmark, which is exactly the SOD replay:

```python
for msg in client.bookmark_subscribe(
        topic="trades/executions",
        bookmark="20260713T000000000000",   # start of trading day
        sub_id="dh-paa-executions",
        options="replace"):
    table_publisher.add(parse_exec(msg.get_data()))   # append-only, no last_by
```

Give the ingester a persistent file-backed **bookmark store**: on
reconnect/failover it resumes from the last acknowledged fill instead of
re-replaying the day (pairs with the HA client's server chooser). The same
mechanism implements the point-in-time rebuilds of
[TIMING-AND-CUTOFFS.md](TIMING-AND-CUTOFFS.md): replay from SOD, stop at
`exec_time ≤ T_snap`.

Operational consequences of "no SOW entry":

- No `sow_and_subscribe` shortcut — a fresh engine always pays the one-day
  executions replay (fast in practice: fill count, not tick data).
- The journal is the only server-side copy — journal retention plus the
  EOD S3 archive job is what makes truncation safe (Part 3).
- Optional hybrid for *other* consumers' convenience: an additional SOW
  keyed by `/exec_id` with `<Expiration>2d</Expiration>` gives dedup-by-key
  and a browsable current-day blotter — an addition, not a replacement;
  the PAA engine consumes the journaled stream either way.

---

## Part 3 — AMPS on EC2

- **Instance profile**: disk-and-memory bound — transaction log on fast
  local NVMe (i4i / i3en) or io2 EBS. SOW sizing = key count × message
  size (trivial here: thousands of keys, not millions).
- **HA**: two-instance replicated pair (AMPS native replication) across two
  AZs; EKS node group in the same AZ as the primary to keep the hot path
  off cross-AZ links. Clients fail over via the AMPS HA client (server
  chooser + bookmark store + publish store) — the ingester resubscribes
  automatically and resumes from its bookmark.
- **Retention**: size the txlog for at least a full trading day plus
  margin (it is the intraday replay source).
- **Security**: tight security groups — publishers (source teams),
  Deephaven ingesters, and admin/monitoring only. Feed AMPS's admin/stats
  endpoint into Prometheus/Grafana.

---

## Part 4 — Consumer connectivity: on-prem and cross-namespace EKS

Consumers live in two places: **on-prem** (product control apps, trader
desktops) and **another EKS namespace** (risk services, dashboards). Serve
them through two deliberate paths rather than one:

### Path A — AMPS results topics (decoupled fan-out; the default)

Deephaven publishes its outputs **back to AMPS** via a small publisher
adapter (the mirror image of the ingester — table listener → AMPS publish):

| Result table | AMPS topic | SOW key |
|---|---|---|
| `paa` | `results/paa` | Book + InstrumentId |
| `paa_summary` / roll-ups | `results/paa_summary` | Book |
| `risk_grid_pos` (+ roll-ups) | `results/risk_grid` | Book + InstrumentId + ShiftPct |
| `paa_grid` (+ roll-ups) | `results/paa_grid` | Book + InstrumentId + ShiftPct |

Why this is the default path:

- **Fan-out is AMPS's job, not the engine's.** Every direct Barrage
  subscription costs the Deephaven JVM memory and cycles; AMPS is built to
  fan out to thousands of subscribers. Keep the engine's direct client
  count to a handful.
- **On-prem apps are already AMPS-native** — they reuse existing
  connectivity and client libraries; no new protocol reaches the desks.
  Optionally run an **on-prem AMPS instance as a replication target** of
  the EC2 pair, so on-prem consumers subscribe locally and only AMPS
  replication crosses the WAN link (one stream, not N).
- **Decoupling**: an engine restart is invisible to results consumers —
  the SOW keeps last values, and the republish refreshes them. Results
  messages carry `SnapTime` per [TIMING-AND-CUTOFFS.md](TIMING-AND-CUTOFFS.md)
  so every consumer knows the as-of.
- Delta-publish on the grid topics keeps bandwidth low (only changed
  cells re-publish per tick).

### Path B — direct Barrage / Web UI (interactive ticking clients)

For users who need the live Deephaven experience (quants and risk analysts
exploring tables, ad-hoc queries):

- **Same-cluster, other namespace**: plain Kubernetes — consumers hit the
  ClusterIP service cross-namespace
  (`deephaven.paa.svc.cluster.local:10000`). Add a **NetworkPolicy**
  allowing ingress only from the consumer namespace (and the ingest path),
  and mTLS via service mesh if the cluster runs one.
- **On-prem**: expose an **internal NLB** (Barrage is gRPC/HTTP2 — L4 NLB
  is the standard choice) reachable over **Direct Connect / Site-to-Site
  VPN**; never public. DNS via a **Route 53 private hosted zone** with
  Resolver inbound endpoints so on-prem resolves the same name. TLS on the
  listener; authentication via Deephaven's PSK or a custom auth handler;
  NLB security group restricted to the on-prem CIDRs.
- **Twins caveat** (from Part 1): with active-active engines, expose two
  endpoints (`paa-a`, `paa-b`) — clients or a thin gateway choose one and
  fail over by reconnecting. Never round-robin one LB across both:
  Barrage sessions are sticky.

### Who uses which path

| Consumer | Location | Path |
|---|---|---|
| Product control apps (P&L sign-off) | On-prem | A — `results/paa`, `results/paa_summary` via on-prem AMPS replica |
| Trader apps / desktops (hedging) | On-prem | A — `results/risk_grid`; interactive users also B via NLB + DX/VPN |
| Risk services & dashboards (model validation) | EKS, other namespace | B — cross-namespace Barrage for ticking tables; A where decoupling matters |

Rule of thumb: **systems consume Path A; humans exploring consume Path B.**

### Appendix to Part 4 — why publish results back to AMPS at all?

*Why not let every consumer connect directly to Deephaven?* Because the
two paths optimize different things, and for many heterogeneous
system-type consumers, direct consumption makes the P&L calculation engine
also be a distribution server. The recommendation splits those jobs.

**1. Every direct subscription taxes the calc engine.** A Barrage
subscription is not a cheap download — the engine holds server-side state
per client (exports, viewports), tracks deltas, and serializes Arrow
batches *in the same JVM that runs the PAA DAG*. Twenty subscribers to
ticking grid tables means the engine spends heap and CPU on distribution
while it is supposed to be repricing the book; a slow or buggy consumer
(tiny TCP window, resubscribe loop) degrades the engine for everyone —
including the desk's own risk view. AMPS makes the opposite trade-off:
fan-out to thousands with content filtering is its core competency, and
subscriber #200 costs the engine nothing because the engine publishes each
result row **once**. The scaling math is the clincher: growing direct
consumers eventually forces the Part-5 replica pool, where each increment
is a full-heap JVM recomputing the entire book just to serve more readers;
growing AMPS consumers is a config entry.

**2. Blast radius and lifecycle decoupling.** With direct consumption, an
engine restart drops every consumer simultaneously, then they thunder back
against a pod still rebuilding its DAG. With results topics, a restart is
invisible: the SOW holds last published values, consumers keep their AMPS
subscriptions, rows refresh when the engine catches up. And nothing a
consumer does can touch the calculation path — for a system whose output
is signed P&L, protecting the producer from its consumers is worth a hop.

**3. The on-prem estate already speaks AMPS.** Desk apps have AMPS client
libraries, entitlements, monitoring, and runbooks today; direct Barrage
means rolling gRPC/Arrow Flight clients on-prem, new firewall paths to
EKS, and a new auth story. On the WAN: one replication stream to the
on-prem AMPS replica vs N independent gRPC streams over Direct Connect.

**4. Topics are a contract; tables are an implementation.**
`results/paa` with a documented schema is an integration contract —
consumers do not care that Deephaven produced it. Swap the engine, run a
[paa-cal](paa-cal/README.md) batch as fallback, split engines by book:
no consumer changes. Direct consumers couple to Deephaven table names and
session semantics. Governance bonus: published results flow through the
transaction log — a journaled, replayable record of exactly what P&L was
distributed and when, with per-book entitlements enforced by AMPS content
filters.

**Where direct consumption is genuinely better — and stays in the design:**

- **Interactive exploration** — AMPS delivers fixed row streams; Deephaven's
  value to a human is ad-hoc filtering/joining/pivoting on live tables.
  Quants and analysts should hit Barrage/Web UI directly.
- **Viewports on big tables** — the PAA grid is books × instruments × 13
  shifts; a scrollable UI is better served by Barrage viewports (only
  visible rows flow) than by subscribing to a whole topic.
- **Consistency semantics** — Barrage delivers per-update-cycle consistent
  table snapshots; an AMPS consumer sees row-by-row updates and must group
  a coherent batch itself. Fix: the results publisher stamps a per-snapshot
  `batch_id` (alongside `SnapTime`) on every row so consumers can assemble
  consistent batches.
- **A few trusted in-cluster services** where the double hop's extra
  milliseconds matter and the client count is bounded.

Honest costs of the AMPS path: one extra hop of latency (milliseconds —
irrelevant for P&L reporting, where the as-of `SnapTime` is what matters)
and one more component to operate (the singleton results publisher of
Part 5). Hence the rule of thumb above — it is not AMPS *instead of*
Deephaven serving; it is putting unbounded fan-out on the component built
for fan-out and keeping the engine's direct clients few, trusted, and
mostly interactive.

---

## Part 5 — Scaling the Barrage tier: read-replica pool + KEDA

Can consumers connect to *multiple* Deephaven replicas via a load balancer
with KEDA autoscaling? **Yes — as a read-replica pool with connection
affinity, never a classic round-robin LB.** The pattern is valid precisely
because of Part 2: every replica independently converges to identical
state from AMPS (`sow_and_subscribe` + SOD bookmark replay), so N replicas
are N engines computing the same tables. It refines — does not replace —
the single-replica baseline of Part 1: the pool scales **read/query
fan-out only**.

### What replicas do and don't scale

- **Do**: more Barrage subscribers, more Web UI users — each replica
  serves its own client population from identical tables.
- **Don't**: calculation capacity. Ten replicas do the full book's work
  ten times. If the book outgrows one heap, partition by book with AMPS
  content filters (`/book = 'DESK1'`) — that is the compute-scaling axis.

### Load balancer: affinity per session, never per request

Barrage sessions are stateful (server-side exports/tickets exist on one
engine), so a client must stay pinned to one replica for the session:

- **NLB (L4)** works naturally per connection — gRPC multiplexes over one
  HTTP/2 connection and a TCP flow hits one target. Enable **source-IP
  stickiness** so reconnects and second channels land on the same replica.
- **Forbidden**: per-request gRPC round-robin (ALB-style) — instant
  "unknown ticket/session" errors when a client's second request hits a
  different pod.
- Cleaner alternative: a session-aware gateway, or client-side chooser
  over a headless service (`paa-0..paa-N`) — the twins pattern of Part 1,
  automated.

### KEDA guardrails

- **Scale-out latency**: a new replica must rebuild and catch up before
  taking traffic. `startupProbe`/`readinessProbe` = "SOW loaded +
  executions replayed + subscribed at head" — not "port open". SOW rebuild
  is fast; budget the executions replay.
- **Scale-in kills live sessions** — the unavoidable cost. Mitigate with:
  long `terminationGracePeriodSeconds` + preStop deregistration/drain,
  long KEDA stabilization window and conservative scale-down (one pod per
  10–15 min), clients that reconnect-and-resubscribe (needed for failover
  anyway). Consider pinning the replica count during trading hours and
  letting KEDA act only off-hours.
- **Scaling metric**: not CPU (a ticking engine is busy at idle). Scale on
  consumer pressure — Barrage subscription/session count via the KEDA
  Prometheus scaler, or p95 request latency.
- **Memory economics**: each replica is a full-heap JVM recomputing
  everything; the scaling unit is "one engine per K concurrent users."
- `minReplicaCount: 2` gives the Part-1 HA twins for free.

### The one singleton: the results publisher

With N replicas, the Path-A adapter publishing `results/*` must run on
**exactly one** engine (leader-elected or pinned, or as its own singleton
deployment) — otherwise N interleaved copies of every result row reach
AMPS. SOW dedupes by key so it half-works, but SnapTimes interleave across
replicas and consumers see churn. This is the only component in the design
that must not be replicated.

### Order of preference

1. **AMPS results topics remain the primary fan-out** (Path A) — they
   remove most of the need for a large Barrage pool.
2. If interactive Barrage users grow: NLB + source-IP stickiness,
   `minReplicaCount: 2`, KEDA on subscription count with slow scale-in.
3. Compute pressure → partition by book, never more replicas.
4. Large consumer populations → evaluate Deephaven Enterprise (persistent
   queries with a controller/dispatcher natively managing many workers).

---

## End-to-end flow

```
source teams → AMPS topics (SOW + txlog) on EC2
            → Deephaven ingest adapters (sow_and_subscribe → TablePublisher → last_by)
            → scripts 02–05 (unchanged)
            → PAA / grids / roll-ups
            → Path A: results publisher → AMPS results/* topics
                        → on-prem consumers (via on-prem AMPS replica)
                        → EKS-namespace services (decoupled)
            → Path B: Barrage/Web UI
                        → EKS-namespace clients (cross-namespace ClusterIP + NetworkPolicy)
                        → on-prem interactive users (internal NLB + Direct Connect/VPN + private DNS)
```

## Related docs

- [ARCHITECTURE.md](ARCHITECTURE.md) — team / data / calculation map (diagram includes the AMPS layer)
- [SNAPSHOT-COHERENCE.md](SNAPSHOT-COHERENCE.md) — the one-message-one-row rule's origin
- [GREEKS-OWNERSHIP.md](GREEKS-OWNERSHIP.md) — the marks+Greeks feed published on `val/greeks`
- [TIMING-AND-CUTOFFS.md](TIMING-AND-CUTOFFS.md) — bookmark replay and trade cut-offs
- [SOD-VS-LIVE-POSITION.md](SOD-VS-LIVE-POSITION.md) — positions/sod semantics
- [README.md](README.md) — project index

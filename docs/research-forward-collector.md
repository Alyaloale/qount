# Unified Research Forward Collector

> **Status**: active research-only infrastructure | **Authority**: research governance | **Updated**: 2026-09-23

The unified collector records one public-data evidence cycle for all forward
research lines. It is deliberately separate from live, paper, and broker paths.
Every cycle is append-only JSONL with a SHA-256 predecessor chain and a frozen
plugin-set contract.

## Runtime

- Core: `src/qount/research/forward_collector.py`
- CLI: `scripts/research/governance/run_forward_collector.py`
- Source graph: `deploy/research/forward-sources.json`
- State root: `/var/lib/qount/research/forward/ops-health-v3` (since 2026-09-29); `ops-health-v2` (stopped 2026-09-27) and `stream-health-v1` remain read-only.
- The contract pins the sha256 of the plugin source file (`forward_collector.py`). Any edit to that shared file, even an unused branch, breaks the active contract and requires a new state root plus matching `--forward-root` in the dashboard publisher.
- Timer template: `deploy/systemd/qount-research-forward-collector.timer`
- Service template: `deploy/systemd/qount-research-forward-collector.service`
- Cadence: every 15 minutes, with a small randomized delay

The service logs only the record hash, observation time and plugin status summary.
Full records remain in the declared JSONL artifacts; the deployed unit omits
`--print-json` to avoid duplicating large source/status payloads in journald.

Each cycle writes:

```text
metadata/collection-contract.json
metadata/current.json
records/YYYY/MM/DD/cycles.jsonl
collector.lock
```

The contract rejects plugin, plugin-source, source-graph, or symbol drift after the first cycle. Each record
contains the observed UTC time, plugin status, contract hash, previous record
hash, current record hash, and explicit `orders_authorized=false` and
`pnl_evaluated=false` guards.

## Integrated Source Graph

The source graph is configured in JSON and is consumed by the single
`research_lines` plugin. It currently binds Binance UM REST for MiniTrend Base,
Funding Veto, Vol Crisis, and FOMC context; the Binance Public Data archive
contract for verified historical klines/funding/metrics; the frozen Federal
Reserve FOMC calendar; the existing liquidation cascade status; the SHA-pinned
Tiingo adjusted-close EOD for L1 passive
`SPY`/`TLT` when `QOUNT_TIINGO_API_KEY` is injected.

The unified contract writes six active line records: `mini_trend_base`, `funding_veto`,
`vol_crisis`, `fomc`, `l1_passive`, and `liquidation_cascade`. CTA-R is collected separately by
the isolated `qount-research-cta-r-collector.timer` under the `cta-r-akshare-v1` state root;
this is public input evidence only and does not restore the CTA-R strategy. Every
line includes separate `mechanism_conclusion`, `data_conclusion`, and
`strategy_return_conclusion` fields. Source availability is not a strategy
result; all line records keep `strategy_results_evaluated=false`.

The four allowed conclusions are `valid`, `insufficient`, `flawed`, and
`rejected`. Missing Tiingo credentials or a missing VPS liquidation status are
`insufficient`; an archive checksum mismatch is `flawed`.

The liquidation source additionally requires the continuous collector to be
`running`, its status metadata and public-stream heartbeat to be no more than
180 seconds old, and all no-order guards to remain false. A missing or stale
heartbeat is `insufficient` even when the systemd process and five-minute REST
snapshot loop are still active. The heartbeat is a public `markPrice@1s`
message used only for transport health; it is not stored as liquidation
evidence or treated as a strategy input.

On a VPS, the optional private environment file is
`/etc/qount/research-forward-collector.env` (`0600 root:root`) and may contain
only `QOUNT_TIINGO_API_KEY=...`. It is outside the repository; without it the
L1 source records `insufficient` and the other lines continue.

The collector is an input recorder. A `valid` plugin result means the input
collection completed; it does not mean the associated strategy passed.
`insufficient`, `flawed`, and `rejected` remain line-level conclusions for
strategy evaluators and are never replaced by a successful raw snapshot.

## Adding A Line Or Source

For a new line backed by an existing source, add one JSON object under
`research_lines` and reference its source IDs. For a new source kind, add an
adapter in `forward_collector.py` and bind it in the same JSON contract. A
plugin adapter implements:

```python
class MyPlugin:
    name = "my_line_inputs"

    def collect(self, context) -> PluginResult:
        return PluginResult("valid", {"...": "public evidence"})
```

It can be loaded without changing the timer:

```text
--plugin my_package.forward_plugin:factory --plugins binance_um_public,my_line_inputs
```

Changing the plugin set or adapter source creates a new state-root contract. It
must not mutate an existing collection history in place.

The CTA-R adapter uses `deploy/research/cta-r-akshare-sources.json` and a
manifested qfq seed at `/var/lib/qount/research/cta-r/etf_source/etf_data.zip`.
It accepts only the eight fixed ETF series, checks bounded ZIP contents and
freshness, and reports `insufficient` for missing or stale data. It does not
read a credential or write paper/NAV/strategy artifacts. Its daily service and
timer are separate from the unified collector so source-graph changes cannot
alter its chain. Note: its 2026-09-27 deploy still edited the shared
`forward_collector.py`, which stopped `ops-health-v2` (see above).

## VPS Boundary

The collector is deployed on `qount-vps` as
`qount-research-forward-collector.timer=enabled/active`, with a 15-minute
cadence. The oneshot service is expected to return to `inactive/dead` after a
successful cycle; inspect its last result with `systemctl show` or the
collector `--status` command. The active state root is
`/var/lib/qount/research/forward/stream-health-v1`, and the current record is an
append-only JSONL entry linked to its predecessor hash. The previous
`/var/lib/qount/research/forward` contract chain is retained read-only because
the plugin-source identity changed when stream freshness validation was added.

The collector is research-only: `orders_authorized=false` and
`pnl_evaluated=false` are written into every cycle. A line or source status of
`insufficient` is an evidence-status result, not a service failure. The old
MiniTrend forward and FOMC shadow units are removed. The liquidation WebSocket
service remains separate because it is a continuous raw event source; the
unified timer reads its status without duplicating that stream.

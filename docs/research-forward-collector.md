# Unified Research Forward Collector

> **Status**: active research-only infrastructure | **Authority**: research governance | **Updated**: 2026-07-31

The unified collector records one public-data evidence cycle for all forward
research lines. It is deliberately separate from live, paper, and broker paths.
Every cycle is append-only JSONL with a SHA-256 predecessor chain and a frozen
plugin-set contract.

## Runtime

- Core: `src/qount/research/forward_collector.py`
- CLI: `scripts/research/governance/run_forward_collector.py`
- Source graph: `deploy/research/forward-sources.json`
- State root: `/var/lib/qount/research/forward`
- Timer template: `deploy/systemd/qount-research-forward-collector.timer`
- Service template: `deploy/systemd/qount-research-forward-collector.service`
- Cadence: every 15 minutes, with a small randomized delay

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
CTA-R `etf_data.zip` archive; and Tiingo adjusted-close EOD for L1 passive
`SPY`/`TLT` when `QOUNT_TIINGO_API_KEY` is injected.

The same cycle writes seven line records: `mini_trend_base`, `funding_veto`,
`vol_crisis`, `fomc`, `cta_r`, `l1_passive`, and `liquidation_cascade`. Every
line includes separate `mechanism_conclusion`, `data_conclusion`, and
`strategy_return_conclusion` fields. Source availability is not a strategy
result; all line records keep `strategy_results_evaluated=false`.

The four allowed conclusions are `valid`, `insufficient`, `flawed`, and
`rejected`. Missing Tiingo credentials or a missing VPS liquidation status are
`insufficient`; an archive checksum mismatch is `flawed`.

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

## VPS Boundary

The collector is deployed on `qount-vps` as
`qount-research-forward-collector.timer=enabled/active`, with a 15-minute
cadence. The oneshot service is expected to return to `inactive/dead` after a
successful cycle; inspect its last result with `systemctl show` or the
collector `--status` command. The state root is
`/var/lib/qount/research/forward`, and the current record is an append-only
JSONL entry linked to its predecessor hash.

The collector is research-only: `orders_authorized=false` and
`pnl_evaluated=false` are written into every cycle. A line or source status of
`insufficient` is an evidence-status result, not a service failure. The old
MiniTrend forward and FOMC shadow units are removed. The liquidation WebSocket
service remains separate because it is a continuous raw event source; the
unified timer reads its status without duplicating that stream.

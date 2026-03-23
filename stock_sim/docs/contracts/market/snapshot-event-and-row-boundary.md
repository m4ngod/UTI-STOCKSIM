# Snapshot Event And Row Boundary

_Last updated: 2026-03-24_

## Goal

Clarify the difference between:
- snapshot event payloads
- persisted `snapshots_1s` rows

---

## Rule

### Snapshot event
Role:
- runtime notification
- replay input
- cross-module signal
- UI / listener input

Should carry:
- `symbol`
- `run_id` when available
- `sim_day`
- `sim_dt`
- lightweight market payload

It is not the final persistence truth.

### Snapshot row (`snapshots_1s`)
Role:
- persisted market-state fact
- queryable 1s snapshot history
- storage-side source for later analytics

Should carry:
- `symbol`
- `ts`
- computed market fields
- `sim_day`
- `sim_dt`

It is not required to preserve the original event payload shape.

---

## Ownership

### Runtime event ownership
- event producers
- event normalization path
- event persistence service

### Row ownership
- `services/snapshot_listener.py`
- `persistence/models_snapshot.py`

---

## Current practical boundary

1. runtime emits snapshot-related event
2. listener normalizes / stamps simulation-time fields when needed
3. listener writes `snapshots_1s`
4. replay may use event log
5. historical market query may use snapshot rows

---

## Current judgment

- event and row should stay related, not identical
- replay/recovery use event history first
- storage/history queries use persisted rows first
- do not force a brittle one-to-one payload == row contract

---

## Immediate next work

1. continue normalizing `SNAPSHOT_UPDATED` payload shape
2. later add stricter replay-vs-row validation
3. avoid over-testing unstable event chain details before ownership is cleaner

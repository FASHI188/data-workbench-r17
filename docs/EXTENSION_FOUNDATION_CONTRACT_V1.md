# Extension Foundation Contract V1

## Purpose

Provide stable extension points between the accepted Stage3 historical feature base and future research/runtime modules without implementing any not-yet-approved business logic.

This foundation does **not** add a news system, market-regime engine, ETF flow model, supply-chain model, Alpha model, training job, live signal, broker integration, or other domain feature. It only defines generic contracts and governance boundaries.

## Mandatory extension points

The architecture reserves these generic interfaces:

1. `SOURCE_ADAPTER` — ingest external information into a standard envelope.
2. `FEATURE_PLUGIN` — transform accepted envelopes into feature outputs.
3. `MODEL_ADAPTER` — isolate future model runtimes behind a stable request/response boundary.
4. `TASK_SCHEDULER` — isolate future scheduling/execution backends.
5. `EVENT_LOG` — append/query correlated execution and decision events.
6. `OUTPUT_ADAPTER` — isolate future sinks, reports or downstream delivery targets.
7. `ENTITY_RESOLVER` — optional foundation interface for canonical issuer/instrument resolution.

No concrete provider is implemented by this contract.

## Default-off and isolation rules

- Every extension is default disabled.
- Merely adding code does not activate a module.
- New modules must be registered explicitly.
- A new module must be enabled separately, tested separately and accepted separately.
- New modules must first run in `SHADOW` before formal enablement.
- Extension failure must be contained inside the extension boundary.
- Extension failure must not modify, invalidate or block an already accepted baseline capability.
- Failure policy is `ISOLATE_FAIL_CLOSED`.
- Fallback behavior is `BASELINE_UNCHANGED`.
- Training and live use are default forbidden.
- A disabled, quarantined or rolled-back extension may not contribute features, model decisions or outputs to the accepted baseline.

## Module lifecycle

`REGISTERED -> SHADOW -> TESTED -> ACCEPTED -> ENABLED`

Exceptional/off states:

- `DISABLED`
- `QUARANTINED`
- `ROLLED_BACK`

`ENABLED` requires an explicit acceptance reference. Activation must be a separate governance change; acceptance of code alone is not activation.

## External data envelope

Every external-data record must preserve source and point-in-time lineage. Required fields are:

- `event_id`
- `idempotency_key`
- `event_time` (or economic/event effective time represented by this field)
- `source`
- `source_ref` (replayable immutable snapshot reference when available; otherwise the strongest reproducible source locator)
- `published_at`
- `available_at`
- `collected_at`
- `source_sha256`
- `schema_version`
- `adapter_version`
- `parser_version`
- `transform_version`
- `run_id`
- `upstream_fingerprint`
- `revision`
- `data_status`

Optional but standardized fields include `source_uri`, `task_id`, `trace_id`, `entity_id`, `instrument_id`, and `supersedes_event_id`.

### Time semantics

- `event_time`: when the represented event/economic fact applies. It may be before or after publication (for example, historical results versus a future scheduled catalyst).
- `published_at`: when the source published the information.
- `available_at`: earliest time the research/trading system is allowed to know the information.
- `collected_at`: when this system actually collected the source.

Hard PIT invariant: `published_at <= available_at <= collected_at`.

No extension may replace these timestamps with a single generic date. No future information may be backfilled into an earlier point-in-time snapshot.

## Identity, deduplication and revisions

- `event_id` is the immutable identity of one event version.
- `idempotency_key` prevents repeated collection/republication from becoming repeated economic evidence.
- `entity_id` and `instrument_id` are canonical identities when the event can be resolved to an issuer/security.
- Name/ticker text alone is not a canonical identity contract.
- Corrections/new official versions create a new event version and link through `supersedes_event_id` plus incremented `revision`.
- Existing source evidence is append-only; revisions do not silently overwrite old PIT evidence.

## Lineage and reproducibility

`source_sha256` identifies the exact collected source bytes/content. That alone is insufficient for downstream reproducibility, so extension outputs must also preserve:

- adapter version
- parser version
- transform version
- run ID
- upstream fingerprint
- replayable source/snapshot reference

Any later training snapshot or decision snapshot must be able to identify the exact accepted module versions and upstream fingerprints that generated it.

## Missingness and fail-closed semantics

Allowed generic data states:

- `AVAILABLE`
- `NOT_AVAILABLE`
- `NOT_APPLICABLE`
- `STALE`
- `INVALID`
- `ERROR_FAIL_CLOSED`

Missing, invalid, stale or failed data must never be silently converted to numeric zero or fabricated values. A module may preserve missingness, quarantine its output, or fail closed according to its separately accepted contract.

## Failure containment and resource budgets

Every extension manifest must declare:

- positive timeout
- bounded retry count
- fail-closed isolation policy
- accepted-baseline fallback behavior

Future implementations may add circuit-breaker/resource limits, but any such behavior must remain local to the module. One provider outage must not damage the accepted baseline chain.

## Observability and event correlation

Execution paths reserve `run_id`, `task_id`, and `trace_id`. A future event logger can correlate collection, transformation, model execution, scheduling and output emission without coupling the modules to one logging backend.

## Schema evolution

- Schemas and contracts are versioned.
- Breaking semantic changes require a new version.
- Old accepted artifacts remain interpretable under their original schema/contract versions.
- A new schema version may not reinterpret old values in place.

## Rollback

Formal activation must always have a previous accepted module set/fingerprint to fall back to. Rollback disables/quarantines the new extension and restores the previously accepted module set; it must not rewrite historical evidence.

## Explicit non-goals

This foundation intentionally does not implement:

- any concrete external data source
- any news/catalyst classification logic
- any market/ETF/commodity/supply-chain feature logic
- any entity-matching heuristic
- any model or training algorithm
- any trading rule
- any brokerage/live output
- any provider-specific scheduler or logger

Those require separate scope, implementation, test, evidence and acceptance.

## Current project boundary

This foundation must not alter the frozen Stage3 dataset fingerprint, Stage3 final manifest, current Stage3 authority, Stage4 lock, Alpha-training prohibition, live-signal prohibition, or `main`. It is infrastructure only on the integration line until separately accepted.

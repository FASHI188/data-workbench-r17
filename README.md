# data-workbench

General-purpose data processing, validation, and reproducibility workspace.

This repository contains experimental pipelines, data-quality checks, transformation utilities, and workflow automation used for internal research and engineering exercises.

## Formal project status

The single project-level readiness source is `data/project_status.json`.

Stage-local manifests are evidence for their own stage only. In particular, a Stage2 field that says downstream/Alpha work is allowed means only that Stage2 no longer blocks downstream work; it does **not** authorize project-level training or live signals unless the project-level status also passes Stage3, freshness, and reproducibility gates.

Current formal state:

- Stage2: PASS (`data/stage2_final/manifest.json`)
- Stage3: NOT_READY
- Stage4: LOCKED
- Alpha training: BLOCKED
- Live investment signals: BLOCKED
- Frozen base data coverage: through 2026-07-24; freshness gate currently STALE

`data/stage2_audit.json` is a superseded legacy placeholder and is not an authoritative readiness source.

Status: active development / research only.

# Stage3 S3G1J V14 representative shard smoke anchor

This branch is based on the V14.1 production-acceptance head `d0ea761e7e9c2f4fcd288eddf1143a2e0c7f1286`.

Frozen comparability contract:

- V14 production acceptance run: `30423298099` — PASS.
- Exact V12.1 version ledger source: V13 representative smoke run `30382695045`, artifact `stage3-s3g1j-v13-smoke-versions`.
- Same 64-shard partitioning.
- Same representative shards: `0, 1, 7, 9`.
- V13 hard-error baselines: shard0=51, shard1=37, shard7=40, shard9=28; total=156.
- Only intended extraction change in this smoke: `extract_stage3_financial_pdf_values_v8.py` -> `extract_stage3_financial_pdf_values_v9.py` (V14.1 role-gated coordinate fallback behind V13).
- Fail-closed semantics remain active. The matrix jobs stay red while any shard contains hard errors; the summary job separately records non-regression and incremental reduction.

This smoke does not unlock Stage4/Alpha and does not change main.

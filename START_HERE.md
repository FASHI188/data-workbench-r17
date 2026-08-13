# START HERE

Stable cross-chat continuation entrypoint for the investment project.

0. Read `governance/INVESTMENT_CONTINUITY_RULES_V3.md`. It is the stable continuation rule layer and contains no dynamic project state.
1. Read Airtable `执行检查点`; if the newest checkpoint is RUNNING or BLOCKED, restore its task and next action.
2. Read Airtable `接续快照` record `INVESTMENT_CURRENT`.
3. Verify the live integration SHA and active PR/Actions on GitHub. Live technical facts override stale snapshots.
4. Read `governance/project_module_index.json` for the complete module map.
5. Read `governance/accepted_project_state.json` for repository-accepted business progression; its live integration SHA must be read from GitHub at runtime.
6. Read ACTIVE Airtable long-term decisions when a named module or architecture alias is referenced.
7. Use maintenance logs for conflict resolution, audit and history, not as the primary real-time continuation source.

Long tasks must create/update a RUNNING checkpoint after each major verifiable step, branch/HEAD/PR change, Actions or Artifact result, blocker, next-action change, or permission-boundary change. Chat memory is only a retrieval clue and must not be used as current technical authority.

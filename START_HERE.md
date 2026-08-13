# START HERE

Stable cross-chat continuation entrypoint for the investment project.

1. Read Airtable `执行检查点`; if the newest checkpoint is RUNNING or BLOCKED, continue from its next action after verifying GitHub.
2. Read Airtable `接续快照` record `INVESTMENT_CURRENT`.
3. Verify the live integration SHA and active PR/Actions on GitHub.
4. Read `governance/project_module_index.json` for the complete module map.
5. Read `governance/accepted_project_state.json` for the latest repository-accepted progression.
6. Read ACTIVE Airtable long-term decisions when a named module or architecture alias is referenced.
7. Use maintenance logs for audit/history, not as the primary real-time continuation source.

Long tasks must update the RUNNING checkpoint after each major verifiable step, branch/PR change, Actions result, or blocker. Chat memory is only a retrieval clue and must not be used as current technical authority.

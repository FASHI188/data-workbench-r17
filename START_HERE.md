# START HERE

Stable cross-chat continuation entrypoint for the investment project. Use the smallest sufficient state package; do not bulk-load chat history.

0. Read `governance/INVESTMENT_CONTINUITY_RULES_V3.md` (currently V3.3). It is the stable continuation, context-budget, and chat-lifecycle rule layer and contains no dynamic project state.
1. Read Airtable `执行检查点`. Only if the newest checkpoint is RUNNING or BLOCKED, restore that task and next action. Do not expand old DONE checkpoints during startup.
2. Read Airtable `接续快照` record `INVESTMENT_CURRENT`.
3. Verify the live integration SHA and only the active/referenced PR, Actions, or Artifact needed for the current task. Live technical facts override stale snapshots.
4. Read `governance/project_module_index.json`; expand only the current module's evidence when needed.
5. Read `governance/accepted_project_state.json` for repository-accepted business progression; its live integration SHA must be read from GitHub at runtime.
6. Read only ACTIVE Airtable long-term decisions directly relevant to the current module or user-named alias.
7. Maintenance logs, old trader chats, historical PR chains, and historical project sources are on-demand audit/history material, not startup context. Read them only for a concrete conflict, root-cause trace, audit, or explicit user request.

Context budget: never copy a previous trader chat's long summary wholesale into a new trader chat; never routinely load the latest 10 maintenance logs; never bulk-expand all decisions or historical PRs. Persist long-task state to Checkpoint/CURRENT/GitHub as work proceeds so the chat window remains disposable.

Chat lifecycle: default active-chat set is current trader + previous trader. After a new trader chat successfully restores and verifies the current state from Airtable/GitHub, the trader two generations back and older should be archived, not deleted. If recovery conflicts, stop the archive step until the conflict is resolved. Normal continuation must not depend on unarchiving old chats.

Long tasks must create/update a RUNNING checkpoint after each major verifiable step, branch/HEAD/PR change, Actions or Artifact result, blocker, next-action change, or permission-boundary change. Chat memory is only a retrieval clue and must not be used as current technical authority.
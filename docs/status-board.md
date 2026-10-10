# Status board

Notion is the only status board. It is reached through the Notion MCP server in `.mcp.json`.

**Board:** not created yet. It is created, and its link added here, in the first session after Notion is connected (D35).

Properties:
- Name.
- Status: `Backlog`, `In Progress`, `Blocked` or `Done`.
- Owner, Branch and Owned files.
- Acceptance criteria, Test command and Evidence.

Cards:
- One card per lane PRD in `docs/features/` (feat-01 to feat-06).
- One card per deliverable the brief requires: working prototype, setup instructions, architecture overview, equivalence and routing write-ups, and AI usage disclosure.
- One card for the submission, which only the user can complete. Its proof is the user's confirmation.

Each card is seeded only after `grill`. Design stays in the repo docs.

A card is Done only after a check that ran, with three-part evidence:
1. The command and its result, including the failure seen first.
2. The judgment calls made without the user.
3. What the diff review found.

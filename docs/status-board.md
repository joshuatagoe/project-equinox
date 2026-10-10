# Status board

Notion is the only status board. It is reached through the Notion MCP server in `.mcp.json`.

**Board:** [Equinox status board](https://app.notion.com/p/cb823378cdeb408bbb9bb9483de963c4) (data source `collection://3c48e59b-14b5-4067-928b-7035281aa974`), created 2026-10-10 (D35).

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

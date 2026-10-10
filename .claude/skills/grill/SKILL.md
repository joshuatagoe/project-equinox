---
name: grill
description: Question a slice from product, engineering, and QA before a Notion card is created and again before every commit. Use before seeding deliverables, before any commit, and when acceptance criteria are still ambiguous. Records routine choices as assumptions and stops for scope, API, schema, auth, or spend. A skipped grill means no commit.
---

# Grill

Run this before `tdd-plan-implementer` seeds a Notion card. One slice at a time. Do not create the card here.

## Ask once

One message, only what the plan and the repo do not already answer:

- **Product** — who it is for, and what is out of scope
- **Engineering** — files, contracts, and failure behavior
- **QA** — the checks that prove it, including a negative case

## Assumptions

If the answer is a routine technical choice and you are at least 80% sure, record it as an assumption and continue. Stop when a question would change scope, a public API, schema or data flow, auth, or spend.

## Hand off

After the user answers, or accepts the named assumptions, those answers are the acceptance criteria. They are not a restatement of the whole plan. `tdd-plan-implementer` seeds the card from them.

## Before every commit

Run this again on the diff, in the same turn you would otherwise commit. This pass is not optional and is not the same as the seed-time grill. One message, against what the user already accepted:

- **Product** — did user-facing behavior drift, and what is still out of scope
- **Engineering** — which files, contracts, or failure behavior changed
- **QA** — which checks proved it, including the negative case, and the failure seen before the code
- **Logs** — this diff's decisions, cuts, and AI course-corrections are in `docs/DECISIONS.md` and `docs/AI_USAGE.md`

Do not commit, push, or mark the card Done in that same message. Wait for an answer or an explicit acceptance of the named assumptions. If grill was skipped, there is no commit.

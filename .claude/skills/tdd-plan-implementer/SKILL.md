---
name: tdd-plan-implementer
description: Implement one slice of the repo plan test-first and record status on the Notion board. Use when the user asks to implement, continue, or finish a plan, architecture document, milestone, or issue in this repo. Follows grill before seeding a card and again before every commit, writes the failing test before the code, freezes approved tests, caps repair loops, limits a parallel worker to the files it owns, and refuses Done without command evidence, judgment calls, and a diff review. A skipped grill means no commit.
---

# TDD plan implementer

The plan is the design. Notion is the status. Implement one vertical slice at a time: the thinnest path that is usable end to end.

## 1. Resolve and seed

Read the plan completely. Do not write a document that restates it.

If several plan files disagree, ask which one to use.

Before any code, follow `grill` for each remaining deliverable. Seed a Notion card only after the user has answered, or has accepted the named assumptions. The card's acceptance criteria are those answers, not a restatement of the plan. Each card starts in Backlog and also carries outcome, dependencies, owned files, and the test command. A card moves to In Progress when work starts, to Blocked with the exact decision that unblocks it, and to Done only with the evidence in §7.

When the plan lists a deliverable only a person can finish (a video, a post, a spend, a login, or an approval), seed a Backlog card for it in that same read. The card names the outcome and the proof: a link, a receipt, or a yes. It has no test command and no owned files. Do not do that work. Seeding a spend card is not permission to spend. Mark it Done only when that proof exists.

If Notion is unreachable, stop. Do not open a markdown kanban.

When resuming, classify each deliverable from the repo and from a check, not from a checkbox or a prior chat: complete, partial, unverified, or not started. Write that onto the card. Leave complete work alone. Stop only if the repo contradicts the plan.

## 2. Orient

In one short paragraph, note repo instructions, git status, what already exists, and the test commands. Run the narrow tests for this area before editing, and record failures that already existed.

## 3. Test first

1. Write the test from the acceptance criteria, including a boundary or negative case.
2. Run it and watch it fail because the behavior is missing, not because of setup.
3. Write the smallest code that makes it pass.
4. Refactor only while the test is green.

Self-check the new test before freezing it: it would still fail if the behavior were wrong, it does not assert an implementation detail, and it does not skip the unit under test with a mock.

A test is frozen when it was approved as a checkpoint, written by someone else, or is a golden answer the project gates on. Do not edit a frozen test. If it looks wrong, stop and name the requirement it contradicts.

If tests for this slice already exist, run them, confirm the expected failure, and implement. Do not weaken, skip, or delete a test to go green.

## 4. Parallel worker

If the dispatch names files you own, edit nothing else. If the slice needs a shared contract, schema, config, or CI file, stop and report it. A slice with UI stays on the main checkout and uses the one shared dev server. Do not start another server. End by saying whether you touched anything outside your ownership. "None" is the expected answer.

## 5. Verify and repair

Run the targeted tests, quote the result, then run the broader suite and the lint, type, and build checks that apply. A failure that existed at the baseline is reported, not silently fixed, unless it blocks this slice.

Never claim a test passed unless it ran in this session.

On a failure: capture the exact error, pick one cause, fix the smallest thing, rerun the narrow test. Cap at 3 attempts per failure class and 8 cycles per slice. Stop if the same failure repeats twice with no new evidence. "The test is wrong" and "this is a flake" need a reread of the requirement and an isolated rerun. That permission does not cover frozen tests.

## 6. Gates

Routine choices (naming, layout, library-idiomatic patterns) proceed when you are at least 80% sure. Pause and ask before:

- changing product scope or user-facing behavior
- changing a public API or wire contract
- any schema, migration, or data-flow change, including ones that look small
- changing auth, privacy, or security boundaries
- destructive or irreversible actions
- spend, pushes, or deploys

A commit is not one of those pauses. It waits on `grill` (§7). Ask before writing the schema change. State the change, what reads and writes it, and whether it is reversible. Approval to write a migration is not approval to run it anywhere but a disposable local database.

## 7. Close the slice

Read the diff for scope creep, secrets, debug leftovers, and unrequested dependencies. Grep the plan and README for names this slice changed. If the plan or README states a test count, re-run the suite and update or remove that number in the same change. A stale count is not a design change. If a doc edit would change the plan, ask first. If nothing is stale, say so in one line.

Report outcome, files, and deviations. Then run `grill` on this diff and stop. Do not commit in that message. Commit only after the user answers or accepts the named assumptions. A skipped grill means no commit. Then continue to the next slice unless a gate or a blocker stops you.

Put Evidence on the Notion card before Done. It has three parts, or the card stays In Progress:

- the command that ran and its result, including the failure seen before the code
- judgment calls made without the user
- what the diff review found: scope, secrets, debug leftovers, and stale plan or README lines

A pass/fail line alone is not Evidence. Refuse Done without all three parts.

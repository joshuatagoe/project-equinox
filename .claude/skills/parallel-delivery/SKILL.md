---
name: parallel-delivery
description: Split a plan across simultaneous agents that share one architecture and do not edit the same files. Use when the user asks for multiple agents, parallel implementation, or worktrees. Coordinator only. UI slices stay on the main checkout and one dev server. Each worker follows tdd-plan-implementer, runs grill before any commit, and a card is Done only with that skill's three-part evidence.
---

# Parallel delivery

Use this when more than one agent will implement at once. You are the coordinator. Workers follow `tdd-plan-implementer` and, when the slice has UI, `frontend-engineer`.

## Split

Read the plan and the Notion backlog. Settle shared contracts (APIs, schemas, types other slices import) before anyone starts. Assign the first thin end-to-end slice to one agent.

Give later slices to separate agents only when their owned files do not overlap. Slices that touch the same file run one after another, more complex ones later.

## Where it runs

Non-UI slices get a separate git worktree and branch. A slice with UI stays on the main checkout. One dev server serves that app. Do not start a second server or assign a port per worktree. Browser verification uses that single app.

## Brief

Every brief includes the plan path, the Notion card, owned paths, forbidden paths, the test command, and the instruction to follow `tdd-plan-implementer`, including `grill` before any commit. A worker that commits without that grill is stopped.

A UI brief also names the main checkout and forbids a private dev server. A non-UI brief names its worktree and branch.

A worker that needs a shared file stops and reports. Do not let it edit that file.

## Integrate

Read the card and the command output. Do not ask a worker to narrate status.

Merge in dependency order only after `grill` has been run on that slice's diff and the user has accepted it. After the wave, run the integration checks once. Mark a card Done only when its Evidence has the three parts required by `tdd-plan-implementer` §7, including that grill. A pass/fail line is not enough.

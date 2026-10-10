# AI usage log

How AI was used on this project: tools, what worked, where it misled us, and how we corrected course. Entries are dated and added in the same commit as the work they describe. The brief asks for AI usage to be disclosed; this file is that disclosure.

## Tools

- **Antigravity agent session** — wrote `docs/prd.md`, ran an "architectural review" subagent (`docs/architectural_review.md`), wrote `docs/architecture.md`, `user/users.md`, and feature PRDs `docs/features/feat-01` to `feat-04`.
- **Claude Code (Claude Opus 5.5)** — reviewed those documents against the brief, ran the specified code, and ran research subagents for venue facts.

## 2026-10-10 — PRD, review and architecture (Antigravity)

### What worked
- **A separate reviewer pass on the PRD.** It raised integer contract sizes, bid-only order books, fee-on-average-price, partial-fill ranking and an unenforced budget. Those became D3–D7. Its facts about the venues are still being checked (D12).

## 2026-10-10 — Resuming in Claude Code

### What worked
- **Four research subagents in parallel, each told to label every fact and to check the earlier claims rather than confirm them.** They returned sourced answers and raw API responses in about ten minutes, and found seven errors in the earlier review (item 6).

### Where AI misled us or we course-corrected
1. **The review said it audited "against the live APIs" but cites no sources.** Caught by reading `docs/architectural_review.md`: no URLs or quotes anywhere. Correction: D12, a research pass that labels each venue fact. Lesson: an unsourced "ground truth" is UNCONFIRMED until checked.
2. **The feat-03 numeric veto lets "25 bps" vs "50 bps" through when both titles name the year.** Caught by running the spec's code unchanged: "Will the Fed cut rates by 25 bps in December 2025?" vs the 50 bps version scored 0.946, EQUIVALENT, because "2025" counts as a shared number. Correction: pending in the architecture revision. Lesson: run a spec's code on the cases it claims to handle before handing it to an implementer.
3. **The entity veto (Pennsylvania vs Michigan) is in the PRD but not in the feat-03 code.** Same script: "Will Trump win Pennsylvania in 2024?" vs the Michigan version scored 0.867, EQUIVALENT. Correction: pending.
4. **The matching thresholds were never tried on realistic titles.** A true pair worded the way the two venues word things ("…at the December 2025 FOMC meeting?" vs "Fed decreases interest rates after December 2025 meeting?") scored 0.419, DISTINCT, so the demo would find nothing to route. Correction: pending; acceptance tests will use labelled title pairs taken from real venue data.
5. **The architecture marked its interfaces "LOCKED" while they could not express two of the CLI's exit codes.** The trace had no status field to tell insufficient liquidity (exit 2) from budget exceeded (exit 3); the router never received the match results it was supposed to report; the review's finding about buying NO was not carried into the models. Correction: D11 and the pending architecture revision.
6. **The review's venue facts were wrong in seven places.** Examples: it called macro markets fee-free on Polymarket (the Fed markets charge 0.05), described Kalshi Fed markets as cumulative thresholds (they are mutually exclusive buckets, or thresholds on the rate level), and gave Polymarket Fed markets a month-end close (their `endDate` falls on the decision day). Caught by the D12 research pass, which was asked to check these claims rather than confirm them. Correction: `docs/research/venue_facts.md`, which lists all seven. Lesson: in a research prompt, state an earlier claim as something to test.
7. **The AI widened "check that the architecture could handle Meridian" into building a Meridian adapter.** After the user said to assume Meridian has an API like the other venues, the plan gained a Meridian adapter lane, a synthetic Meridian fixture, a stock-market parser for Polymarket and CLI demo rows. The user corrected it: the goal is robustness to a venue like Meridian, not integration. Correction: D26. The check is now a paper mapping (architecture §9.1) plus hand-built test markets run through the real matcher and router, and the adapter, fixture, parser and demo rows are cut. Lesson: "make sure the system could handle X" asks for evidence that the design fits, not for X to be built.
8. **The AI pushed to the wrong host and skipped GitHub.** Asked to push, it sent the branch to `origin`, which pointed at origin.cursor.com and stalled on a credentials dialog. Then, after the user said the origin is labs.gauntletai.com, it pushed to GitLab only, although the README names both GitHub and GitLab. The user asked "did we also push to github?". Correction: D34, plus a remotes table in the README and AGENTS.md. Lesson: before any push, list the remotes and compare them with the hosts the project names.

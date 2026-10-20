# Progress

The work log for the overnight run of 2026-10-20 (started 12:50, while you're away). Newest first under each heading. This file is where to catch up: what's done, what's next, and the questions only you can answer.

## Task list

| # | Task | Status |
|---|---|---|
| 1 | Commit the last session's unfinished work: the logo reader's fixes, and Wikidata for pages that block us, with tests | done |
| 2 | Model layer: one gateway for Gemini (typed JSON answers, images, retries), a free-tier rate limiter with daily counts, a disk cache of answers, and a log of every call with its tokens and cost | to do |
| 3 | Jev as the Decider (pick one, yes/no, score, find in an image), and Gemini as the Decider's backup when there's no Jev key | to do |
| 4 | Keys from environment variables or the system keychain; `bi2 keys` and `bi2 doctor` | to do |
| 5 | The AI pass for unsure answers: names, logos (numbered screenshot), phones, emails | to do |
| 6 | MCC: schema.org hints, a local search of the 914 codes, Jev to pick, Gemini to break ties | to do |
| 7 | Address: structured data, then address lines in the footer and contact page, then Jev or Gemini; geocoding as a check | to do |
| 8 | More logo sources: Wikidata on every site, the web app manifest, and brand colors from the logo | to do |
| 9 | Agents: an investigator with read-only tools and a budget, for fields still missing; a checker that samples answers | to do |
| 10 | Measure: gold set and test set on saved pages, before and after, with accuracy, cost and time | to do |
| 11 | CI/CD: tests in CI, a nightly live eval, releases to PyPI and a Docker image | to do |
| 12 | An MCP server, so AI assistants can use v2 | to do |
| 13 | Docs: architecture, README, and the scores | to do |

## Done

- **Last session's work, committed.** The logo reader now looks inside shadow roots, CSS masks, slim wordmarks in a logo link, and logos drawn as styled text. Pages that block us or won't load are looked up on Wikidata by their domain, with tests for the lookup, its answers, and the pipeline (309 tests before, all passing).

## Next

- Task 2, the model layer.

## Questions for you

- None yet.

## Notes

- Commits are local only. Nothing has been pushed.
- Your Jev and Gemini keys are on free tiers, so every model call goes through a rate limiter that stays under their limits, and answers are cached on disk so a rerun on saved pages costs nothing.

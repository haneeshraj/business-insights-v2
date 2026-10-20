# Progress

The work log for the overnight run of 2026-10-20 (started 12:50, while you're away). This file is where to catch up: what's done, what's next, and the questions only you can answer.

## Task list

| # | Task | Status |
|---|---|---|
| 1 | Commit the last session's unfinished work: the logo reader's fixes, and Wikidata for pages that block us, with tests | done |
| 2 | Model layer: one gateway for Gemini (typed JSON answers, images, retries), a free-tier rate limiter with daily counts, a disk cache of answers, and a log of every call with its tokens and cost | done |
| 3 | Jev as the Decider (pick one, yes/no, score, find in an image), and Gemini as the Decider's backup and second opinion | done |
| 4 | Keys from environment variables (`GEMINI_API_KEY`, `JEV_API_KEY`); `bi2 keys` and `bi2 doctor` | keys done; the two commands to do |
| 5 | The AI pass for unsure answers: names, logos (numbered screenshot), phones, emails | done |
| 6 | MCC: Jev picks from the official list in two rounds, chain codes, schema.org hints | done |
| 7 | Address: structured data, footer and contact page lines, Wikidata's head office, Gemini, web search; geocoded with Nominatim for the coordinates | done |
| 8 | More logo sources: Wikidata on every site; brand colors from the logo | Wikidata done; colors to do |
| 9 | Agents: the address search investigator; a checker that samples answers | investigator done (Google refuses search on this free key); checker to do |
| 10 | Measure: gold set and test set on saved pages, before and after, with accuracy, cost and time | gold set done; test set running |
| 11 | CI/CD: tests in CI, a nightly live eval, releases to PyPI and a Docker image | done |
| 12 | An MCP server, so AI assistants can use v2 | done |
| 13 | Docs: architecture, README, the scores, a blog article, a logo, diagrams, cost per model and provider | to do |

## Scores so far

On the 56 gold sites' saved pages (the same pages every run, so only the code changes):

| Field | Rules only | With Jev and Gemini | Right and sure, rules only | With Jev and Gemini |
|---|---|---|---|---|
| Company name | 54 of 56 | 56 of 56 | 50 | 55 |
| Logo | 36 of 46 | 36 of 46 | 33 | 36 |
| Phone | 19 of 23 | 19 of 23 | 18 | 18 |
| Email | 42 of 45 | 42 of 45 | 21 | 22 |
| Social links | 37 of 37 | 37 of 37 | 37 | 37 |
| MCC | not built | 53 of 56 | | 49 |
| Address | not built | 26 of 47 | | 11 |

- About 3 to 4 model calls a site, almost all to Jev. A whole gold-set run cost $0.04 at list price, under a tenth of a cent a site; on the free tiers it costs nothing.
- Jev answers in 0.3 to 0.6 seconds. Gemini's free tier takes 15 to 60 seconds a call, and gives Gemini Flash only 20 requests a day, so v2 asks Gemini as little as it can.

## Done

- **The AI pass** (task 5). Jev picks among the rules' own candidates, so it can't make an answer up: the logo box on a numbered screenshot, the name among the page's names, the main phone number, the general email address. Gemini is Jev's backup, a second opinion for logos, and reads names and addresses off the page when no candidate will do. A name or address an LLM gives must be quoted from the page.
- **MCC** (task 6). Jev reads the page in any language and picks from the 914 official codes, in two rounds of one call each. Chains like Air Canada get their own code (3009). An unsure pick is asked again with the options reversed, since Jev leans toward the first option.
- **Address and coordinates** (task 7). Cheapest first: structured data, address lines found by postcodes or street words, the head office Wikidata gives big brands (Rogers, Air Canada), then Gemini. Nominatim (OpenStreetMap, free) adds the coordinates and says whether the map agrees on the postcode.
- **MCP server** (task 12): `bi2 mcp`, with `analyze_website`, `explain_field`, `find_mcc` and `model_usage`.
- **CI/CD** (task 11): CI also builds and installs the wheel; a nightly live eval fails when accuracy drops or a site costs more than $0.005; a version tag publishes to PyPI and ghcr.io.
- **Free tiers** (your rule): every model call takes a turn from a limiter that counts requests per minute and per day, kept in a file so the count lasts across runs. When Google says a quota is used up, v2 stops asking that model until it resets. Answers are kept on disk, so a rerun on saved pages costs nothing.
- **The last session's work**, committed: the logo reader's fixes, and Wikidata for pages that block us.

## Next

- Measure on the 166-site test set (running), and time live runs on a sample.
- Docs: the architecture with the agents, a blog article, a logo, diagrams, and what a site costs on each provider's models.
- `bi2 doctor` and `bi2 keys`; brand colors; the answer checker.

## Questions for you

- **Push to GitHub?** Every commit is local. CI and the release workflow run once it's pushed. The nightly eval needs two repository secrets, `GEMINI_API_KEY` and `JEV_API_KEY`, in an environment named `eval`, and publishing to PyPI needs trusted publishing set up for the project on pypi.org.
- **Google Search grounding** is refused on your free Gemini key, so the head-office search step is skipped. A paid key would turn it on. Without it, a chain's head office comes from Wikidata when it's there.
- **Gold-set answers to check:** Warby Parker's MCC (v2 says 8044, "Optical Goods and Eyeglasses"; the gold set says 8043), Grace O'Malley's (7801, licensed online gambling, against 7995).

## Notes

- One test, `tests/cli/test_review.py::test_only_the_page_it_served_can_save_checks`, fails now and then on Windows with a dropped local connection when the machine is busy, and passes when run again. It did before tonight's changes too.
- Usage was checked every 5 minutes, as you asked, and the session pauses at 90%.

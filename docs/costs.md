# What a site costs, and how long it takes

Measured on 2026-10-20, on the gold set's 56 sites and the test set's 165, from each run's own log of model calls (`model-calls.jsonl`). `python eval/cost_per_site.py bi2-results/<run>` prints these tables for any run.

## Where the money goes

A site's model calls, on the gold set's saved pages, with every question asked afresh:

| | Per site |
|---|---|
| Model calls | 3.4: 2.5 to Jev, 0.9 to Gemini |
| Jev input tokens | 8,986, almost all the MCC's first round, which lists 319 codes |
| Gemini tokens, in and out | 766 and 48 |
| Cost at list price | $0.00073 |
| Cost on the free tiers | $0 |

On the test set's 166 sites, which no rule was tuned on, with every question asked afresh:

| | Per site |
|---|---|
| Model calls | 3.9 on average, 7 at most (the cap is 12): 3.7 to Jev, 0.5 to Gemini |
| Jev input tokens | 10,283 |
| Gemini tokens, in and out | 473 and 37 |
| Cost at list price | $0.00066 on average, $0.00052 the median, $0.00154 the most |
| The whole run | $0.11 at list price for 166 sites; nothing on the free tiers |

The rules answer most fields with no model at all. A model is asked only about the answers the rules aren't sure of, and only with the evidence that answer needs: a few labeled lines, never the page's HTML.

## The same calls on other providers' models

bi2's split is Jev for decisions (pick one of these, yes or no) and an LLM for generation (read this name or address off the page). The table prices the gold run's own token counts on other models, both ways: with Jev making the decisions, and with the LLM making them too.

For an LLM making Jev's decisions, each one costs the same input plus about 250 tokens of instructions that turn it into a JSON question, and about 40 output tokens a question. List prices per million tokens, as published on 2026-10-20: Google's and Anthropic's from their pricing pages; OpenAI's and Jev's from third-party price lists, since their own pages couldn't be read.

| Models | Input / output price | Per site | Per 1,000 sites |
|---|---|---|---|
| **Jev + Gemini 3.5 Flash-Lite** (the default) | $0.042 / free; $0.30 / $2.50 | **$0.00073** | **$0.73** |
| Gemini 3.5 Flash-Lite alone | $0.30 / $2.50 | $0.00347 | $3.47 |
| Jev + Gemini 3.6 Flash | $0.75 / $3.75 | $0.00113 | $1.13 |
| Gemini 3.6 Flash alone | | $0.00832 | $8.32 |
| Jev + Gemini 3.1 Pro | $2.00 / $12.00 | $0.00248 | $2.48 |
| Gemini 3.1 Pro alone | | $0.02248 | $22.48 |
| Jev + Claude Haiku 5.5 | $0.10 / $0.50 | $0.00048 | $0.48 |
| Claude Haiku 5.5 alone | | $0.00111 | $1.11 |
| Jev + Claude Sonnet 5.5 | $2.00 / $10.00 | $0.00239 | $2.39 |
| Claude Sonnet 5.5 alone | | $0.02218 | $22.18 |
| Jev + Claude Opus 5.5 | $4.00 / $20.00 | $0.00440 | $4.40 |
| Claude Opus 5.5 alone | | $0.04437 | $44.37 |
| Jev + GPT-5.4 nano | $0.20 / $1.25 | $0.00059 | $0.59 |
| GPT-5.4 nano alone | | $0.00225 | $2.25 |
| Jev + GPT-5.4 mini | $0.75 / $4.50 | $0.00117 | $1.17 |
| GPT-5.4 mini alone | | $0.00843 | $8.43 |

- **Jev makes every pairing cheaper,** by 2 to 10 times, because most of the tokens are decisions, and Jev charges $0.042 a million input tokens and nothing for output. Its answers also come with a probability for every option, which an LLM's stated confidence doesn't give.
- **The generation model barely matters** to the total: under one call a site.
- **Google Search grounding,** for the investigator, costs $14 per 1,000 searches on Gemini 3 models after 5,000 free a month, and isn't offered on the free tier.

### Against v1

v1 sent each homepage's cleaned HTML, 4,000 to 104,000 tokens, in each of its calls: one for the brand, two for the MCC and one or two for the address. At 30,000 tokens a call and four calls a site on Gemini 2.5 Flash ($0.30 / $2.50), that's about $0.04 a site, some 50 times bi2's default, for four fields instead of seven.

## Where the time goes

| Step | Time |
|---|---|
| Loading the page in the browser, live | about 19 s, the median on 45 live sites on 2026-10-13 |
| Evidence and rules, with no model | about 0.3 s |
| A Jev call | 0.2 to 0.6 s, the median, when the free tier's 20 a minute leave room; 2.5 to 3.7 a site |
| A Gemini call on the free tier | 15 to 60 s, the median 53 s in the gold run, with the limiter's waits |
| A Gemini call on a paid tier | typically 1 to 3 s (not measured here) |
| Geocoding | 1.1 s per address, one request a second for the whole run, as Nominatim asks |

On 24 live sites from the gold set, loaded in the browser with `--fast` (Jev alone), three at a time, with every question asked afresh:

| | Per site |
|---|---|
| Wall-clock time, median | 16.7 s, page load included |
| 90th percentile | 51.3 s, for slow sites and ones whose contact page was read too |
| Jev calls | 2.8, with a median of 0.2 s each |
| Cost at list price | $0.00039 |
| Fields answered | names 23 of 24, logos 24, MCC 24 (22 sure), phones 19, emails 17, addresses 16 |

### At scale: the 166-site test set, live

All 166 test-set sites loaded live in the browser on 2026-10-20, with Jev alone (`--fast`), three at a time, every question new:

| | |
|---|---|
| The whole run | 25.1 minutes: 9.1 seconds a site of wall-clock time |
| Each site's own time | 26.6 s, the median; 45.0 s, the 90th percentile |
| Sites that wouldn't load | 7 of 166, behind bot checks or timing out |
| Jev calls | 2.9 a site; 480 in all |
| Cost at list price | $0.066 for the run: $0.0004 a site |
| Sure answers | names 152, logos 145, MCC 127, social links 140, phones 98, emails 85, addresses 42 |

Three at a time kept the browser's memory low on a machine shared with other work; the default is one site for every two cores, up to 8.

- **On the free tiers, the limits are the bottleneck.** Jev's calls wait for room in its 20 a minute when many sites run at once: on the 166-site test set, six at a time, a Jev call took 40 seconds, the median, almost all of it waiting for its turn, and a site took 61 seconds. A paid tier's higher limits remove the wait, and the page load is what's left.
- **Gemini on its free tier is slower still.** A site that needs one Gemini call waits as long as the page took to load, or longer. `--fast` leaves Gemini out and keeps Jev.
- **Several sites at once:** one site for every two cores, up to 8. On 2026-10-13, 45 live sites took 223 seconds at 8 at once, about 5 seconds a site of wall-clock time.

## Fewer calls: fan-out

When a site's specialists ask Jev at the same time, their questions go in one call. On the gold set, with every question new, that took 154 Jev calls instead of 176, with one name less sure and one phone and one email surer. Sending the MCC's first round along too would save 38% of calls, but left one more answer unsure, so it goes on its own.

## The free tiers' capacity

What a day of free tiers covers, at the gold set's calls per site:

| Model | Free requests a day | bi2 uses up to | Sites a day |
|---|---|---|---|
| Jev | not published; v2 caps itself at 2,000 | 90%: 1,800 | about 730, at 2.5 calls a site |
| Gemini 3.5 Flash-Lite | not published; over 250 on 2026-10-20 | 90% of the cap in `data/models.toml` | the rest of the day's sites, at under one call a site |
| Gemini 3.5 Flash | 20, as Google reported on 2026-10-20 | 18 | the backup only |

Every answer is kept on disk, so a rerun of the same site asks no model at all.

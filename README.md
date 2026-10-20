<p align="center"><img src="docs/assets/wordmark.svg" alt="bi2, Business Insights v2" width="420"></p>

# Business Insights v2

Find a business's name, logo, merchant category code (MCC), head-office address with map coordinates, phone number, email address and social media links from its website. It's built for bank teams that do merchant onboarding, KYB, merchant risk and transaction enrichment.

Every answer comes with a status (`ok`, `needs_review`, `not_found` or `error`), a confidence, its source and the evidence it rests on, so an analyst can check it. Nothing is guessed.

```
$ bi2 analyze https://bellwoodsbrewery.com/ https://www.barvolo.com/ ... --fast
[5/24] https://bellwoodsbrewery.com/  name ok  logo ok  mcc ok  address ok  phone ok  email ok  social ok  7.1 s
```

| Field | Answer, from a live run on 2026-10-20 |
|---|---|
| Name | Bellwoods Brewery |
| Logo | its SVG wordmark, saved from the page's code; brand color #ee412f |
| MCC | 5921, Package Stores: Beer, Wine and Liquor |
| Address | 124 Ossington Ave, Toronto, ON M6J 2Z5, with its map coordinates |
| Phone | +14165354586 |
| Email | info@bellwoodsbrewery.com |
| Cost | 2 Jev calls, $0.00037 at list price |

## How it works

Evidence first, models last. bi2 reads the page once, with no model: its structured data, meta tags, the images that could be its logo with their places on the screenshot, its phone numbers, emails, postcodes and links, and what Wikidata knows about big brands. Then seven field specialists run at once, each climbing a ladder that stops at the first sure answer:

1. **Rules**, free and instant.
2. **[Jev](https://docs.typesafe.ai)**, a typed-decision model, picks among the rules' own candidates with a probability: which numbered box is the logo, which code fits, which number is the main one. It answers in under a second and can't make an answer up.
3. **Gemini** reads what no candidate covers, like a name inside a logo or an address in an unfamiliar format, and must quote the page.
4. **An investigator** searches the web for what the pages never say, like a chain's head office.

![architecture](docs/assets/architecture.svg)

Read more in [the architecture](docs/architecture.md), [what a site costs](docs/costs.md), and [the blog post](docs/blog/evidence-first-models-last.md).

## Results

On the 56 gold sites, with Jev and Gemini, on the same saved pages every run:

| Field | Right | Rules alone |
|---|---|---|
| Company name | 56 of 56 | 54 |
| Logo | 36 of 46 | 36 |
| MCC | 53 of 56 | not built |
| Head-office address | 30 of 47 (14 sure) | not built |
| Phone | 19 of 23 | 19 |
| Email | 42 of 45 | 42 |
| Social links | 37 of 37 | 37 |

About 3 model calls a site, almost all to Jev: under a tenth of a cent a site at list prices, and nothing on the free tiers.

## Install

```
pip install "business-insights[mcp]"     # or: uv tool install "business-insights[mcp]"
playwright install chromium
```

Add a key, or both. Without one, bi2 uses its rules alone.

```
bi2 keys set jev          # saved in the system keychain; or set JEV_API_KEY
bi2 keys set gemini       # or set GEMINI_API_KEY
bi2 doctor                # checks the keys, the models, the browser and the free services
```

Free keys work. bi2 keeps every model under its free tier's limits per minute and per day, counts each day's requests across runs, and keeps every answer on disk, so asking about the same site twice asks no model twice.

## Use

| Command | Does |
|---|---|
| `bi2 analyze <url> [<url>...]` | Analyze sites; results (JSON Lines and CSV), logos and an HTML report go to `bi2-results/analyze` |
| `bi2 analyze --file sites.txt` | Analyze a list of sites, one a line |
| `bi2 analyze --gold eval/gold.toml` | Analyze the gold set and score it |
| `bi2 analyze ... --fast` | Jev alone, no Gemini: a second or two a site on top of loading the page |
| `bi2 analyze ... --no-ai` | Rules alone, no model calls |
| `bi2 review <results>` | Check answers right or wrong in the browser |
| `bi2 eval score` / `bi2 eval compare` | Score a run, or say what got better or worse between two |
| `bi2 eval check` | Ask the checker about a run's sure answers, and measure it against people's checks |
| `bi2 doctor` | Check the setup |
| `bi2 keys set\|show\|delete` | Keep keys in the system keychain |
| `bi2 mcp` | Run as an MCP server for AI assistants |

### As an MCP server

Add bi2 to Claude Code, Claude Desktop or any MCP client:

```json
{
  "mcpServers": {
    "business-insights": { "command": "bi2", "args": ["mcp"] }
  }
}
```

Its tools: `analyze_website`, `explain_field` (how one field was decided, step by step), `find_mcc` and `model_usage`.

### With Docker

```
docker run --rm -e JEV_API_KEY -e GEMINI_API_KEY -v "$PWD:/data" ghcr.io/haneeshraj/business-insights-v2 analyze https://example.com
```

## Docs

- [Architecture](docs/architecture.md): what v2 does and why
- [Costs](docs/costs.md): what a site costs on each provider's models, and how long it takes
- [Codebase guide](docs/codebase.md): how the code is organized
- [Evaluation](eval/README.md): the gold set, the test set and how answers are judged
- [Contributing](CONTRIBUTING.md): setup and checks
- [Progress](PROGRESS.md): the latest work log

## License

MIT. See [LICENSE](LICENSE).

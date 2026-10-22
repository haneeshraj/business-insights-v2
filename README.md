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
3. **An LLM**, Gemini unless you [choose another](#choose-the-llm), reads what no candidate covers, like a name inside a logo or an address in an unfamiliar format, and must quote the page.
4. **An investigator** searches the web for what the pages never say, like a chain's head office.

![architecture](docs/assets/architecture.svg)

Read more in [the architecture](docs/architecture.md) and [what a site costs](docs/costs.md).

## Results

On the 56 gold sites, with Jev and Gemini, on the same saved pages every run:

| Field | Right | Rules alone |
|---|---|---|
| Company name | 56 of 56 | 54 |
| Logo | 36 of 46 | 36 |
| MCC | 55 of 56 | not built |
| Head-office address | 31 of 47 (25 sure) | not built |
| Phone | 19 of 23 | 19 |
| Email | 42 of 45 | 42 |
| Social links | 37 of 37 | 37 |

On the 166-site test set, which no rule was tuned on, counting the answers a person or a drafted check against the site's own pages has verified:

| Field | Right | Right and sure | Right and sure, rules alone |
|---|---|---|---|
| Company name | 110 of 116 | 106 | 94 |
| Logo | 101 of 116 | 96 | 86 |
| Phone | 115 of 133 | 99 | 83 |
| Email | 139 of 145 | 89 | 80 |
| Social links | 107 of 115 | 95 | 95 |
| MCC | 142 of 148 | 128 | not built |

The MCC checks are drafted against each site's title and description, and not yet confirmed by a person.

A sure answer is one nobody checks, so the costliest mistake is a sure answer that's wrong. How often that happened, counted with `python eval/calibration.py`:

| Field | Gold set | Test set |
|---|---|---|
| Company name | 0 of 54 | 3 of 109 |
| MCC | 0 of 51 | 2 of 130 |
| Phone | 1 of 20 | 3 of 102 |
| Email | 0 of 23 | 0 of 89 |
| Social links | 0 of 37 | 4 of 99 |
| Logo | 1 of 38 | 8 of 104 |
| Head-office address | 3 of 28 | not checked yet |

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

## Choose the LLM

Gemini is the default, since its free tier is enough to try bi2. Any of these can take its place or be its backup, named as `provider:model`:

| Provider | For example | Its key |
|---|---|---|
| Google Gemini | `gemini:gemini-3.5-flash` | `GEMINI_API_KEY` |
| Anthropic | `anthropic:claude-haiku-5-5` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai:gpt-5.4-mini` | `OPENAI_API_KEY` |
| Mistral, Groq, DeepSeek, xAI, Cohere, Perplexity | `mistral:mistral-small-latest`, `groq:llama-3.3-70b-versatile` | `MISTRAL_API_KEY`, `GROQ_API_KEY` and so on |
| OpenRouter, Together, Fireworks, Cerebras, Hugging Face | `openrouter:meta-llama/llama-3.3-70b-instruct` | `OPENROUTER_API_KEY` and so on |
| Ollama, LM Studio, vLLM | `ollama:llama3.1:8b` | none |

A model bi2 lists can go by its name alone, like `claude-haiku-5-5`, and so can one whose name says whose it is, as in v1: `gpt-…`, `claude-…`, `gemini-…`, `mistral-…`, `grok-…`. Any other server that speaks OpenAI's chat API can be added by its address.

`bi2 config` walks you through it with the arrow keys: the provider, then the model, listing the ones your key can use, then any settings, like the temperature, a backup model or the calls a site may make, or the defaults. It saves them in a `bi2.toml`, yours for every folder or this folder's for a project, and the key in the system keychain, never in the file.

Or set it wherever bi2 runs:

| Where | How |
|---|---|
| One run | `bi2 analyze <url> --model anthropic:claude-haiku-5-5 --backup-model none` |
| A project or a team | a `bi2.toml` in its folder, like the one below |
| CI, Docker, a server | `BI2_AI__LLM_MODEL=openai:gpt-5.4-mini` and the provider's key, like `OPENAI_API_KEY` |
| An MCP client | `"args": ["mcp", "--model", "openai:gpt-5.4-mini"]` |

```toml
[ai]
llm_model = "anthropic:claude-haiku-5-5"
backup_model = "gemini-flash-lite-latest"  # asked when the first is down or out of requests; "none" for none
search_model = "gemini-3.5-flash"          # web searches for head offices; only Gemini searches here
temperature = 0.0

[providers.ollama]
base_url = "http://gpu-box:11434/v1"       # another machine's Ollama

[models."openai:gpt-5.4-mini"]
per_minute = 5000                          # a paid key's limits, in place of the free tier's
```

Each layer overrides the one before it: the defaults, your own `bi2.toml`, this folder's (or the file `BI2_CONFIG` names), environment variables like `BI2_AI__TEMPERATURE=0.2`, then a command's flags. `bi2 config show` prints every setting and where it came from, and `bi2 doctor` checks that each provider takes its key and offers the model you named. A model bi2 doesn't list runs with modest limits and no price, until a `[models."provider:model"]` table gives it its own.

## Use

| Command | Does |
|---|---|
| `bi2` | At a terminal, an interactive session: paste addresses, then `/show`, `/why`, `/export` |
| `bi2 analyze <url> [<url>...]` | Analyze sites; results (JSON Lines and CSV), logos and an HTML report go to `bi2-results/analyze` |
| `bi2 analyze --file sites.txt` | Analyze a list of sites, one a line |
| `bi2 analyze --gold eval/gold.toml` | Analyze the gold set and score it |
| `bi2 analyze ... --fast` | Jev alone, no LLM: a second or two a site on top of loading the page |
| `bi2 analyze ... --no-ai` | Rules alone, no model calls |
| `bi2 analyze ... --model <provider:model>` | Ask another LLM this run |
| `bi2 review <results>` | Check answers right or wrong in the browser |
| `bi2 eval score` / `bi2 eval compare` | Score a run, or say what got better or worse between two |
| `bi2 eval check` | Ask the checker about a run's sure answers, and measure it against people's checks |
| `bi2 config` / `bi2 config show` | Choose the LLM and its settings, or see every setting and where it came from |
| `bi2 doctor` | Check the setup |
| `bi2 keys set\|delete <provider>`, `bi2 keys show` | Keep keys in the system keychain, and see which are set |
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

Its tools: `analyze_website`, `explain_field` (how one field was decided, step by step), `find_mcc` and `model_usage`. Add `"--model", "anthropic:claude-haiku-5-5"` to the args for another LLM; the server reads keys from the keychain or the environment, like the terminal app.

### With Docker

```
docker run --rm -e JEV_API_KEY -e GEMINI_API_KEY -v "$PWD:/data" ghcr.io/haneeshraj/business-insights-v2 analyze https://example.com
```

The container reads a `bi2.toml` in the folder mounted at `/data`, or the model from the environment: `-e BI2_AI__LLM_MODEL=openai:gpt-5.4-mini -e OPENAI_API_KEY`. For an Ollama on the same machine, add `-e BI2_PROVIDERS__OLLAMA__BASE_URL=http://host.docker.internal:11434/v1`.

### In CI

Set the model and the provider's key in the job's environment, with the key from the CI's secrets:

```yaml
- run: bi2 analyze --file sites.txt --out results
  env:
    BI2_AI__LLM_MODEL: anthropic:claude-haiku-5-5
    ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
```

This repository's nightly eval (`.github/workflows/eval.yml`) takes its models from the repository variables `BI2_LLM_MODEL` and `BI2_BACKUP_MODEL`, and a run started by hand can name its own.

## Docs

- [Architecture](docs/architecture.md): what v2 does and why
- [Costs](docs/costs.md): what a site costs on each provider's models, and how long it takes
- [Codebase guide](docs/codebase.md): how the code is organized
- [Evaluation](eval/README.md): the gold set, the test set and how answers are judged
- [Contributing](CONTRIBUTING.md): setup and checks

## License

MIT. See [LICENSE](LICENSE).

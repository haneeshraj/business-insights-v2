# Codebase guide

Status: draft, 2026-10-09. This is the companion to [architecture.md](architecture.md). That doc says what v2 does and why; this one says where code goes and how to write it.

## Goals

1. **Easy to understand.** A new contributor can find where anything lives, and the whole codebase follows the same few patterns.
2. **Easy to extend.** Adding a field, a model provider, a country or an output format means adding files, not editing the core.
3. **Easy to test.** Every test except the live eval runs without network access or API keys.
4. **Conventions are checked by tools.** Contributors don't have to memorize them, and reviewers don't have to police them.

## Lessons from v1

| v1 problem | v2 rule |
|---|---|
| `utils/` mixed unrelated things: the LLM client, config loading, URL-list loading and terminal colors | There is no `utils` folder. Helpers live in modules named after their topic. |
| The agents printed to the terminal themselves | Library code emits events and never prints. Only the terminal app and the server decide how to show progress. |
| A config singleton, with `.env` loaded when a module was imported | Settings are loaded once by the entry point and passed in. Environment variables are read in one file only. |
| Result dicts whose keys drifted between modules (`geocoding` vs `geocoding_result`, two location schemas) | Pydantic models between every stage, checked by mypy |
| Bare `except:` blocks and silent fallbacks | Typed errors that map to field statuses |
| A hard-coded list of allowed model names | A model registry data file, with aliases |
| `sys.path.append` in the entry points | An installed package with console-script entry points |

## Layers

```
   cli · server · eval · wiring               entry points: build a RunContext, call the pipeline
                  │
     ┌────────────┴─────────────┐
     ▼                          ▼
  logic                      infrastructure
  pipeline, resolvers,       fetch, llm, decide, retrieval,
  agent, evidence            services, adapters
  (pure, or uses ports)      (implements ports, does the I/O)
     │                          │
     └────────────┬─────────────┘
                  ▼
                core                          models, ports, errors, settings, events, pure helpers
```

- **`core`** imports nothing else from `bi2`.
- **Logic** never imports infrastructure. It reaches the outside world only through the interfaces ("ports") defined in `core/ports.py`, which it receives in the `RunContext`.
- **Infrastructure** never imports logic. Each module implements one or more ports.
- **Entry points** are the only code that imports both. They choose the implementations and wire them together, through `wiring.py`.

CI checks these rules with import-linter, so a pull request that breaks them fails.

Why it matters:
- Logic can be tested with fakes.
- The terminal app and the website share the logic unchanged.
- Swapping a provider never touches resolver code.
- The website can scale by adding workers, because the logic doesn't know where it runs.

## Package layout

```
src/bi2/
├── core/                   building blocks; imports nothing else from bi2
│   ├── models.py           Status, FieldResult, SiteResult, PageSnapshot, Evidence and its parts
│   ├── ports.py            interfaces for everything that does I/O
│   ├── errors.py           exception types, and the field status each one maps to
│   ├── settings.py         the config schema and loader; the only file that reads env vars
│   ├── events.py           progress events and the EventSink interface
│   ├── text.py             whitespace, accents, company-name normalization, name matching
│   ├── urls.py             URL normalization, registrable domain, same-site checks
│   ├── netsafety.py        which IP addresses may be fetched (pure; the DNS lookup is in fetch/)
│   ├── hashing.py          content hashes and stable cache keys
│   ├── money.py            token usage → cost, using the model registry
│   ├── aio.py              bounded concurrency, timeouts, retry with backoff
│   ├── clock.py            Clock interface, with real and fake clocks
│   └── context.py          RunContext: the settings and ports a run needs
├── data/                   shipped data files (see "Data files")
├── prompts/                one folder per prompt (see "Prompts")
├── evidence/               extract_* functions: page snapshot → Evidence
├── resolvers/              cascade.py, plus name.py, logo.py, mcc.py, address.py
├── agent/                  the investigator and its read-only tools
├── pipeline.py             fetch → evidence → resolvers → SiteResult, emitting events
├── fetch/                  Playwright and plain-HTTP fetchers, with the DNS safety check
├── llm/                    the gateway, provider adapters (gemini, openai, anthropic), prompt loader
├── decide/                 JevDecider and LLMDecider
├── retrieval/              local embedding model and MCC vector search
├── services/               search (SerpAPI) and geocoding (Nominatim)
├── adapters/
│   ├── local/              files, in-memory cache and rate limiter, keys from env or keychain
│   └── hosted/             Postgres store, Redis cache, limiter and queue, encrypted keys
├── wiring.py               builds a RunContext from real implementations: local and hosted
├── cli/                    Typer commands, the interactive session, Rich display, output writers
└── server/                 FastAPI app, accounts, worker (installed with the `server` extra)
```

Each package's `__init__.py` starts with a docstring saying what belongs in it and what doesn't, so the answer to "where does this go?" is in the code itself.

## Where shared helpers go

- **A helper lives next to the only code that uses it.** Move it into `core/` when a second package needs it, and only if it is pure (no I/O).
- **Helpers that do I/O** belong with the infrastructure they serve, for example the shared HTTP client in `fetch/`.
- **Modules are named after their topic** (`text.py`, `urls.py`), never `utils.py`, `helpers.py` or `misc.py`.

The core helpers v2 starts with:

| Module | Functions |
|---|---|
| `text.py` | `clean_space(s)`, `fold(s)` (case and accents removed, for comparing), `normalize_company_name(s)` (drops legal suffixes such as Inc. and Ltd.), `names_match(a, b)` |
| `urls.py` | `normalize_url(url)`, `registrable_domain(url)` (`shop.example.co.uk` → `example.co.uk`), `domain_name(url)` (→ `example`), `same_site(a, b)`, `absolute_url(base, href)` |
| `netsafety.py` | `is_public_address(ip)` |
| `hashing.py` | `content_hash(data)`, `cache_key(namespace, **parts)` |
| `money.py` | `cost_usd(model, usage)` |
| `aio.py` | `gather_limited(tasks, limit)`, `with_timeout(task, seconds)`, `retry(call, policy)` (honors a provider's retry-after) |
| `errors.py` | `is_retryable(exc)`, `status_for(exc)` |

## The RunContext

Everything a run needs from the outside world travels in one object. The entry point builds it and passes it explicitly. There are no global singletons and no API clients created at import time.

```python
@dataclass(frozen=True)
class RunContext:
    settings: Settings
    fetcher: Fetcher  # Playwright + plain HTTP, with URL safety checks
    llm: LLMGateway  # every model call goes through here: cost log, cache, retries
    decider: Decider  # JevDecider or LLMDecider, chosen by the available keys
    codes: CodeSearch  # MCC vector search
    search: SearchClient | None  # None when there is no SerpAPI key
    geocoder: Geocoder
    cache: Cache
    limiter: RateLimiter
    store: ResultStore
    events: EventSink
    clock: Clock
```

- `RunContext` lives in `core/context.py`, so resolvers can use it without importing infrastructure.
- The builders live in `wiring.py`. The terminal app calls `build_local_context(settings)`, and the website's worker calls `build_hosted_context(settings, job)`.
- A test builds one from fakes in a couple of lines.

## Function conventions

**There are three kinds of functions, named by what they do:**

| Prefix | Does | Example |
|---|---|---|
| `extract_*` | Pure: turns a page snapshot or text into typed data, with no I/O | `extract_logo_candidates(snapshot) -> list[LogoCandidate]` |
| `resolve_*` | Runs one field's cascade, using ports from the context | `resolve_mcc(evidence, ctx) -> FieldResult[Mcc]` |
| `fetch_*` and adapter methods | Does I/O, behind a port | `fetch_page(url) -> PageSnapshot` |

**Every field follows the same recipe.** A resolver is a list of steps handed to one shared helper:

```python
async def resolve_name(ev: Evidence, ctx: RunContext) -> FieldResult[CompanyName]:
    return await run_cascade(
        "company_name",
        steps=[names_from_free_sources, names_by_decider, names_by_llm],
        ev=ev,
        ctx=ctx,
    )
```

Each step returns either `Resolved(value, confidence, source, evidence)` or `Escalate(reason)`. `run_cascade` handles the rest the same way for every field:

- It accepts the first answer whose confidence clears the configured threshold, and the field is `ok`.
- It keeps the best answer that falls short. If no answer clears the threshold, the field is `needs_review` with that best answer, so the analyst has a starting point.
- If no step finds anything, the field is `not_found`.
- A provider error is recorded and the next step runs. If every step fails, the field is `error`, never a guessed default.
- It records which steps ran, what each one cost, and why each one escalated. This becomes the field's audit trail.

**Other rules:**
- **Typing.** Type hints everywhere, checked by mypy in strict mode, and Pydantic models at every boundary between stages.
- **Errors.** Errors are raised as the types in `core/errors.py`. Only `run_cascade` and the pipeline turn them into statuses.
- **No printing.** There is no `print` in library code (enforced by ruff). Progress goes out as events, such as `StageFinished(site, stage, seconds, status)`, and the terminal app or the server decides how to show them.
- **Environment variables** are read only in `core/settings.py` (enforced by ruff's banned-API rule).
- **Documentation.** Every public function has a one-line docstring, and comments explain why, not what.
- **Size.** Aim for about 50 lines per function and 300 per module. Past that, split it.
- **No clever metaprogramming.** Registries are plain dictionaries you can read.

## Extension points

Most contributions should mean adding files plus one registry line:

| To add | You create | You register it in |
|---|---|---|
| A field | A model in `core/models.py`, a resolver, its prompts, gold-set labels | `resolvers/__init__.py` |
| An LLM provider | An adapter implementing `LLMProvider` | `llm/providers/__init__.py` and `data/models.toml` |
| A search or geocoding provider | An adapter implementing the port | `services/__init__.py` |
| A country | Its names, domains, main languages, postcode format and provinces | `data/countries.toml` |
| A platform (Pinterest, Yelp and so on) | Its domains and profile URL patterns | `data/platforms.toml` |
| An output format | A writer | `cli/output.py` |
| An interactive command | A handler function | The command table in `cli/interactive/commands.py` |

Each of these gets a step-by-step guide in `docs/recipes/`. Third-party plugins through Python entry points can come later, if people ask for them.

## Configuration

**There is one schema.** A pydantic-settings model in `core/settings.py` defines every setting, with its type, default and documentation. Config files are TOML, which Python reads natively and which `pyproject.toml` already uses.

**Settings come in layers, lowest priority first:**
1. Defaults in the schema
2. The chosen profile: `cheap`, `balanced` (the default) or `accurate`, from `data/profiles.toml`
3. The user's config file, then a project file (`./bi2.toml`) for team or CI settings. The user's file lives in the user's config folder, found with Typer's `get_app_dir` so the location is right on Windows, macOS and Linux.
4. Environment variables (`BI2_…`)
5. Command-line flags

**Example config file:**

```toml
profile = "balanced"

[run]
concurrency = 4            # sites analyzed at once
page_timeout_s = 20
output_dir = "./bi2-results"

[models]                   # aliases from data/models.toml; override the profile per task
decide = "jev"             # falls back to an LLM when there's no Jev key
vision = "fast"
fallback = "fast"
escalation = "strong"

[thresholds]
accept = 0.85              # confidence needed to accept an answer
mcc_margin = 0.15          # lead the top MCC needs over the runner-up

[search]
enabled = true             # needs a SerpAPI key
locale = "auto"            # taken from the site's country hints

[agent]
enabled = true
max_tool_calls = 5

[cache]
evidence_ttl_hours = 24
```

**Keys are never in config files**, because config files often get committed or shared. The terminal app looks for each key in two places, in this order:
1. The provider's usual environment variable (`GEMINI_API_KEY`, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `SERPAPI_KEY` and Jev's). This is what CI, Docker and servers use.
2. The operating system's keychain: macOS Keychain, Windows Credential Manager, or Secret Service on Linux. `bi2 init` offers to save keys there when one is available. When there isn't one, as on most headless servers, it explains the environment variables instead.

There is no automatic `.env` loading, because a `.env` file in a project folder is easy to commit by accident. `bi2 doctor` shows where each key was found, with all but the last four characters hidden.

**The website** uses the same schema, with its settings taken from environment variables: database and Redis URLs, OAuth client IDs, free tries per account, the free-try daily cap and the shared-result reuse window.

**Two helper commands:**
- `bi2 config show` prints every effective setting and where it came from: default, profile, file, environment or flag.
- `bi2 config schema` prints a JSON schema, so editors can autocomplete and check config files.

## Model registry

`data/models.toml` is the one place that knows about specific models:

```toml
[aliases]
fast = "gemini:gemini-2.5-flash"     # example IDs
strong = "gemini:gemini-2.5-pro"

[models."gemini:gemini-2.5-flash"]
vision = true
structured_output = true
# plus the context window and per-token prices, copied from the provider's pricing page
```

- Config and code refer to aliases or full IDs, never to hard-coded model names.
- When a provider retires a model or changes its prices, one file changes, followed by an eval run.
- `bi2 doctor` warns when a configured model isn't available with the user's keys.

## Data files

Data files ship inside the package and are loaded with `importlib.resources`, so they work after `pip install`:

| File | Contents | Updated how |
|---|---|---|
| `mcc_codes.csv` | The 914 codes and descriptions, from v1 | By hand, rarely |
| `mcc_synonyms.toml` | Plain-language terms for each code ("taproom" and "brewpub" for 5813) | By hand, followed by an eval run |
| `mcc_vectors.npy` + `mcc_vectors.json` | Embeddings of the codes plus synonyms, with the embedding model's name and a checksum of the inputs | Rebuilt by a dev command. CI fails if the checksum doesn't match the inputs. |
| `schema_types.toml` | schema.org business types → likely MCC codes | By hand |
| `models.toml` | Model aliases, capabilities and prices | When providers change models or prices |
| `profiles.toml` | The `cheap`, `balanced` and `accurate` presets | Alongside eval runs |
| `countries.toml` | Each country's names, domains, main languages, postcode pattern and provinces | By hand; adding a country is one entry |
| `legal_suffixes.txt` | Inc., Ltd., LLC, GmbH, S.A. and so on | By hand |
| `platforms.toml` | Platforms where businesses have pages (Pinterest, Instagram, Yelp, TripAdvisor…), with their profile URL patterns | By hand; adding a platform is one entry |

Each file carries a version, and every result records the versions it was produced with.

## Prompts

- Each prompt has its own folder, for example `prompts/mcc_tiebreak/`, holding two files:
  - `prompt.md`: the template, with labeled evidence sections
  - `meta.toml`: version, output schema, temperature and token limit
- Templates use plain `{placeholders}`, not a template engine.
- The prompt version goes into the LLM-call log and into the result.
- Changing a prompt means a new version and an eval run, and the pull request shows the before-and-after scores.

## Output contract

- Every JSON result carries a `schema_version`, so people who build on the terminal app's output know when it changes.
- A breaking change bumps the major version and is listed in the changelog.
- CSV output has one row per site and four columns per field: `<field>`, `<field>_status`, `<field>_confidence` and `<field>_source`.

## Tests

| Kind | What it covers | Needs network or keys? |
|---|---|---|
| Unit | Pure functions: `core` helpers, `extract_*` functions on saved HTML fixtures, `run_cascade` with fake steps | No |
| Contract | One shared test suite per port, run against every implementation (for example both the local and the Redis cache) | No (Redis runs in a container) |
| Replay | The whole pipeline, on synthetic test pages with recorded model responses | No |
| Interactive | The session's command handlers, and its screens captured with Rich's recording console | No |
| Eval | The gold set, against live sites and models | Yes. It runs nightly with the project's keys, and on pull requests that change prompts, models or thresholds when a maintainer triggers it. |

A contributor can run everything except the eval right after cloning.

**Test pages are synthetic.** We write small HTML pages that reproduce the tricky patterns found on real sites: JSON-LD blocks, lazy-loaded and inline-SVG logos, several versions of a logo, footer addresses, cookie banners and so on. They are our own work, so they can be published under the project's license. The repository never contains copies of third-party websites:
- The gold set stores URLs and the expected answers (names, codes, addresses, logo URLs), not page content or images.
- The nightly eval fetches the live sites and publishes scores only.
- Maintainers can keep page snapshots on their own machines for debugging. The snapshot folder is git-ignored.

## Dependencies

Each dependency is here for a reason, and anything new needs one too.

| Package | Why |
|---|---|
| pydantic, pydantic-settings | Typed models and the layered config |
| httpx | Async HTTP for plain fetches, SerpAPI and Nominatim |
| playwright | Rendered pages, element positions and screenshots |
| google-genai, openai, anthropic | Provider SDKs, all installed so any key works out of the box |
| typer, rich | Terminal app commands and display |
| keyring | Saving keys in the operating system's keychain |
| prompt_toolkit | The interactive session's input line: history, completion of `/` commands and multi-line paste, on Windows, macOS and Linux |
| selectolax | Fast HTML parsing with CSS selectors, for evidence extraction (Python's own parser can't select elements) |
| pillow | Shrinking screenshots before they go to a model, drawing numbered boxes for the logo question, detecting real image types |
| phonenumbers | Reliable phone parsing, and country hints from phone numbers |
| tldextract (with its bundled suffix list) | Correct registrable domains (`.co.uk`, `.com.au`) |
| fastembed | The local embedding model for MCC search, without PyTorch. It downloads the small model once and caches it. |
| numpy | Searching the 914 MCC vectors in memory |
| opentelemetry-api | Tracing hooks; an exporter is optional |
| Extra `server` (build phase 4) | FastAPI, uvicorn, the Postgres and Redis clients, the OAuth library |

Jev needs no package of its own: `JevDecider` calls its REST API with httpx.

**Dev tools:**
- uv: environments and the lockfile
- ruff: linting and formatting
- mypy: strict type checking
- pytest, with pytest-asyncio
- import-linter: the layer rules
- pre-commit hooks that run the same checks as CI

**Considered and not needed yet:**
- **extruct:** JSON-LD and OpenGraph are simple to parse ourselves. Add extruct only if microdata turns out to matter on the gold set.
- **rapidfuzz:** the standard library's `difflib` is fast enough for a handful of names.
- **LiteLLM:** our own small gateway keeps structured output, cost logging and caching under our control.
- **Jinja2:** plain placeholders are enough.

## Keeping it healthy

- **Model changes:** edit `data/models.toml`, run the eval, and note the change in the changelog.
- **MCC data changes:** edit the codes or synonyms, rebuild the vectors, and run the eval.
- **New fields:** follow `docs/recipes/adding-a-field.md`, which lists the model, resolver, prompts, gold labels, eval metric and output columns to add.
- **Releases:** semantic versioning and a changelog. Each release lists its prompt, data and output-schema versions.
- **Contributor docs:**
  - README for users
  - CONTRIBUTING for setup and the checks
  - this guide for structure
  - recipes for common changes
  - issue and pull-request templates

## Open questions

- Command and package name (`bi2` is a placeholder).

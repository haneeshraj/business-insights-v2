# Changelog

v2 follows [semantic versioning](https://semver.org). The output format, `SiteResult` with its `schema_version`, changes only with a major version.

## Unreleased: 2.0.0

### Added

- **Every v2.0 field:** company name, logo, MCC, head-office address with map coordinates, phone, email and social links, each with a status, a confidence, its source, its evidence and an audit trail.
- **The AI pass:** Jev as the Decider for typed picks among the rules' own candidates, Gemini for quoted readings, as Jev's backup and as a second opinion, and a web-search investigator for head offices the pages never give.
- **MCC:** Jev picks from the official 914 codes in two rounds, chain codes by the business's name, schema.org types as a hint, and a reversed second ask when unsure.
- **Address:** structured data, address lines by postcodes or street words, the privacy policy, Wikidata's head office, Gemini, and Nominatim for coordinates and a postcode check.
- **Logos:** a numbered screenshot for Jev to pick from, Wikidata's logo file as a last resort, and the brand's colors.
- **Fan-out:** a site's questions for Jev asked at the same time go in one call.
- **Free tiers:** a limiter per model for requests a minute, a day and at once, counted across runs; answers kept on disk; at most 12 model calls a site.
- **Commands:** `bi2` alone opens an interactive session; `bi2 doctor`, `bi2 keys`, `bi2 mcp`, `bi2 eval check`, `bi2 analyze --fast`, `--no-ai`, `--file` and `--answers`; results as CSV too.
- **CI/CD:** a nightly live eval with accuracy floors and a cost ceiling, releases to PyPI and ghcr.io, a Dockerfile, Dependabot.
- **Docs:** the architecture as built, costs per provider and model, a logo, and every diagram as an SVG image, drawn by `docs/assets/diagrams.py`.

### Removed

- fastembed, numpy and the Google, OpenAI and Anthropic SDKs, which v2 never imported.

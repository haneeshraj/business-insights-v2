# Evaluation

This folder holds what v2 is measured against. The code that does the measuring is in `src/bi2/evaluation`.

- `gold.toml`: the gold set, sites with known answers.
- `baselines/`: tools for measuring other systems on the same sites, starting with v1.

## The gold file

One `[[site]]` table per site:

```toml
[[site]]
url = "https://www.example-cafe.ca/"
category = "cafe"                    # groups sites in reports
confirmed = false                    # set to true once a person has checked the answers
company_names = ["Example Cafe"]     # any of these is correct
logo_urls = ["https://www.example-cafe.ca/logo.png"]
mcc_codes = ["5814", "5812"]         # any of these is correct; put the best one first
address = { street = "12 Queen St W", city = "Toronto", postal_code = "M5H 2N2", country = "CA" }
notes = "Where the answers came from."
```

For each field:
- **Leave the key out** when the field isn't checked for that site.
- **Write `"none"`** when the site has no such thing, so finding nothing is correct.
- **Otherwise, list the accepted answers.**

A platform page, such as a cafe's Pinterest profile, also sets `page_kind = "platform_profile"` and `platform = "pinterest"`.

How answers are judged:

| Field | Correct when |
|---|---|
| Company name | It matches an accepted name, ignoring case, accents, punctuation, a leading "The" and legal suffixes such as Inc. or Ltd. |
| Logo | Its URL matches an accepted URL, ignoring the scheme, "www.", query strings and CDN size tags such as `_400x` |
| MCC | The code is one of the accepted codes |
| Address | The postal code matches (or the city, when no postal code is given) and so does the house number |
| Page kind | The page is recognized as the business's own site, or as a profile on the right platform |

## Scoring results

Save results as JSON Lines, one SiteResult per line, then run:

```
uv run bi2 eval score eval/gold.toml results.jsonl
```

Add `--confirmed-only` to score only sites a person has checked, and `--json report.json` to save the full report.

## Reviewing the gold set

Answers marked `confirmed = false` were drafted from each site's own pages, or from general knowledge where a site blocks plain requests. The notes say which. To confirm a site, open it, check each answer, fix anything wrong, and set `confirmed = true`.

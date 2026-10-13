# Evaluation

This folder holds what v2 is measured against. The code that does the measuring is in `src/bi2/evaluation`.

- `gold.toml`: the gold set, sites with known answers. It's the tuning set: the sites rules are written against.
- `test-set.toml`: the test set, sites the rules are never tuned on. Their accuracy is the accuracy we report.
- `verifications.jsonl`: answers a person checked on the review page, with their notes.
- `drafted-checks.jsonl`: answers checked against each site's own pages that no person has confirmed yet.
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
phones = ["+14165550123"]            # E.164 format; any of these is correct
emails = ["hello@example-cafe.ca"]   # lowercase; any of these is correct
social_links = ["https://instagram.com/examplecafe"]  # all of these must be found
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
| Phone | It's one of the accepted numbers, both written in E.164 format |
| Email | It's one of the accepted addresses, ignoring case |
| Social links | Every expected profile is found, ignoring "www.", "m." and twitter.com versus x.com. Extra profiles don't count against it. |
| Page kind | The page is recognized as the business's own site, or as a profile on the right platform |

## Scoring results

Save results as JSON Lines, one SiteResult per line, then run:

```
uv run bi2 eval score eval/gold.toml results.jsonl
```

Add `--confirmed-only` to score only sites a person has checked, and `--json report.json` to save the full report.

## Checked answers

`bi2 review` saves each check to `verifications.jsonl`, one per line, newest last:

```json
{"site": "https://www.example-cafe.ca/", "field": "logo", "answer": "example-cafe.ca/logo-dark.png", "shown": "https://www.example-cafe.ca/logo-dark.png", "verdict": "right", "note": "the dark copy of the logo", "status": "ok", "confidence": 0.9, "checked_at": "2026-10-12T23:42:50Z"}
```

- `answer` is the answer written the forgiving way it's compared, so a check still applies when a later run gives the same answer. When a run gives a different answer, the old check doesn't apply to it.
- `shown` is the answer as the page showed it, `status` and `confidence` are how v2 had marked it, and `note` is what the person saw.
- A newer check of the same answer replaces an older one. The older lines stay, as history.
- A person's check counts over the gold set's, since the gold set can be wrong: it lists one file for a logo that has several.
- `correct` is the right answer, given with an answer marked wrong: a name, a phone number in E.164 format, an email address, the logo's address, or profile addresses separated by spaces. On the review page, a logo can be given as its candidate number, like `#2`, and is saved as that candidate's address.

The right answers people confirm or give also count on later runs. When a run's answer has changed, it's scored against them the way the gold set scores answers, before the gold set itself. The review page says "Your earlier answers" for these.

## Drafted checks

`drafted-checks.jsonl` has the same form as `verifications.jsonl`. It holds checks made against each site's own pages, its contact page or the live site, for answers no person has checked. The note on each one says what it was checked against.

- A person's check of an answer always counts before a draft of it, and drafts count before the gold set.
- On the review page, a draft shows as "Drafted", with its note. Pressing Right or Wrong confirms or overrides it.
- An answer that couldn't be verified has no draft, so it's left out of the scores rather than guessed.
- **Emails:** the right answer is the business's general address, like info@ or customer service. When the pages show none, an address the business gives for reaching a store or a person is right too. An address for one purpose, like the press, jobs or fraud reports, is wrong, and "not found" is right when the pages show no other.

## The test set

`test-set.toml` lists only the sites, what kind of business each is, and, for profiles on a platform, which platform. The right answers come from checks: a person's on the review page, or drafted ones. It has two batches:

- 57 sites, mostly Canadian chains, banks and services.
- 64 small businesses in 26 countries, with sites in their own languages. A few are there on purpose: a domain that now redirects to a lottery site, one that's parked for sale, a homepage that leads to "page not found", and sites behind bot checks.

```
uv run bi2 dev fetch --gold eval/test-set.toml --out eval/snapshots/test-set    # save the pages once
uv run bi2 analyze --saved eval/snapshots/test-set --gold eval/test-set.toml --out bi2-results/test-set
uv run bi2 review bi2-results/test-set --gold eval/test-set.toml               # check the answers
```

- Saved pages go in `eval/snapshots/`, which git ignores, since copies of other sites never go in the repository.
- Each site's folder also holds the contact page its homepage links, in `pages/`. A run reads it when the homepage doesn't show a phone number or an email address that could be the business's general one, the same as a live run would.
- A run on saved pages keeps the files it downloads beside the pages, so a rerun sees exactly the same pages and files, with no network.
- Never change a rule because of a test-set site. Add a site like it to the gold set and work on that one, or the test set stops measuring sites the rules haven't seen.

## Comparing runs

```
uv run bi2 eval compare bi2-results/before bi2-results/after --gold eval/gold.toml
```

It lists the answers that got better, got worse, changed with no one having checked them, or changed but are as good as before, judged by checks and the gold set. It exits with 1 when anything got worse, including a site that no longer loads, and with 2 when a file can't be read.

## Reviewing the gold set

Answers marked `confirmed = false` were drafted from each site's own pages, or from general knowledge where a site blocks plain requests. The notes say which. To confirm a site, open it, check each answer, fix anything wrong, and set `confirmed = true`.

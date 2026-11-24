# lawfirm_enrich

A Scrapy project (Python 3.11) that takes a list of Australian law firms, visits a small number of
pages on each firm's website, and writes an enriched spreadsheet: how many solicitors are listed, the
principal(s), practice areas, postal address / PO Box, which pages were used, and a size/exclusion
classification.

It runs on the Scrapy in this repository (`brseeger-cloud/scrapy`). It also works with Scrapy 2.13 or
later from PyPI.

## What it does

For each row of `firms.csv`:

1. **Do-not-contact check.** If the firm's ABN, website domain or name matches `do_not_contact.csv`,
   it is skipped: no request is sent and no row is written. The pipeline checks again after
   redirects, so a site that redirects to an excluded domain is also dropped. The run will not start
   if `do_not_contact.csv` is missing.
2. **Crawl at most 6 pages**: the home page, then about, team/our-people and contact pages. These are
   found from the site's own links. If no link is found, it tries a few common paths
   (`/our-team`, `/contact-us`, `/about-us`, …). Blogs, news, PDFs, careers pages, other domains and
   so on are never followed.
3. **Extract**
   - number of solicitors listed (names paired with lawyer job titles; paralegals, clerks,
     assistants, practice managers and licensed conveyancers are not counted)
   - principal name(s) (Principal, Partner, Director, Founder, …)
   - practice areas: Conveyancing, Wills & Estates, Family, Personal Injury, Commercial, Criminal
   - postal address / PO Box, and street address
   - the URLs of the pages used
4. **Classify** as `Sole`, `Small (2-4)`, `Larger`, `Exclude` or `Check manually`.
   `exclude_reason` is one of `barrister`, `in-house`, `government`, `licensed conveyancer` or
   `not a law firm`.

**No email addresses are collected or stored.** `mailto:` links are dropped before any text is read.
Email-like strings (including `name [at] firm [dot] com`) are removed from page text before analysis.
Every output value is scrubbed again in the pipeline and once more when the spreadsheet is written.
Pages are never cached to disk, and the log level keeps page content out of the log. If `firms.csv`
has extra columns (for example an email column), they are ignored; only the six documented columns
are read.

## Crawl settings

Set in `lawfirm_enrich/settings.py`:

| Setting | Value |
|---|---|
| `ROBOTSTXT_OBEY` | `True` |
| `AUTOTHROTTLE_ENABLED` | `True` (start 2s, max 30s) |
| `DOWNLOAD_DELAY` | `2` seconds (not randomised, so it is a true minimum) |
| `CONCURRENT_REQUESTS_PER_DOMAIN` | `1` |
| `USER_AGENT` | `LawAuditResearch (audit@lawaudit.com.au)` |
| `RETRY_TIMES` | `2` |
| `DOWNLOAD_TIMEOUT` / `DNS_TIMEOUT` | `20` seconds |
| `HTTPCACHE_ENABLED`, `COOKIES_ENABLED` | `False` |
| `LAWFIRM_MAX_PAGES` | `6` |

Different firms are crawled in parallel (up to 16 sites at once). Each site gets one request at a
time, at least 2 seconds apart.

## Setup

```bash
cd lawfirm_enrich
python3.11 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ..                  # Scrapy from this repository
pip install -r requirements.txt
```

## Input files

**`firms.csv`** (UTF-8; a header row is required, column order does not matter):

```csv
firm_name,abn,entity_type,state,postcode,website
Example Sole Lawyers,11 111 111 111,Individual/Sole Trader,NSW,2150,www.sole-lawyers.example
```

`website` can be given with or without `https://`. If no scheme is given and HTTPS fails with a
connection or TLS error, the crawler tries plain HTTP once. Rows with no website still appear in the
output (`crawl_status = no website`).

**`do_not_contact.csv`**: always applied. A firm is excluded if **any** of these match:

```csv
firm_name,abn,website,reason,date_added
Opted Out Lawyers,55 555 555 555,optedout.example,Asked not to be contacted,2026-10-01
```

- `abn`: spaces are ignored.
- `website`: matches the domain and its subdomains, with or without `www`.
- `firm_name`: case, punctuation, `&`/`and` and `Pty Ltd`/`Limited` are ignored.

Any of the three can be left blank on a row. `reason` and `date_added` are for your records. The
`examples/` folder has samples of both files.

## Running

```bash
python run.py
```

This reads `firms.csv` and `do_not_contact.csv` from the project folder and writes:

| File | Contents |
|---|---|
| `output/firms_enriched.xlsx` | sheets **Firms** (one row per firm), **Failed sites**, **Run info** (counts and settings used) |
| `output/failed_sites.csv` | the same failed-sites log as a CSV |
| `logs/crawl_YYYYMMDD_HHMMSS.log` | full Scrapy log |

Options:

```bash
python run.py --input path/to/firms.csv --dnc path/to/do_not_contact.csv --output out/enriched.xlsx --failed-log out/failed.csv
```

Any Scrapy setting can be overridden with `-s`, for example:

```bash
python run.py -s CONCURRENT_REQUESTS=8
```

You can also use the standard Scrapy command:

```bash
scrapy crawl firms -a input=firms.csv -a dnc=do_not_contact.csv -s LAWFIRM_OUTPUT_XLSX=output/firms_enriched.xlsx
```

If the workbook is open in Excel when the run finishes, it is saved under a timestamped name instead.

### How long it takes

Each site needs about 3–6 requests at least 2 seconds apart, plus a robots.txt request. That is
roughly 10–20 seconds per site, and about 16 sites run in parallel. 1,000 firms take around 15–25
minutes, depending on how fast the sites respond.

## Output columns (Firms sheet)

| Column | Meaning |
|---|---|
| `input_row` … `website` | copied from `firms.csv` |
| `classification` | `Sole` / `Small (2-4)` / `Larger` / `Exclude` / `Check manually` |
| `exclude_reason` | for `Exclude`: barrister, in-house, government, licensed conveyancer, not a law firm |
| `classification_notes` | why: the evidence, conflicts, or what could not be determined |
| `solicitor_count` | number of solicitors found |
| `count_basis` | `team page listing`, `about/home page listing`, `stated on site` (e.g. "our team of 12 lawyers"), `principal mentions only`, or `not found` |
| `principal_names` | `;`-separated |
| `practice_areas` + 6 Y/N columns | conveyancing, wills_estates, family, personal_injury, commercial, criminal |
| `postal_address` | PO Box / labelled postal address if found, otherwise the street address |
| `po_box`, `street_address` | as found |
| `address_postcode_matches_input` | Y/N: postcode of `postal_address` vs input `postcode` |
| `crawl_status` | `ok`, `ok (some pages failed)`, `failed`, `no website` |
| `final_url` | home page after redirects |
| `pages_used`, `pages_failed` | every page URL read (and any that failed), one per line |
| `source_url` | the site's home page as fetched (the row's source) |
| `count_source_url`, `address_source_url` | the page each of those facts came from |
| `date_collected` | date of the crawl (Australia/Sydney; change with `LAWFIRM_TIMEZONE`) |

### Classification rules

1. Site could not be crawled → **Check manually** (and listed in Failed sites).
2. Strong exclusion evidence → **Exclude**:
   - **government**: `.gov.au` domain, a government ABN entity type, or a name such as Legal Aid,
     Crown Solicitor, DPP or Council
   - **barrister**: "Chambers", "Barrister" or "SC/KC" in the name, or "barrister-at-law" / "member
     of the NSW Bar" on the site. "Barristers & Solicitors" firms are **not** excluded.
   - **in-house**: "in-house", "legal department" or "general counsel" in the name or entity type
   - **licensed conveyancer**: a conveyancing business name, or "licensed conveyancer" wording, with
     no solicitors on the site
   - **not a law firm**: no legal terms anywhere on the site, or the name suggests another business
     (accountant, migration agent, …) and there are no solicitors
3. Weaker evidence of the above, or a community legal centre or parked domain → **Check manually**,
   with the evidence in `classification_notes`.
4. Otherwise, size by the number of solicitors:
   - 1 → **Sole**
   - 2–4 → **Small (2-4)**
   - 5 or more → **Larger**

   A count from a staff listing is preferred. If there is no listing, a number stated on the site is
   used, or "sole practitioner" / first-person wording for a sole practice.
5. No usable count, or the listing conflicts with a number stated on the site → **Check manually**.

These are heuristics over free-form websites. Spot-check the `Check manually` rows and a sample of
the others. The `*_source_url` columns take you straight to the evidence.

## Tests

```bash
pip install -r requirements.txt
python -m pytest tests
```

`tests/test_crawl.py` runs the full pipeline (`run.py`) against small mock websites served on
localhost (`tests/sites/`). It checks the do-not-contact exclusion (the site gets zero requests),
robots.txt blocking, the 6-page cap, that no email addresses appear in the output, the
classifications, and the failed-sites log. No real websites are contacted by the tests.

## Project layout

```
lawfirm_enrich/
├── run.py                      # entry point
├── scrapy.cfg
├── firms.csv                   # your input (header only in the repo)
├── do_not_contact.csv          # always applied (header only in the repo)
├── examples/                   # sample input files
├── lawfirm_enrich/
│   ├── settings.py             # crawl settings
│   ├── spiders/firms.py        # page discovery and crawling (max 6 pages/site)
│   ├── extract.py              # text, people/roles, practice areas, addresses, exclusion signals
│   ├── classify.py             # Sole / Small / Larger / Exclude / Check manually
│   ├── inputs.py               # firms.csv and do_not_contact.csv
│   ├── privacy.py              # email scrubbing
│   ├── pipelines.py            # do-not-contact → email scrub → Excel export
│   ├── items.py                # output columns
│   └── export.py               # xlsx / csv writing
└── tests/
```

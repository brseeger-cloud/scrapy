# lawfirm_enrich

A Scrapy project (Python 3.11) that takes a list of Australian law firms, visits a small number of
pages on each firm's website, and writes an enriched spreadsheet: how many solicitors are listed, the
principal(s), practice areas, postal address / PO Box, which pages were used, and a size/exclusion
classification.

It needs Python 3.11 or later and Scrapy 2.15 or later (tested with 2.15–2.20 from PyPI, and with
the Scrapy in this repository).

## What it does

For each row of `firms.csv`:

1. **Do-not-contact check.** If the firm's ABN, website domain or name matches `do_not_contact.csv`
   (or you marked it "Opted out" in the master list),
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
   - published email addresses (see [Email addresses](#email-addresses))
   - the URLs of the pages used
4. **Classify** as `Sole`, `Small (2-4)`, `Larger`, `Exclude` or `Check manually`.
   `exclude_reason` is one of `barrister`, `in-house`, `government`, `licensed conveyancer` or
   `not a law firm`.

## Email addresses

Email addresses are collected only in ways that support **inferred consent** under the Spam Act
2003, which allows commercial email to an address that is conspicuously published, if the message
is relevant to the recipient's work and the site has no statement refusing unsolicited messages.

- **Only plainly published addresses:** `mailto:` links and addresses written out on the page.
  Addresses a site has deliberately hidden (`jane [at] firm [dot] com`, Cloudflare email
  protection, images) are never decoded.
- **Only the firm's own addresses:** on the firm's website domain, or a common webmail domain
  (Bigpond, Gmail, …) that many sole practitioners use. Third-party addresses (web designers, law
  societies) are dropped, as are careers, privacy, accounts and no-reply addresses.
- **Evidence kept:**
  - `email_source_url`: the page each address came from
  - `email_type`: `general` (info@, reception@, …) or `personal` (an individual's address)
  - `no_unsolicited_email_notice`: any sentence where the site refuses unsolicited email. Firms
    with one are never put on an email list.
- **Nowhere else:** email addresses appear only in the `email` and `other_emails` columns. Every
  other value is scrubbed of anything that looks like an address. Pages are never cached to disk,
  and the log level keeps page content out of the log.

**Before you send:** each email must identify you, include a working unsubscribe link, and be
relevant to the recipient's legal practice. Act on unsubscribes within 5 business days by marking
the firm "Opted out". The Spam Act also restricts using "harvested" address lists to send email
that breaks these consent rules. This is a summary, not legal advice: check ACMA's guidance, or ask
a lawyer, before your first email campaign.

## Crawl settings

Set in `lawfirm_enrich/settings.py`:

| Setting | Value |
|---|---|
| `ROBOTSTXT_OBEY` | `True` |
| `AUTOTHROTTLE_ENABLED` | `True` (start 2s, max 30s) |
| `DOWNLOAD_DELAY` | `2` seconds (not randomised, so it is a true minimum) |
| `CONCURRENT_REQUESTS_PER_DOMAIN` | `1` |
| `USER_AGENT` | `LawAudit (audit@lawaudit.com.au)` |
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
pip install -r requirements.txt   # installs Scrapy from PyPI
```

## Building the firm list

`firms.csv` can be built from the **ABN Bulk Extract**, the public Australian Business Register.
It's free on data.gov.au (search "ABN Bulk Extract") under a CC BY licence.

1. Download both zip files, `public_split_1_10.zip` and `public_split_11_20.zip` (about 1 GB each).
   There is no need to unzip them.
2. Run:

   ```bash
   python build_firm_list.py ~/Downloads/public_split_1_10.zip ~/Downloads/public_split_11_20.zip
   ```

   This takes about 10–15 minutes.

**What it adds:** every *active* ABN whose legal, trading or business name contains "Lawyers",
"Legal", "Solicitors", "Law", "Attorneys", "Notary" or "Barristers & Solicitors".

**What it leaves out:**
- super funds, government bodies and deceased estates
- false matches such as "in-law", "Law Society", "Legal Aid", "paralegal"
- firms on `do_not_contact.csv`
- "… Conveyancing" businesses, which are mostly licensed conveyancers. Add `--include-conveyancers`
  to keep them.

**How rows are filled in:**
- `firm_name` is the business name the public sees.
- Entities of the same practice (company, service trust, partnership) are merged into one row. The
  GST-registered ABN is used, and the others go in `other_abns`.
- Extra columns are added: `legal_name`, `other_names`, `other_abns`, `gst_registered` and
  `source`. The crawler ignores them.
- Re-running it later adds only new firms. Existing rows, and websites you filled in, are kept.

**Limits:** the register has no industry codes, websites or street addresses. A firm that trades
only under a person's own name (e.g. "Jane Citizen") cannot be recognised as a law firm and is
missed. Street addresses come later, from the firm's website.

### Finding websites

```bash
python find_websites.py --limit 50   # try it on 50 firms first
python find_websites.py              # then the rest
```

For each firm with no website, this guesses domains from its name, for example "Smith & Co
Lawyers" → `smithcolawyers.com.au`, `smithandco.com.au`, `smith-co-lawyers.com.au`,
`smithcolawyers.au`. At most 9 guesses are made per firm. Each guessed home page is fetched once,
obeying robots.txt and with the same user agent, and a site is accepted only if:

| `website_found_by` | Meaning |
|---|---|
| `ABN on site` | the page shows the firm's ABN (strongest) |
| `name on site` | the firm's distinctive name, legal wording, and its postcode or state |
| `name on site (location unconfirmed)` | name and legal wording, but no address on the home page. Worth a quick look |
| `not found` | no guess matched |

Parked "domain for sale" pages are rejected, as are pages whose only address is in another state
(probably a same-named firm elsewhere). Firms that don't use their name as their domain are not
found; fill those in by hand if they matter.

**How it handles firms.csv:**
- It's updated in place. A backup (`firms.backup-<date-time>.csv`) is made first, and progress is
  saved every 200 firms.
- Rows that already have a website are left alone, and firms on the do-not-contact list are never
  searched.
- Firms marked `not found` are skipped next time; use `--recheck-not-found` to retry them.

**Time:** about 17,000 firms take a few hours, since most guesses are quick "domain does not
exist" failures.

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
- `website`: matches the domain and its subdomains, with or without `www`. Don't use this for
  a firm whose site is on a shared platform (a Facebook page, a Wix or Google Sites address):
  it would block every firm on that platform. Use the ABN or name instead.
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
| `data/master.xlsx` | the master list, updated by every run (see below) |
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
`run.py` refuses to start while the master list is open in Excel; close it first.

### Resuming or refreshing

```bash
python run.py --skip-crawled-within 1
```

This skips every firm the master list shows was crawled today, so an interrupted run carries on
where it stopped. The master list is saved every 1,000 firms. Use a larger number to refresh only
firms that are due, for example `--skip-crawled-within 90` once a month re-crawls firms last
crawled more than 90 days ago, plus any new firms in `firms.csv`.

## Master list and mailing lists

`data/master.xlsx` is the long-term record: one row per firm, keyed by ABN (or the website domain,
or the name, when there is no ABN). Each run adds new firms and updates existing ones.

**Firms sheet**
- The crawled columns are updated on every run. If a crawl fails, the last good results are kept;
  only `crawl_status` and `last_crawled` change.
- The orange columns are yours and are never overwritten:
  - `my_status`: set it to **Opted out** (or **Do not contact**) and, on the next run or list
    export, the firm is added to `do_not_contact.csv` and removed from the master list.
  - `last_contacted`: a date. `make_list.py --mark-contacted` fills it in for you.
  - `my_notes`: anything you like.

  Columns you add yourself are kept too.
- `first_seen`, `last_crawled`, `last_successful_crawl` and `last_changed` record when each firm
  was found, crawled and last changed.

**Changes sheet:** one row per change to a firm's classification, solicitor count, principals,
address, practice areas or crawl status, with the date. Use it to spot firms that grew, moved or
closed.

**Making a mailing list**

```bash
python make_list.py --size Sole "Small (2-4)" --state NSW VIC --area conveyancing wills_estates --not-contacted-days 180 --out output/mailing_list.csv --mark-contacted
```

| Option | Meaning |
|---|---|
| `--size` | classifications to include: `Sole`, `Small (2-4)`, `Larger`, `Check manually` (default: the first three) |
| `--state` | states to include (default: all) |
| `--area` | firms doing at least one of these: `conveyancing`, `wills_estates`, `family`, `personal_injury`, `commercial`, `criminal` (default: any) |
| `--not-contacted-days N` | leave out firms contacted in the last N days |
| `--channel post\|email` | `post` (default): firms with a postal address. `email`: firms with a published email address and no refusal notice |
| `--general-email-only` | email channel: only general addresses such as info@, not individuals' |
| `--include-no-address` | post channel: include firms with no postal address found (left out by default) |
| `--mark-contacted` | set `last_contacted` to today for every firm exported |

The CSV has `firm_name`, `addressee` (the first principal, or "The Principal"), `postal_address`,
`email`, `email_type`, `state`, `postcode`, `classification`, `solicitor_count`, `practice_areas`, `website` and
`firm_key`. It opens directly in Excel and works with Word mail merge. Firms classified `Exclude`
and firms on `do_not_contact.csv` are never exported, whatever the options. For an email list:

```bash
python make_list.py --channel email --general-email-only --not-contacted-days 90 --out output/email_list.csv --mark-contacted
```

### Recommended cycle

1. Build `firms.csv` (see [Building the firm list](#building-the-firm-list)), run
   `find_websites.py`, then run `python run.py`. About 17,000 firms take roughly 3–6
   hours, so run it overnight.
2. Review the `Check manually` rows in the master list.
3. Run `make_list.py` for each campaign, with `--mark-contacted`.
4. Mark opt-outs in `my_status` as they come in.
5. Monthly or quarterly, run `python run.py --skip-crawled-within 90` to refresh.

### Keep real data out of this repository

This repository is public. `data/`, `output/` and `logs/` are git-ignored because they contain
principals' names. Do not commit a filled-in `firms.csv` or `do_not_contact.csv` either: the
second reveals which firms opted out. Keep them outside the repository and pass their paths with
`--input` and `--dnc`, or simply don't commit your edits.

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
| `email`, `email_type`, `other_emails` | best published address (general addresses first), its type, and up to 4 more |
| `email_source_url` | the page the address came from |
| `no_unsolicited_email_notice` | the site's statement refusing unsolicited email, if any |
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
localhost (`tests/sites/`). It checks:
- the do-not-contact exclusion (the site gets zero requests), including opt-outs marked in the
  master list
- robots.txt blocking and the 6-page cap
- which email addresses are collected, and that no address appears outside the email columns
- the classifications and the failed-sites log
- the master list, and resuming with `--skip-crawled-within`

No real websites are contacted by the tests.

Lint with `ruff check . && ruff format --check .` (rules in `ruff.toml`).

## Project layout

```
lawfirm_enrich/
├── run.py                      # crawl and update the master list
├── make_list.py                # export a mailing list from the master list
├── build_firm_list.py          # build firms.csv from the ABN Bulk Extract
├── find_websites.py            # fill in firms' websites
├── scrapy.cfg
├── firms.csv                   # your input (header only in the repo)
├── do_not_contact.csv          # always applied (header only in the repo)
├── examples/                   # sample input files
├── lawfirm_enrich/
│   ├── settings.py             # crawl settings
│   ├── spiders/firms.py        # page discovery and crawling (max 6 pages/site)
│   ├── spiders/websites.py     # checking guessed domains
│   ├── extract.py              # text, people/roles, practice areas, addresses, exclusion signals
│   ├── classify.py             # Sole / Small / Larger / Exclude / Check manually
│   ├── inputs.py               # firms.csv and do_not_contact.csv
│   ├── emails.py               # which published email addresses are collected
│   ├── privacy.py              # email scrubbing for every other column
│   ├── pipelines.py            # do-not-contact → email scrub → master list → Excel export
│   ├── master.py               # the master list (data/master.xlsx)
│   ├── lists.py                # selecting firms for a mailing list
│   ├── abr.py                  # reading the ABN Bulk Extract
│   ├── websites.py             # guessing and verifying firm websites
│   ├── items.py                # output columns
│   └── export.py               # xlsx / csv writing
└── tests/
```

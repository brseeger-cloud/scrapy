# lawfirm_enrich

Tools for building and maintaining a marketing list of Australian law firms:
- build the firm list from the Australian Business Register
- find each firm's website
- crawl a few pages per site for its size, principals, practice areas, postal address and
  published email address
- keep it all in one master spreadsheet, exporting postal or email lists from it

It needs Python 3.11 or later and Scrapy 2.15 or later (tested with 2.15–2.20 from PyPI, and with
the Scrapy in this repository). It runs on your own computer.

## Quick start

1. **Get the code.** Download
   https://github.com/brseeger-cloud/scrapy/archive/refs/heads/add-lawfirm-enrich.zip (once the
   pull request is merged, use `master` instead of `add-lawfirm-enrich`), unzip it, and open the
   `lawfirm_enrich` folder inside.
2. **Set up (once).** You need Python 3.11 or later from https://www.python.org/downloads/.
   - Mac/Linux: in a terminal in the `lawfirm_enrich` folder, run `bash setup.sh`.
   - Windows: double-click `setup.bat`.
3. **Run the steps** from the `lawfirm_enrich` folder. On Windows use `.venv\Scripts\python`
   instead of `.venv/bin/python`.

   ```bash
   .venv/bin/python lawaudit.py status          # where things stand, and what to do next
   .venv/bin/python lawaudit.py build-list ~/Downloads/public_split_1_10.zip ~/Downloads/public_split_11_20.zip
   .venv/bin/python lawaudit.py find-websites --limit 50
   .venv/bin/python lawaudit.py crawl
   .venv/bin/python lawaudit.py make-list --mark-contacted --campaign "Feb letter"   # mail campaign
   .venv/bin/python lawaudit.py make-list --channel email --mark-contacted --campaign "Feb email"
   .venv/bin/python lawaudit.py unsubscribe ~/Downloads/unsubscribes.csv
   ```

   Add `--help` after any step for its options. `status` always tells you the next step.

The rest of this README explains each step. The steps are also available as separate scripts:
`build_firm_list.py`, `find_websites.py`, `run.py` (= `crawl`) and `make_list.py`, which take the
same options.

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
   - mailing address and office address(es) (see [Addresses](#addresses))
   - published email addresses (see [Email addresses](#email-addresses))
   - the URLs of the pages used
4. **Classify** as `Sole`, `Small (2-4)`, `Larger`, `Exclude` or `Check manually`.
   `exclude_reason` is one of `barrister`, `in-house`, `government`, `licensed conveyancer` or
   `not a law firm`.

## Addresses

Two addresses are recorded for each firm:
- **Office address:** the firm's street address. Further offices go in `other_office_addresses`,
  up to 3.
- **Mailing address** (`postal_address`), where to send mail: in order of preference, the address
  labelled "Postal address", a PO Box / GPO Box / Locked Bag (also in `po_box`), or the office
  address.

They are found in two ways, best first:
1. **Structured data** that many firm sites embed for Google (schema.org `PostalAddress`, often
   added by WordPress SEO plugins). It gives exact street, suburb, state and postcode fields.
2. **Addresses written on the page**: contact page first, then home, about and team pages. Common
   Australian formats are recognised: "Level 2, 45 Smith Street, Parramatta NSW 2150",
   "Suite 3/12-14 Main Rd Penrith New South Wales 2750", "PO Box 123, Parramatta NSW 2124",
   "Locked Bag 5 Sydney NSW 2001", including addresses split over several lines or written in
   capitals. DX (document exchange) numbers are not addresses and are ignored.

Every address is written the same way, `<line>, <Suburb> <STATE> <postcode>` (for example
"Level 2, 45 Smith Street, Parramatta NSW 2150"), so mailing lists can split it into separate
fields. `address_postcode_matches_input` checks the postcode against the ABN register; an `N` is
worth a look, as the site may belong to a different firm.

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
relevant to the recipient's legal practice. Unsubscribes must take effect within 5 business days
(see [Unsubscribes](#unsubscribes)). The Spam Act also restricts using "harvested" address lists to send email
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

`setup.sh` (Mac/Linux) and `setup.bat` (Windows) do this for you:

```bash
cd lawfirm_enrich
python3 -m venv .venv
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
| `name on site (redirected to another site)` | the guessed address redirected to a site whose address shares no word with the firm's name, e.g. a rebrand or a news article. Worth a look |
| `not found` | no guess matched |

Some pages are rejected:
- parked "domain for sale" pages
- pages whose only address is in another state (probably a same-named firm elsewhere)
- social media and directory pages (Facebook, LinkedIn, Yellow Pages, …)

A firm's page on a website builder (Google Sites, Wix, …) is kept with its full address. A
builder's own home page, such as `https://sites.google.com/`, is never treated as a firm's site. Firms that don't use their name as their domain are not
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

**`do_not_contact.csv`**: always applied. It's created empty the first time you run a step. A firm is excluded if **any** of these match:

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

## Master list

`data/master.xlsx` is the long-term record: one row per firm, keyed by ABN (or the website domain,
or the name, when there is no ABN). Each run adds new firms and updates existing ones.

**Firms sheet**
- The crawled columns are updated on every run. If a crawl fails, the last good results are kept;
  only `crawl_status` and `last_crawled` change.
- The orange columns are yours and are never overwritten:
  - `my_status`: set it to **Opted out** (or **Do not contact**) and, on the next run or list
    export, the firm is added to `do_not_contact.csv` and removed from the master list.
  - `last_contacted`: a date you contacted the firm yourself, e.g. a phone call. It keeps the firm
    off *every* list made with `--not-contacted-days`.
  - `my_notes`: anything you like.

  Columns you add yourself are kept too.
- `last_mailed`, `last_emailed` and `last_campaign` are filled in by `make-list --mark-contacted`.
  Each channel has its own date, so a mail-out doesn't stop the same firm getting the email
  campaign.
- `first_seen`, `last_crawled`, `last_successful_crawl` and `last_changed` record when each firm
  was found, crawled and last changed.

**Changes sheet:** one row per change to a firm's classification, solicitor count, principals,
address, practice areas or crawl status, with the date. Use it to spot firms that grew, moved or
closed.

**Campaigns sheet:** one row per firm per campaign sent with `--mark-contacted`: date, campaign
name, channel, and the address or email it went to. It's your record of who was sent what, which
is also useful evidence if a recipient ever queries a message.

## Running campaigns

`lawaudit.py make-list` (or `make_list.py`) exports the firms for one campaign as a CSV that
opens in Excel.

**Mail campaign:**

```bash
python lawaudit.py make-list --size Sole "Small (2-4)" --state NSW VIC --not-contacted-days 180 --mark-contacted --campaign "Feb 2027 audit letter"
```

writes `output/mailing_list.csv` with:
- `firm_name`
- `addressee`, `first_name`, `last_name`: the first principal, or "The Principal"
- `address_line_1`, `suburb`, `state`, `postcode`
- `full_address`
- `address_type`: `PO Box`, `postal` or `office`

Use it for Word mail merge, or give it to a mail house; they can sort and barcode it for Australia
Post's bulk mail discounts. It goes to each firm's mailing address (its PO Box if it has one). Add
`--address office` to send to the office instead.

**Email campaign:**

```bash
python lawaudit.py make-list --channel email --not-contacted-days 90 --mark-contacted --campaign "Feb 2027 audit email"
```

writes `output/email_list.csv` with:
- `email`
- `first_name`, `last_name`, `addressee`: the principal whose name is in a personal address, else
  the first principal
- `firm_name`, `email_type` and firm details

Import it into your email service (Mailchimp, Campaign Monitor, …) and use its merge fields and
unsubscribe link. Add `--general-email-only` to send only to addresses like info@. Firms whose
site refuses unsolicited email are always left out.

| Option | Meaning |
|---|---|
| `--channel post\|email` | `post` (default) or `email` |
| `--size` | classifications to include: `Sole`, `Small (2-4)`, `Larger`, `Check manually` (default: the first three) |
| `--state` | states to include (default: all) |
| `--area` | firms doing at least one of these: `conveyancing`, `wills_estates`, `family`, `personal_injury`, `commercial`, `criminal` (default: any) |
| `--not-contacted-days N` | leave out firms sent this channel in the last N days, or that you marked `last_contacted` |
| `--address postal\|office` | post: send to the mailing address (default) or the office address |
| `--general-email-only` | email: only general addresses such as info@ |
| `--include-no-address` | post: include firms with no address found (left out by default) |
| `--mark-contacted` | record the send: sets `last_mailed` / `last_emailed` and logs each firm in the Campaigns sheet |
| `--campaign NAME` | the campaign name recorded with `--mark-contacted` |
| `--out FILE` | where to write (default `output/mailing_list.csv` or `output/email_list.csv`) |

**Each firm is sent a campaign once.** Several register entries can match the same website, for
example "Robert Law" and "Robert Law Pty Ltd". They get one letter or email between them, and no
email address is used twice. The command reports how many duplicates it left out. Different firms
that merely share a postal address (shared offices) each still get their letter.

**Never exported, whatever the options:**
- firms classified `Exclude`
- firms on `do_not_contact.csv`
- unsubscribed addresses

**Only use `--mark-contacted` for the export you actually send.** For a trial run, leave it off.

### Unsubscribes

When people unsubscribe, export the list from your email service (any CSV works: the email
addresses are picked out of it automatically) and run:

```bash
python lawaudit.py unsubscribe ~/Downloads/unsubscribes.csv
python lawaudit.py unsubscribe jane@smithlaw.com.au      # or type addresses directly
```

The addresses are added to `unsubscribed.csv` and removed from the master list straight away.
From then on they are never stored by a crawl or put on any list. The firm's other addresses and
its postal address can still be used, because an unsubscribe applies to the address that asked.

To stop contacting the whole firm instead, add `--whole-firm`. The firm then goes on
`do_not_contact.csv` and is removed from the master list. Keep `unsubscribed.csv` out of this
public repository, like the other files with real data.

### Recommended cycle

1. `lawaudit.py build-list`, then `find-websites`, then `crawl`. About 17,000 firms take a few
   hours for websites and roughly 3–6 hours to crawl, so run them overnight.
2. Review the `Check manually` rows, and websites marked "location unconfirmed", in the master list.
3. `lawaudit.py make-list … --mark-contacted --campaign NAME` for each mail or email campaign
   (see [Running campaigns](#running-campaigns)).
4. Process unsubscribes at least weekly (`lawaudit.py unsubscribe …`), and mark firms that ask
   not to be contacted at all as "Opted out" in `my_status`.
5. Monthly or quarterly: `lawaudit.py crawl --skip-crawled-within 90` to refresh, and
   `build-list` with a fresh ABN Bulk Extract to pick up new firms.

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
| `postal_address` | mailing address: labelled postal address, else PO Box, else office address |
| `po_box` | PO Box / GPO Box / Locked Bag, if any |
| `office_address` | the firm's street address |
| `other_office_addresses` | further offices, one per line (up to 3) |
| `address_postcode_matches_input` | Y/N: postcode of the mailing or office address vs the input `postcode` |
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
├── lawaudit.py                 # one command for every step (start here)
├── setup.sh, setup.bat         # one-time setup
├── run.py                      # crawl and update the master list
├── make_list.py                # export a mailing list from the master list
├── build_firm_list.py          # build firms.csv from the ABN Bulk Extract
├── find_websites.py            # fill in firms' websites
├── scrapy.cfg
├── firms.csv                   # your firm list (made by build-list; not in the download)
├── do_not_contact.csv          # always applied (created empty on first use; not in the download)
├── examples/                   # sample input files
├── lawfirm_enrich/
│   ├── settings.py             # crawl settings
│   ├── spiders/firms.py        # page discovery and crawling (max 6 pages/site)
│   ├── spiders/websites.py     # checking guessed domains
│   ├── extract.py              # text, people/roles, practice areas, addresses, exclusion signals
│   ├── classify.py             # Sole / Small / Larger / Exclude / Check manually
│   ├── inputs.py               # firms.csv and do_not_contact.csv
│   ├── addresses.py            # finding mailing and office addresses
│   ├── emails.py               # which published email addresses are collected
│   ├── privacy.py              # email scrubbing for every other column
│   ├── unsubscribe.py          # unsubscribed.csv
│   ├── status.py               # the status report
│   ├── pipelines.py            # do-not-contact → email scrub → master list → Excel export
│   ├── master.py               # the master list (data/master.xlsx)
│   ├── lists.py                # selecting firms for a mailing list
│   ├── abr.py                  # reading the ABN Bulk Extract
│   ├── websites.py             # guessing and verifying firm websites
│   ├── items.py                # output columns
│   └── export.py               # xlsx / csv writing
└── tests/
```

"""A plain-English summary of where your data stands, and what to do next."""

from __future__ import annotations

import csv
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from .inputs import DoNotContactList
from .master import MasterList, _as_date, _norm
from .unsubscribe import load_unsubscribed

MIN_SCRAPY = (2, 15)
REFRESH_DAYS = 90


def _version_tuple(text: str) -> tuple[int, ...]:
    return tuple(int(p) for p in text.split(".")[:2] if p.isdigit())


def setup_line() -> tuple[str, bool]:
    py = ".".join(str(v) for v in sys.version_info[:3])
    ok = sys.version_info >= (3, 11)
    try:
        import scrapy

        scrapy_version = scrapy.__version__
        ok = ok and _version_tuple(scrapy_version) >= MIN_SCRAPY
    except ImportError:
        scrapy_version = "not installed"
        ok = False
    mark = "OK" if ok else "PROBLEM: needs Python 3.11+ and Scrapy 2.15+ (run the setup script)"
    return f"Setup: Python {py}, Scrapy {scrapy_version} - {mark}", ok


def status_report(
    firms_path: str | Path,
    master_path: str | Path,
    dnc_path: str | Path,
    unsubscribed_path: str | Path,
    today: date | None = None,
) -> str:
    today = today or date.today()
    lines = [f"LawAudit firm data - status on {today.isoformat()}", ""]
    setup, setup_ok = setup_line()
    lines.append(setup)

    # firms.csv
    firms_path = Path(firms_path)
    firm_rows: list[dict] = []
    if firms_path.exists():
        with firms_path.open(newline="", encoding="utf-8-sig") as fh:
            firm_rows = list(csv.DictReader(fh))
    with_site = sum(1 for r in firm_rows if (r.get("website") or "").strip())
    not_found = sum(1 for r in firm_rows if (r.get("website_found_by") or "") == "not found")
    unsearched = len(firm_rows) - with_site - not_found
    lines.append(
        f"Firm list ({firms_path.name}): {len(firm_rows):,} firms; {with_site:,} with a website; "
        f"{not_found:,} searched, none found; {unsearched:,} not yet searched"
    )

    # master list
    master_path = Path(master_path)
    due = 0
    master = MasterList.load(master_path) if master_path.exists() else None
    if master is None or not master.rows:
        lines.append(f"Master list ({master_path}): not created yet")
    else:
        rows = list(master.rows.values())
        counts = Counter(_norm(r.get("classification")) or "(none)" for r in rows)
        order = ["Sole", "Small (2-4)", "Larger", "Check manually", "Exclude"]
        sizes = " | ".join(f"{k} {counts[k]:,}" for k in order if counts[k])
        emails = Counter(_norm(r.get("email_type")) for r in rows if _norm(r.get("email")))
        refuse = sum(1 for r in rows if _norm(r.get("no_unsolicited_email_notice")))
        postal = sum(1 for r in rows if _norm(r.get("postal_address")))
        po_box = sum(1 for r in rows if _norm(r.get("po_box")))
        office = sum(1 for r in rows if _norm(r.get("office_address")))
        crawled = [d for d in (_as_date(r.get("last_crawled")) for r in rows) if d]
        due = sum(1 for d in crawled if d < today - timedelta(days=REFRESH_DAYS))
        recent = today - timedelta(days=REFRESH_DAYS)
        mailed = sum(1 for r in rows if (d := _as_date(r.get("last_mailed"))) and d >= recent)
        emailed = sum(1 for r in rows if (d := _as_date(r.get("last_emailed"))) and d >= recent)
        campaigns = list(dict.fromkeys((c.get("campaign"), c.get("channel")) for c in master.campaigns))
        lines += [
            f"Master list ({master_path}): {len(rows):,} firms",
            f"  {sizes}",
            f"  with a mailing address: {postal:,} (of which PO Box {po_box:,}); with an office address: {office:,}",
            f"  with an email address: {sum(emails.values()):,} (general {emails['general']:,}, "
            f"personal {emails['personal']:,}); site refuses unsolicited email: {refuse:,}",
            f"  last crawled: {min(crawled).isoformat() if crawled else '-'} to "
            f"{max(crawled).isoformat() if crawled else '-'}; due for a refresh (over {REFRESH_DAYS} days): {due:,}",
            f"  mailed in the last {REFRESH_DAYS} days: {mailed:,}; emailed: {emailed:,}",
            f"  campaigns recorded: {len(campaigns):,}"
            + (f" (latest: {campaigns[-1][0]}, {campaigns[-1][1]})" if campaigns else ""),
        ]

    dnc_count = len(DoNotContactList.load(dnc_path)) if Path(dnc_path).exists() else 0
    lines.append(
        f"Do-not-contact entries: {dnc_count:,}; unsubscribed addresses: {len(load_unsubscribed(unsubscribed_path)):,}"
    )

    # what to do next
    if not setup_ok:
        step = "run the setup script (setup.sh on Mac/Linux, setup.bat on Windows)"
    elif not firm_rows:
        step = "build the firm list:  python lawaudit.py build-list <the two ABN Bulk Extract zip files>"
    elif unsearched:
        step = "find websites:  python lawaudit.py find-websites  (try --limit 50 first)"
    elif master is None or len(master.rows) < with_site * 0.9:
        step = "crawl the websites:  python lawaudit.py crawl  (add --skip-crawled-within 1 to resume)"
    elif due:
        step = f"refresh older firms:  python lawaudit.py crawl --skip-crawled-within {REFRESH_DAYS}"
    else:
        step = "make a list:  python lawaudit.py make-list --help"
    lines += ["", f"Next step: {step}"]
    return "\n".join(lines)

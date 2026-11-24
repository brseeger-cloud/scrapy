"""Fill in the website column of firms.csv for firms that have none.

    python find_websites.py                 # every firm with no website
    python find_websites.py --limit 50      # try it on 50 firms first

For each firm it guesses likely domains from the name (smithlawyers.com.au,
smith-lawyers.com.au, smithlawyers.au, ...) and accepts one only if the home
page shows the firm's ABN, or its name plus legal wording and its postcode or
state. firms.csv is backed up first and saved as it goes; firms not found are
marked so later runs skip them (use --recheck-not-found to try them again).
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", default="firms.csv", help="firm list to update in place (default: firms.csv)")
    parser.add_argument("--dnc", default="do_not_contact.csv", help="do-not-contact CSV (default: do_not_contact.csv)")
    parser.add_argument("--limit", type=int, default=0, help="only check this many firms (default: all)")
    parser.add_argument("--recheck-not-found", action="store_true", help="try firms not found last time again")
    parser.add_argument("--log-dir", default="logs", help="directory for the log file")
    parser.add_argument(
        "-s", "--set", action="append", default=[], metavar="NAME=VALUE", help="override any Scrapy setting"
    )
    args = parser.parse_args(argv)

    sys.path.insert(0, str(HERE))
    from lawfirm_enrich.inputs import ensure_default_dnc

    ensure_default_dnc(args.dnc)
    for label, path in (("input", args.input), ("do-not-contact", args.dnc)):
        if not Path(path).exists():
            print(f"error: {label} file not found: {path}", file=sys.stderr)
            return 2
    for name in ("input", "dnc", "log_dir"):
        setattr(args, name, str(Path(getattr(args, name)).resolve()))
    os.chdir(HERE)
    os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "lawfirm_enrich.settings")
    sys.path.insert(0, str(HERE))

    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    settings = get_project_settings()
    Path(args.log_dir).mkdir(parents=True, exist_ok=True)
    log_file = Path(args.log_dir) / f"websites_{datetime.now():%Y%m%d_%H%M%S}.log"
    settings.set("LOG_FILE", str(log_file), priority="cmdline")
    for item in args.set:
        name, _, value = item.partition("=")
        settings.set(name.strip(), value.strip(), priority="cmdline")

    process = CrawlerProcess(settings)
    crawler = process.create_crawler("websites")
    process.crawl(crawler, input=args.input, dnc=args.dnc, limit=args.limit, recheck=args.recheck_not_found)
    print(
        f"Started. This can take hours: progress is shown every 100 firms. Leave this window open.\n"
        f"Full log: {log_file}",
        flush=True,
    )
    process.start()

    stats = crawler.stats.get_stats() if crawler.stats else {}
    print(f"Firms checked:  {stats.get('websites/firms_to_check', 0)}")
    print(f"Found by ABN:   {stats.get('websites/ABN_on_site', 0)}")
    print(f"Found by name:  {stats.get('websites/name_on_site', 0)}")
    unconfirmed = stats.get("websites/name_on_site_(location_unconfirmed)", 0)
    print(f"Found by name, location unconfirmed (worth a look): {unconfirmed}")
    print(f"Not found:      {stats.get('websites/not_found', 0)}")
    print(f"Updated:        {args.input}")
    print(f"Log file:       {log_file}")
    if stats.get("finish_reason") not in (None, "finished"):
        print(f"Run ended early: {stats.get('finish_reason')} (see log)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Run the whole enrichment: crawl, classify, write firms_enriched.xlsx.

python run.py                       # uses firms.csv and do_not_contact.csv
python run.py --input my_firms.csv --output out/enriched.xlsx
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
    parser.add_argument("--input", default="firms.csv", help="input CSV (default: firms.csv)")
    parser.add_argument("--dnc", default="do_not_contact.csv", help="do-not-contact CSV (default: do_not_contact.csv)")
    parser.add_argument(
        "--unsubscribed", default="unsubscribed.csv", help="unsubscribed addresses (default: unsubscribed.csv)"
    )
    parser.add_argument("--output", default="output/firms_enriched.xlsx", help="output workbook")
    parser.add_argument("--failed-log", default="output/failed_sites.csv", help="failed-sites CSV")
    parser.add_argument("--log-dir", default="logs", help="directory for the Scrapy log file")
    parser.add_argument(
        "--master", default="data/master.xlsx", help="master list to update (default: data/master.xlsx)"
    )
    parser.add_argument("--no-master", action="store_true", help="don't update a master list")
    parser.add_argument(
        "--skip-crawled-within",
        type=int,
        default=0,
        metavar="DAYS",
        help="skip firms the master list shows were crawled in the last DAYS days (use 1 to resume an interrupted run)",
    )
    parser.add_argument(
        "-s",
        "--set",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help="override any Scrapy setting, e.g. -s CONCURRENT_REQUESTS=8",
    )
    args = parser.parse_args(argv)

    sys.path.insert(0, str(HERE))
    from lawfirm_enrich.inputs import ensure_default_dnc

    ensure_default_dnc(args.dnc)
    for label, path in (("input", args.input), ("do-not-contact", args.dnc)):
        if not Path(path).exists():
            print(f"error: {label} file not found: {path}", file=sys.stderr)
            return 2

    # Resolve paths against the caller's directory, then run from the project
    # directory so Scrapy finds scrapy.cfg and the settings module.
    for name in ("input", "dnc", "output", "failed_log", "log_dir", "master", "unsubscribed"):
        setattr(args, name, str(Path(getattr(args, name)).resolve()))
    os.chdir(HERE)
    os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "lawfirm_enrich.settings")
    sys.path.insert(0, str(HERE))

    from lawfirm_enrich.master import check_writable

    if not args.no_master:
        try:
            check_writable(args.master)
        except PermissionError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    from scrapy.crawler import CrawlerProcess
    from scrapy.utils.project import get_project_settings

    settings = get_project_settings()
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"crawl_{datetime.now():%Y%m%d_%H%M%S}.log"
    settings.set("LOG_FILE", str(log_file), priority="cmdline")
    settings.set("LAWFIRM_OUTPUT_XLSX", args.output, priority="cmdline")
    settings.set("LAWFIRM_FAILED_CSV", args.failed_log, priority="cmdline")
    settings.set("LAWFIRM_UNSUBSCRIBED_CSV", args.unsubscribed, priority="cmdline")
    settings.set("LAWFIRM_MASTER_XLSX", "" if args.no_master else args.master, priority="cmdline")
    settings.set("LAWFIRM_SKIP_CRAWLED_WITHIN_DAYS", args.skip_crawled_within, priority="cmdline")
    for item in args.set:
        name, _, value = item.partition("=")
        settings.set(name.strip(), value.strip(), priority="cmdline")

    process = CrawlerProcess(settings)
    crawler = process.create_crawler("firms")
    process.crawl(crawler, input=args.input, dnc=args.dnc)
    print(
        f"Started. This can take hours: progress is shown every 100 firms. Leave this window open.\n"
        f"Full log: {log_file}",
        flush=True,
    )
    process.start()

    stats = crawler.stats.get_stats() if crawler.stats else {}
    print(f"Log file:      {log_file}")
    print(f"Workbook:      {args.output}")
    print(f"Failed sites:  {args.failed_log}")
    if not args.no_master:
        print(
            f"Master list:   {stats.get('lawfirm/master_path', args.master)} ({stats.get('lawfirm/master_rows', 0)} firms)"
        )
    print(
        f"Sites OK / failed / on do-not-contact list: {stats.get('lawfirm/sites_ok', 0)} / "
        f"{stats.get('lawfirm/sites_failed', 0)} / {stats.get('lawfirm/dnc_excluded', 0)}"
    )
    if stats.get("finish_reason") not in (None, "finished"):
        print(f"Crawl ended early: {stats.get('finish_reason')} (see log)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

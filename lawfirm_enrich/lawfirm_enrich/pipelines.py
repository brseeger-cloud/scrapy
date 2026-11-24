"""Item pipelines.

Order (see ITEM_PIPELINES in settings.py):

1. DoNotContactPipeline – drops any row whose firm is on do_not_contact.csv
   (checked again here, after redirects, even though the spider already
   skips those firms before crawling), and removes addresses listed in
   unsubscribed.csv.
2. EmailScrubPipeline – removes anything that looks like an email address
   from every field except the email columns.
3. MasterListPipeline – merges each row into the master list
   (data/master.xlsx), saving every 1,000 rows and at the end.
4. ExcelExportPipeline – collects rows and writes firms_enriched.xlsx and
   failed_sites.csv when the crawl finishes.
"""

from __future__ import annotations

import csv
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path

from scrapy.exceptions import DropItem

from .export import write_failed_csv, write_workbook
from .inputs import DoNotContactList, Firm
from .items import EMAIL_COLUMNS, FAILED_COLUMNS, OUTPUT_COLUMNS
from .master import MasterList
from .privacy import scrub_value
from .unsubscribe import load_unsubscribed, strip_unsubscribed

logger = logging.getLogger(__name__)


class DoNotContactPipeline:
    def __init__(self, crawler):
        self.crawler = crawler
        self.dnc: DoNotContactList | None = None
        self.unsubscribed: set[str] | None = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_item(self, item):
        if self.dnc is None:
            # Loaded on first use, after the spider has synced opt-outs from the
            # master list. Fails if the file is missing: exclusion is never skipped.
            path = getattr(self.crawler.spider, "dnc_path", None) or self.crawler.settings.get("LAWFIRM_DNC_CSV")
            self.dnc = DoNotContactList.load(path)
        firm = Firm(
            row=0,
            firm_name=item.get("firm_name", ""),
            abn=item.get("abn", ""),
            entity_type="",
            state="",
            postcode="",
            website=item.get("website", ""),
            url="",
            scheme_given=False,
        )
        if self.dnc.matches_firm(firm, item.get("final_url", ""), *item.get("pages_used", "").split("\n")):
            self.crawler.stats.inc_value("lawfirm/dnc_dropped_in_pipeline")
            raise DropItem(f"Row {item.get('input_row')}: on do-not-contact list")
        if self.unsubscribed is None:
            self.unsubscribed = load_unsubscribed(self.crawler.settings.get("LAWFIRM_UNSUBSCRIBED_CSV"))
        item = dict(item)
        if strip_unsubscribed(item, self.unsubscribed):
            self.crawler.stats.inc_value("lawfirm/unsubscribed_addresses_removed")
        return item


class EmailScrubPipeline:
    def process_item(self, item):
        return {k: v if k in EMAIL_COLUMNS else scrub_value(v) for k, v in dict(item).items()}


class MasterListPipeline:
    SAVE_EVERY = 1000  # rows between saves, so a long run that crashes loses little

    def __init__(self, crawler):
        self.crawler = crawler
        self.path = crawler.settings.get("LAWFIRM_MASTER_XLSX")
        self.master: MasterList | None = None
        self.unsaved = 0

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def _master(self) -> MasterList:
        if self.master is None:
            self.master = MasterList.load(self.path)
            dnc_path = getattr(self.crawler.spider, "dnc_path", None) or self.crawler.settings.get("LAWFIRM_DNC_CSV")
            removed = self.master.remove_do_not_contact(DoNotContactList.load(dnc_path))
            if removed:
                logger.info(f"Removed {removed} do-not-contact firm(s) from the master list")
            unsubscribed = load_unsubscribed(self.crawler.settings.get("LAWFIRM_UNSUBSCRIBED_CSV"))
            for row in self.master.rows.values():
                strip_unsubscribed(row, unsubscribed)
        return self.master

    def process_item(self, item):
        if self.path:
            self._master().upsert(dict(item))
            self.unsaved += 1
            if self.unsaved >= self.SAVE_EVERY:
                self.master.save()
                self.unsaved = 0
        return item

    def close_spider(self):
        if not self.path:
            return
        master = self._master()
        saved = master.save()
        self.crawler.stats.set_value("lawfirm/master_rows", len(master.rows))
        self.crawler.stats.set_value("lawfirm/master_path", str(saved))
        logger.info(f"Master list {saved}: {len(master.rows)} firms")


class ExcelExportPipeline:
    def __init__(self, crawler):
        self.crawler = crawler
        self.rows: list[dict] = []
        self.started = datetime.now()

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_item(self, item):
        self.rows.append(dict(item))
        return item

    def close_spider(self):
        s = self.crawler.settings
        stats = self.crawler.stats
        spider = self.crawler.spider
        rows = sorted(self.rows, key=lambda r: int(r.get("input_row") or 0))

        failed = []
        for r in rows:
            if r.get("crawl_status") in ("failed", "no website"):
                failed.append(
                    {
                        "input_row": r.get("input_row"),
                        "firm_name": r.get("firm_name"),
                        "abn": r.get("abn"),
                        "website": r.get("website"),
                        "failed_url": r.get("source_url") if r.get("crawl_status") == "failed" else "",
                        "error": r.get("_error") or r.get("crawl_status"),
                        "date_collected": r.get("date_collected"),
                    }
                )

        counts: dict[str, int] = {}
        for r in rows:
            counts[r["classification"]] = counts.get(r["classification"], 0) + 1

        run_info = [
            ("run started", self.started.isoformat(timespec="seconds")),
            ("run finished", datetime.now().isoformat(timespec="seconds")),
            ("input file", getattr(spider, "input_path", "")),
            ("do-not-contact file", getattr(spider, "dnc_path", "")),
            ("firms in input", stats.get_value("lawfirm/firms_in_input", 0)),
            (
                "excluded: on do-not-contact list (not crawled, not in output)",
                stats.get_value("lawfirm/dnc_excluded", 0) + stats.get_value("lawfirm/dnc_dropped_in_pipeline", 0),
            ),
            (
                f"skipped: crawled within the last {s.getint('LAWFIRM_SKIP_CRAWLED_WITHIN_DAYS')} days",
                stats.get_value("lawfirm/skipped_recent", 0),
            ),
            ("rows written", len(rows)),
            ("sites crawled OK", stats.get_value("lawfirm/sites_ok", 0)),
            ("sites failed", stats.get_value("lawfirm/sites_failed", 0)),
            ("rows with no website", stats.get_value("lawfirm/no_website", 0)),
            ("master list", s.get("LAWFIRM_MASTER_XLSX") or "(disabled)"),
            *[(f"classified: {k}", v) for k, v in sorted(counts.items())],
            ("user agent", s.get("USER_AGENT")),
            ("ROBOTSTXT_OBEY", s.getbool("ROBOTSTXT_OBEY")),
            ("AUTOTHROTTLE_ENABLED", s.getbool("AUTOTHROTTLE_ENABLED")),
            ("DOWNLOAD_DELAY (s)", s.getfloat("DOWNLOAD_DELAY")),
            ("RETRY_TIMES", s.getint("RETRY_TIMES")),
            ("DOWNLOAD_TIMEOUT (s)", s.getint("DOWNLOAD_TIMEOUT")),
            ("max pages per site", s.getint("LAWFIRM_MAX_PAGES")),
            (
                "email addresses",
                "only plainly published addresses on the firm's own (or a webmail) domain, in the email columns",
            ),
        ]

        xlsx = write_workbook(
            s.get("LAWFIRM_OUTPUT_XLSX"),
            columns=OUTPUT_COLUMNS,
            rows=rows,
            failed_columns=FAILED_COLUMNS,
            failed_rows=failed,
            run_info=run_info,
        )
        csv_path = write_failed_csv(s.get("LAWFIRM_FAILED_CSV"), FAILED_COLUMNS, failed)
        logger.info(f"Wrote {len(rows)} rows to {xlsx}; {len(failed)} failed sites logged to {csv_path}")


class WebsiteListPipeline:
    """Writes websites found by the "websites" spider back into firms.csv.

    The original file is copied to firms.backup-<date-time>.csv first, and the
    file is rewritten every 200 results so an interrupted run keeps its work.
    """

    SAVE_EVERY = 200

    def __init__(self, crawler):
        self.crawler = crawler
        self.unsaved = 0
        self.backed_up = False

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler)

    def process_item(self, item):
        spider = self.crawler.spider
        row = spider.rows[item["row"]]
        if item["website"]:
            row["website"] = item["website"]
        row["website_found_by"] = item["found_by"]
        row["website_checked"] = datetime.now().date().isoformat()
        self.crawler.stats.inc_value(f"websites/{item['found_by'].replace(' ', '_')}")
        self.unsaved += 1
        if self.unsaved >= self.SAVE_EVERY:
            self._save()
        return item

    def close_spider(self):
        if self.unsaved:
            self._save()

    def _save(self):
        spider = self.crawler.spider
        path = Path(spider.input_path)
        if not self.backed_up:
            backup = path.with_name(f"{path.stem}.backup-{datetime.now():%Y%m%d-%H%M%S}{path.suffix}")
            shutil.copy2(path, backup)
            logger.info(f"Backed up {path} to {backup}")
            self.backed_up = True
        fieldnames = list(spider.fieldnames)
        for extra in ("website_found_by", "website_checked"):
            if extra not in fieldnames:
                fieldnames.append(extra)
        tmp = path.with_name(f".{path.name}.tmp")
        with tmp.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(spider.rows)
        os.replace(tmp, path)
        self.unsaved = 0

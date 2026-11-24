"""Item pipelines.

Order (see ITEM_PIPELINES in settings.py):

1. DoNotContactPipeline – drops any row whose firm is on do_not_contact.csv
   (checked again here, after redirects, even though the spider already
   skips those firms before crawling).
2. EmailScrubPipeline – removes anything that looks like an email address
   from every field.
3. MasterListPipeline – merges each row into the master list
   (data/master.xlsx), saving every 1,000 rows and at the end.
4. ExcelExportPipeline – collects rows and writes firms_enriched.xlsx and
   failed_sites.csv when the crawl finishes.
"""

from __future__ import annotations

import logging
from datetime import datetime

from scrapy.exceptions import DropItem

from .export import write_failed_csv, write_workbook
from .inputs import DoNotContactList, Firm
from .items import FAILED_COLUMNS, OUTPUT_COLUMNS
from .master import MasterList
from .privacy import scrub_value

logger = logging.getLogger(__name__)


class DoNotContactPipeline:
    def __init__(self, crawler):
        self.crawler = crawler
        self.dnc: DoNotContactList | None = None

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
        return item


class EmailScrubPipeline:
    def process_item(self, item):
        return scrub_value(dict(item))


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
            ("email addresses collected", "none – all page text and output is scrubbed of email addresses"),
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

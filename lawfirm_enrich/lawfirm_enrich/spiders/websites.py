"""Find websites for firms in firms.csv that have none (see websites.py)."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from urllib.parse import urlsplit

import scrapy
from scrapy.http import HtmlResponse

from ..extract import html_to_lines
from ..inputs import DoNotContactList
from ..websites import candidate_domains, verify

logger = logging.getLogger(__name__)


class WebsitesSpider(scrapy.Spider):
    name = "websites"
    custom_settings = {
        "ITEM_PIPELINES": {"lawfirm_enrich.pipelines.WebsiteListPipeline": 100},
        # Most guessed domains do not exist; don't spend long on each.
        "RETRY_TIMES": 1,
        "DOWNLOAD_TIMEOUT": 15,
        "CONCURRENT_REQUESTS": 32,
    }

    def __init__(
        self,
        *args,
        input: str | None = None,
        dnc: str | None = None,
        limit: str | int = 0,
        recheck: str | bool = False,
        **kwargs,
    ):
        super().__init__(*args, **kwargs)
        self.input_path = input
        self.dnc_path = dnc
        self.limit = int(limit or 0)
        self.recheck = str(recheck).lower() in ("1", "true", "yes")
        self.fieldnames: list[str] = []
        self.rows: list[dict] = []

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.input_path = spider.input_path or crawler.settings.get("LAWFIRM_INPUT_CSV")
        spider.dnc_path = spider.dnc_path or crawler.settings.get("LAWFIRM_DNC_CSV")
        return spider

    async def start(self):
        with Path(self.input_path).open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            self.fieldnames = list(reader.fieldnames or [])
            self.rows = list(reader)
        dnc = DoNotContactList.load(self.dnc_path)

        todo = []
        for i, row in enumerate(self.rows):
            if (row.get("website") or "").strip():
                continue
            if row.get("website_checked") and not self.recheck:
                continue  # searched before and not found
            if dnc.matches(firm_name=row.get("firm_name", ""), abn=row.get("abn", "")):
                continue
            todo.append(i)
        if self.limit:
            todo = todo[: self.limit]
        logger.info(f"{len(todo)} of {len(self.rows)} firms need a website")
        self.crawler.stats.set_value("websites/firms_to_check", len(todo))

        for i in todo:
            row = self.rows[i]
            domains = candidate_domains(row.get("firm_name", ""), row.get("legal_name", ""))
            if domains:
                yield self._request(i, domains, 0)
            else:
                yield {"row": i, "website": "", "found_by": "not found"}

    def _request(self, i: int, domains: list[str], k: int) -> scrapy.Request:
        return scrapy.Request(
            f"https://www.{domains[k]}/",
            callback=self.check,
            errback=self.failed,
            cb_kwargs={"i": i, "domains": domains, "k": k},
            dont_filter=True,
        )

    def _next(self, i: int, domains: list[str], k: int):
        if k + 1 < len(domains):
            yield self._request(i, domains, k + 1)
        else:
            yield {"row": i, "website": "", "found_by": "not found"}

    def check(self, response, i: int, domains: list[str], k: int):
        if isinstance(response, HtmlResponse):
            row = self.rows[i]
            title = response.css("title::text").get() or ""
            text = title + "\n" + "\n".join(html_to_lines(root=response.selector.root))
            abns = [row.get("abn", ""), *(row.get("other_abns") or "").split(";")]
            how = verify(
                text, row.get("firm_name", ""), abns, state=row.get("state", ""), postcode=row.get("postcode", "")
            )
            if how:
                parts = urlsplit(response.url)
                yield {"row": i, "website": f"{parts.scheme}://{parts.netloc}/", "found_by": how}
                return
        yield from self._next(i, domains, k)

    def failed(self, failure):
        kw = failure.request.cb_kwargs
        yield from self._next(kw["i"], kw["domains"], kw["k"])

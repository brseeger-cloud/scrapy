"""Crawl each firm's home, about, team/our-people and contact pages."""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

import scrapy
from scrapy.exceptions import (
    CannotResolveHostError,
    DownloadConnectionRefusedError,
    DownloadFailedError,
    DownloadTimeoutError,
    IgnoreRequest,
)
from scrapy.http import HtmlResponse
from scrapy.spidermiddlewares.httperror import HttpError

from ..classify import classify
from ..emails import extract_emails
from ..extract import Page, analyse, html_to_lines
from ..inputs import DoNotContactList, Firm, host_of, read_firms
from ..items import build_row
from ..master import MasterList, firm_key, sync_opt_outs

logger = logging.getLogger(__name__)

# How many pages of each kind to fetch (in addition to the home page)
CATEGORY_LIMITS = {"team": 2, "about": 1, "contact": 1}

# Tried, in this order, only when no link to that kind of page was found
GUESSED_PATHS = [
    ("team", "/our-team"),
    ("contact", "/contact-us"),
    ("about", "/about-us"),
    ("team", "/our-people"),
    ("contact", "/contact"),
    ("about", "/about"),
]

_LINK_RULES = {
    "about": (
        re.compile(r"\babout\b|who we are|our firm|the firm|our story|firm profile|our history", re.I),
        re.compile(r"about|who-?we-?are|our-?firm|the-?firm|our-?story|firm-?profile|history", re.I),
    ),
    "team": (
        re.compile(
            r"\bteam\b|\bpeople\b|our lawyers|\blawyers\b|\bsolicitors\b|\bstaff\b|meet (?:the|our)|"
            r"professionals|\bpartners\b|who'?s who|our practitioners",
            re.I,
        ),
        re.compile(r"team|people|lawyers|solicitors|staff|professionals|partners|practitioners|meet-", re.I),
    ),
    "contact": (
        re.compile(r"contact|location|\boffices?\b|find us|get in touch", re.I),
        re.compile(r"contact|locations?|offices?|find-?us|get-?in-?touch", re.I),
    ),
}
_SKIP_PATH_RE = re.compile(
    r"(?:^|/)(?:blog|news|articles?|insights|category|tag|author|wp-content|wp-admin|wp-json|feed|login|"
    r"cart|shop|careers?|jobs|privacy|terms|disclaimer|sitemap|search|events?|publications|"
    r"testimonials|faqs?|cdn-cgi)(?:/|$)|\.(?:pdf|jpe?g|png|gif|docx?|xlsx?|pptx?|zip|mp4|mp3|svg|webp|ics|vcf)$",
    re.I,
)


@dataclass
class FirmState:
    firm: Firm
    max_pages: int
    hosts: set[str] = field(default_factory=set)
    queue: list[tuple[str, str]] = field(default_factory=list)
    tried: set[str] = field(default_factory=set)
    requested: int = 0
    pages: list[Page] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    categories: Counter = field(default_factory=Counter)
    guesses: list[tuple[str, str]] = field(default_factory=lambda: list(GUESSED_PATHS))
    final_url: str = ""
    home_error: str = ""
    http_fallback_done: bool = False
    guessed_urls: set[str] = field(default_factory=set)


def _url_key(url: str) -> str:
    p = urlsplit(url)
    path = p.path.rstrip("/") or "/"
    return urlunsplit(("", (p.hostname or "").removeprefix("www."), path.lower(), p.query, ""))


def describe_failure(failure) -> str:
    if failure.check(HttpError):
        return f"HTTP {failure.value.response.status}"
    if failure.check(IgnoreRequest):
        msg = str(failure.value)
        return "blocked by robots.txt" if "robots" in msg.lower() else (msg or "request ignored")
    if failure.check(CannotResolveHostError):
        return "DNS lookup failed (domain does not resolve)"
    if failure.check(DownloadTimeoutError):
        return "timed out"
    if failure.check(DownloadConnectionRefusedError):
        return "connection refused"
    name = type(failure.value).__name__
    text = f"{name}: {failure.value}"
    if "ssl" in text.lower() or "tls" in text.lower() or "certificate" in text.lower():
        return f"SSL/TLS error: {failure.value}"[:250]
    if failure.check(DownloadFailedError):
        return f"download failed: {failure.value}"[:250]
    return text[:250]


class FirmsSpider(scrapy.Spider):
    name = "firms"

    def __init__(self, *args, input: str | None = None, dnc: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.input_path = input
        self.dnc_path = dnc

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        s = crawler.settings
        spider.input_path = spider.input_path or s.get("LAWFIRM_INPUT_CSV")
        spider.dnc_path = spider.dnc_path or s.get("LAWFIRM_DNC_CSV")
        spider.max_pages = s.getint("LAWFIRM_MAX_PAGES", 6)
        spider.tz = ZoneInfo(s.get("LAWFIRM_TIMEZONE", "Australia/Sydney"))
        spider.master_path = s.get("LAWFIRM_MASTER_XLSX")
        spider.skip_days = s.getint("LAWFIRM_SKIP_CRAWLED_WITHIN_DAYS")
        return spider

    async def start(self):
        firms = read_firms(self.input_path)
        if self.master_path:
            # Firms marked "Opted out" in the master list join the do-not-contact
            # list before it is loaded below.
            sync_opt_outs(self.master_path, self.dnc_path)
        self.dnc = DoNotContactList.load(self.dnc_path)
        stats = self.crawler.stats
        stats.set_value("lawfirm/firms_in_input", len(firms))
        logger.info(f"Loaded {len(firms)} firms from {self.input_path}; do-not-contact entries: {len(self.dnc)}")

        recent: dict = {}
        if self.master_path and self.skip_days > 0:
            cutoff = datetime.now(self.tz).date() - timedelta(days=self.skip_days)
            recent = {k: d for k, d in MasterList.load(self.master_path).last_crawled().items() if d > cutoff}

        for firm in firms:
            if self.dnc.matches_firm(firm):
                # Deliberately log only the row number, not the firm's details.
                stats.inc_value("lawfirm/dnc_excluded")
                logger.info(f"Row {firm.row}: on do-not-contact list - skipped")
                continue
            if firm_key(firm.abn, firm.website, firm.firm_name) in recent:
                stats.inc_value("lawfirm/skipped_recent")
                continue
            if not firm.url:
                stats.inc_value("lawfirm/no_website")
                yield self._row(
                    FirmState(firm, self.max_pages), status="no website", error="no usable website in input"
                )
                continue
            state = FirmState(firm, self.max_pages, hosts={host_of(firm.url)})
            yield self._request(state, firm.url, "home")

    # ------------------------------------------------------------------ requests

    def _request(self, state: FirmState, url: str, category: str) -> scrapy.Request:
        state.requested += 1
        state.tried.add(_url_key(url))
        return scrapy.Request(
            url,
            callback=self.parse_page,
            errback=self.on_error,
            cb_kwargs={"state": state, "category": category},
            meta={"firm_row": state.firm.row},
            dont_filter=True,  # per-firm de-duplication is done via state.tried
        )

    def _next(self, state: FirmState):
        """Yield the next request for this firm, or its finished row."""
        if state.requested < state.max_pages:
            while state.queue:
                url, category = state.queue.pop(0)
                if _url_key(url) in state.tried:
                    continue
                yield self._request(state, url, category)
                return
            if state.pages:  # only guess paths once the site is known to respond
                base = state.final_url or state.firm.url
                while state.guesses:
                    category, path = state.guesses.pop(0)
                    if state.categories[category]:
                        continue
                    url = urlunsplit(urlsplit(base)._replace(path=path, query="", fragment=""))
                    if _url_key(url) in state.tried:
                        continue
                    state.categories[category] += 1
                    state.guessed_urls.add(url)
                    yield self._request(state, url, category)
                    return
        yield self._finish(state)

    # ----------------------------------------------------------------- callbacks

    def parse_page(self, response, state: FirmState, category: str):
        if not isinstance(response, HtmlResponse):
            state.failed.append(f"{response.url} (not an HTML page)")
            if category == "home" and not state.pages:
                state.home_error = "home page is not HTML"
            yield from self._next(state)
            return

        if category == "home":
            state.final_url = response.url
            state.hosts.add(host_of(response.url))
        elif _url_key(response.url) in {_url_key(p.url) for p in state.pages}:
            # e.g. a guessed /about-us that redirected back to the home page
            yield from self._next(state)
            return

        page = Page(
            url=response.url,
            category=category,
            lines=html_to_lines(root=response.selector.root),
            emails=extract_emails(response.selector.root, state.hosts),
        )
        state.pages.append(page)
        self._discover_links(response, state)
        yield from self._next(state)

    def on_error(self, failure):
        request = failure.request
        state: FirmState = request.cb_kwargs["state"]
        category: str = request.cb_kwargs["category"]
        reason = describe_failure(failure)
        logger.info(f"Row {state.firm.row}: {category} page failed ({reason}): {request.url}")

        if category == "home" and not state.pages:
            # A site given without a scheme may only work over plain HTTP.
            if (
                not state.firm.scheme_given
                and not state.http_fallback_done
                and request.url.startswith("https://")
                and not failure.check(HttpError, CannotResolveHostError, IgnoreRequest)
            ):
                state.http_fallback_done = True
                yield self._request(state, "http://" + request.url[len("https://") :], "home")
                return
            state.home_error = reason
            state.failed.append(f"{request.url} ({reason})")
            yield self._finish(state)
            return

        # A guessed path that does not exist is expected, not a failure.
        guess_missing = (
            request.url in state.guessed_urls
            and failure.check(HttpError)
            and failure.value.response.status in (404, 410)
        )
        if not guess_missing:
            state.failed.append(f"{request.url} ({reason})")
        yield from self._next(state)

    # ------------------------------------------------------------------- helpers

    def _discover_links(self, response, state: FirmState) -> None:
        candidates: dict[str, list[tuple[int, str]]] = {c: [] for c in CATEGORY_LIMITS}
        seen = set()
        for a in response.css("a[href]"):
            href = (a.attrib.get("href") or "").strip()
            if not href or href.startswith(("mailto:", "tel:", "javascript:", "#", "sms:", "fax:")):
                continue
            url = response.urljoin(href).split("#", 1)[0]
            parts = urlsplit(url)
            if parts.scheme not in ("http", "https") or host_of(url) not in state.hosts:
                continue
            path = parts.path or "/"
            if path in ("", "/") or _SKIP_PATH_RE.search(path):
                continue
            key = _url_key(url)
            if key in seen or key in state.tried:
                continue
            seen.add(key)
            text = " ".join(" ".join(a.css("::text").getall()).split())
            text = f"{text} {a.attrib.get('title', '')}".strip()
            segments = [s for s in path.split("/") if s]
            last = segments[-1] if segments else ""
            for category, (text_re, path_re) in _LINK_RULES.items():
                score = 0
                if text and len(text) < 40 and text_re.search(text):
                    score += 3
                if path_re.search(last):
                    score += 2
                score -= max(0, len(segments) - 1)
                if score >= 2:
                    candidates[category].append((score, url))

        for category, limit in CATEGORY_LIMITS.items():
            ranked = sorted(candidates[category], key=lambda t: (-t[0], len(t[1])))
            for score, url in ranked:
                if state.categories[category] >= limit:
                    break
                # extra pages of the same kind only when the link text clearly matches
                if state.categories[category] >= 1 and score < 3:
                    break
                if any(_url_key(url) == _url_key(u) for u, _ in state.queue):
                    continue
                state.queue.append((url, category))
                state.categories[category] += 1

    def _today(self) -> str:
        return datetime.now(self.tz).date().isoformat()

    def _row(self, state: FirmState, *, status: str, error: str = "") -> dict:
        return build_row(
            state.firm,
            analysis=None,
            classification=classify(None, crawl_error=error),
            crawl_status=status,
            final_url=state.final_url,
            pages_used=[],
            pages_failed=state.failed,
            date_collected=self._today(),
            error=error,
        )

    def _finish(self, state: FirmState) -> dict:
        stats = self.crawler.stats
        if not state.pages:
            stats.inc_value("lawfirm/sites_failed")
            return self._row(state, status="failed", error=state.home_error or "no pages fetched")

        host = host_of(state.final_url or state.firm.url)
        analysis = analyse(state.firm.firm_name, state.firm.entity_type, host, state.pages)
        classification = classify(analysis, entity_type=state.firm.entity_type)
        stats.inc_value("lawfirm/sites_ok")
        stats.inc_value("lawfirm/pages_used", len(state.pages))
        return build_row(
            state.firm,
            analysis=analysis,
            classification=classification,
            crawl_status="ok" if not state.failed else "ok (some pages failed)",
            final_url=state.final_url,
            pages_used=[p.url for p in state.pages],
            pages_failed=state.failed,
            date_collected=self._today(),
        )

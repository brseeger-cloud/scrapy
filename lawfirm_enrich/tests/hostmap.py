"""Test-only downloader middleware: serves guessed domains from local mock sites.

Mapped hosts are rewritten to a local server; every other host fails as if it
did not exist, so tests never contact a real website.
"""

import json
from urllib.parse import urlsplit, urlunsplit

from scrapy.exceptions import CannotResolveHostError


class HostMapMiddleware:
    def __init__(self, mapping):
        self.mapping = mapping

    @classmethod
    def from_crawler(cls, crawler):
        return cls(json.loads(crawler.settings.get("TEST_HOST_MAP") or "{}"))

    def process_request(self, request):
        parts = urlsplit(request.url)
        host = parts.hostname or ""
        if host in ("127.0.0.1", "localhost"):
            return None
        target = self.mapping.get(host.removeprefix("www."))
        if not target:
            raise CannotResolveHostError(f"{host} (not mapped in test)")
        t = urlsplit(target)
        return request.replace(url=urlunsplit((t.scheme, t.netloc, parts.path, parts.query, "")))

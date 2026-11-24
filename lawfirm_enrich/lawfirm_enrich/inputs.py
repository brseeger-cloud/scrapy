"""Reading firms.csv and do_not_contact.csv."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

INPUT_COLUMNS = ("firm_name", "abn", "entity_type", "state", "postcode", "website")
DNC_COLUMNS = ("firm_name", "abn", "website", "reason", "date_added")


@dataclass
class Firm:
    row: int  # 1-based data row number in firms.csv
    firm_name: str
    abn: str
    entity_type: str
    state: str
    postcode: str
    website: str  # as given
    url: str  # normalised start URL ("" if none)
    scheme_given: bool

    def as_dict(self) -> dict[str, str]:
        return {c: getattr(self, c) for c in INPUT_COLUMNS}


def normalise_abn(abn: str) -> str:
    return re.sub(r"\D", "", abn or "")


def normalise_url(website: str) -> tuple[str, bool]:
    """Return (start URL, whether the input included a scheme)."""
    w = (website or "").strip()
    if not w or w.lower() in {"n/a", "na", "none", "-", "null"}:
        return "", False
    scheme_given = bool(re.match(r"^https?://", w, re.I))
    if not scheme_given:
        w = "https://" + w.lstrip("/")
    parts = urlsplit(w)
    host = parts.hostname or ""
    if not host or ("." not in host and host != "localhost"):
        return "", scheme_given
    path = parts.path or "/"
    url = f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"
    if parts.query:
        url += "?" + parts.query
    return url, scheme_given


def host_of(url: str) -> str:
    """Lower-case host name without a leading "www." and without a port."""
    if not url:
        return ""
    if "://" not in url:
        url = "http://" + url
    host = (urlsplit(url).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


_NAME_SUFFIX_RE = re.compile(r"\b(pty\.?\s*ltd\.?|pty\.?\s*limited|proprietary limited|limited|ltd\.?|inc\.?|incorporated)\b")


def normalise_name(name: str) -> str:
    n = (name or "").lower().replace("&", " and ")
    n = _NAME_SUFFIX_RE.sub(" ", n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    n = re.sub(r"^\s*the\s+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        headers = [h.strip().lower() for h in (reader.fieldnames or [])]
        rows = []
        for raw in reader:
            rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k is not None})
    return headers, rows


def read_firms(path: str | Path) -> list[Firm]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")
    headers, rows = _read_rows(path)
    missing = [c for c in INPUT_COLUMNS if c not in headers]
    if missing:
        raise ValueError(f"{path} is missing required column(s): {', '.join(missing)}")
    firms = []
    for i, r in enumerate(rows, start=1):
        if not any(r.get(c) for c in INPUT_COLUMNS):
            continue  # blank line
        url, scheme_given = normalise_url(r.get("website", ""))
        # Only the six documented columns are ever read; anything else in the
        # file (e.g. an email column) is ignored and never copied to output.
        firms.append(
            Firm(
                row=i,
                firm_name=r.get("firm_name", ""),
                abn=r.get("abn", ""),
                entity_type=r.get("entity_type", ""),
                state=r.get("state", ""),
                postcode=r.get("postcode", ""),
                website=r.get("website", ""),
                url=url,
                scheme_given=scheme_given,
            )
        )
    return firms


class DoNotContactList:
    """Firms that must never be crawled or written to output.

    A firm matches if its ABN, website domain or normalised name matches any
    row of do_not_contact.csv.
    """

    def __init__(self, abns: set[str], domains: set[str], names: set[str], path: Path | None = None):
        self.abns = abns
        self.domains = domains
        self.names = names
        self.path = path

    def __len__(self) -> int:
        return len(self.abns) + len(self.domains) + len(self.names)

    @classmethod
    def load(cls, path: str | Path) -> "DoNotContactList":
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(
                f"Do-not-contact file not found: {path}. It is required (an empty file with just "
                f"the header row is fine): {','.join(DNC_COLUMNS)}"
            )
        headers, rows = _read_rows(path)
        if not ({"firm_name", "abn", "website", "domain"} & set(headers)):
            raise ValueError(f"{path} must have at least one of the columns firm_name, abn, website")
        abns, domains, names = set(), set(), set()
        for r in rows:
            abn = normalise_abn(r.get("abn", ""))
            if len(abn) >= 9:
                abns.add(abn)
            for col in ("website", "domain"):
                host = host_of(r.get(col, ""))
                if host:
                    domains.add(host)
            name = normalise_name(r.get("firm_name", ""))
            if name:
                names.add(name)
        return cls(abns, domains, names, path)

    def matches(self, *, firm_name: str = "", abn: str = "", urls: tuple[str, ...] = ()) -> bool:
        a = normalise_abn(abn)
        if a and a in self.abns:
            return True
        n = normalise_name(firm_name)
        if n and n in self.names:
            return True
        for url in urls:
            host = host_of(url)
            if host and any(host == d or host.endswith("." + d) for d in self.domains):
                return True
        return False

    def matches_firm(self, firm: Firm, *extra_urls: str) -> bool:
        return self.matches(firm_name=firm.firm_name, abn=firm.abn, urls=(firm.website, firm.url, *extra_urls))

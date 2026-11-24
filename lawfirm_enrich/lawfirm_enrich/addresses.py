"""Finding a firm's mailing (postal) and office addresses on its website.

Two sources, best first:

1. Structured data that many sites embed for search engines (schema.org
   ``PostalAddress`` in JSON-LD or microdata): exact street, suburb, state and
   postcode fields.
2. Addresses written out in the page text, e.g. "Level 2, 45 Smith Street,
   Parramatta NSW 2150" or "PO Box 123, Parramatta NSW 2124".

The office address is the firm's street address; any further street addresses
are other offices. The mailing address is a PO Box / Locked Bag, or an address
labelled "Postal address", or else the office address.

Every address is kept as parts (line, suburb, state, postcode) and written in
one format, "<line>, <suburb> <STATE> <postcode>", so mailing lists can split it
back into fields reliably.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

STATE_ABBREVIATIONS = {
    "new south wales": "NSW",
    "victoria": "VIC",
    "queensland": "QLD",
    "south australia": "SA",
    "western australia": "WA",
    "tasmania": "TAS",
    "northern territory": "NT",
    "australian capital territory": "ACT",
}
_ABBR = ("NSW", "VIC", "QLD", "SA", "WA", "TAS", "NT", "ACT")
_STATES = (
    r"(?:NSW|VIC|Vic|QLD|Qld|SA|WA|TAS|Tas|NT|ACT|New South Wales|Victoria|Queensland|South Australia|"
    r"Western Australia|Tasmania|Northern Territory|Australian Capital Territory)"
)
_STREET_TYPES = (
    r"(?i:Street|St|Road|Rd|Avenue|Ave|Av|Highway|Hwy|Parade|Pde|Lane|Ln|Drive|Dr|Place|Pl|Terrace|Tce|"
    r"Boulevard|Blvd|Court|Ct|Crescent|Cres|Cr|Way|Circuit|Cct|Close|Cl|Mall|Square|Sq|Esplanade|Esp|"
    r"Grove|Gr|Row|Walk|Arcade|Plaza|Promenade|Quay|Strand|Circle|Point|Pt|Rise|Track|Freeway|Fwy|"
    r"Gardens|Gdns|Green|Mews|Approach|App)"
)
_UNIT_PREFIX = r"(?:(?i:Level|Lvl|L|Suite|Ste|Shop|Unit|Office|Ground Floor|Floor|Building|Bldg|Tower)\s*\d*[A-Z]?\s*[,/]?\s*){0,2}"
_WORD = r"[A-Z][A-Za-z'’\-]+"
_STREET_RE = re.compile(
    r"(?P<line>" + _UNIT_PREFIX + r"\b\d+[A-Z]?(?:\s*[-/]\s*\d+[A-Z]?)?\s+(?:" + _WORD + r"\s+){1,4}" + _STREET_TYPES
    + r")\b\.?(?:\s*,\s*|\s+)(?P<suburb>(?:" + _WORD + r"\s*){1,4}?),?\s*(?P<state>" + _STATES
    + r")\.?,?\s*(?P<postcode>\d{4})\b"
)  # fmt: skip
_PO_BOX_RE = re.compile(
    r"(?P<line>\b(?:P\.?\s?O\.?\s?Box|Post Office Box|GPO Box|Locked Bag|Private Bag|PMB|Reply Paid)\s*\d+[A-Z]?)"
    r"[,\s]+(?P<suburb>(?:[A-Za-z'’\-]+\s*){1,4}?),?\s*(?P<state>" + _STATES + r")\.?,?\s*(?P<postcode>\d{4})\b",
    re.I,
)
_IS_PO_BOX_RE = re.compile(r"\b(?:P\.?\s?O\.?\s?Box|Post Office Box|GPO Box|Locked Bag|Private Bag|PMB)\b", re.I)
_POSTAL_LABEL_RE = re.compile(
    r"\b(?:postal address|postal|mailing address|mail to|post to|correspondence(?: address)?)\b\s*[:\-]?", re.I
)
_FORMATTED_RE = re.compile(
    r"^(?P<line>.+?),\s*(?P<suburb>[^,]+?)\s+(?P<state>" + "|".join(_ABBR) + r")\s+(?P<postcode>\d{4})$"
)


def normalise_state(state: str) -> str:
    s = (state or "").strip().rstrip(".")
    return STATE_ABBREVIATIONS.get(s.lower(), s.upper())


def _clean(text: str) -> str:
    text = re.sub(r"\s*,\s*(?:,\s*)+", ", ", text or "")
    return re.sub(r"\s+", " ", text).strip(" ,")


@dataclass(frozen=True)
class ParsedAddress:
    line: str  # "Level 2, 45 Smith Street" or "PO Box 123"
    suburb: str
    state: str  # abbreviation, e.g. NSW
    postcode: str

    @property
    def is_po_box(self) -> bool:
        return bool(_IS_PO_BOX_RE.search(self.line))

    @property
    def key(self) -> tuple:
        """The same address written differently ("Level 2, 45 Smith St" / "45 Smith Street") has the same key."""
        numbers = re.findall(r"\d+", self.line)
        return (self.postcode, numbers[-1] if numbers else self.line.lower(), self.is_po_box)

    def __str__(self) -> str:
        return f"{self.line}, {self.suburb} {self.state} {self.postcode}"


def _make(line: str, suburb: str, state: str, postcode: str) -> ParsedAddress | None:
    line, suburb, state, postcode = _clean(line), _clean(suburb), normalise_state(state), (postcode or "").strip()
    if not (line and suburb and state in _ABBR and re.fullmatch(r"\d{4}", postcode)):
        return None
    if suburb.isupper() and len(suburb) > 3:
        suburb = suburb.title()
    return ParsedAddress(line, suburb, state, postcode)


def split_address(text: str) -> ParsedAddress | None:
    """Split an address written by this project (or any "line, Suburb STATE 1234") into parts."""
    text = _clean(text)
    m = _FORMATTED_RE.match(text) or _PO_BOX_RE.search(text) or _STREET_RE.search(text)
    return _make(m["line"], m["suburb"], m["state"], m["postcode"]) if m else None


def find_in_text(text: str) -> tuple[list[ParsedAddress], list[ParsedAddress], list[ParsedAddress]]:
    """Return (PO boxes, street addresses, addresses labelled as postal) found in page text."""
    boxes = [a for m in _PO_BOX_RE.finditer(text) if (a := _make(m["line"], m["suburb"], m["state"], m["postcode"]))]
    streets = []
    for m in _STREET_RE.finditer(text):
        a = _make(m["line"], m["suburb"], m["state"], m["postcode"])
        if a and not a.is_po_box:
            streets.append(a)
    labelled = []
    for lm in _POSTAL_LABEL_RE.finditer(text):
        window = text[lm.end() : lm.end() + 160]
        m = _PO_BOX_RE.search(window) or _STREET_RE.search(window)
        if m and m.start() < 20:
            a = _make(m["line"], m["suburb"], m["state"], m["postcode"])
            if a:
                labelled.append(a)
    return boxes, streets, labelled


# --------------------------------------------------------------------------
# schema.org structured data
# --------------------------------------------------------------------------


def _from_schema(obj: dict) -> ParsedAddress | None:
    country = str(obj.get("addressCountry") or "")
    if isinstance(obj.get("addressCountry"), dict):
        country = str(obj["addressCountry"].get("name") or "")
    if country and country.strip().lower() not in ("au", "aus", "australia"):
        return None
    street = obj.get("streetAddress") or ""
    if isinstance(street, list):
        street = ", ".join(str(s) for s in street)
    box = obj.get("postOfficeBoxNumber")
    if box and not street:
        street = f"PO Box {box}"
    return _make(str(street).replace("\n", ", "), str(obj.get("addressLocality") or ""),
                 str(obj.get("addressRegion") or ""), str(obj.get("postalCode") or ""))  # fmt: skip


def _walk(node, found: list[ParsedAddress]) -> None:
    if isinstance(node, dict):
        types = node.get("@type")
        types = types if isinstance(types, list) else [types]
        if "PostalAddress" in types or "streetAddress" in node:
            a = _from_schema(node)
            if a:
                found.append(a)
        for value in node.values():
            _walk(value, found)
    elif isinstance(node, list):
        for value in node:
            _walk(value, found)


def find_structured(root) -> list[ParsedAddress]:
    """Addresses in schema.org JSON-LD and microdata on a page (lxml *root*)."""
    found: list[ParsedAddress] = []
    for script in root.xpath('//script[contains(translate(@type, "LDJSON", "ldjson"), "ld+json")]'):
        try:
            _walk(json.loads(script.text or ""), found)
        except (ValueError, TypeError):
            continue  # malformed JSON-LD is common; ignore it
    for scope in root.xpath('//*[@itemscope and contains(@itemtype, "PostalAddress")]'):
        props = {}
        for el in scope.xpath(".//*[@itemprop]"):
            props.setdefault(el.get("itemprop"), " ".join(" ".join(el.itertext()).split()) or el.get("content", ""))
        a = _from_schema(props)
        if a:
            found.append(a)
    return found


# --------------------------------------------------------------------------
# Choosing a firm's addresses
# --------------------------------------------------------------------------


@dataclass
class FirmAddresses:
    postal: ParsedAddress | None = None  # where to send mail
    po_box: ParsedAddress | None = None
    office: ParsedAddress | None = None  # main street address
    other_offices: list[ParsedAddress] = field(default_factory=list)
    source_url: str = ""


def choose_addresses(pages) -> FirmAddresses:
    """Pick the firm's addresses from its pages (contact page first; structured data first)."""
    order = {"contact": 0, "home": 1, "about": 2, "team": 3}
    pages = sorted(pages, key=lambda p: order.get(p.category, 9))
    result = FirmAddresses()
    offices: dict[tuple, ParsedAddress] = {}
    labelled: ParsedAddress | None = None

    def note(page_url: str) -> None:
        result.source_url = result.source_url or page_url

    for structured_pass in (True, False):
        for page in pages:
            if structured_pass:
                found = page.structured_addresses
                boxes = [a for a in found if a.is_po_box]
                streets = [a for a in found if not a.is_po_box]
                labels = []
            else:
                boxes, streets, labels = find_in_text(", ".join(page.lines))
            if boxes and not result.po_box:
                result.po_box = boxes[0]
                note(page.url)
            if labels and not labelled:
                labelled = labels[0]
                note(page.url)
            for a in streets:
                if a.key not in offices:
                    offices[a.key] = a
                    note(page.url)

    office_list = list(offices.values())
    result.office = office_list[0] if office_list else None
    result.other_offices = office_list[1:4]
    result.postal = labelled or result.po_box or result.office
    return result

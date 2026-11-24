"""Turn fetched pages into structured facts about a firm.

All functions here are pure (no network, no Scrapy objects) so they can be
unit-tested with plain HTML strings.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field

from parsel import Selector

from .privacy import scrub_emails

# --------------------------------------------------------------------------
# HTML -> visible text lines
# --------------------------------------------------------------------------

_DROP_TAGS = {"script", "style", "noscript", "svg", "template", "iframe", "head", "object", "canvas"}
_BLOCK_TAGS = {
    "address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
    "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "hr", "li", "main", "nav", "ol", "p", "section", "table", "td", "th",
    "tr", "ul", "button", "label", "option",
}


@dataclass
class Page:
    """One fetched page: its URL, which kind of page it is, and its text."""

    url: str
    category: str  # home / about / team / contact
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def html_to_lines(html: str | None = None, *, root=None) -> list[str]:
    """Return visible text of a page, one block element per line.

    Email addresses are removed here, before any other code sees the text.
    ``mailto:`` links are dropped entirely.
    """
    if root is None:
        root = Selector(text=html or "<html></html>").root
    root = copy.deepcopy(root)

    for el in list(root.iter()):
        tag = el.tag if isinstance(el.tag, str) else ""
        if tag.lower() in _DROP_TAGS:
            _drop(el)
        elif tag.lower() == "a" and (el.get("href") or "").lower().startswith("mailto:"):
            _drop(el)

    for el in root.iter():
        if not isinstance(el.tag, str):
            continue
        if el.tag.lower() in _BLOCK_TAGS:
            el.tail = "\n" + (el.tail or "")
            if el.tag.lower() != "br":
                el.text = "\n" + (el.text or "")

    text = root.text_content() if hasattr(root, "text_content") else "".join(root.itertext())
    lines = []
    for raw in text.split("\n"):
        line = re.sub(r"\s+", " ", raw.replace("\xa0", " ")).strip()
        if line:
            lines.append(scrub_emails(line))
    return lines


def _drop(el) -> None:
    parent = el.getparent()
    if parent is None:
        return
    tail = el.tail
    prev = el.getprevious()
    parent.remove(el)
    if tail:
        if prev is not None:
            prev.tail = (prev.tail or "") + tail
        else:
            parent.text = (parent.text or "") + tail


# --------------------------------------------------------------------------
# People: names and roles
# --------------------------------------------------------------------------

_TITLE_PREFIX_RE = re.compile(r"^(?:(?:Mr|Mrs|Ms|Miss|Mx|Dr|Prof|Professor|The Hon|Hon)\.?\s+)+", re.I)
_NAME_TOKEN_RE = re.compile(
    r"^(?:[A-Z][a-z]{0,3}[A-Z][a-z]+|[A-Z][a-z]+|[A-Z]\.?|O['’][A-Z][a-z]+)(?:[-'’][A-Z][a-z]+)*$"
)
_PARTICLES = {"van", "der", "de", "da", "di", "von", "le", "la", "du", "del", "bin", "binti", "al", "el", "ten", "ter"}
_POSTNOMINALS = {
    "llb", "llm", "ba", "bcom", "bec", "bbus", "bsc", "bjuris", "blaws", "ma", "mba", "jd", "phd",
    "gdlp", "gdlpp", "gradcert", "graddip", "dip", "hons", "am", "oam", "ao", "sc", "qc", "kc",
    "fca", "cpa", "cta", "tep", "accspec", "mappsc", "llb/ba", "ba/llb", "bcom/llb", "llb(hons)",
    "acc.", "spec", "(hons)", "jp",
}
_NAME_STOPWORDS = {
    # generic page words
    "about", "us", "our", "the", "and", "of", "for", "with", "in", "at", "to", "by", "a", "an", "is",
    "team", "people", "staff", "contact", "home", "news", "blog", "read", "more", "view", "profile",
    "call", "today", "now", "book", "appointment", "free", "consultation", "click", "here", "menu",
    "search", "privacy", "policy", "terms", "conditions", "copyright", "rights", "reserved",
    "welcome", "testimonials", "faq", "faqs", "careers", "location", "locations", "find", "get",
    "touch", "phone", "fax", "email", "mobile", "enquiry", "enquiries", "send", "message", "submit",
    "name", "address", "dear", "kind", "regards", "hello", "best", "meet", "learn", "how", "we",
    "help", "you", "your", "why", "choose", "what", "who", "client", "clients", "service",
    "services", "areas", "area", "office", "offices", "hours", "opening", "map", "directions",
    "level", "suite", "po", "box", "street", "road", "st", "rd", "avenue", "parade", "lane",
    # legal / business words
    "law", "laws", "lawyer", "lawyers", "legal", "solicitor", "solicitors", "firm", "practice",
    "practices", "partners", "partner", "associates", "associate", "principal", "director",
    "directors", "counsel", "barrister", "barristers", "chambers", "attorney", "attorneys",
    "pty", "ltd", "limited", "group", "company", "co", "family", "wills", "will", "estates",
    "estate", "probate", "property", "conveyancing", "commercial", "criminal", "injury",
    "personal", "business", "accident", "accidents", "compensation", "claims", "employment",
    "dispute", "disputes", "litigation", "migration", "immigration", "planning", "accredited",
    "specialist", "specialists", "member", "society", "court", "courts", "high", "federal",
    "supreme", "district", "local", "magistrates", "tribunal", "senior", "special", "managing",
    "consultant", "paralegal", "clerk", "assistant", "secretary", "receptionist", "manager",
    "support", "insights", "resources", "corporate", "leasing", "traffic", "divorce",
    # places
    "australia", "australian", "nsw", "vic", "qld", "wa", "sa", "tas", "nt", "act", "sydney",
    "melbourne", "brisbane", "perth", "adelaide", "hobart", "darwin", "canberra", "victoria",
    "queensland", "tasmania", "new", "south", "wales", "western", "northern", "territory",
    "capital", "gold", "coast", "sunshine", "central", "north", "east", "west", "city", "cbd",
    # dates
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july", "august", "september",
    "october", "november", "december",
}

_STRONG_LAWYER_RE = re.compile(
    r"\b(solicitors?|lawyers?|barristers?|special counsel|counsel|attorneys?|legal practitioners?|"
    r"legal practitioner director)\b",
    re.I,
)
_GENERIC_LAWYER_RE = re.compile(r"\b(principals?|partners?|directors?|associates?)\b", re.I)
_NON_LAWYER_RE = re.compile(
    r"\b(paralegals?|law clerks?|legal (?:assistants?|secretar(?:y|ies)|support|administrators?|"
    r"executives?|cashiers?|interns?)|secretar(?:y|ies)|receptionists?|(?:practice|office|operations|"
    r"business|client services|accounts|marketing|finance|IT|HR) managers?|marketing|accounts?|"
    r"bookkeepers?|administrat\w*|(?:licensed |registered )?conveyancers?|conveyancing "
    r"(?:clerks?|assistants?|officers?|managers?|coordinators?)|settlement (?:agents?|clerks?|"
    r"officers?)|executive assistants?|personal assistants?|trainees?|support staff|"
    r"director of [a-z]+|(?:finance|marketing|operations|creative|art) directors?|"
    r"migration agents?|mediators?|accountants?|financial planners?|students?|clerks?)\b",
    re.I,
)
_PRINCIPAL_ROLE_RE = re.compile(
    r"\b(principals?|principal (?:solicitor|lawyer)|(?:managing |founding |equity |senior )?partners?|"
    r"(?:legal practitioner )?directors?|founder|sole practitioner)\b",
    re.I,
)
_NOT_PRINCIPAL_RE = re.compile(r"\b(associate directors?|associates? to|partner'?s? (?:assistant|secretary))\b", re.I)

_SEPARATOR_RE = re.compile(r"\s+[-–—|•·]\s+|\s*\|\s*|\s*,\s+|\s*:\s+")


@dataclass
class Person:
    name: str
    role: str
    is_lawyer: bool
    is_principal: bool
    source_url: str = ""


def is_role_text(text: str) -> bool:
    if len(text) > 90:
        return False
    return bool(_STRONG_LAWYER_RE.search(text) or _GENERIC_LAWYER_RE.search(text) or _NON_LAWYER_RE.search(text))


def classify_role(role: str) -> tuple[bool, bool]:
    """Return (is_lawyer, is_principal) for a job title."""
    if not role:
        return False, False
    stripped = _NON_LAWYER_RE.sub(" ", role)
    non_lawyer = stripped != role
    if _STRONG_LAWYER_RE.search(stripped):
        is_lawyer = True
    elif _GENERIC_LAWYER_RE.search(stripped) and not non_lawyer:
        is_lawyer = True
    else:
        is_lawyer = False
    is_principal = bool(
        is_lawyer and _PRINCIPAL_ROLE_RE.search(stripped) and not _NOT_PRINCIPAL_RE.search(role)
    )
    return is_lawyer, is_principal


def clean_name(candidate: str) -> str | None:
    """Return a normalised person name, or None if *candidate* is not one."""
    if not candidate or "@" in candidate or any(ch.isdigit() for ch in candidate):
        return None
    candidate = re.sub(r"\([^)]*\)", " ", candidate)
    candidate = candidate.strip(" .,;:-–—|*\"'“”")
    candidate = _TITLE_PREFIX_RE.sub("", candidate).strip()
    if not candidate or len(candidate) > 45:
        return None
    letters = [c for c in candidate if c.isalpha()]
    if letters and all(c.isupper() for c in letters):
        candidate = " ".join(_title_token(t) for t in candidate.split())

    tokens = candidate.replace(",", " ").split()
    while tokens and tokens[-1].lower().strip(".") in _POSTNOMINALS | {"hons)"}:
        tokens.pop()
    while tokens and tokens[-1].lower().strip(".") in _NAME_STOPWORDS:
        tokens.pop()

    core = [t for t in tokens if t.lower() not in _PARTICLES]
    if not 2 <= len(core) <= 4:
        return None
    for pos, t in enumerate(core):
        if not _NAME_TOKEN_RE.match(t):
            return None
        is_middle_initial = len(t.strip(".")) == 1 and 0 < pos < len(core) - 1
        if not is_middle_initial and t.lower().strip(".") in _NAME_STOPWORDS:
            return None
    # need at least two "real" name tokens (not bare initials)
    if sum(1 for t in core if len(t.strip(".")) > 1) < 2:
        return None
    return " ".join(tokens)


def _title_token(token: str) -> str:
    if len(token) <= 2 and token.endswith("."):
        return token
    parts = re.split(r"([-'’])", token.lower())
    out = "".join(p.capitalize() if p not in "-'’" else p for p in parts)
    if out.startswith("Mc") and len(out) > 2:
        out = "Mc" + out[2].upper() + out[3:]
    return out


def name_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", _TITLE_PREFIX_RE.sub("", name).lower())


def parse_person_line(line: str) -> tuple[str, str] | None:
    """If *line* starts with a person's name, return (name, inline_role)."""
    if len(line) > 120:
        return None
    parts = [p for p in _SEPARATOR_RE.split(line) if p.strip()]
    if not parts:
        return None
    name = clean_name(parts[0])
    if not name:
        return None
    rest = [p.strip() for p in parts[1:]]
    # drop post-nominal-only parts ("Jane Smith, LLB, GDLP – Solicitor")
    rest = [p for p in rest if not all(t.lower().strip(".()") in _POSTNOMINALS for t in p.split())]
    inline_role = " ".join(rest)
    if inline_role and not is_role_text(inline_role):
        # "Jane Smith, Sydney" – a name followed by something that is not a role
        inline_role = ""
    return name, inline_role


def extract_people(page: Page) -> list[Person]:
    """Find a staff listing on a page: names paired with job titles."""
    lines = page.lines
    parsed = [parse_person_line(l) for l in lines]

    def role_at(i: int) -> str | None:
        if 0 <= i < len(lines) and parsed[i] is None and is_role_text(lines[i]) and len(lines[i]) <= 70:
            return lines[i]
        return None

    name_idx = [i for i, p in enumerate(parsed) if p is not None]
    after = sum(1 for i in name_idx if not parsed[i][1] and role_at(i + 1))
    before = sum(1 for i in name_idx if not parsed[i][1] and role_at(i - 1))
    role_first = before > after

    people: dict[str, Person] = {}
    section_role: str | None = None
    for i, line in enumerate(lines):
        p = parsed[i]
        if p is None:
            # Section headings such as "Our Solicitors" or "Support Staff"
            if len(line) <= 40 and is_role_text(line) and _looks_like_heading(line):
                section_role = line
            continue
        name, role = p
        if not role:
            if role_first:
                role = role_at(i - 1) or ""
            else:
                role = role_at(i + 1) or ""
        if not role and section_role:
            role = section_role
        if not role:
            continue
        is_lawyer, is_principal = classify_role(role)
        key = name_key(name)
        existing = people.get(key)
        if existing is None or (is_lawyer and not existing.is_lawyer):
            people[key] = Person(name, role, is_lawyer, is_principal, page.url)
    return list(people.values())


def _looks_like_heading(line: str) -> bool:
    low = line.lower().strip(" :")
    words = low.split()
    if low.startswith(("our ", "meet ", "the ")):
        return True
    # plural role words ("Partners", "Solicitors", "Support Staff")
    return any(w.endswith("s") and len(w) > 3 for w in words) or "staff" in low


# Principals named in running text, e.g. "Our principal solicitor, Jane Smith, ..."
_INLINE_NAME = r"((?:[A-Z][a-z]+(?:[-'’][A-Z][a-z]+)?)(?:\s+[A-Z]\.)?(?:\s+(?:Mc|Mac|O['’])?[A-Z][a-z]+(?:[-'’][A-Z][a-z]+)?){1,2})"
_INLINE_TITLE = r"(?:(?:Mr|Mrs|Ms|Miss|Dr)\.?\s+)?"
_PRINCIPAL_INLINE_PATTERNS = [
    re.compile(
        r"(?i:\b(?:principal(?:\s+(?:solicitor|lawyer))?|founder|founding partner|managing partner|"
        r"legal practitioner director|sole practitioner))\s*(?:,|:|-|–|is)?\s*" + _INLINE_TITLE + _INLINE_NAME
    ),
    re.compile(
        _INLINE_TITLE + _INLINE_NAME + r"\s*,?\s+(?i:is|was|has been|,)\s+(?i:the\s+)?(?i:firm'?s\s+|our\s+)?"
        r"(?i:principal|founder|founding partner|managing partner|sole practitioner|legal practitioner director)\b"
    ),
    re.compile(r"(?i:\b(?:founded|established|started)\s+(?:in\s+\d{4}\s+)?by)\s+" + _INLINE_TITLE + _INLINE_NAME),
]


def extract_inline_principals(page: Page) -> list[str]:
    names = []
    for line in page.lines:
        for pat in _PRINCIPAL_INLINE_PATTERNS:
            for m in pat.finditer(line):
                name = clean_name(m.group(1))
                if name:
                    names.append(name)
    return names


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20,
    "thirty": 30, "forty": 40, "fifty": 50,
}
_COUNT_WORD = r"(\d{1,3}|" + "|".join(_NUMBER_WORDS) + r")\+?"
_ADJ = r"(?:(?:experienced|dedicated|specialist|qualified|expert|skilled|talented|friendly|senior|highly|accredited)\s+)*"
_STATED_COUNT_RES = [
    re.compile(rf"\b(?:team|group) of (?:over |more than |around |about )?{_COUNT_WORD}\s+{_ADJ}(?:lawyers|solicitors|legal practitioners|legal professionals)\b", re.I),
    re.compile(rf"\bour {_COUNT_WORD}\s+{_ADJ}(?:lawyers|solicitors|partners)\b", re.I),
    re.compile(rf"\b{_COUNT_WORD}\s+{_ADJ}(?:lawyers|solicitors)\s+(?:and|who|with|across|in|on)\b", re.I),
]


def extract_stated_count(text: str) -> int | None:
    for pat in _STATED_COUNT_RES:
        m = pat.search(text)
        if m:
            raw = m.group(1).lower()
            n = _NUMBER_WORDS.get(raw) or (int(raw) if raw.isdigit() else None)
            if n and 0 < n < 1000:
                return n
    return None


_SOLE_PHRASE_RE = re.compile(
    r"\bsole practitioner\b|\bI (?:am|have been) (?:an? |the )?(?:experienced |practising |principal )?"
    r"(?:solicitor|lawyer)\b|\bI have been practi[sc]ing\b|\bI was admitted\b|\bmy practice\b|"
    r"\bone[- ](?:wo)?man (?:practice|firm|band)\b",
    re.I,
)


def has_sole_phrase(text: str) -> bool:
    return bool(_SOLE_PHRASE_RE.search(text))


# --------------------------------------------------------------------------
# Practice areas
# --------------------------------------------------------------------------

PRACTICE_AREAS: dict[str, re.Pattern[str]] = {
    "Conveyancing": re.compile(
        r"\bconveyanc\w*|\bproperty law\b|\breal estate law\b|\bbuying (?:or|and|&) selling (?:a |your )?"
        r"(?:home|house|property)\b|\bproperty (?:transactions?|purchases?|sales?)\b|\boff[- ]the[- ]plan\b",
        re.I,
    ),
    "Wills & Estates": re.compile(
        r"\bwills\b|\bestate planning\b|\bprobate\b|\bdeceased estates?\b|\bestate (?:administration|"
        r"litigation|disputes?)\b|\bpowers? of attorney\b|\benduring guardian\w*\b|\bfamily provision\b|"
        r"\bwill disputes?\b|\bletters of administration\b|\bsuccession planning\b|\btestamentary\b",
        re.I,
    ),
    "Family": re.compile(
        r"\bfamily law\b|\bdivorce\b|\bparenting (?:orders?|arrangements?|plans?|matters?)\b|"
        r"\bchild custody\b|\bproperty settlements?\b|\bde facto\b|\bchild support\b|"
        r"\bspousal maintenance\b|\bbinding financial agreements?\b|\bseparation\b|\bfamily court\b",
        re.I,
    ),
    "Personal Injury": re.compile(
        r"\bpersonal injur\w*|\bcompensation (?:claims?|law)\b|\bworkers'?\s?comp\w*|"
        r"\bmotor vehicle accidents?\b|\bcar accidents?\b|\bmedical negligence\b|\bpublic liability\b|"
        r"\btpd\b|\btotal and permanent disab\w*|\bctp\b|\bslip and fall\b|\bno win,? no fee\b|"
        r"\bwork(?:place)? injur\w*|\bsuperannuation claims?\b",
        re.I,
    ),
    "Commercial": re.compile(
        r"\bcommercial (?:law|litigation|leas\w*|property|disputes?|contracts?|advice|matters|transactions?)\b|"
        r"\bbusiness law\b|\bcorporate (?:law|advisory|and commercial|& commercial)\b|"
        r"\b(?:corporate|commercial) (?:and|&) (?:corporate|commercial)\b|\bbusiness (?:sales?|purchases?|"
        r"structur\w*|succession|transactions?)\b|\bbuying (?:or|and|&) selling (?:a |your )?business\b|"
        r"\bfranchis\w*|\bshareholders?'? agreements?\b|\bpartnership agreements?\b|\bmergers? (?:and|&) acquisitions\b|"
        r"\bdebt recovery\b|\bcommercial\b",
        re.I,
    ),
    "Criminal": re.compile(
        r"\bcriminal (?:law|defen[cs]e|matters?|charges?|lawyers?|cases?)\b|\btraffic (?:offen[cs]es?|law|matters?)\b|"
        r"\bdrink[- ]driving\b|\bdrug (?:charges?|offen[cs]es?|possession)\b|\bassault charges?\b|"
        r"\bbail applications?\b|\bapprehended (?:domestic )?violence orders?\b|\bAVOs?\b|"
        r"\bintervention orders?\b|\bdomestic violence orders?\b|\bcriminal\b",
        re.I,
    ),
}


def extract_practice_areas(text: str) -> list[str]:
    return [area for area, pat in PRACTICE_AREAS.items() if pat.search(text)]


# --------------------------------------------------------------------------
# Addresses
# --------------------------------------------------------------------------

_STATES = (
    r"(?:NSW|VIC|Vic|QLD|Qld|SA|WA|TAS|Tas|NT|ACT|New South Wales|Victoria|Queensland|South Australia|"
    r"Western Australia|Tasmania|Northern Territory|Australian Capital Territory)"
)
_PO_BOX_RE = re.compile(
    r"\b(?:P\.?\s?O\.?\s?Box|Post Office Box|GPO Box|Locked Bag|Private Bag|PMB)\s*\d+[A-Z]?\b"
    r"[^\n]{0,60}?\b" + _STATES + r"\.?,?\s*\d{4}\b",
    re.I,
)
_STREET_TYPES = (
    r"(?:Street|St|Road|Rd|Avenue|Ave|Highway|Hwy|Parade|Pde|Lane|Ln|Drive|Dr|Place|Pl|Terrace|Tce|"
    r"Boulevard|Blvd|Court|Ct|Crescent|Cres|Way|Circuit|Cct|Close|Cl|Mall|Square|Sq|Esplanade|Esp|"
    r"Grove|Gr|Row|Walk|Arcade|Plaza|Promenade|Quay|Strand|Circle)"
)
_STREET_RE = re.compile(
    r"(?:(?:Level|Lvl|Suite|Shop|Unit|Office|Ground Floor|Floor)\s*\d*[A-Z]?\s*[,/]?\s*)?"
    r"\b\d+[A-Z]?(?:\s*[-/]\s*\d+[A-Z]?)?\s+(?:[A-Z][A-Za-z'’\-]+\s+){1,4}" + _STREET_TYPES +
    r"\b\.?(?:\s*,\s*|\s+)(?:[A-Z][A-Za-z'’\-]+\s*){1,4},?\s*" + _STATES + r"\.?,?\s*\d{4}\b"
)
_POSTAL_LABEL_RE = re.compile(r"\b(?:postal address|postal|mailing address|post to|correspondence(?: address)?)\b\s*[:\-]?", re.I)
_POSTCODE_RE = re.compile(r"(\d{4})\b(?!.*\d{4}\b)")


@dataclass
class Address:
    po_box: str = ""
    street: str = ""
    postal: str = ""
    source_url: str = ""
    postcode: str = ""


def _tidy(addr: str) -> str:
    addr = re.sub(r"\s*,\s*(?:,\s*)+", ", ", addr)
    addr = re.sub(r"\s+", " ", addr)
    return addr.strip(" ,")


def extract_address(pages: list[Page]) -> Address:
    """Find a PO Box / postal address and a street address, preferring the contact page."""
    order = {"contact": 0, "home": 1, "about": 2, "team": 3}
    result = Address()
    for page in sorted(pages, key=lambda p: order.get(p.category, 9)):
        joined = ", ".join(page.lines)
        if not result.po_box:
            m = _PO_BOX_RE.search(joined)
            if m:
                result.po_box = _tidy(m.group(0))
                result.source_url = result.source_url or page.url
        if not result.postal:
            for lm in _POSTAL_LABEL_RE.finditer(joined):
                window = joined[lm.end(): lm.end() + 160]
                m = _PO_BOX_RE.search(window) or _STREET_RE.search(window)
                if m and m.start() < 20:
                    result.postal = _tidy(m.group(0))
                    result.source_url = result.source_url or page.url
                    break
        if not result.street:
            m = _STREET_RE.search(joined)
            if m:
                result.street = _tidy(m.group(0))
                result.source_url = result.source_url or page.url
        if result.street and (result.po_box or result.postal):
            break
    result.postal = result.postal or result.po_box or result.street
    pm = _POSTCODE_RE.search(result.postal)
    result.postcode = pm.group(1) if pm else ""
    return result


# --------------------------------------------------------------------------
# Signals used by the classifier
# --------------------------------------------------------------------------


@dataclass
class Signal:
    reason: str  # barrister / in-house / government / licensed conveyancer / not a law firm / other
    strength: str  # "strong" => Exclude, "weak" => Check manually
    evidence: str


_BAR_AND_SOL_RE = re.compile(r"barristers?\s*(?:and|&)\s*solicitors?|solicitors?\s*(?:and|&)\s*barristers?", re.I)
_BARRISTER_NAME_RE = re.compile(r"\b(barristers?|chambers|barrister[- ]at[- ]law)\b|\b[SK]\.?C\.?$", re.I)
_BARRISTER_TEXT_RE = re.compile(
    r"\bbarrister[- ]at[- ]law\b|\bbarristers'? chambers\b|\b(?:I am|I'm) an? (?:\w+ )?barrister\b|"
    r"\bpractis(?:es|ing|e) (?:solely |exclusively )?as an? barrister\b|\bdirect (?:access|brief\w*) barrister\b|"
    r"\bmember of (?:the )?(?:NSW |Victorian |Queensland |WA |SA |Tasmanian |ACT |NT |New South Wales |"
    r"Western Australian |South Australian |Northern Territory )?Bar\b(?! Association of)|\bsigned the bar roll\b|"
    r"\b(?:is|am) an? (?:\w+ )?barrister\b(?!\s*(?:and|&)\s*solicitor)",
    re.I,
)
_GOV_NAME_RE = re.compile(
    r"\b(legal aid|crown solicitor|state solicitor|government solicitor|solicitor[- ]general|public defenders?|"
    r"director of public prosecutions|\bDPP\b|department of|council|attorney[- ]general|ombudsman|"
    r"commission|public trustee|trustee and guardian|state trustees|police|government)\b",
    re.I,
)
_INHOUSE_RE = re.compile(r"\b(in[- ]house|legal department|general counsel|corporate counsel)\b", re.I)
_INHOUSE_TEXT_RE = re.compile(r"\b(?:our|the) in[- ]house legal (?:team|department|function)\b", re.I)
_LAW_WORDS_RE = re.compile(r"\b(law|lawyers?|legal|solicitors?|attorneys?|barristers?)\b", re.I)
_SOLICITOR_WORDS_RE = re.compile(r"\b(solicitors?|lawyers?|law firm|legal practitioners?)\b", re.I)
_CONVEYANCER_TEXT_RE = re.compile(r"\b(?:licensed|registered|qualified|certified) conveyancers?\b|\bsettlement agents?\b", re.I)
_ANY_LEGAL_RE = re.compile(r"\b(law|lawyers?|legal|solicitors?|barristers?|attorneys?|conveyanc\w*|litigation|court)\b", re.I)
_OTHER_BUSINESS_RE = re.compile(
    r"\b(registered migration agents?|migration agents?|chartered accountants?|accountants?|accounting|"
    r"tax agents?|bookkeeping|financial planners?|financial planning|mortgage brokers?|real estate agen\w+|"
    r"debt collect\w*|legal document preparation|document preparation service|process servers?|"
    r"private investigators?|recruitment)\b",
    re.I,
)
_CLC_RE = re.compile(r"\b(community legal (?:centre|center|service)s?|aboriginal legal service|legal service(?:s)? (?:inc|incorporated))\b", re.I)
_PARKED_RE = re.compile(
    r"\b(this domain (?:is|may be) for sale|domain (?:is )?parked|buy this domain|website (?:is )?coming soon|"
    r"under construction|account (?:has been )?suspended|this site can'?t be reached|default web site page|"
    r"website expired|hosting (?:has )?expired|it works!)\b",
    re.I,
)


def detect_signals(
    firm_name: str,
    entity_type: str,
    host: str,
    pages: list[Page],
    lawyer_count: int,
) -> list[Signal]:
    signals: list[Signal] = []
    text = "\n".join(p.text for p in pages)
    name_clean = _BAR_AND_SOL_RE.sub(" ", firm_name or "")
    text_clean = _BAR_AND_SOL_RE.sub(" ", text)

    # Government
    if host.endswith((".gov.au", ".gov")):
        signals.append(Signal("government", "strong", f"government domain {host}"))
    if "government" in (entity_type or "").lower():
        signals.append(Signal("government", "strong", f"ABN entity type '{entity_type}'"))
    m = _GOV_NAME_RE.search(firm_name or "")
    if m:
        signals.append(Signal("government", "strong", f"firm name contains '{m.group(0)}'"))

    # Barrister
    m = _BARRISTER_NAME_RE.search(name_clean)
    if m:
        signals.append(Signal("barrister", "strong", f"firm name contains '{m.group(0)}'"))
    m = _BARRISTER_TEXT_RE.search(text_clean)
    if m:
        strength = "strong" if lawyer_count <= 1 else "weak"
        signals.append(Signal("barrister", strength, f"site text: '{m.group(0)}'"))

    # In-house
    m = _INHOUSE_RE.search(firm_name or "") or _INHOUSE_RE.search(entity_type or "")
    if m:
        signals.append(Signal("in-house", "strong", f"name/entity type contains '{m.group(0)}'"))
    m = _INHOUSE_TEXT_RE.search(text)
    if m:
        signals.append(Signal("in-house", "weak", f"site text: '{m.group(0)}'"))

    # Licensed conveyancer
    name_has_conv = bool(re.search(r"\bconveyanc\w*", firm_name or "", re.I))
    name_has_law = bool(_LAW_WORDS_RE.search(firm_name or ""))
    site_has_solicitor = bool(_SOLICITOR_WORDS_RE.search(text))
    conv_text = _CONVEYANCER_TEXT_RE.search(text)
    if name_has_conv and not name_has_law:
        if not site_has_solicitor and lawyer_count == 0:
            signals.append(Signal("licensed conveyancer", "strong", "conveyancing business name; no solicitors mentioned on site"))
        else:
            signals.append(Signal("licensed conveyancer", "weak", "conveyancing business name but site mentions solicitors/lawyers"))
    elif conv_text and not site_has_solicitor and lawyer_count == 0:
        signals.append(Signal("licensed conveyancer", "strong", f"site text: '{conv_text.group(0)}'; no solicitors mentioned"))

    # Not a law firm
    if pages and not _ANY_LEGAL_RE.search(text) and not _ANY_LEGAL_RE.search(firm_name or ""):
        signals.append(Signal("not a law firm", "strong", "no legal-practice terms found on site"))
    m = _OTHER_BUSINESS_RE.search(firm_name or "")
    if m:
        strength = "strong" if (lawyer_count == 0 and not site_has_solicitor) else "weak"
        signals.append(Signal("not a law firm", strength, f"firm name suggests '{m.group(0)}'"))
    elif pages and lawyer_count == 0 and not site_has_solicitor:
        m = _OTHER_BUSINESS_RE.search(text)
        if m:
            signals.append(Signal("not a law firm", "weak", f"site text mentions '{m.group(0)}'; no solicitors found"))

    # Other things a human should look at
    m = _CLC_RE.search(firm_name or "") or _CLC_RE.search(text)
    if m:
        signals.append(Signal("community legal centre", "weak", f"'{m.group(0)}'"))
    m = _PARKED_RE.search(text)
    if m and len(text) < 3000:
        signals.append(Signal("site not usable", "weak", f"site text: '{m.group(0)}'"))
    return signals


# --------------------------------------------------------------------------
# Whole-firm analysis
# --------------------------------------------------------------------------


@dataclass
class Analysis:
    solicitor_count: int | None = None
    count_basis: str = "not found"
    count_source_url: str = ""
    stated_count: int | None = None
    principals: list[str] = field(default_factory=list)
    people: list[Person] = field(default_factory=list)
    practice_areas: list[str] = field(default_factory=list)
    address: Address = field(default_factory=Address)
    sole_phrase: bool = False
    signals: list[Signal] = field(default_factory=list)


def analyse(firm_name: str, entity_type: str, host: str, pages: list[Page]) -> Analysis:
    a = Analysis()
    team_pages = [p for p in pages if p.category == "team"]
    other_pages = [p for p in pages if p.category != "team"]

    # 1. Staff listing – team pages first, then about/home/contact
    lawyers: dict[str, Person] = {}
    for group, basis in ((team_pages, "team page listing"), (other_pages, "about/home page listing")):
        found: dict[str, Person] = {}
        for page in group:
            for person in extract_people(page):
                if person.is_lawyer:
                    found.setdefault(name_key(person.name), person)
        if found:
            lawyers = found
            a.count_basis = basis
            a.count_source_url = next(iter(found.values())).source_url
            break
    a.people = list(lawyers.values())

    # 2. Principals: from listing roles, then from running text
    principals: dict[str, str] = {}
    for person in a.people:
        if person.is_principal:
            principals.setdefault(name_key(person.name), person.name)
    for page in pages:
        for name in extract_inline_principals(page):
            principals.setdefault(name_key(name), name)
    a.principals = list(principals.values())[:12]

    all_text = "\n".join(p.text for p in pages)
    a.stated_count = extract_stated_count(all_text)
    a.sole_phrase = has_sole_phrase(all_text)

    if lawyers:
        keys = set(lawyers) | set(principals)
        a.solicitor_count = len(keys)
    elif a.stated_count:
        a.solicitor_count = a.stated_count
        a.count_basis = "stated on site"
    elif principals:
        a.solicitor_count = len(principals)
        a.count_basis = "principal mentions only"
        a.count_source_url = pages[0].url if pages else ""

    a.practice_areas = extract_practice_areas(all_text)
    a.address = extract_address(pages)
    a.signals = detect_signals(firm_name, entity_type, host, pages, len(lawyers))
    return a

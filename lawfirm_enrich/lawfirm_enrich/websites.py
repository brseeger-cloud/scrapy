"""Finding a firm's website by guessing domains from its name and checking them.

A guessed site is accepted only if its home page shows the firm's ABN, or the
distinctive words of the firm's name together with legal wording, and it is not
a parked "domain for sale" page. Anything else is rejected, so a wrong site is
far less likely than a missed one.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .extract import _PARKED_RE
from .inputs import normalise_abn

TLDS = (".com.au", ".au", ".com")
MAX_DOMAINS = 9

# Words dropped when guessing a domain or matching a name
_ENTITY_WORDS = {"pty", "ltd", "limited", "proprietary", "inc", "incorporated", "the", "trustee", "for", "trust"}
_LEGAL_WORDS = {"lawyers", "lawyer", "legal", "law", "solicitors", "solicitor", "attorneys", "barristers", "and", "co"}
_LEGAL_TEXT_RE = re.compile(r"\b(lawyers?|legal|law|solicitors?|attorneys?|barristers?)\b", re.I)
_AU_ADDRESS_RE = re.compile(r"\b(?:NSW|VIC|QLD|SA|WA|TAS|NT|ACT)\b\.?,?\s*\d{4}\b", re.I)
_FOR_SALE_RE = re.compile(
    r"\b(?:dan\.com|afternic|sedo|hugedomains|undeveloped|domain (?:name )?(?:is )?for sale)\b", re.I
)


def _words(name: str) -> list[str]:
    name = name.lower().replace("’", "'").replace("'", "")
    name = re.sub(r"^\s*the trustee for\s+", "", name)
    words = re.findall(r"[a-z0-9]+|&", name)
    return [w for w in words if w not in _ENTITY_WORDS]


_PRACTICE_WORDS = _LEGAL_WORDS - {"and", "co"}


def _variants(words: list[str]) -> list[list[str]]:
    without_and = [w for w in words if w != "&"]
    with_and = ["and" if w == "&" else w for w in words]
    return [without_and, with_and] if "&" in words else [without_and]


def candidate_domains(*names: str) -> list[str]:
    """Likely domains for a firm, most likely first (at most MAX_DOMAINS)."""
    joined: list[str] = []
    hyphenated: list[str] = []
    for name in names:
        words = _words(name or "")
        if not words:
            continue
        forms = _variants(words)
        # the name without "Lawyers"/"Legal" etc., only when that still leaves
        # something distinctive: "Smith & Co Lawyers" -> smithandco, but never
        # "Smith Lawyers" -> smith
        core = [w for w in words if w not in _PRACTICE_WORDS]
        if core != words and (len(name_tokens(name)) >= 2 or "co" in core):
            forms += _variants(core)
        for form in forms:
            joined.append("".join(form))
            hyphenated.append("-".join(form))
    labels: list[str] = []
    for label in joined + hyphenated:
        if 3 <= len(label) <= 63 and label not in labels:
            labels.append(label)
    # every name variant is tried on .com.au before any is tried on .au or .com
    domains = [label + tld for tld in TLDS for label in labels]
    return domains[:MAX_DOMAINS]


def name_tokens(firm_name: str) -> list[str]:
    """The distinctive words of a firm's name ("Smith & Co Lawyers" -> ["smith"])."""
    return [w for w in _words(firm_name) if w != "&" and w not in _LEGAL_WORDS]


def verify(text: str, firm_name: str, abns: list[str], *, state: str = "", postcode: str = "") -> str:
    """Say how a page was matched to the firm, or return "" if it is not the firm's.

    Returns "ABN on site", "name on site" (name, legal wording and the firm's
    postcode or state), or "name on site (location unconfirmed)" when the page
    shows no Australian address at all. A page whose only address is in
    another state is rejected: probably a same-named firm elsewhere.
    """
    for abn in abns:
        digits = normalise_abn(abn)
        # the 11 digits as one number, allowing a space or dash between groups
        if len(digits) == 11 and re.search(r"(?<!\d)" + r"[ -]?".join(digits) + r"(?!\d)", text):
            return "ABN on site"
    if _PARKED_RE.search(text) or _FOR_SALE_RE.search(text):
        return ""
    tokens = name_tokens(firm_name)
    if not tokens or not _LEGAL_TEXT_RE.search(text):
        return ""
    low = text.lower().replace("’", "'").replace("'", "")
    if not all(re.search(rf"\b{re.escape(t)}\b", low) for t in tokens):
        return ""
    places = [p for p in (postcode.strip(), state.strip()) if p]
    if not places or any(re.search(rf"\b{re.escape(p)}\b", text, re.I) for p in places):
        return "name on site"
    if _AU_ADDRESS_RE.search(text):
        return ""  # shows an address, but in another state: probably a same-named firm
    return "name on site (location unconfirmed)"
    return ""


# Website builders where a firm's site is a page or subdomain of a shared host:
# the full address is kept, as the host's own home page is not the firm's.
_SITE_BUILDERS = (
    "sites.google.com", "wixsite.com", "weebly.com", "wordpress.com", "blogspot.com", "business.site",
    "godaddysites.com", "square.site", "squarespace.com", "webflow.io", "jimdosite.com",
)  # fmt: skip
# Pages about a firm that are not its own website (social media, directories)
_NOT_FIRM_SITES = (
    "facebook.com", "linkedin.com", "instagram.com", "twitter.com", "x.com", "youtube.com", "google.com",
    "yellowpages.com.au", "truelocal.com.au", "hotfrog.com.au", "localsearch.com.au", "yelp.com",
)  # fmt: skip


def _on(host: str, domains: tuple[str, ...]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def website_for(final_url: str) -> str | None:
    """The website to record for the page a guessed domain led to, or None if it is not the firm's own site."""
    parts = urlsplit(final_url)
    host = (parts.hostname or "").lower()
    if _on(host, _SITE_BUILDERS):
        return f"{parts.scheme}://{parts.netloc}{parts.path or '/'}"
    if _on(host, _NOT_FIRM_SITES):
        return None
    return f"{parts.scheme}://{parts.netloc}{parts.path or '/'}"


def is_site_builder_home(url: str) -> bool:
    """True for a website builder's own home page (e.g. https://sites.google.com/), which is no firm's site."""
    parts = urlsplit(url if "://" in url else "https://" + url)
    return _on((parts.hostname or "").lower(), _SITE_BUILDERS) and parts.path in ("", "/")


def redirected_elsewhere(guessed_domain: str, final_url: str, firm_name: str) -> bool:
    """True if a guess led to a different site whose address shares no word with the firm's name."""
    final_host = (urlsplit(final_url).hostname or "").lower().removeprefix("www.")
    if final_host == guessed_domain or final_host.endswith("." + guessed_domain):
        return False
    return not any(token in final_host for token in name_tokens(firm_name))

"""Collecting the email addresses a firm publishes on its own website.

Only addresses that are plainly published are collected: ``mailto:`` links and
addresses written out in the page text. Addresses a site has deliberately
obscured ("jane [at] firm [dot] com", Cloudflare email protection, images) are
never decoded, because the site has signalled it does not want them harvested.

Kept: addresses on the firm's own domain, or on a common webmail domain (many
sole practitioners use one). Dropped: third-party addresses (web designers,
law societies), and role addresses that are not for enquiries (careers,
privacy, accounts, no-reply).

Each address is labelled "general" (info@, reception@, …) or "personal"
(an individual's address). The site is also checked for a statement that it
does not accept unsolicited commercial email, which removes inferred consent
under the Spam Act 2003.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

from .inputs import host_of

_EMAIL_RE = re.compile(r"(?<![\w.%+\-])([A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)")

FREEMAIL_DOMAINS = {
    "gmail.com",
    "googlemail.com",
    "outlook.com",
    "outlook.com.au",
    "hotmail.com",
    "hotmail.com.au",
    "live.com",
    "live.com.au",
    "yahoo.com",
    "yahoo.com.au",
    "icloud.com",
    "me.com",
    "bigpond.com",
    "bigpond.net.au",
    "bigpond.com.au",
    "optusnet.com.au",
    "iinet.net.au",
    "tpg.com.au",
    "internode.on.net",
    "westnet.com.au",
    "dodo.com.au",
    "aapt.net.au",
    "ozemail.com.au",
}
_SKIP_LOCAL_RE = re.compile(
    r"^(?:no-?reply|do-?not-?reply|careers?|jobs?|recruit\w*|hr|humanresources|privacy|accounts?|"
    r"accounts?payable|billing|invoices?|payments?|trust(?:account)?|webmaster|postmaster|hostmaster|"
    r"abuse|wordpress|example|test|user|name|email|your\w*|marketing|media|press|subscribe|unsubscribe)$",
    re.I,
)
_GENERAL_LOCAL_RE = re.compile(
    r"^(?:info|information|enquir\w*|inquir\w*|reception|admin\w*|office|mail|contact\w*|hello|hi|law|legal|"
    r"lawyers?|solicitors?|firm|team|general|conveyanc\w*|wills?|estates?|family(?:law)?|property|"
    r"commercial|criminal|bookings?|appointments?|clients?|service|help|support|"
    r"\w+law|\w+legal|\w+lawyers?)$",
    re.I,
)
_FILE_SUFFIX_RE = re.compile(r"\.(?:png|jpe?g|gif|svg|webp|css|js)$", re.I)

_NO_UNSOLICITED_RE = re.compile(
    r"(?:do not|don't|does not|will not|won't)\s+(?:wish to\s+|want to\s+)?(?:accept|receive|consent to"
    r"(?: receiving| receive)?)\s+(?:any\s+)?unsolicited"
    r"|\bno unsolicited\b"
    r"|\bunsolicited (?:commercial )?(?:e-?mails?|electronic messages|marketing|messages|offers)\s+"
    r"(?:are|is|will)\s+not\b"
    r"|\bnot (?:to )?(?:be )?(?:taken|deemed|construed|regarded) (?:as|to be) (?:an? )?(?:inferred )?consent\b"
    r"|\b(?:does not|do not|doesn't) (?:constitute|amount to|imply) (?:an? )?(?:inferred )?consent\b",
    re.I,
)


def _domain_allowed(domain: str, site_hosts: set[str]) -> bool:
    if domain in FREEMAIL_DOMAINS:
        return True
    for host in site_hosts:
        if domain == host or domain.endswith("." + host) or host.endswith("." + domain):
            return True
    return False


def extract_emails(root, site_hosts: set[str]) -> list[str]:
    """Return addresses published on a page (lxml *root*), most prominent first."""
    found: list[str] = []
    for href in root.xpath("//a/@href"):
        if href.lower().startswith("mailto:"):
            addresses = unquote(href[7:].split("?", 1)[0])
            found.extend(a.strip() for a in addresses.split(","))
    text = " ".join(
        root.xpath("//body//text()[not(ancestor::script) and not(ancestor::style) and not(ancestor::noscript)]")
    )
    found.extend(m.group(1) for m in _EMAIL_RE.finditer(text))

    hosts = {h for h in (host_of(h) for h in site_hosts) if h}
    result: list[str] = []
    for addr in found:
        addr = addr.strip().strip(".").lower()
        m = _EMAIL_RE.fullmatch(addr)
        if not m or _FILE_SUFFIX_RE.search(addr):
            continue
        local, domain = addr.rsplit("@", 1)
        if not re.search(r"\.[a-z]{2,}$", domain) or _SKIP_LOCAL_RE.match(local):
            continue
        if not _domain_allowed(domain, hosts):
            continue
        if addr not in result:
            result.append(addr)
    return result


def email_type(address: str) -> str:
    local = address.split("@", 1)[0]
    return "general" if _GENERAL_LOCAL_RE.match(local) else "personal"


def find_no_unsolicited_notice(lines: list[str]) -> str:
    """Return the sentence where a site refuses unsolicited email, or ""."""
    for line in lines:
        m = _NO_UNSOLICITED_RE.search(line)
        if m:
            start = max(0, m.start() - 60)
            return line[start : m.end() + 80].strip()
    return ""

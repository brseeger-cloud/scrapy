"""Building a list of law firms from the ABN Bulk Extract.

The ABN Bulk Extract (data.gov.au, dataset "abn-bulk-extract") is the public
Australian Business Register: every ABN with its status, entity type, legal
name, trading and business names, state and postcode. It is published as two
zip files of XML (``public_split_1_10.zip`` and ``public_split_11_20.zip``)
under a CC BY licence.

The register has no industry codes, websites or street addresses, so law firms
are picked out by name: an active ABN whose legal, trading or business name
contains "Lawyers", "Legal", "Solicitors", "Law", etc. Firms that trade only
under a person's own name are therefore missed.
"""

from __future__ import annotations

import csv
import logging
import os
import re
import zipfile
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

from lxml import etree

from .inputs import DoNotContactList, normalise_abn, normalise_name

logger = logging.getLogger(__name__)

LIST_COLUMNS = [
    "firm_name",
    "abn",
    "entity_type",
    "state",
    "postcode",
    "website",
    "legal_name",
    "other_names",
    "other_abns",
    "gst_registered",
    "source",
]

_LAW_NAME_RE = re.compile(
    r"\b(?:lawyers?|solicitors?|legal|law|attorneys?|notar(?:y|ies)(?: public)?|"
    r"barristers?\s*(?:and|&)\s*solicitors?)\b",
    re.I,
)
_CONVEYANCER_RE = re.compile(r"\bconveyanc\w*", re.I)
_NOT_A_FIRM_RE = re.compile(
    r"\b(?:in[- ]laws?|by[- ]laws?|law ?enforcement|law ?society|law ?school|law ?students?|law ?library|"
    r"law ?reform|law ?council|law ?institute|legal ?aid|legal ?tender|paralegal\w*|legally|"
    r"commission|department|ministry|university|college|institute|association|society|foundation|"
    r"super(?:annuation)? fund|bookkeep\w*|accounting|accountants?)\b",
    re.I,
)
_SKIP_ENTITY_RE = re.compile(r"super(?:annuation)? fund|government|deceased estate", re.I)

# Preference for the name shown as firm_name (what the public sees)
_NAME_TYPE_RANK = {"BN": 0, "TRD": 1, "OTN": 2, "MN": 3, "LGL": 3}


@dataclass
class AbnRecord:
    abn: str
    active: bool
    entity_type: str
    state: str
    postcode: str
    gst: bool
    legal_name: str
    names: list[tuple[str, str]] = field(default_factory=list)  # (type, name), legal name included


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def parse_record(el) -> AbnRecord:
    """Read one <ABR> element (a single pass over its sub-elements)."""
    abn = status = entity_type = state = postcode = legal_name = ""
    gst = False
    names: list[tuple[str, str]] = []
    for c in el.iter():
        tag = _local(c.tag)
        if tag == "ABN":
            abn, status = (c.text or "").strip(), c.get("status") or ""
        elif tag == "EntityTypeText":
            entity_type = (c.text or "").strip()
        elif tag == "State" and not state:
            state = (c.text or "").strip()
        elif tag == "Postcode" and not postcode:
            postcode = (c.text or "").strip()
        elif tag == "GST":
            gst = (c.get("status") or "").upper() == "ACT"
        elif tag == "NonIndividualName":
            kind = c.get("type") or ""
            raw = " ".join("".join(t.itertext()) for t in c if _local(t.tag) == "NonIndividualNameText")
            text = " ".join(raw.split())
            if text:
                names.append((kind, text))
                if kind in ("MN", "LGL") and not legal_name:
                    legal_name = text
        elif tag == "IndividualName":
            parts = [(g.text or "").strip() for g in c.iter() if _local(g.tag) in ("GivenName", "FamilyName")]
            person = " ".join(p for p in parts if p)
            if person and not legal_name:
                legal_name = person
                names.append((c.get("type") or "LGL", person))
    return AbnRecord(
        abn=abn,
        active=status.upper() == "ACT",
        entity_type=entity_type,
        state=state,
        postcode=postcode,
        gst=gst,
        legal_name=legal_name,
        names=names,
    )


def _xml_streams(paths: Iterable[str | Path]) -> Iterator[tuple[str, object]]:
    for path in paths:
        path = Path(path)
        if path.is_dir():
            yield from _xml_streams(sorted(p for p in path.iterdir() if p.suffix.lower() in (".zip", ".xml")))
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as zf:
                for info in sorted(zf.infolist(), key=lambda i: i.filename):
                    if info.filename.lower().endswith(".xml"):
                        with zf.open(info) as fh:
                            yield f"{path.name}:{info.filename}", fh
        else:
            with path.open("rb") as fh:
                yield path.name, fh


# Cheap first test on a record's raw text: only records mentioning one of these
# words are parsed in full (fewer than 1 in 1,000 of the ~20 million).
_PREFILTER_RE = re.compile(rb"(?i)law|legal|solicit|attorney|notar|conveyanc")


def iter_records(paths: Iterable[str | Path], counter: dict | None = None) -> Iterator[AbnRecord]:
    """Stream ABR records that mention a legal word, from zip files, XML files or folders of them.

    *counter*, if given, gets ``counter["read"]`` = records read so far.
    """
    counter = counter if counter is not None else {}
    counter.setdefault("read", 0)
    for name, fh in _xml_streams(paths):
        logger.info(f"Reading {name}")
        for _, el in etree.iterparse(fh, events=("end",), tag=("ABR", "{*}ABR"), huge_tree=True):
            counter["read"] += 1
            if counter["read"] % 1_000_000 == 0:
                logger.info(f"{counter['read']:,} records read")
            if _PREFILTER_RE.search(etree.tostring(el, method="text", encoding="utf-8")):
                yield parse_record(el)
            # free memory as we go: the files hold millions of records
            el.clear()
            parent = el.getparent()
            while parent is not None and el.getprevious() is not None:
                del parent[0]


def is_law_name(name: str, *, include_conveyancers: bool = False) -> bool:
    if _NOT_A_FIRM_RE.search(name):
        return False
    if _LAW_NAME_RE.search(name):
        return True
    return include_conveyancers and bool(_CONVEYANCER_RE.search(name))


def display_name(name: str) -> str:
    """'SMITH & CO LAWYERS PTY LTD' -> 'Smith & Co Lawyers Pty Ltd'."""
    if not name.isupper():
        return name
    out = []
    for word in name.split():
        w = word.capitalize()
        w = re.sub(r"(?<=['’-])([a-z])", lambda m: m.group(1).upper(), w)  # O'Brien, Smith-Jones
        w = re.sub(r"^Mc([a-z])", lambda m: "Mc" + m.group(1).upper(), w)
        out.append(w)
    text = " ".join(out)
    return re.sub(r"\bThe Trustee For\b", "The Trustee for", text)


def law_firm_row(rec: AbnRecord, *, include_conveyancers: bool = False, source: str = "") -> dict | None:
    """Return a firms.csv row if *rec* looks like an active law firm, else None."""
    if not rec.active or not rec.abn or _SKIP_ENTITY_RE.search(rec.entity_type):
        return None
    matching = [(kind, n) for kind, n in rec.names if is_law_name(n, include_conveyancers=include_conveyancers)]
    if not matching:
        return None
    matching.sort(key=lambda kn: _NAME_TYPE_RANK.get(kn[0], 9))
    firm_name = display_name(matching[0][1])
    others = []
    for _, n in rec.names:
        d = display_name(n)
        if d != firm_name and d not in others:
            others.append(d)
    return {
        "firm_name": firm_name,
        "abn": rec.abn,
        "entity_type": rec.entity_type,
        "state": rec.state,
        "postcode": rec.postcode,
        "website": "",
        "legal_name": display_name(rec.legal_name),
        "other_names": "; ".join(others[:5]),
        "other_abns": "",
        "gst_registered": "Y" if rec.gst else "N",
        "source": source,
    }


def _dedupe_key(row: dict) -> tuple[str, str]:
    name = normalise_name(row["firm_name"])
    name = re.sub(r"^the trustee for ", "", name)
    name = re.sub(r"\b(unit|discretionary|family|service|practice) trust\b|\btrust\b", "", name).strip()
    return name, row["state"]


def merge_duplicates(rows: list[dict]) -> list[dict]:
    """One row per firm: entities with the same name in the same state are merged.

    A practice often has several ABNs (company, service trust, partnership).
    The GST-registered one is kept as the main ABN; the rest go in other_abns.
    """
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault(_dedupe_key(row), []).append(row)
    merged = []
    for group in groups.values():
        group.sort(key=lambda r: (r["gst_registered"] != "Y", "trust" in r["entity_type"].lower()))
        main = dict(group[0])
        extra = [r["abn"] for r in group[1:]]
        if extra:
            main["other_abns"] = "; ".join(extra)
        merged.append(main)
    return merged


@dataclass
class BuildResult:
    records_read: int = 0
    law_firms_found: int = 0
    after_merge: int = 0
    dnc_excluded: int = 0
    already_listed: int = 0
    added: int = 0
    total: int = 0


def build_firm_list(
    sources: list[str | Path],
    out_path: str | Path,
    dnc_path: str | Path,
    *,
    states: Iterable[str] = (),
    include_conveyancers: bool = False,
    source_label: str = "ABN Bulk Extract",
) -> BuildResult:
    """Write (or extend) *out_path* with law firms found in the ABN Bulk Extract.

    Rows already in *out_path* are kept as they are (including websites you
    have filled in); only firms with new ABNs are added. Firms on the
    do-not-contact list are never added.
    """
    states = {s.upper() for s in states}
    dnc = DoNotContactList.load(dnc_path)
    res = BuildResult()
    found = []
    counter: dict = {}
    for rec in iter_records(sources, counter):
        if states and rec.state.upper() not in states:
            continue
        row = law_firm_row(rec, include_conveyancers=include_conveyancers, source=source_label)
        if row:
            found.append(row)
    res.records_read = counter.get("read", 0)
    res.law_firms_found = len(found)
    merged = merge_duplicates(found)
    res.after_merge = len(merged)

    out_path = Path(out_path)
    existing: list[dict] = []
    fieldnames = list(LIST_COLUMNS)
    if out_path.exists() and out_path.stat().st_size:
        with out_path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            fieldnames += [f for f in (reader.fieldnames or []) if f and f not in fieldnames]
            existing = list(reader)
    known = set()
    for r in existing:
        known.add(normalise_abn(r.get("abn", "")))
        known.update(normalise_abn(a) for a in (r.get("other_abns") or "").split(";"))
    known.discard("")

    new_rows = []
    for row in sorted(merged, key=lambda r: (r["state"], r["firm_name"].lower())):
        abns = {row["abn"], *(a.strip() for a in row["other_abns"].split(";") if a.strip())}
        if known & {normalise_abn(a) for a in abns}:
            res.already_listed += 1
            continue
        if dnc.matches(firm_name=row["firm_name"], abn=row["abn"]) or any(dnc.matches(abn=a) for a in abns):
            res.dnc_excluded += 1
            continue
        new_rows.append(row)
    res.added = len(new_rows)
    res.total = len(existing) + len(new_rows)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(f".{out_path.name}.tmp")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(existing)
        writer.writerows(new_rows)
    os.replace(tmp, out_path)
    return res

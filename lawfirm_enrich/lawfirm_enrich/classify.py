"""Firm size / exclusion classification."""

from __future__ import annotations

from dataclasses import dataclass

from .extract import Analysis

SOLE = "Sole"
SMALL = "Small (2-4)"
LARGER = "Larger"
EXCLUDE = "Exclude"
CHECK = "Check manually"

EXCLUDE_REASONS = ("barrister", "in-house", "government", "licensed conveyancer", "not a law firm")


@dataclass
class Classification:
    classification: str
    exclude_reason: str = ""
    notes: str = ""


def size_bucket(count: int) -> str:
    if count <= 1:
        return SOLE
    if count <= 4:
        return SMALL
    return LARGER


def classify(analysis: Analysis | None, *, entity_type: str = "", crawl_error: str = "") -> Classification:
    if analysis is None:
        return Classification(CHECK, notes=f"site not crawled: {crawl_error}" if crawl_error else "site not crawled")

    notes: list[str] = []
    strong = [s for s in analysis.signals if s.strength == "strong"]
    weak = [s for s in analysis.signals if s.strength == "weak"]

    if strong:
        reason = strong[0].reason
        evidence = "; ".join(f"{s.reason}: {s.evidence}" for s in strong + weak)
        return Classification(EXCLUDE, exclude_reason=reason, notes=evidence)

    if weak:
        notes.extend(f"possible {s.reason}: {s.evidence}" for s in weak)

    count = analysis.solicitor_count
    basis = analysis.count_basis
    bucket: str | None = None

    if count and basis in ("team page listing", "about/home page listing"):
        bucket = size_bucket(count)
        notes.insert(0, f"{count} solicitor(s) from {basis}")
        stated = analysis.stated_count
        if stated and size_bucket(stated) != bucket:
            notes.append(f"site states {stated} lawyers – conflicts with listing")
            bucket = None
        elif bucket != SOLE and analysis.sole_phrase and count <= 2:
            notes.append("site wording suggests a sole practitioner")
            bucket = None
    elif count and basis == "stated on site":
        bucket = size_bucket(count)
        notes.insert(0, f"{count} lawyers stated on site (no staff listing found)")
    elif analysis.sole_phrase and (count or 0) <= 1:
        bucket = SOLE
        notes.insert(0, "sole practitioner wording on site (no staff listing found)")
    elif count and basis == "principal mentions only":
        if count == 1 and "sole trader" in (entity_type or "").lower():
            bucket = SOLE
            notes.insert(0, "one principal named; ABN entity is a sole trader (no staff listing found)")
        else:
            notes.insert(0, f"{count} principal(s) named but no staff listing found")
    else:
        notes.insert(0, "could not find a staff listing or stated number of solicitors")

    if bucket is None or weak:
        return Classification(CHECK, notes="; ".join(notes))
    return Classification(bucket, notes="; ".join(notes))

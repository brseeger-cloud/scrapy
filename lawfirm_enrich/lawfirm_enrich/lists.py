"""Selecting firms from the master list for a marketing campaign."""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .inputs import DoNotContactList
from .items import EMAIL_COLUMNS
from .master import MasterList, _as_date, _norm, sync_opt_outs
from .privacy import scrub_emails

SIZES = ("Sole", "Small (2-4)", "Larger", "Check manually")
AREAS = ("conveyancing", "wills_estates", "family", "personal_injury", "commercial", "criminal")
LIST_COLUMNS = [
    "firm_name",
    "addressee",
    "postal_address",
    "email",
    "email_type",
    "state",
    "postcode",
    "classification",
    "solicitor_count",
    "practice_areas",
    "website",
    "firm_key",
]


@dataclass
class Criteria:
    sizes: list[str] = field(default_factory=lambda: ["Sole", "Small (2-4)", "Larger"])
    states: list[str] = field(default_factory=list)  # empty = all
    areas: list[str] = field(default_factory=list)  # empty = any; otherwise at least one
    not_contacted_days: int = 0  # 0 = ignore last_contacted
    channel: str = "post"  # "post": needs a postal address; "email": needs an email address
    require_address: bool = True  # post channel only
    general_email_only: bool = False  # email channel only: skip individuals' addresses


def select(master: MasterList, dnc: DoNotContactList, criteria: Criteria, today: date | None = None) -> list[dict]:
    today = today or date.today()
    sizes = {s.lower() for s in criteria.sizes}
    states = {s.upper() for s in criteria.states}
    chosen = []
    for row in master.rows.values():
        # Excluded firms are never selected, whatever the criteria say.
        if _norm(row.get("classification")).lower() not in sizes or row.get("classification") == "Exclude":
            continue
        if dnc.matches(
            firm_name=_norm(row.get("firm_name")),
            abn=_norm(row.get("abn")),
            urls=(_norm(row.get("website")), _norm(row.get("final_url"))),
        ):
            continue
        if states and _norm(row.get("state")).upper() not in states:
            continue
        if criteria.areas and not any(_norm(row.get(a)).upper() == "Y" for a in criteria.areas):
            continue
        if criteria.channel == "post" and criteria.require_address and not _norm(row.get("postal_address")):
            continue
        if criteria.channel == "email":
            if not _norm(row.get("email")):
                continue
            # A site that refuses unsolicited email gives no inferred consent: never selected.
            if _norm(row.get("no_unsolicited_email_notice")):
                continue
            if criteria.general_email_only and _norm(row.get("email_type")) != "general":
                continue
        if criteria.not_contacted_days:
            last = _as_date(row.get("last_contacted"))
            if last and last > today - timedelta(days=criteria.not_contacted_days):
                continue
        chosen.append(row)
    return sorted(chosen, key=lambda r: (_norm(r.get("state")), _norm(r.get("firm_name")).lower()))


def to_list_row(row: dict) -> dict:
    principals = [p.strip() for p in _norm(row.get("principal_names")).split(";") if p.strip()]
    out = {c: _norm(row.get(c)) for c in LIST_COLUMNS}
    out["addressee"] = principals[0] if principals else "The Principal"
    return {k: v if k in EMAIL_COLUMNS else scrub_emails(v) for k, v in out.items()}


def make_list(
    master_path: str | Path,
    dnc_path: str | Path,
    out_path: str | Path,
    criteria: Criteria,
    *,
    mark_contacted: bool = False,
    today: date | None = None,
) -> int:
    """Write a CSV of firms matching *criteria*; return how many were written."""
    today = today or date.today()
    sync_opt_outs(master_path, dnc_path)
    master = MasterList.load(master_path)
    dnc = DoNotContactList.load(dnc_path)
    rows = select(master, dnc, criteria, today)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel reads UTF-8
        writer = csv.DictWriter(fh, fieldnames=LIST_COLUMNS)
        writer.writeheader()
        writer.writerows(to_list_row(r) for r in rows)

    if mark_contacted and rows:
        for r in rows:
            r["last_contacted"] = today.isoformat()
        master.save()
    return len(rows)

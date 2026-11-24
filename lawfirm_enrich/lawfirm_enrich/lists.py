"""Selecting firms from the master list for a mail or email campaign.

* Postal lists have the address split into fields (address_line_1, suburb,
  state, postcode) for Word mail merge or a mail house.
* Email lists have first_name / last_name for an email service's merge fields.

``mark_contacted`` records the send: last_mailed or last_emailed on each firm
(so a mail-out does not stop the same firm getting the email campaign) and one
row per firm in the master list's Campaigns sheet.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from .addresses import ParsedAddress, split_address
from .inputs import DoNotContactList, host_of
from .items import EMAIL_COLUMNS
from .master import MasterList, _as_date, _norm, sync_opt_outs
from .privacy import scrub_emails
from .unsubscribe import load_unsubscribed, strip_unsubscribed

SIZES = ("Sole", "Small (2-4)", "Larger", "Check manually")
AREAS = ("conveyancing", "wills_estates", "family", "personal_injury", "commercial", "criminal")
_DETAIL_COLUMNS = ["classification", "solicitor_count", "practice_areas", "website", "firm_key"]
POSTAL_LIST_COLUMNS = [
    "firm_name",
    "addressee",
    "first_name",
    "last_name",
    "address_line_1",
    "suburb",
    "state",
    "postcode",
    "full_address",
    "address_type",
    *_DETAIL_COLUMNS,
]
EMAIL_LIST_COLUMNS = [
    "email",
    "first_name",
    "last_name",
    "addressee",
    "firm_name",
    "email_type",
    "state",
    *_DETAIL_COLUMNS,
]
_CHANNEL_DATE = {"post": "last_mailed", "email": "last_emailed"}


@dataclass
class Criteria:
    sizes: list[str] = field(default_factory=lambda: ["Sole", "Small (2-4)", "Larger"])
    states: list[str] = field(default_factory=list)  # empty = all
    areas: list[str] = field(default_factory=list)  # empty = any; otherwise at least one
    not_contacted_days: int = 0  # 0 = ignore; else skip firms sent this channel (or contacted by you) recently
    channel: str = "post"  # "post": needs an address; "email": needs an email address
    address: str = "postal"  # post channel: "postal" (mailing address) or "office"
    require_address: bool = True  # post channel only
    general_email_only: bool = False  # email channel only: skip individuals' addresses


def _address(row: dict, criteria: Criteria) -> ParsedAddress | None:
    column = "office_address" if criteria.address == "office" else "postal_address"
    return split_address(_norm(row.get(column)))


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
        if criteria.channel == "post" and criteria.require_address and _address(row, criteria) is None:
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
            cutoff = today - timedelta(days=criteria.not_contacted_days)
            dates = [_as_date(row.get(_CHANNEL_DATE[criteria.channel])), _as_date(row.get("last_contacted"))]
            if any(d and d > cutoff for d in dates):
                continue
        chosen.append(row)
    return sorted(chosen, key=lambda r: (_norm(r.get("state")), _norm(r.get("firm_name")).lower()))


def addressee(row: dict, email: str = "") -> str:
    """Who to address: the principal whose name is in a personal email address, else the first principal."""
    principals = [p.strip() for p in _norm(row.get("principal_names")).split(";") if p.strip()]
    if email and _norm(row.get("email_type")) == "personal":
        local = email.split("@", 1)[0].lower()
        for person in principals:
            if any(len(part) > 2 and part.lower() in local for part in person.split()):
                return person
    return principals[0] if principals else ""


def _names(person: str) -> tuple[str, str]:
    parts = person.split()
    return (parts[0], parts[-1]) if len(parts) >= 2 else ("", "")


def to_postal_row(row: dict, criteria: Criteria) -> dict:
    person = addressee(row)
    first, last = _names(person)
    addr = _address(row, criteria)
    out = {c: _norm(row.get(c)) for c in _DETAIL_COLUMNS}
    out.update(
        firm_name=_norm(row.get("firm_name")),
        addressee=person or "The Principal",
        first_name=first,
        last_name=last,
        address_line_1=addr.line if addr else "",
        suburb=addr.suburb if addr else "",
        state=addr.state if addr else _norm(row.get("state")),
        postcode=addr.postcode if addr else "",
        full_address=str(addr) if addr else "",
        address_type=("PO Box" if addr.is_po_box else criteria.address) if addr else "",
    )
    return {k: scrub_emails(v) for k, v in out.items()}


def to_email_row(row: dict) -> dict:
    email = _norm(row.get("email"))
    person = addressee(row, email)
    first, last = _names(person)
    out = {c: _norm(row.get(c)) for c in _DETAIL_COLUMNS}
    out.update(
        email=email,
        first_name=first,
        last_name=last,
        addressee=person or "The Principal",
        firm_name=_norm(row.get("firm_name")),
        email_type=_norm(row.get("email_type")),
        state=_norm(row.get("state")),
    )
    return {k: v if k in EMAIL_COLUMNS else scrub_emails(v) for k, v in out.items()}


def make_list(
    master_path: str | Path,
    dnc_path: str | Path,
    out_path: str | Path,
    criteria: Criteria,
    *,
    mark_contacted: bool = False,
    campaign: str = "",
    today: date | None = None,
    unsubscribed_path: str | Path | None = None,
    stats: dict | None = None,
) -> int:
    """Write a CSV of firms matching *criteria*; return how many were written.

    Addresses in *unsubscribed_path* are removed first, so they are never
    exported. Firms sharing a website (several register entries for one firm)
    get one letter or email between them, and an email address is never used
    twice, so no firm is sent the same campaign twice; *stats*, if given, gets
    ``stats["duplicates"]``, the number left out for that reason. With
    *mark_contacted*, the send is recorded against *campaign*.
    """
    today = today or date.today()
    sync_opt_outs(master_path, dnc_path)
    master = MasterList.load(master_path)
    unsubscribed = load_unsubscribed(unsubscribed_path)
    for row in master.rows.values():
        strip_unsubscribed(row, unsubscribed)
    dnc = DoNotContactList.load(dnc_path)
    rows = select(master, dnc, criteria, today)

    if criteria.channel == "email":
        columns, candidates = EMAIL_LIST_COLUMNS, [(r, to_email_row(r)) for r in rows]
    else:
        columns, candidates = POSTAL_LIST_COLUMNS, [(r, to_postal_row(r, criteria)) for r in rows]
    # Several register entries can match the same website, i.e. the same firm:
    # each website gets one letter or email, and each email address one email.
    seen: set[str] = set()
    rows, out_rows = [], []
    for row, out in candidates:
        keys = {f"site:{host_of(_norm(row.get('final_url')) or _norm(row.get('website')))}"} - {"site:"}
        if criteria.channel == "email":
            keys.add(f"email:{out['email'].lower()}")
        elif not keys:
            keys.add(f"address:{out['full_address'].lower()}")
        if keys & seen:
            continue
        seen |= keys
        rows.append(row)
        out_rows.append(out)
    if stats is not None:
        stats["duplicates"] = len(candidates) - len(rows)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8-sig") as fh:  # BOM so Excel reads UTF-8
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        writer.writerows(out_rows)

    if mark_contacted and rows:
        name = campaign or f"{criteria.channel} list {today.isoformat()}"
        for row, sent in zip(rows, out_rows, strict=True):
            row[_CHANNEL_DATE[criteria.channel]] = today.isoformat()
            row["last_campaign"] = name
            master.campaigns.append(
                {
                    "date": today.isoformat(),
                    "campaign": name,
                    "channel": criteria.channel,
                    "firm_key": row["firm_key"],
                    "firm_name": _norm(row.get("firm_name")),
                    "sent_to": sent["email"] if criteria.channel == "email" else sent["full_address"],
                }
            )
        master.save()
    return len(rows)

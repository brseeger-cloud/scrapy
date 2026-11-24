"""Unsubscribed email addresses (unsubscribed.csv).

An unsubscribe applies to the address that asked: that address is never stored
again or put on an email list, but the firm's other addresses and its postal
address can still be used. To stop contacting the whole firm, use
``whole_firm=True`` (adds the firm to do_not_contact.csv) or mark the firm
"Opted out" in the master list.

Under the Spam Act 2003, unsubscribe requests must take effect within 5
business days.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .emails import email_type
from .inputs import DNC_COLUMNS, DoNotContactList

UNSUBSCRIBED_COLUMNS = ["email", "date_added", "source"]
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")


def load_unsubscribed(path: str | Path | None) -> set[str]:
    """Addresses in unsubscribed.csv (lower case). A missing file means none."""
    if not path or not Path(path).exists():
        return set()
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        return {(r.get("email") or "").strip().lower() for r in csv.DictReader(fh)} - {""}


def read_addresses(sources: list[str]) -> list[str]:
    """Email addresses from files (any CSV or text export, e.g. from an email service) or typed directly."""
    found: list[str] = []
    for source in sources:
        path = Path(source)
        text = path.read_text(encoding="utf-8-sig", errors="replace") if path.is_file() else source
        for addr in _EMAIL_RE.findall(text):
            addr = addr.lower().strip(".")
            if addr not in found:
                found.append(addr)
    return found


def strip_unsubscribed(row: dict, unsubscribed: set[str]) -> bool:
    """Remove unsubscribed addresses from a row's email columns; return True if any were removed."""
    if not unsubscribed:
        return False
    addresses = [row.get("email") or "", *(row.get("other_emails") or "").split(";")]
    addresses = [a.strip() for a in addresses if a and a.strip()]
    kept = [a for a in addresses if a.lower() not in unsubscribed]
    if len(kept) == len(addresses):
        return False
    row["email"] = kept[0] if kept else ""
    row["email_type"] = email_type(kept[0]) if kept else ""
    row["other_emails"] = "; ".join(kept[1:])
    return True


@dataclass
class UnsubscribeResult:
    addresses: list[str] = field(default_factory=list)
    newly_added: int = 0
    found_in_master: int = 0
    firms_added_to_dnc: list[str] = field(default_factory=list)


def _append_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    exists = path.exists() and path.stat().st_size > 0
    needs_newline = exists and not path.read_bytes().endswith(b"\n")
    with path.open("a", newline="", encoding="utf-8") as fh:
        if needs_newline:
            fh.write("\n")
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        if not exists:
            writer.writeheader()
        writer.writerows(rows)


def process_unsubscribes(
    sources: list[str],
    unsubscribed_path: str | Path,
    master_path: str | Path,
    dnc_path: str | Path,
    *,
    whole_firm: bool = False,
    source_label: str = "",
) -> UnsubscribeResult:
    """Record unsubscribes and remove the addresses (or whole firms) from the master list."""
    from .master import MasterList  # here to avoid an import cycle

    res = UnsubscribeResult(addresses=read_addresses(sources))
    unsubscribed_path = Path(unsubscribed_path)
    already = load_unsubscribed(unsubscribed_path)
    today = date.today().isoformat()
    new = [{"email": a, "date_added": today, "source": source_label} for a in res.addresses if a not in already]
    if new:
        _append_csv(unsubscribed_path, UNSUBSCRIBED_COLUMNS, new)
    res.newly_added = len(new)

    master_path = Path(master_path)
    if not master_path.exists():
        return res
    master = MasterList.load(master_path)
    targets = set(res.addresses)
    dnc_rows = []
    for key, row in master.rows.items():
        if not strip_unsubscribed(row, targets):
            continue
        res.found_in_master += 1
        if whole_firm:
            dnc_rows.append(
                {
                    "firm_name": row.get("firm_name") or "",
                    "abn": row.get("abn") or "",
                    "website": "",
                    "reason": "unsubscribed (whole firm)",
                    "date_added": today,
                }
            )
            res.firms_added_to_dnc.append(str(row.get("firm_name") or key))
    if dnc_rows:
        _append_csv(Path(dnc_path), list(DNC_COLUMNS), dnc_rows)
        master.remove_do_not_contact(DoNotContactList.load(dnc_path))
    if res.found_in_master:
        master.save()
    return res

"""The master list: one row per firm, kept up to date across runs.

The master list is an Excel workbook (``data/master.xlsx`` by default) with:

* **Firms** – one row per firm, keyed by ``firm_key`` (ABN, else website
  domain, else normalised name). Each crawl updates the crawled columns. Your
  own columns (``my_status``, ``last_contacted``, ``my_notes`` and any column
  you add yourself) are never overwritten.
* **Changes** – one row per changed value (classification, solicitor count,
  principals, address, …) so you can see what changed and when.

Firms on the do-not-contact list are removed from the master list. Setting
``my_status`` to "Opted out" or "Do not contact" adds the firm to
do_not_contact.csv and removes it from the master list on the next run.
"""

from __future__ import annotations

import csv
import logging
import os
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from .inputs import DNC_COLUMNS, DoNotContactList, host_of, normalise_abn, normalise_name, normalise_url
from .items import OUTPUT_COLUMNS
from .privacy import contains_email, scrub_emails

logger = logging.getLogger(__name__)

USER_COLUMNS = ["my_status", "last_contacted", "my_notes"]
TRACKING_COLUMNS = ["first_seen", "last_crawled", "last_successful_crawl", "last_changed"]
CRAWL_COLUMNS = [c for c in OUTPUT_COLUMNS if c != "input_row"]
MASTER_COLUMNS = ["firm_key", *CRAWL_COLUMNS[:9], *USER_COLUMNS, *CRAWL_COLUMNS[9:], *TRACKING_COLUMNS]
CHANGE_COLUMNS = ["date", "firm_key", "firm_name", "field", "old_value", "new_value"]

# Changes to these columns are recorded in the Changes sheet
TRACKED_COLUMNS = [
    "firm_name",
    "website",
    "final_url",
    "classification",
    "exclude_reason",
    "solicitor_count",
    "principal_names",
    "practice_areas",
    "postal_address",
    "street_address",
    "crawl_status",
]
# Crawl results that only reflect the latest attempt, updated even when it failed
ATTEMPT_COLUMNS = {"crawl_status", "pages_failed", "date_collected"}
# Copied from firms.csv on every run
INPUT_COLUMNS = {"firm_name", "abn", "entity_type", "state", "postcode", "website"}

OPT_OUT_STATUSES = {"opted out", "opt out", "opt-out", "do not contact", "dnc", "unsubscribe", "unsubscribed"}
FAILED_STATUSES = {"failed", "no website"}


def firm_key(abn: str, website: str, firm_name: str) -> str:
    a = normalise_abn(abn)
    if len(a) == 11:
        return f"abn:{a}"
    host = host_of(normalise_url(website)[0])
    if host:
        return f"web:{host}"
    return f"name:{normalise_name(firm_name)}"


def _as_date(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str) and value.strip():
        text = value.strip()
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def _blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _norm(value) -> str:
    return "" if value is None else str(value).strip()


@dataclass
class MasterList:
    path: Path
    columns: list[str] = field(default_factory=lambda: list(MASTER_COLUMNS))
    rows: dict[str, dict] = field(default_factory=dict)
    changes: list[dict] = field(default_factory=list)

    # ---------------------------------------------------------------- load/save

    @classmethod
    def load(cls, path: str | Path) -> MasterList:
        path = Path(path)
        master = cls(path)
        if not path.exists():
            return master
        wb = load_workbook(path)
        if "Firms" in wb.sheetnames:
            ws = wb["Firms"]
            header = [_norm(c.value) for c in ws[1]]
            # keep any columns you added yourself, after the standard ones
            master.columns += [h for h in header if h and h not in master.columns]
            for values in ws.iter_rows(min_row=2, values_only=True):
                row = {h: v for h, v in zip(header, values, strict=False) if h}
                key = _norm(row.get("firm_key"))
                if key:
                    master.rows[key] = row
        if "Changes" in wb.sheetnames:
            ws = wb["Changes"]
            header = [_norm(c.value) for c in ws[1]]
            for values in ws.iter_rows(min_row=2, values_only=True):
                master.changes.append(dict(zip(header, values, strict=False)))
        return master

    def save(self) -> Path:
        wb = Workbook()
        ws = wb.active
        ws.title = "Firms"
        _write(
            ws,
            self.columns,
            sorted(self.rows.values(), key=lambda r: (_norm(r.get("firm_name")).lower(), r["firm_key"])),
        )
        _write(wb.create_sheet("Changes"), CHANGE_COLUMNS, self.changes)

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.stem}.tmp{self.path.suffix}")
        wb.save(tmp)
        try:
            os.replace(tmp, self.path)  # never leaves a half-written master list
        except PermissionError:
            alt = self.path.with_name(f"{self.path.stem}_{datetime.now():%Y%m%d_%H%M%S}{self.path.suffix}")
            os.replace(tmp, alt)
            logger.error(
                f"{self.path} is open in another program; saved the master list as {alt} instead. "
                f"Close the file and rename {alt.name} to {self.path.name}."
            )
            return alt
        return self.path

    # ------------------------------------------------------------------- update

    def upsert(self, crawl_row: dict) -> None:
        """Merge one crawl result into the master list."""
        key = firm_key(crawl_row.get("abn", ""), crawl_row.get("website", ""), crawl_row.get("firm_name", ""))
        today = _norm(crawl_row.get("date_collected")) or date.today().isoformat()
        failed = crawl_row.get("crawl_status") in FAILED_STATUSES
        existing = self.rows.get(key)

        if existing is None:
            row = dict.fromkeys(self.columns, "")
            row.update({c: crawl_row.get(c, "") for c in CRAWL_COLUMNS})
            row.update(firm_key=key, first_seen=today, last_crawled=today, last_changed=today)
            row["last_successful_crawl"] = "" if failed else today
            self.rows[key] = row
            return

        had_good_data = not _blank(existing.get("last_successful_crawl"))
        if failed and had_good_data:
            # Keep the last good results; record only that this attempt failed.
            update_cols = INPUT_COLUMNS | ATTEMPT_COLUMNS
        else:
            update_cols = set(CRAWL_COLUMNS)

        changed = False
        for col in sorted(update_cols, key=CRAWL_COLUMNS.index):
            new = crawl_row.get(col, "")
            old = existing.get(col)
            if _norm(old) != _norm(new):
                if col in TRACKED_COLUMNS:
                    self.changes.append(
                        {
                            "date": today,
                            "firm_key": key,
                            "firm_name": crawl_row.get("firm_name", ""),
                            "field": col,
                            "old_value": _norm(old),
                            "new_value": _norm(new),
                        }
                    )
                    changed = True
                existing[col] = new
        existing["last_crawled"] = today
        if not failed:
            existing["last_successful_crawl"] = today
        if changed:
            existing["last_changed"] = today

    def remove_do_not_contact(self, dnc: DoNotContactList) -> int:
        doomed = [
            k
            for k, r in self.rows.items()
            if dnc.matches(
                firm_name=_norm(r.get("firm_name")),
                abn=_norm(r.get("abn")),
                urls=(_norm(r.get("website")), _norm(r.get("final_url"))),
            )
        ]
        for k in doomed:
            del self.rows[k]
        # their change history goes too
        gone = set(doomed)
        self.changes = [c for c in self.changes if c.get("firm_key") not in gone]
        return len(doomed)

    def last_crawled(self) -> dict[str, date]:
        out = {}
        for key, row in self.rows.items():
            d = _as_date(row.get("last_crawled"))
            if d:
                out[key] = d
        return out


def _safe(value):
    if isinstance(value, str):
        if contains_email(value):
            value = scrub_emails(value)
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    return value


def _write(ws, columns: list[str], rows) -> None:
    ws.append(columns)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        is_user = cell.value in USER_COLUMNS
        cell.fill = PatternFill("solid", fgColor="C65911" if is_user else "305496")
    for row in rows:
        ws.append([_safe(row.get(c, "")) for c in columns])
    for idx, col in enumerate(columns, start=1):
        letter = get_column_letter(idx)
        ws.column_dimensions[letter].width = (
            40
            if col
            in {
                "firm_name",
                "classification_notes",
                "pages_used",
                "postal_address",
                "street_address",
                "my_notes",
                "old_value",
                "new_value",
            }
            else 16
        )
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions


def sync_opt_outs(master_path: str | Path, dnc_path: str | Path) -> int:
    """Copy firms you marked as opted out in the master list to do_not_contact.csv.

    Returns how many firms were added. The master list itself is cleaned up
    (those firms removed) the next time it is saved.
    """
    master_path, dnc_path = Path(master_path), Path(dnc_path)
    if not master_path.exists():
        return 0
    master = MasterList.load(master_path)
    dnc = DoNotContactList.load(dnc_path)
    new_rows = []
    for row in master.rows.values():
        status = _norm(row.get("my_status")).lower()
        if status not in OPT_OUT_STATUSES:
            continue
        name, abn, website = _norm(row.get("firm_name")), _norm(row.get("abn")), _norm(row.get("website"))
        if dnc.matches(firm_name=name, abn=abn, urls=(website,)):
            continue
        # The website is recorded only when there is no ABN: matching is by
        # domain, and a firm on a shared platform (a Facebook page, a Wix site)
        # would otherwise block every other firm on that platform.
        new_rows.append(
            {
                "firm_name": name,
                "abn": abn,
                "website": "" if len(normalise_abn(abn)) == 11 else website,
                "reason": f"marked '{row.get('my_status')}' in master list",
                "date_added": date.today().isoformat(),
            }
        )
    if new_rows:
        needs_newline = dnc_path.stat().st_size > 0 and not dnc_path.read_bytes().endswith(b"\n")
        with dnc_path.open("a", newline="", encoding="utf-8") as fh:
            if needs_newline:
                fh.write("\n")
            writer = csv.DictWriter(fh, fieldnames=list(DNC_COLUMNS), extrasaction="ignore")
            writer.writerows(new_rows)
        logger.info(f"Added {len(new_rows)} opted-out firm(s) from the master list to {dnc_path}")
    removed = master.remove_do_not_contact(DoNotContactList.load(dnc_path))
    if removed:
        master.save()
    return len(new_rows)


def check_writable(path: str | Path) -> None:
    """Fail early if the master list is open in Excel (Windows locks open files)."""
    path = Path(path)
    if path.exists():
        try:
            with path.open("r+b"):
                pass
        except PermissionError as exc:
            raise PermissionError(f"{path} is open in another program (Excel?). Close it and run again.") from exc

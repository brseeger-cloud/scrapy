"""Writing firms_enriched.xlsx and failed_sites.csv."""

from __future__ import annotations

import csv
import logging
from datetime import datetime
from pathlib import Path

from openpyxl import Workbook
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .items import EMAIL_COLUMNS
from .privacy import contains_email, scrub_emails

logger = logging.getLogger(__name__)

_WIDE = {
    "classification_notes": 60,
    "pages_used": 60,
    "pages_failed": 50,
    "principal_names": 35,
    "practice_areas": 40,
    "postal_address": 40,
    "office_address": 40,
    "other_office_addresses": 40,
    "po_box": 30,
    "firm_name": 35,
}
_WRAP = {"classification_notes", "pages_used", "pages_failed", "other_office_addresses"}
_FILLS = {
    "Sole": "DDEBF7",
    "Small (2-4)": "E2EFDA",
    "Larger": "FFF2CC",
    "Exclude": "F8CBAD",
    "Check manually": "EDEDED",
}


def safe_cell(value, column: str = ""):
    """Cell-safe value; email addresses are removed unless *column* is an email column."""
    if isinstance(value, str):
        if column not in EMAIL_COLUMNS and contains_email(value):
            logger.warning("Removed an email-like string from an output cell")
            value = scrub_emails(value)
        return ILLEGAL_CHARACTERS_RE.sub("", value)
    return value


def _write_sheet(ws, columns: list[str], rows: list[dict]) -> None:
    ws.append(columns)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="305496")
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    for row in rows:
        ws.append([safe_cell(row.get(c, ""), c) for c in columns])
    for idx, col in enumerate(columns, start=1):
        letter = get_column_letter(idx)
        ws.column_dimensions[letter].width = _WIDE.get(col, max(12, min(len(col) + 2, 28)))
        if col in _WRAP:
            for cell in ws[letter][1:]:
                cell.alignment = Alignment(wrap_text=True, vertical="top")
        if col == "classification":
            for cell in ws[letter][1:]:
                colour = _FILLS.get(cell.value or "")
                if colour:
                    cell.fill = PatternFill("solid", fgColor=colour)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions


def write_workbook(
    path: str | Path,
    *,
    columns: list[str],
    rows: list[dict],
    failed_columns: list[str],
    failed_rows: list[dict],
    run_info: list[tuple[str, object]],
) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Firms"
    _write_sheet(ws, columns, rows)
    _write_sheet(wb.create_sheet("Failed sites"), failed_columns, failed_rows)

    info = wb.create_sheet("Run info")
    info.append(["item", "value"])
    for cell in info[1]:
        cell.font = Font(bold=True)
    # Run info holds only this project's own configuration and counts (never
    # scraped content), so it is recorded verbatim, e.g. the exact user agent.
    for key, value in run_info:
        info.append([str(key), value if isinstance(value, (int, float)) else ILLEGAL_CHARACTERS_RE.sub("", str(value))])
    info.column_dimensions["A"].width = 34
    info.column_dimensions["B"].width = 80

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        wb.save(path)
    except PermissionError:
        # Typically the file is open in Excel; don't lose the run.
        alt = path.with_name(f"{path.stem}_{datetime.now():%Y%m%d_%H%M%S}{path.suffix}")
        logger.error(f"Could not write {path} (is it open?); writing {alt} instead")
        wb.save(alt)
        path = alt
    return path


def write_failed_csv(path: str | Path, columns: list[str], rows: list[dict]) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({c: safe_cell(row.get(c, ""), c) for c in columns})
    return path

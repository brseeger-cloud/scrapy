"""Output row layout and construction."""

from __future__ import annotations

from .classify import Classification
from .extract import Analysis
from .inputs import Firm

# Column order of the "Firms" sheet in firms_enriched.xlsx
OUTPUT_COLUMNS = [
    "input_row",
    "firm_name",
    "abn",
    "entity_type",
    "state",
    "postcode",
    "website",
    "classification",
    "exclude_reason",
    "classification_notes",
    "solicitor_count",
    "count_basis",
    "principal_names",
    "practice_areas",
    "conveyancing",
    "wills_estates",
    "family",
    "personal_injury",
    "commercial",
    "criminal",
    "postal_address",
    "po_box",
    "street_address",
    "address_postcode_matches_input",
    "crawl_status",
    "final_url",
    "pages_used",
    "pages_failed",
    "source_url",
    "count_source_url",
    "address_source_url",
    "date_collected",
]

# Column order of the failed-sites log (sheet + failed_sites.csv)
FAILED_COLUMNS = ["input_row", "firm_name", "abn", "website", "failed_url", "error", "date_collected"]

_AREA_COLUMNS = {
    "Conveyancing": "conveyancing",
    "Wills & Estates": "wills_estates",
    "Family": "family",
    "Personal Injury": "personal_injury",
    "Commercial": "commercial",
    "Criminal": "criminal",
}


def build_row(
    firm: Firm,
    *,
    analysis: Analysis | None,
    classification: Classification,
    crawl_status: str,
    final_url: str,
    pages_used: list[str],
    pages_failed: list[str],
    date_collected: str,
    error: str = "",
) -> dict:
    row = dict.fromkeys(OUTPUT_COLUMNS, "")
    row.update(firm.as_dict())
    row["input_row"] = firm.row
    row["classification"] = classification.classification
    row["exclude_reason"] = classification.exclude_reason
    row["classification_notes"] = classification.notes
    row["crawl_status"] = crawl_status
    row["final_url"] = final_url
    row["pages_used"] = "\n".join(pages_used)
    row["pages_failed"] = "\n".join(pages_failed)
    row["source_url"] = final_url or firm.url or firm.website
    row["date_collected"] = date_collected
    row["_error"] = error  # used for the failed-sites log only; not a sheet column

    if analysis is not None:
        row["solicitor_count"] = analysis.solicitor_count if analysis.solicitor_count is not None else ""
        row["count_basis"] = analysis.count_basis
        row["count_source_url"] = analysis.count_source_url
        row["principal_names"] = "; ".join(analysis.principals)
        row["practice_areas"] = "; ".join(analysis.practice_areas)
        for area, col in _AREA_COLUMNS.items():
            row[col] = "Y" if area in analysis.practice_areas else "N"
        addr = analysis.address
        row["postal_address"] = addr.postal
        row["po_box"] = addr.po_box
        row["street_address"] = addr.street
        row["address_source_url"] = addr.source_url
        if addr.postcode and firm.postcode:
            row["address_postcode_matches_input"] = "Y" if addr.postcode == firm.postcode.strip().zfill(4) else "N"
    return row

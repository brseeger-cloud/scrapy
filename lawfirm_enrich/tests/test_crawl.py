"""End-to-end: run run.py against local mock sites and inspect the workbook."""

import csv
import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook

from lawfirm_enrich.privacy import contains_email

ROOT = Path(__file__).resolve().parent.parent


def test_full_run(sites, tmp_path):
    rows = [
        ("Citizen Legal", "11 111 111 111", "Individual/Sole Trader", "NSW", "2124", sites["sole"].url),
        ("Example Partners", "22 222 222 222", "Australian Private Company", "VIC", "3000", sites["partners"].url),
        ("Small & Co Lawyers", "33 333 333 333", "Family Partnership", "QLD", "4000", sites["small"].url),
        ("John Smith SC", "44 444 444 444", "Individual/Sole Trader", "NSW", "2000", sites["barrister"].url),
        ("Blocked Lawyers", "55 555 555 555", "Australian Private Company", "NSW", "2000", sites["blocked"].url),
        ("Sunrise Bakery", "66 666 666 666", "Australian Private Company", "SA", "5000", sites["bakery"].url),
        ("Quick Conveyancing", "77 777 777 777", "Australian Private Company", "NSW", "2000", sites["conveyancer"].url),
        ("Opted Out Lawyers", "88 888 888 888", "Australian Private Company", "NSW", "2000", sites["optedout"].url),
        ("Big Law Firm", "99 999 999 999", "Australian Private Company", "NSW", "2000", sites["bigsite"].url),
        ("Dead Site Lawyers", "10 101 010 101", "Australian Private Company", "NSW", "2000", "http://127.0.0.1:9/"),
        ("No Website Legal", "12 121 212 121", "Family Partnership", "SA", "5000", ""),
    ]
    firms = tmp_path / "firms.csv"
    with firms.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["firm_name", "abn", "entity_type", "state", "postcode", "website"])
        w.writerows(rows)
    dnc = tmp_path / "dnc.csv"
    dnc.write_text("firm_name,abn,website,reason,date_added\n,88888888888,,opted out,2026-01-01\n")
    out = tmp_path / "out.xlsx"
    failed = tmp_path / "failed.csv"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "run.py"),
            "--input",
            str(firms),
            "--dnc",
            str(dnc),
            "--output",
            str(out),
            "--failed-log",
            str(failed),
            "--log-dir",
            str(tmp_path / "logs"),
            "--master",
            str(tmp_path / "master.xlsx"),
            "-s",
            "DOWNLOAD_DELAY=0",
            "-s",
            "AUTOTHROTTLE_ENABLED=False",
            "-s",
            "DOWNLOAD_TIMEOUT=5",
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    log = "".join(p.read_text() for p in (tmp_path / "logs").glob("*.log"))
    assert result.returncode == 0, result.stderr + log

    # do-not-contact: never requested, not in output
    assert sites["optedout"].requests == []
    # robots.txt obeyed
    assert sites["blocked"].page_requests == []
    # page cap
    assert len(sites["bigsite"].page_requests) <= 6

    wb = load_workbook(out)
    ws = wb["Firms"]
    header = [c.value for c in ws[1]]
    data = {
        r[header.index("firm_name")]: dict(zip(header, r, strict=False))
        for r in ws.iter_rows(min_row=2, values_only=True)
    }
    assert "Opted Out Lawyers" not in data
    assert len(data) == len(rows) - 1

    for row in data.values():
        assert row["date_collected"]
        if row["crawl_status"] != "no website":
            assert row["source_url"].startswith("http://127.0.0.1")
        for v in row.values():
            assert not (isinstance(v, str) and contains_email(v)), v

    sole = data["Citizen Legal"]
    assert sole["classification"] == "Sole"
    assert sole["principal_names"] == "Jane Citizen"
    assert sole["po_box"] == "PO Box 123, Parramatta NSW 2124"
    assert sole["street_address"] == "Level 2, 45 Smith Street, Parramatta NSW 2150"
    assert sole["address_postcode_matches_input"] == "Y"
    assert sole["conveyancing"] == "Y" and sole["wills_estates"] == "Y" and sole["criminal"] == "N"
    assert "/contact" in sole["pages_used"] and "/about-us" in sole["pages_used"]
    assert "/blog" not in sole["pages_used"]
    assert sole["crawl_status"] == "ok" and sole["pages_failed"] is None  # guessed /our-team 404 is not a failure

    partners = data["Example Partners"]
    assert partners["classification"] == "Larger"
    assert partners["solicitor_count"] == 5
    assert partners["count_basis"] == "team page listing"
    assert set(partners["principal_names"].split("; ")) == {"Robert Example", "Sarah O'Neill"}
    assert "/our-people" in partners["count_source_url"]
    assert partners["po_box"] == "GPO Box 99, Melbourne VIC 3001"
    for area in ("family", "commercial", "criminal", "personal_injury"):
        assert partners[area] == "Y"
    assert "brochure" not in partners["pages_used"] and "/news" not in partners["pages_used"]

    small = data["Small & Co Lawyers"]
    assert small["classification"] == "Small (2-4)"
    assert small["solicitor_count"] == 3
    assert small["principal_names"] == "Alice Nguyen"

    assert (data["John Smith SC"]["classification"], data["John Smith SC"]["exclude_reason"]) == (
        "Exclude",
        "barrister",
    )
    assert (data["Sunrise Bakery"]["classification"], data["Sunrise Bakery"]["exclude_reason"]) == (
        "Exclude",
        "not a law firm",
    )
    assert data["Quick Conveyancing"]["exclude_reason"] == "licensed conveyancer"

    assert data["Blocked Lawyers"]["classification"] == "Check manually"
    assert data["Blocked Lawyers"]["crawl_status"] == "failed"
    assert data["Dead Site Lawyers"]["crawl_status"] == "failed"
    assert data["No Website Legal"]["crawl_status"] == "no website"

    with failed.open() as fh:
        failed_rows = {r["firm_name"]: r for r in csv.DictReader(fh)}
    assert set(failed_rows) == {"Blocked Lawyers", "Dead Site Lawyers", "No Website Legal"}
    assert failed_rows["Blocked Lawyers"]["error"] == "blocked by robots.txt"
    assert "refused" in failed_rows["Dead Site Lawyers"]["error"]
    assert wb["Failed sites"].max_row == 4

    info = {r[0]: r[1] for r in wb["Run info"].iter_rows(min_row=2, values_only=True)}
    assert info["excluded: on do-not-contact list (not crawled, not in output)"] == 1
    assert info["user agent"] == "LawAuditResearch (audit@lawaudit.com.au)"

    # master list: one row per firm (do-not-contact firm left out)
    master = load_workbook(tmp_path / "master.xlsx")["Firms"]
    mh = [c.value for c in master[1]]
    mrows = {
        r[mh.index("firm_name")]: dict(zip(mh, r, strict=False)) for r in master.iter_rows(min_row=2, values_only=True)
    }
    assert len(mrows) == len(rows) - 1 and "Opted Out Lawyers" not in mrows
    assert mrows["Example Partners"]["firm_key"] == "abn:22222222222"


def test_rerun_skips_recently_crawled_and_syncs_opt_outs(sites, tmp_path):
    firms = tmp_path / "firms.csv"
    firms.write_text(
        "firm_name,abn,entity_type,state,postcode,website\n"
        f"Small & Co Lawyers,33 333 333 333,Family Partnership,QLD,4000,{sites['small'].url}\n"
        f"Citizen Legal,11 111 111 111,Individual/Sole Trader,NSW,2124,{sites['sole'].url}\n"
    )
    dnc = tmp_path / "dnc.csv"
    dnc.write_text("firm_name,abn,website,reason,date_added\n")
    master_path = tmp_path / "master.xlsx"

    def run(*extra):
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "run.py"),
                "--input",
                str(firms),
                "--dnc",
                str(dnc),
                "--output",
                str(tmp_path / "out.xlsx"),
                "--failed-log",
                str(tmp_path / "failed.csv"),
                "--log-dir",
                str(tmp_path / "logs"),
                "--master",
                str(master_path),
                "-s",
                "DOWNLOAD_DELAY=0",
                "-s",
                "AUTOTHROTTLE_ENABLED=False",
                *extra,
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 0, result.stderr

    run()
    first = len(sites["small"].page_requests)
    assert first > 0

    # Mark one firm as opted out in the master list, as a user would in Excel
    wb = load_workbook(master_path)
    ws = wb["Firms"]
    header = [c.value for c in ws[1]]
    for r in ws.iter_rows(min_row=2):
        if r[header.index("firm_name")].value == "Citizen Legal":
            r[header.index("my_status")].value = "Opted out"
        else:
            r[header.index("my_notes")].value = "called, interested"
    wb.save(master_path)
    sole_before = len(sites["sole"].page_requests)

    run("--skip-crawled-within", "1")
    assert len(sites["small"].page_requests) == first  # crawled today already: skipped
    assert len(sites["sole"].page_requests) == sole_before  # opted out: never requested again
    assert "Citizen Legal" in dnc.read_text()

    ws = load_workbook(master_path)["Firms"]
    header = [c.value for c in ws[1]]
    remaining = [dict(zip(header, r, strict=False)) for r in ws.iter_rows(min_row=2, values_only=True)]
    assert [r["firm_name"] for r in remaining] == ["Small & Co Lawyers"]
    assert remaining[0]["my_notes"] == "called, interested"

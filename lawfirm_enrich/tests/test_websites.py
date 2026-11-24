import csv
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from lawfirm_enrich.websites import candidate_domains, name_tokens, verify

ROOT = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent


@pytest.mark.parametrize(
    "names,first,absent",
    [
        (
            ("Smith Lawyers Pty Ltd",),
            ["smithlawyers.com.au", "smith-lawyers.com.au", "smithlawyers.au"],
            "smith.com.au",
        ),
        (("Smith & Co Lawyers",), ["smithcolawyers.com.au", "smithandcolawyers.com.au", "smithco.com.au"], None),
        (("The Trustee for Citizen Legal Trust",), ["citizenlegal.com.au"], "trustee"),
    ],
)
def test_candidate_domains(names, first, absent):
    domains = candidate_domains(*names)
    assert domains[: len(first)] == first
    assert len(domains) <= 9
    if absent:
        assert not any(absent in d for d in domains)


def test_name_tokens():
    assert name_tokens("O'Brien & Co Solicitors Pty Ltd") == ["obrien"]


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Smith Lawyers | ABN 11 111 111 111", "ABN on site"),
        ("Smith Lawyers | ABN: 11-111-111-111", "ABN on site"),
        ("Call 0211111111111", ""),  # digits inside a longer number
        ("Smith Lawyers - family law in Sydney NSW 2000", "name on site"),
        ("Smith Lawyers - family law in Perth WA 6000", ""),  # same name, other state
        ("Smith Lawyers - family law experts", "name on site (location unconfirmed)"),
        ("Smith Plumbing, Sydney NSW 2000", ""),  # no legal wording
        ("This domain is for sale. smithlawyers law NSW", ""),  # parked
    ],
)
def test_verify(text, expected):
    assert verify(text, "Smith Lawyers", ["11 111 111 111"], state="NSW", postcode="2000") == expected


def test_find_websites(sites, tmp_path):
    firms = tmp_path / "firms.csv"
    rows = [
        # found by ABN in the footer (second guess is the real one)
        ["Citizen Legal", "11 111 111 111", "Individual/Sole Trader", "NSW", "2150", "", "Jane Citizen"],
        # first guess is a parked domain: rejected; found by name on a later guess
        ["Example Partners", "22 222 222 222", "Australian Private Company", "VIC", "3000", "", ""],
        # guessed domain is a bakery: rejected, not found
        ["Sunrise Lawyers", "66 666 666 666", "Australian Private Company", "SA", "5000", "", ""],
        # already has a website: untouched, not requested
        ["Small & Co Lawyers", "33 333 333 333", "Family Partnership", "QLD", "4000", "https://small.example/", ""],
        # on the do-not-contact list: never searched
        ["Opted Out Lawyers", "88 888 888 888", "Australian Private Company", "NSW", "2000", "", ""],
    ]
    with firms.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["firm_name", "abn", "entity_type", "state", "postcode", "website", "legal_name"])
        w.writerows(rows)
    dnc = tmp_path / "dnc.csv"
    dnc.write_text("firm_name,abn,website,reason,date_added\n,88 888 888 888,,,\n")
    host_map = {
        "citizen-legal.com.au": sites["sole"].url,
        "examplepartners.com.au": sites["parked"].url,
        "examplepartners.au": sites["partners"].url,
        "sunriselawyers.com.au": sites["bakery"].url,
        "optedoutlawyers.com.au": sites["optedout"].url,
    }
    env = {**os.environ, "PYTHONPATH": str(TESTS)}
    cmd = [
        sys.executable, str(ROOT / "find_websites.py"), "--input", str(firms), "--dnc", str(dnc),
        "--log-dir", str(tmp_path / "logs"), "-s", "DOWNLOAD_DELAY=0", "-s", "AUTOTHROTTLE_ENABLED=False",
        "-s", 'DOWNLOADER_MIDDLEWARES={"hostmap.HostMapMiddleware": 50}', "-s", f"TEST_HOST_MAP={json.dumps(host_map)}",
    ]  # fmt: skip
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
    assert result.returncode == 0, result.stderr
    assert "Started." in result.stdout and "3 of 3 firms done, 2 websites found" in result.stdout

    with firms.open(newline="") as fh:
        out = {r["firm_name"]: r for r in csv.DictReader(fh)}
    assert out["Citizen Legal"]["website"].startswith("http://127.0.0.1")
    assert out["Citizen Legal"]["website_found_by"] == "ABN on site"
    assert out["Example Partners"]["website_found_by"] == "name on site (location unconfirmed)"
    assert out["Sunrise Lawyers"]["website"] == "" and out["Sunrise Lawyers"]["website_found_by"] == "not found"
    assert out["Small & Co Lawyers"]["website"] == "https://small.example/"
    assert out["Small & Co Lawyers"]["website_found_by"] == ""
    assert out["Opted Out Lawyers"]["website_checked"] == ""
    assert sites["optedout"].requests == []
    assert out["Citizen Legal"]["legal_name"] == "Jane Citizen"  # other columns kept
    assert list(tmp_path.glob("firms.backup-*.csv"))

    # a second run skips firms already checked
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=env)
    assert "Firms checked:  0" in result.stdout

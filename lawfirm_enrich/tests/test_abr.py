import csv
import subprocess
import sys
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

import pytest

from lawfirm_enrich.abr import build_firm_list, display_name, is_law_name

ROOT = Path(__file__).resolve().parent.parent


def company(
    abn, name, *, status="ACT", gst="ACT", state="NSW", postcode="2000", others=(), etype="Australian Private Company"
):
    name = escape(name)
    other = "".join(
        f'<OtherEntity><NonIndividualName type="{t}"><NonIndividualNameText>{escape(n)}</NonIndividualNameText>'
        "</NonIndividualName></OtherEntity>"
        for t, n in others
    )
    return (
        f'<ABR recordLastUpdatedDate="20260101" replaced="N"><ABN status="{status}" ABNStatusFromDate="20000101">{abn}</ABN>'
        f"<EntityType><EntityTypeInd>PRV</EntityTypeInd><EntityTypeText>{etype}</EntityTypeText></EntityType>"
        f'<MainEntity><NonIndividualName type="MN"><NonIndividualNameText>{name}</NonIndividualNameText></NonIndividualName>'
        f"<BusinessAddress><AddressDetails><State>{state}</State><Postcode>{postcode}</Postcode></AddressDetails>"
        f'</BusinessAddress></MainEntity><GST status="{gst}" GSTStatusFromDate="20000701"/>{other}</ABR>'
    )


def sole_trader(abn, given, family, business_name, state="QLD", postcode="4000"):
    return (
        f'<ABR recordLastUpdatedDate="20260101" replaced="N"><ABN status="ACT" ABNStatusFromDate="20000101">{abn}</ABN>'
        "<EntityType><EntityTypeInd>IND</EntityTypeInd><EntityTypeText>Individual/Sole Trader</EntityTypeText></EntityType>"
        f'<LegalEntity><IndividualName type="LGL"><NameTitle>MS</NameTitle><GivenName>{given}</GivenName>'
        f"<FamilyName>{family}</FamilyName></IndividualName><BusinessAddress><AddressDetails><State>{state}</State>"
        f"<Postcode>{postcode}</Postcode></AddressDetails></BusinessAddress></LegalEntity>"
        f'<GST status="ACT" GSTStatusFromDate="20000701"/><OtherEntity><NonIndividualName type="BN">'
        f"<NonIndividualNameText>{business_name}</NonIndividualNameText></NonIndividualName></OtherEntity></ABR>"
    )


RECORDS = [
    company("11111111111", "SMITH LAWYERS PTY LTD", others=[("BN", "SMITH LAWYERS")]),
    # the same practice's service trust, no GST: merged into the row above
    company(
        "22222222222",
        "THE TRUSTEE FOR SMITH LAWYERS TRUST",
        gst="NON",
        etype="Discretionary Trading Trust",
        others=[("BN", "SMITH LAWYERS")],
    ),
    sole_trader("33333333333", "JANE", "CITIZEN", "CITIZEN LEGAL"),
    sole_trader("44444444444", "JOHN", "PLAIN", "PLAIN HANDYMAN"),  # not a law firm
    company("55555555555", "OLD LAW PTY LTD", status="CAN"),  # cancelled
    company("66666666666", "SMITH LEGAL SUPER FUND", etype="ATO Regulated Self-Managed Superannuation Fund"),
    company("77777777777", "MOTHER IN LAW CAFE PTY LTD"),
    company("88888888888", "QUICK CONVEYANCING PTY LTD"),
    company("99999999999", "O'BRIEN & CO SOLICITORS PTY LTD", state="VIC", postcode="3000"),
    company("10101010101", "OPTED OUT LAWYERS PTY LTD"),
    company("12121212121", "LAW SOCIETY OF EXAMPLE"),
]


@pytest.fixture
def extract(tmp_path):
    """A bulk-extract-style zip with two XML files."""
    path = tmp_path / "public_split_1_10.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for i, chunk in enumerate((RECORDS[:5], RECORDS[5:]), start=1):
            xml = '<?xml version="1.0" encoding="UTF-8"?><Transfer>' + "".join(chunk) + "</Transfer>"
            zf.writestr(f"20261120_Public{i:02d}.xml", xml)
    return path


@pytest.fixture
def dnc(tmp_path):
    p = tmp_path / "dnc.csv"
    p.write_text("firm_name,abn,website,reason,date_added\n,10 101 010 101,,,\n")
    return p


def read(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def test_build_firm_list(extract, dnc, tmp_path):
    out = tmp_path / "firms.csv"
    res = build_firm_list([extract], out, dnc)
    rows = {r["firm_name"]: r for r in read(out)}
    assert set(rows) == {"Smith Lawyers", "Citizen Legal", "O'Brien & Co Solicitors Pty Ltd"}
    assert res.records_read == len(RECORDS)
    assert res.dnc_excluded == 1

    smith = rows["Smith Lawyers"]
    assert (smith["abn"], smith["other_abns"], smith["gst_registered"]) == ("11111111111", "22222222222", "Y")
    assert smith["legal_name"] == "Smith Lawyers Pty Ltd" and smith["website"] == ""
    citizen = rows["Citizen Legal"]
    assert (citizen["entity_type"], citizen["state"], citizen["postcode"]) == ("Individual/Sole Trader", "QLD", "4000")
    assert citizen["legal_name"] == "Jane Citizen"


def test_rebuild_keeps_existing_rows_and_websites(extract, dnc, tmp_path):
    out = tmp_path / "firms.csv"
    out.write_text(
        "firm_name,abn,entity_type,state,postcode,website,my_column\n"
        "Smith Lawyers,22 222 222 222,Trust,NSW,2000,https://smith.example,keep\n"
    )
    res = build_firm_list([extract], out, dnc)
    rows = read(out)
    assert res.already_listed == 1 and res.added == 2
    assert rows[0]["website"] == "https://smith.example" and rows[0]["my_column"] == "keep"
    assert len(rows) == 3


def test_state_filter_and_conveyancers(extract, dnc, tmp_path):
    out = tmp_path / "firms.csv"
    build_firm_list([extract], out, dnc, states=["NSW"], include_conveyancers=True)
    assert {r["firm_name"] for r in read(out)} == {"Smith Lawyers", "Quick Conveyancing Pty Ltd"}


@pytest.mark.parametrize(
    "name,expected",
    [
        ("SMITH LAWYERS", True),
        ("JONES LEGAL", True),
        ("BROWN LAW", True),
        ("WEST BARRISTERS & SOLICITORS", True),
        ("LAWSON PLUMBING", False),
        ("LAWN MASTERS", False),
        ("SON IN LAW TRANSPORT", False),
        ("LEGAL AID COMMISSION", False),
        ("PARALEGAL SERVICES", False),
        ("SMITH CHAMBERS", False),
    ],
)
def test_is_law_name(name, expected):
    assert is_law_name(name) is expected


@pytest.mark.parametrize(
    "raw,shown",
    [
        ("SMITH & CO LAWYERS PTY LTD", "Smith & Co Lawyers Pty Ltd"),
        ("O'BRIEN SMITH-JONES LEGAL", "O'Brien Smith-Jones Legal"),
        ("MCDONALD LAW", "McDonald Law"),
        ("Already Mixed Case Legal", "Already Mixed Case Legal"),
    ],
)
def test_display_name(raw, shown):
    assert display_name(raw) == shown


def test_cli(extract, dnc, tmp_path):
    out = tmp_path / "firms.csv"
    result = subprocess.run(
        [sys.executable, str(ROOT / "build_firm_list.py"), str(extract), "--out", str(out), "--dnc", str(dnc)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Added:                         3" in result.stdout

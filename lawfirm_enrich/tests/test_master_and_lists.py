import csv
from datetime import date

import pytest
from openpyxl import load_workbook

from lawfirm_enrich.inputs import DoNotContactList
from lawfirm_enrich.items import OUTPUT_COLUMNS
from lawfirm_enrich.lists import EMAIL_LIST_COLUMNS, POSTAL_LIST_COLUMNS, Criteria, addressee, make_list, select
from lawfirm_enrich.master import MasterList, firm_key, sync_opt_outs

DNC_HEADER = "firm_name,abn,website,reason,date_added\n"


def crawl_row(**overrides):
    row = dict.fromkeys(OUTPUT_COLUMNS, "")
    row.update(
        firm_name="Smith Lawyers",
        abn="11 111 111 111",
        state="NSW",
        postcode="2000",
        website="smith.example",
        classification="Small (2-4)",
        solicitor_count=3,
        principal_names="Jane Smith; Bob Jones",
        postal_address="PO Box 1, Sydney NSW 2001",
        office_address="Level 2, 45 Smith Street, Sydney NSW 2000",
        conveyancing="Y",
        family="N",
        crawl_status="ok",
        email="info@smith.example",
        email_type="general",
        date_collected="2026-11-01",
    )
    row.update(overrides)
    return row


@pytest.mark.parametrize(
    "abn,website,name,key",
    [
        ("11 111 111 111", "x.example", "X", "abn:11111111111"),
        ("", "https://www.x.example/home", "X", "web:x.example"),
        ("", "", "X Lawyers Pty Ltd", "name:x lawyers"),
    ],
)
def test_firm_key(abn, website, name, key):
    assert firm_key(abn, website, name) == key


def test_upsert_keeps_user_columns_and_records_changes(tmp_path):
    path = tmp_path / "master.xlsx"
    m = MasterList.load(path)
    m.upsert(crawl_row())
    m.save()

    wb = load_workbook(path)
    ws = wb["Firms"]
    header = [c.value for c in ws[1]]
    ws.cell(row=1, column=len(header) + 1, value="my_own_column")
    ws.cell(row=2, column=header.index("my_notes") + 1, value="spoke to Jane")
    ws.cell(row=2, column=len(header) + 1, value="keep me")
    wb.save(path)

    m = MasterList.load(path)
    m.upsert(crawl_row(solicitor_count=6, classification="Larger", date_collected="2026-12-01"))
    m.save()

    m = MasterList.load(path)
    (row,) = m.rows.values()
    assert row["my_notes"] == "spoke to Jane" and row["my_own_column"] == "keep me"
    assert row["classification"] == "Larger" and row["solicitor_count"] == 6
    assert row["first_seen"] == "2026-11-01" and row["last_changed"] == "2026-12-01"
    changed = {c["field"]: (c["old_value"], c["new_value"]) for c in m.changes}
    assert changed == {"classification": ("Small (2-4)", "Larger"), "solicitor_count": ("3", "6")}


def test_failed_crawl_keeps_last_good_data(tmp_path):
    m = MasterList.load(tmp_path / "master.xlsx")
    m.upsert(crawl_row())
    m.upsert(
        crawl_row(
            crawl_status="failed",
            classification="Check manually",
            solicitor_count="",
            postal_address="",
            date_collected="2026-12-01",
        )
    )
    (row,) = m.rows.values()
    assert row["classification"] == "Small (2-4)" and row["postal_address"] == "PO Box 1, Sydney NSW 2001"
    assert row["crawl_status"] == "failed"
    assert row["last_crawled"] == "2026-12-01" and row["last_successful_crawl"] == "2026-11-01"


def test_do_not_contact_firms_are_removed(tmp_path):
    m = MasterList.load(tmp_path / "master.xlsx")
    m.upsert(crawl_row())
    m.upsert(crawl_row(firm_name="Other Law", abn="22 222 222 222", website="other.example"))
    dnc = tmp_path / "dnc.csv"
    dnc.write_text(DNC_HEADER + ",,https://other.example,,\n")
    assert m.remove_do_not_contact(DoNotContactList.load(dnc)) == 1
    assert [r["firm_name"] for r in m.rows.values()] == ["Smith Lawyers"]


def test_sync_opt_outs(tmp_path):
    path = tmp_path / "master.xlsx"
    m = MasterList.load(path)
    m.upsert(crawl_row())
    m.rows["abn:11111111111"]["my_status"] = "Opted out"
    m.save()
    dnc = tmp_path / "dnc.csv"
    dnc.write_text(DNC_HEADER.rstrip("\n"))  # no trailing newline
    assert sync_opt_outs(path, dnc) == 1
    assert sync_opt_outs(path, dnc) == 0  # not added twice
    assert DoNotContactList.load(dnc).matches(abn="11111111111")
    assert "smith.example" not in dnc.read_text()  # domain left out when there is an ABN
    assert MasterList.load(path).rows == {}


@pytest.fixture
def master_with_firms(tmp_path):
    m = MasterList.load(tmp_path / "master.xlsx")
    m.upsert(crawl_row())
    m.upsert(
        crawl_row(
            firm_name="Solo Law",
            abn="22 222 222 222",
            website="solo.example",
            classification="Sole",
            principal_names="",
            state="VIC",
            conveyancing="N",
            family="Y",
            email="sam.solo@solo.example",
            email_type="personal",
        )
    )
    m.upsert(crawl_row(firm_name="Chambers", abn="33 333 333 333", website="ch.example", classification="Exclude"))
    m.upsert(
        crawl_row(
            firm_name="No Address Law",
            abn="44 444 444 444",
            website="na.example",
            postal_address="",
            no_unsolicited_email_notice="We do not accept unsolicited emails.",
        )
    )
    m.upsert(
        crawl_row(firm_name="Unsure Law", abn="55 555 555 555", website="u.example", classification="Check manually")
    )
    m.save()
    dnc = tmp_path / "dnc.csv"
    dnc.write_text(DNC_HEADER)
    return m, dnc


@pytest.mark.parametrize(
    "criteria,expected",
    [
        (Criteria(), ["Smith Lawyers", "Solo Law"]),
        (Criteria(states=["vic"]), ["Solo Law"]),
        (Criteria(areas=["family", "criminal"]), ["Solo Law"]),
        (Criteria(sizes=["Sole"]), ["Solo Law"]),
        (Criteria(require_address=False), ["No Address Law", "Smith Lawyers", "Solo Law"]),
        (Criteria(sizes=["Check manually"]), ["Unsure Law"]),
        (Criteria(channel="email"), ["Smith Lawyers", "Solo Law"]),
        (Criteria(channel="email", general_email_only=True), ["Smith Lawyers"]),
    ],
)
def test_select(master_with_firms, criteria, expected):
    m, dnc = master_with_firms
    assert sorted(r["firm_name"] for r in select(m, DoNotContactList.load(dnc), criteria)) == expected


def read_csv(path):
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def test_postal_list_is_mail_merge_ready(master_with_firms, tmp_path):
    m, dnc = master_with_firms
    dnc.write_text(DNC_HEADER + "Solo Law,,,,\n")
    out = tmp_path / "list.csv"
    assert make_list(m.path, dnc, out, Criteria()) == 1  # Solo Law is on the do-not-contact list
    (row,) = read_csv(out)
    assert list(row) == POSTAL_LIST_COLUMNS
    assert row["addressee"] == "Jane Smith" and (row["first_name"], row["last_name"]) == ("Jane", "Smith")
    assert (row["address_line_1"], row["suburb"], row["state"], row["postcode"]) == (
        "PO Box 1",
        "Sydney",
        "NSW",
        "2001",
    )
    assert row["address_type"] == "PO Box"

    # the office address: a firm with no mailing address but an office address is now included
    assert make_list(m.path, dnc, out, Criteria(address="office")) == 2
    row = next(r for r in read_csv(out) if r["firm_name"] == "Smith Lawyers")
    assert (row["address_line_1"], row["postcode"], row["address_type"]) == (
        "Level 2, 45 Smith Street",
        "2000",
        "office",
    )


def test_email_list_is_email_service_ready(master_with_firms, tmp_path):
    m, dnc = master_with_firms
    out = tmp_path / "list.csv"
    make_list(m.path, dnc, out, Criteria(channel="email"))
    rows = {r["firm_name"]: r for r in read_csv(out)}
    assert list(rows["Smith Lawyers"]) == EMAIL_LIST_COLUMNS
    assert rows["Smith Lawyers"]["email"] == "info@smith.example"  # not scrubbed
    assert (rows["Smith Lawyers"]["first_name"], rows["Smith Lawyers"]["addressee"]) == ("Jane", "Jane Smith")
    assert (rows["Solo Law"]["first_name"], rows["Solo Law"]["addressee"]) == ("", "The Principal")


@pytest.mark.parametrize(
    "email,email_type,expected",
    [
        ("bob.jones@smith.example", "personal", "Bob Jones"),  # the person whose address it is
        ("bjones@smith.example", "personal", "Bob Jones"),
        ("info@smith.example", "general", "Jane Smith"),  # first principal
        ("kim.lee@smith.example", "personal", "Jane Smith"),  # not a principal
    ],
)
def test_addressee(email, email_type, expected):
    row = {"principal_names": "Jane Smith; Bob Jones", "email_type": email_type}
    assert addressee(row, email) == expected


def test_campaigns_tracked_per_channel(master_with_firms, tmp_path):
    m, dnc = master_with_firms
    out = tmp_path / "list.csv"
    sent = make_list(m.path, dnc, out, Criteria(), mark_contacted=True, campaign="Dec letter", today=date(2026, 12, 1))
    assert sent == 2
    later = date(2026, 12, 15)
    # posted recently, so the next postal list leaves them out ...
    assert make_list(m.path, dnc, out, Criteria(not_contacted_days=90), today=later) == 0
    assert make_list(m.path, dnc, out, Criteria(not_contacted_days=10), today=later) == 2
    # ... but the email campaign still goes to them
    email = Criteria(channel="email", not_contacted_days=90)
    assert make_list(m.path, dnc, out, email, mark_contacted=True, campaign="Dec email", today=later) == 2

    master = MasterList.load(m.path)
    smith = master.rows["abn:11111111111"]
    assert (smith["last_mailed"], smith["last_emailed"], smith["last_campaign"]) == (
        "2026-12-01",
        "2026-12-15",
        "Dec email",
    )
    log = [(c["campaign"], c["channel"], c["sent_to"]) for c in master.campaigns if c["firm_name"] == "Smith Lawyers"]
    assert log == [("Dec letter", "post", "PO Box 1, Sydney NSW 2001"), ("Dec email", "email", "info@smith.example")]


def test_manual_last_contacted_blocks_every_channel(master_with_firms, tmp_path):
    m, dnc = master_with_firms
    master = MasterList.load(m.path)
    for row in master.rows.values():
        row["last_contacted"] = "2026-11-30"
    master.save()
    for channel in ("post", "email"):
        criteria = Criteria(channel=channel, not_contacted_days=30)
        assert make_list(m.path, dnc, tmp_path / "l.csv", criteria, today=date(2026, 12, 1)) == 0

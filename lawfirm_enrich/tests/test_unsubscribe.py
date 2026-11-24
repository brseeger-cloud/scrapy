import csv

from lawfirm_enrich.inputs import DoNotContactList
from lawfirm_enrich.items import OUTPUT_COLUMNS
from lawfirm_enrich.lists import Criteria, make_list
from lawfirm_enrich.master import MasterList
from lawfirm_enrich.unsubscribe import load_unsubscribed, process_unsubscribes, read_addresses, strip_unsubscribed

DNC_HEADER = "firm_name,abn,website,reason,date_added\n"


def firm(name, abn, email, other=""):
    row = dict.fromkeys(OUTPUT_COLUMNS, "")
    row.update(
        firm_name=name,
        abn=abn,
        website=f"{name.split()[0].lower()}.example",
        classification="Sole",
        postal_address="PO Box 1, Sydney NSW 2001",
        state="NSW",
        email=email,
        other_emails=other,
        email_type="general",
        crawl_status="ok",
        date_collected="2026-11-01",
    )
    return row


def test_read_addresses_from_service_export_and_typed(tmp_path):
    export = tmp_path / "unsubscribes.csv"
    export.write_text('"Email Address","Unsubscribed At"\n"Info@Smith.example","2026-11-20"\njane@jones.example,x\n')
    assert read_addresses([str(export), "bob@brown.example", "info@smith.example"]) == [
        "info@smith.example", "jane@jones.example", "bob@brown.example",
    ]  # fmt: skip


def test_strip_unsubscribed_promotes_next_address():
    row = {"email": "info@smith.example", "other_emails": "jane@smith.example; bob@smith.example"}
    assert strip_unsubscribed(row, {"info@smith.example", "bob@smith.example"})
    assert row == {"email": "jane@smith.example", "email_type": "personal", "other_emails": ""}
    assert not strip_unsubscribed(row, {"nobody@x.example"})


def _master(tmp_path):
    m = MasterList.load(tmp_path / "master.xlsx")
    m.upsert(firm("Smith Law", "11 111 111 111", "info@smith.example", "jane@smith.example"))
    m.upsert(firm("Jones Law", "22 222 222 222", "info@jones.example"))
    m.save()
    dnc = tmp_path / "dnc.csv"
    dnc.write_text(DNC_HEADER)
    return m.path, dnc


def test_unsubscribe_address_only(tmp_path):
    master_path, dnc = _master(tmp_path)
    unsub = tmp_path / "unsubscribed.csv"
    res = process_unsubscribes(["info@smith.example"], unsub, master_path, dnc, source_label="manual")
    assert (res.newly_added, res.found_in_master, res.firms_added_to_dnc) == (1, 1, [])
    rows = {r["firm_name"]: r for r in MasterList.load(master_path).rows.values()}
    assert rows["Smith Law"]["email"] == "jane@smith.example"  # firm kept, next address used
    assert load_unsubscribed(unsub) == {"info@smith.example"}
    # recorded once only
    assert process_unsubscribes(["info@smith.example"], unsub, master_path, dnc).newly_added == 0
    with unsub.open() as fh:
        assert [r["source"] for r in csv.DictReader(fh)] == ["manual"]


def test_unsubscribe_whole_firm(tmp_path):
    master_path, dnc = _master(tmp_path)
    res = process_unsubscribes(["info@jones.example"], tmp_path / "u.csv", master_path, dnc, whole_firm=True)
    assert res.firms_added_to_dnc == ["Jones Law"]
    assert [r["firm_name"] for r in MasterList.load(master_path).rows.values()] == ["Smith Law"]
    assert DoNotContactList.load(dnc).matches(abn="22222222222")


def test_lists_never_include_unsubscribed_addresses(tmp_path):
    master_path, dnc = _master(tmp_path)
    unsub = tmp_path / "unsubscribed.csv"
    unsub.write_text("email,date_added,source\ninfo@smith.example,2026-11-20,x\ninfo@jones.example,2026-11-20,x\n")
    out = tmp_path / "list.csv"
    n = make_list(master_path, dnc, out, Criteria(channel="email"), unsubscribed_path=unsub)
    text = out.read_text(encoding="utf-8-sig")
    assert n == 1 and "jane@smith.example" in text
    assert "info@smith.example" not in text and "Jones Law" not in text

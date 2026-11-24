import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from lawfirm_enrich.items import OUTPUT_COLUMNS
from lawfirm_enrich.master import MasterList
from lawfirm_enrich.status import status_report

ROOT = Path(__file__).resolve().parent.parent
FIRMS_HEADER = "firm_name,abn,entity_type,state,postcode,website,website_found_by\n"


def lawaudit(*args, cwd):
    return subprocess.run([sys.executable, str(ROOT / "lawaudit.py"), *args], capture_output=True, text=True,
                          timeout=120, cwd=cwd)  # fmt: skip


def row(name, abn, **kw):
    r = dict.fromkeys(OUTPUT_COLUMNS, "")
    r.update(firm_name=name, abn=abn, classification="Sole", postal_address="PO Box 1, Sydney NSW 2001",
             crawl_status="ok", date_collected="2026-11-01")  # fmt: skip
    r.update(kw)
    return r


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / "do_not_contact.csv").write_text("firm_name,abn,website,reason,date_added\n")
    (tmp_path / "firms.csv").write_text(
        FIRMS_HEADER + "Smith Law,11 111 111 111,Co,NSW,2000,https://smith.example/,ABN on site\n"
        "Jones Law,22 222 222 222,Co,NSW,2000,https://jones.example/,name on site\n"
        "Lost Law,33 333 333 333,Co,NSW,2000,,not found\n"
    )
    m = MasterList.load(tmp_path / "data" / "master.xlsx")
    m.upsert(row("Smith Law", "11 111 111 111", email="info@smith.example", email_type="general"))
    m.upsert(row("Jones Law", "22 222 222 222", classification="Larger", date_collected="2026-07-01",
                 email="amy@jones.example", email_type="personal", no_unsolicited_email_notice="No unsolicited"))  # fmt: skip
    m.save()
    return tmp_path


def test_status_report(workspace):
    report = status_report(workspace / "firms.csv", workspace / "data" / "master.xlsx",
                           workspace / "do_not_contact.csv", workspace / "unsubscribed.csv", today=date(2026, 11, 24))  # fmt: skip
    assert "3 firms; 2 with a website; 1 searched, none found; 0 not yet searched" in report
    assert "Sole 1 | Larger 1" in report
    assert "with an email address: 2 (general 1, personal 1); site refuses unsolicited email: 1" in report
    assert "due for a refresh (over 90 days): 1" in report
    assert "with a mailing address: 2 (of which PO Box 0); with an office address: 0" in report
    assert "campaigns recorded: 0" in report
    assert "Next step: refresh older firms" in report


@pytest.mark.parametrize(
    "firms,next_step",
    [
        (FIRMS_HEADER, "build the firm list"),
        (FIRMS_HEADER + "New Law,44 444 444 444,Co,NSW,2000,,\n", "find websites"),
    ],
)
def test_status_next_step(tmp_path, firms, next_step):
    (tmp_path / "firms.csv").write_text(firms)
    report = status_report(tmp_path / "firms.csv", tmp_path / "m.xlsx", tmp_path / "dnc.csv", tmp_path / "u.csv")
    assert f"Next step: {next_step}" in report
    assert "Master list (" in report and "not created yet" in report


def test_cli_status_and_help(workspace):
    result = lawaudit("status", cwd=workspace)
    assert result.returncode == 0 and "Master list (data/master.xlsx): 2 firms" in result.stdout
    assert "build-list" in lawaudit("--help", cwd=workspace).stdout
    help_text = lawaudit("make-list", "--help", cwd=workspace).stdout
    assert help_text.startswith("usage: lawaudit.py make-list")
    assert lawaudit("nonsense", cwd=workspace).returncode == 2


def test_cli_unsubscribe(workspace):
    export = workspace / "export.csv"
    export.write_text("Email Address,Date\nINFO@smith.example,2026-11-20\n")
    result = lawaudit("unsubscribe", str(export), cwd=workspace)
    assert result.returncode == 0, result.stderr
    assert "Removed from the master list:   1" in result.stdout
    assert "info@smith.example" in (workspace / "unsubscribed.csv").read_text()

    result = lawaudit("unsubscribe", "amy@jones.example", "--whole-firm", cwd=workspace)
    assert "Firms put on do-not-contact:    Jones Law" in result.stdout
    assert lawaudit("unsubscribe", "no addresses here", cwd=workspace).returncode == 1


def test_cli_campaigns(workspace):
    result = lawaudit("make-list", "--mark-contacted", "--campaign", "Mail Dec", cwd=workspace)
    assert result.returncode == 0, result.stderr
    assert "Wrote 2 firms to output/mailing_list.csv" in result.stdout
    header = (workspace / "output" / "mailing_list.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert header.startswith("firm_name,addressee,first_name,last_name,address_line_1,suburb,state,postcode")

    # Jones's site refuses unsolicited email, so only Smith gets the email campaign
    result = lawaudit("make-list", "--channel", "email", "--not-contacted-days", "30", "--mark-contacted",
                      "--campaign", "Email Dec", cwd=workspace)  # fmt: skip
    assert "Wrote 1 firms to output/email_list.csv" in result.stdout
    assert "info@smith.example" in (workspace / "output" / "email_list.csv").read_text(encoding="utf-8-sig")
    assert "campaigns recorded: 2 (latest: Email Dec, email)" in lawaudit("status", cwd=workspace).stdout


def test_default_dnc_file_created_but_typed_path_required(tmp_path):
    (tmp_path / "firms.csv").write_text(FIRMS_HEADER)
    result = lawaudit("unsubscribe", "a@b.example", cwd=tmp_path)
    assert result.returncode == 0 and "Created an empty do_not_contact.csv" in result.stdout
    assert (tmp_path / "do_not_contact.csv").read_text().startswith("firm_name,abn,website")
    result = lawaudit("unsubscribe", "a@b.example", "--dnc", "typo.csv", cwd=tmp_path)
    assert result.returncode == 2 and not (tmp_path / "typo.csv").exists()

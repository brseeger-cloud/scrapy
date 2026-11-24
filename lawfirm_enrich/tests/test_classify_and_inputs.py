import pytest

from lawfirm_enrich.classify import CHECK, EXCLUDE, LARGER, SMALL, SOLE, classify
from lawfirm_enrich.extract import Analysis, Signal
from lawfirm_enrich.inputs import DoNotContactList, normalise_url, read_firms


@pytest.mark.parametrize(
    "count,basis,expected",
    [
        (1, "team page listing", SOLE),
        (2, "team page listing", SMALL),
        (4, "about/home page listing", SMALL),
        (5, "team page listing", LARGER),
        (12, "stated on site", LARGER),
        (2, "principal mentions only", CHECK),
        (None, "not found", CHECK),
    ],
)
def test_size_buckets(count, basis, expected):
    assert classify(Analysis(solicitor_count=count, count_basis=basis)).classification == expected


def test_strong_signal_excludes():
    a = Analysis(
        solicitor_count=3, count_basis="team page listing", signals=[Signal("government", "strong", "gov domain")]
    )
    c = classify(a)
    assert (c.classification, c.exclude_reason) == (EXCLUDE, "government")


def test_weak_signal_needs_manual_check():
    a = Analysis(solicitor_count=3, count_basis="team page listing", signals=[Signal("in-house", "weak", "text")])
    assert classify(a).classification == CHECK


def test_listing_conflicting_with_stated_count():
    a = Analysis(solicitor_count=2, count_basis="team page listing", stated_count=20)
    assert classify(a).classification == CHECK


def test_failed_crawl_is_check_manually():
    c = classify(None, crawl_error="DNS lookup failed")
    assert c.classification == CHECK and "DNS" in c.notes


@pytest.mark.parametrize(
    "website,url",
    [
        ("www.Smith.example", "https://www.smith.example/"),
        ("http://smith.example/home", "http://smith.example/home"),
        ("", ""),
        ("n/a", ""),
        ("not a website", ""),
    ],
)
def test_normalise_url(website, url):
    assert normalise_url(website)[0] == url


def test_dnc_matching(tmp_path):
    p = tmp_path / "dnc.csv"
    p.write_text(
        "firm_name,abn,website,reason,date_added\n"
        "Opted Out Lawyers Pty Ltd,,,,\n,12 345 678 901,,,\n,,https://www.blocked.example/x,,\n"
    )
    dnc = DoNotContactList.load(p)
    assert dnc.matches(firm_name="opted out lawyers")
    assert dnc.matches(abn="12345678901")
    assert dnc.matches(urls=("blocked.example",))
    assert dnc.matches(urls=("https://sub.blocked.example/",))
    assert not dnc.matches(firm_name="Other Lawyers", abn="999", urls=("notblocked.example",))


def test_dnc_file_is_required(tmp_path):
    with pytest.raises(FileNotFoundError):
        DoNotContactList.load(tmp_path / "missing.csv")


def test_read_firms_requires_columns(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text("firm_name,website\nA,a.example\n")
    with pytest.raises(ValueError, match="abn"):
        read_firms(p)


def test_read_firms_ignores_extra_columns(tmp_path):
    p = tmp_path / "f.csv"
    p.write_text(
        "﻿firm_name,abn,entity_type,state,postcode,website,email\n"
        "A Law,1,Company,NSW,2000,a.example,someone@a.example\n\n"
    )
    (firm,) = read_firms(p)
    assert "someone" not in repr(firm.as_dict())

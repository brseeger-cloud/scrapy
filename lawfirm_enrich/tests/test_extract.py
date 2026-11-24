import pytest

from lawfirm_enrich.extract import (
    Page,
    analyse,
    classify_role,
    clean_name,
    extract_address,
    extract_people,
    extract_practice_areas,
    extract_stated_count,
    html_to_lines,
)
from lawfirm_enrich.privacy import contains_email, scrub_emails


def page(html, category="team", url="https://firm.example/team"):
    return Page(url=url, category=category, lines=html_to_lines(html))


@pytest.mark.parametrize(
    "text",
    [
        "jane@firm.example.com.au",
        "Email: jane.smith+law@firm.example",
        "jane [at] firm [dot] com [dot] au",
        "jane(at)firm(dot)example",
        "mailto:jane%40firm.example",
    ],
)
def test_emails_are_scrubbed(text):
    assert contains_email(text)
    assert not contains_email(scrub_emails(text))


def test_html_to_lines_drops_scripts_and_mailto():
    lines = html_to_lines(
        '<html><head><script>x="a@b.example"</script></head><body><p>Hi</p>'
        '<a href="mailto:a@b.example">Email Jane</a><p>Call us</p></body></html>'
    )
    assert lines == ["Hi", "Call us"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Jane Smith", "Jane Smith"),
        ("Mr Tom McDonald LLB (Hons)", "Tom McDonald"),
        ("SARAH O'NEILL", "Sarah O'Neill"),
        ("Liam van der Berg", "Liam van der Berg"),
        ("Jane A. Smith", "Jane A. Smith"),
        ("Our People", None),
        ("Family Law", None),
        ("Read More", None),
        ("Contact Us Today", None),
        ("Smith Lawyers", None),
        ("Parramatta NSW", None),
        ("jane@firm.example", None),
    ],
)
def test_clean_name(raw, expected):
    assert clean_name(raw) == expected


@pytest.mark.parametrize(
    "role,lawyer,principal",
    [
        ("Principal Solicitor", True, True),
        ("Managing Partner", True, True),
        ("Legal Practitioner Director", True, True),
        ("Senior Associate", True, False),
        ("Solicitor", True, False),
        ("Special Counsel", True, False),
        ("Paralegal", False, False),
        ("Legal Assistant", False, False),
        ("Practice Manager", False, False),
        ("Licensed Conveyancer", False, False),
        ("Principal Conveyancer", False, False),
        ("Director of Marketing", False, False),
        ("Solicitor and Practice Manager", True, False),
    ],
)
def test_classify_role(role, lawyer, principal):
    assert classify_role(role) == (lawyer, principal)


def test_people_role_after_name():
    p = page(
        "<h3>Jane Smith</h3><p>Principal</p><h3>John Lee</h3><p>Solicitor</p>"
        "<h3>Amy Wu</h3><p>Paralegal</p>"
    )
    people = {x.name: x for x in extract_people(p)}
    assert set(people) == {"Jane Smith", "John Lee", "Amy Wu"}
    assert people["Jane Smith"].is_principal
    assert people["John Lee"].is_lawyer and not people["John Lee"].is_principal
    assert not people["Amy Wu"].is_lawyer


def test_people_role_before_name():
    p = page("<p>Principal Solicitor</p><h4>Alice Nguyen</h4><p>Solicitor</p><h4>Ben Carter</h4>")
    people = {x.name: x for x in extract_people(p)}
    assert people["Alice Nguyen"].is_principal
    assert people["Ben Carter"].is_lawyer and not people["Ben Carter"].is_principal


def test_people_inline_role_and_section_headings():
    p = page(
        "<h2>Our Partners</h2><p>Jane Smith</p><p>Bob Jones</p>"
        "<h2>Support Staff</h2><p>Kim Lee</p>"
        "<p>Ann Brown – Senior Associate</p>"
    )
    people = {x.name: x for x in extract_people(p)}
    assert people["Jane Smith"].is_lawyer and people["Bob Jones"].is_principal
    assert not people["Kim Lee"].is_lawyer
    assert people["Ann Brown"].is_lawyer


def test_names_without_roles_are_not_counted():
    p = page("<p>Jane Smith</p><p>Great service, highly recommend!</p>")
    assert extract_people(p) == []


def test_practice_areas():
    text = (
        "We help with buying or selling a home, wills, probate, divorce and parenting orders, "
        "workers compensation, shareholder agreements and drink driving charges."
    )
    assert extract_practice_areas(text) == [
        "Conveyancing", "Wills & Estates", "Family", "Personal Injury", "Commercial", "Criminal",
    ]


def test_will_as_a_verb_is_not_wills():
    assert extract_practice_areas("We will call you back.") == []


@pytest.mark.parametrize(
    "text,count",
    [
        ("Our team of 12 experienced lawyers", 12),
        ("a team of five solicitors", 5),
        ("Call 1300 LAWYERS", None),
    ],
)
def test_stated_count(text, count):
    assert extract_stated_count(text) == count


def test_address_prefers_contact_page_and_finds_po_box():
    pages = [
        page("<p>Visit us at 1 Other Road, Penrith NSW 2750</p>", "home", "https://f.example/"),
        page("<address>Level 2, 45 Smith Street<br>Parramatta NSW 2150</address>"
             "<p>Postal address: PO Box 123, Parramatta NSW 2124</p>", "contact", "https://f.example/contact"),
    ]
    addr = extract_address(pages)
    assert addr.street == "Level 2, 45 Smith Street, Parramatta NSW 2150"
    assert addr.po_box == "PO Box 123, Parramatta NSW 2124"
    assert addr.postal == "PO Box 123, Parramatta NSW 2124"
    assert addr.postcode == "2124"
    assert addr.source_url == "https://f.example/contact"


def test_analyse_counts_and_principals():
    pages = [
        page("<p>Founded by Robert Example in 1985.</p>", "about", "https://f.example/about"),
        page("<h3>Robert Example</h3><p>Managing Partner</p><h3>Priya Sharma</h3><p>Solicitor</p>"
             "<h3>Emma Jones</h3><p>Paralegal</p>"),
    ]
    a = analyse("Example Partners", "Australian Private Company", "f.example", pages)
    assert a.solicitor_count == 2
    assert a.count_basis == "team page listing"
    assert a.principals == ["Robert Example"]


@pytest.mark.parametrize(
    "firm_name,text,reason",
    [
        ("John Smith SC", "Barrister-at-Law", "barrister"),
        ("Level 5 Chambers", "Commercial law", "barrister"),
        ("Legal Aid NSW", "Free legal help", "government"),
        ("Quick Conveyancing", "Our licensed conveyancer can help", "licensed conveyancer"),
        ("Sunrise Bakery", "Fresh bread", "not a law firm"),
        ("Acme Ltd In-house Legal", "legal", "in-house"),
    ],
)
def test_exclusion_signals(firm_name, text, reason):
    a = analyse(firm_name, "", "x.example", [page(f"<p>{text}</p>", "home")])
    assert reason in [s.reason for s in a.signals if s.strength == "strong"]


@pytest.mark.parametrize(
    "firm_name,text",
    [
        ("Smith & Co Barristers & Solicitors", "Family law and conveyancing solicitors"),
        ("Jones Lawyers", "Jane is admitted as a barrister and solicitor. We brief barristers."),
    ],
)
def test_barrister_and_solicitor_firms_are_not_excluded(firm_name, text):
    a = analyse(firm_name, "", "x.example", [page(f"<p>{text}</p>", "home")])
    assert not [s for s in a.signals if s.strength == "strong"]

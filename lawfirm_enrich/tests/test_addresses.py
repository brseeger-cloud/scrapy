import pytest
from parsel import Selector

from lawfirm_enrich.addresses import ParsedAddress, choose_addresses, find_in_text, find_structured, split_address
from lawfirm_enrich.extract import Page, html_to_lines


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Level 2, 45 Smith Street, Parramatta NSW 2150", "Level 2, 45 Smith Street, Parramatta NSW 2150"),
        ("Suite 3, Level 10, 1 Martin Place Sydney NSW 2000", "Suite 3, Level 10, 1 Martin Place, Sydney NSW 2000"),
        ("2/45 Smith St, Parramatta, NSW 2150", "2/45 Smith St, Parramatta NSW 2150"),
        ("Shop 4, 12-14 Main Road, Penrith New South Wales 2750", "Shop 4, 12-14 Main Road, Penrith NSW 2750"),
        ("88 George street Sydney NSW 2000", "88 George street, Sydney NSW 2000"),
        ("LEVEL 5, 100 QUEEN STREET, BRISBANE QLD 4000", "LEVEL 5, 100 QUEEN STREET, Brisbane QLD 4000"),
        (
            "Visit us: 7 Beach Pde, Surfers Paradise Qld 4217. Parking at rear.",
            "7 Beach Pde, Surfers Paradise QLD 4217",
        ),
        ("45 Smith Street, Parramatta, NSW 2150", "45 Smith Street, Parramatta NSW 2150"),  # lines joined
    ],
)
def test_office_addresses_in_text(text, expected):
    boxes, streets, _ = find_in_text(text)
    assert [str(a) for a in streets] == [expected] and boxes == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("PO Box 123, Parramatta NSW 2124", "PO Box 123, Parramatta NSW 2124"),
        ("Locked Bag 5 Sydney NSW 2001", "Locked Bag 5, Sydney NSW 2001"),
        ("GPO Box 99, Melbourne VIC 3001", "GPO Box 99, Melbourne VIC 3001"),
        ("P.O. Box 7, Hobart Tas 7001", "P.O. Box 7, Hobart TAS 7001"),
    ],
)
def test_po_boxes_in_text(text, expected):
    boxes, streets, _ = find_in_text(text)
    assert [str(a) for a in boxes] == [expected] and streets == []


@pytest.mark.parametrize(
    "text",
    ["DX 1234 Sydney", "Phone 02 9999 0000, fax 02 9999 0001", "Over 30 years serving Parramatta NSW clients"],
)
def test_not_addresses(text):
    assert find_in_text(text) == ([], [], [])


def test_labelled_postal_address():
    _, _, labelled = find_in_text("Office: 1 Main St, Ryde NSW 2112. Postal address: 9 Other Rd, Ryde NSW 2112")
    assert [str(a) for a in labelled] == ["9 Other Rd, Ryde NSW 2112"]


def test_structured_json_ld_and_microdata():
    html = """<html><head><script type="application/ld+json">
    {"@context": "https://schema.org", "@graph": [{"@type": "LegalService", "name": "Smith Lawyers",
      "address": {"@type": "PostalAddress", "streetAddress": "Level 3\\n50 Pitt Street",
                  "addressLocality": "Sydney", "addressRegion": "New South Wales", "postalCode": "2000",
                  "addressCountry": "AU"}}]}
    </script><script type="application/ld+json">{ not valid json </script></head><body>
    <div itemscope itemtype="https://schema.org/PostalAddress"><span itemprop="postOfficeBoxNumber">77</span>
      <span itemprop="addressLocality">Sydney</span> <span itemprop="addressRegion">NSW</span>
      <span itemprop="postalCode">2001</span></div>
    <script type="application/ld+json">{"@type": "PostalAddress", "streetAddress": "1 Queen St",
      "addressLocality": "Auckland", "postalCode": "1010", "addressCountry": "NZ"}</script>
    </body></html>"""
    found = find_structured(Selector(text=html).root)
    assert [str(a) for a in found] == ["Level 3, 50 Pitt Street, Sydney NSW 2000", "PO Box 77, Sydney NSW 2001"]


def page(html, category, url="https://f.example/"):
    root = Selector(text=html).root
    return Page(url=url, category=category, lines=html_to_lines(root=root), structured_addresses=find_structured(root))


def test_choose_addresses():
    pages = [
        page("<p>Head office: Level 2, 45 Smith Street, Parramatta NSW 2150</p>", "home"),
        page(
            "<h2>Our offices</h2><p>45 Smith St<br>Parramatta NSW 2150</p><p>3 King St<br>Penrith NSW 2750</p>"
            "<p>Postal: PO Box 123, Parramatta NSW 2124</p>",
            "contact",
            "https://f.example/contact",
        ),
    ]
    a = choose_addresses(pages)
    assert str(a.office) == "45 Smith St, Parramatta NSW 2150"  # contact page first; same office not repeated
    assert [str(o) for o in a.other_offices] == ["3 King St, Penrith NSW 2750"]
    assert str(a.po_box) == str(a.postal) == "PO Box 123, Parramatta NSW 2124"
    assert a.source_url == "https://f.example/contact"


def test_structured_data_preferred():
    html = (
        '<script type="application/ld+json">{"@type": "Attorney", "address": {"@type": "PostalAddress", '
        '"streetAddress": "45 Smith Street", "addressLocality": "Parramatta", "addressRegion": "NSW", '
        '"postalCode": "2150"}}</script><p>Find us at Level 2, 45 Smith St, Parramatta NSW 2150</p>'
    )
    a = choose_addresses([page(html, "home")])
    assert str(a.office) == str(a.postal) == "45 Smith Street, Parramatta NSW 2150"
    assert a.other_offices == []


@pytest.mark.parametrize(
    "text,parts",
    [
        ("Level 2, 45 Smith Street, Parramatta NSW 2150", ("Level 2, 45 Smith Street", "Parramatta", "NSW", "2150")),
        ("PO Box 123, North Sydney NSW 2059", ("PO Box 123", "North Sydney", "NSW", "2059")),
        ("not an address", None),
    ],
)
def test_split_address(text, parts):
    a = split_address(text)
    assert (a.line, a.suburb, a.state, a.postcode) == parts if parts else a is None


def test_parsed_address_is_po_box():
    assert ParsedAddress("Locked Bag 5", "Sydney", "NSW", "2001").is_po_box
    assert not ParsedAddress("5 Box Hill Rd", "Box Hill", "VIC", "3128").is_po_box

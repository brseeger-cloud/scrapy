import pytest
from parsel import Selector

from lawfirm_enrich.emails import email_type, extract_emails, find_no_unsolicited_notice

SITE = {"smithlaw.example"}


def emails(html, hosts=SITE):
    return extract_emails(Selector(text=html).root, hosts)


def test_mailto_and_text_addresses_on_own_domain():
    html = (
        '<a href="mailto:Info@SmithLaw.example?subject=Hi">Email us</a>'
        "<p>Jane: jane.smith@smithlaw.example.</p><p>Again info@smithlaw.example</p>"
    )
    assert emails(html) == ["info@smithlaw.example", "jane.smith@smithlaw.example"]


@pytest.mark.parametrize(
    "html",
    [
        "<p>hello@webdesigner.example</p>",  # third party
        "<p>jane [at] smithlaw [dot] example</p>",  # obfuscated: never decoded
        '<a href="/cdn-cgi/l/email-protection#abc">[email&#160;protected]</a>',  # Cloudflare-protected
        "<p>careers@smithlaw.example privacy@smithlaw.example noreply@smithlaw.example</p>",  # not for enquiries
        '<img src="logo@2x.png"><p>logo@2x.png</p>',
        "<script>var a='hidden@smithlaw.example'</script>",
    ],
)
def test_addresses_not_collected(html):
    assert emails(html) == []


def test_webmail_and_subdomains_allowed():
    html = "<p>smithlaw@bigpond.com, reception@mail.smithlaw.example</p>"
    assert emails(html, {"www.smithlaw.example"}) == ["smithlaw@bigpond.com", "reception@mail.smithlaw.example"]


@pytest.mark.parametrize(
    "address,kind",
    [
        ("info@firm.example", "general"),
        ("enquiries@firm.example", "general"),
        ("smithlaw@bigpond.com", "general"),
        ("jane.smith@firm.example", "personal"),
        ("jsmith@firm.example", "personal"),
    ],
)
def test_email_type(address, kind):
    assert email_type(address) == kind


@pytest.mark.parametrize(
    "text,found",
    [
        ("We do not accept unsolicited commercial emails.", True),
        ("No unsolicited marketing please.", True),
        ("Publication of this address is not to be taken as consent to receive marketing.", True),
        ("Listing our email does not constitute consent to commercial messages.", True),
        ("Publication of our email address should not be deemed as consent to unsolicited messages.", True),
        ("We will not share your details.", False),
    ],
)
def test_no_unsolicited_notice(text, found):
    assert bool(find_no_unsolicited_notice(["Contact us", text])) is found

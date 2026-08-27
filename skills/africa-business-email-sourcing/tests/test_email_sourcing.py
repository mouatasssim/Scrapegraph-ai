import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "email_sourcing.py"
spec = importlib.util.spec_from_file_location("email_sourcing", MODULE_PATH)
mod = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(mod)


def test_extracts_observed_mailto_without_generation():
    crawler = mod.PublicEmailCrawler(
        mod.Target("ACME", "https://acme.example", "A"),
        verify_mx=False,
    )
    raw = """
    <html>
      <head><title>Contact</title></head>
      <body>
        <a href="mailto:communication@acme.example">Communication</a>
        <p>Direction de la communication: communication@acme.example</p>
      </body>
    </html>
    """
    items, _ = crawler._extract_from_html("https://acme.example/contact", raw)
    assert [x.email for x in items] == ["communication@acme.example"]
    assert items[0].role_label == "communication"


def test_never_accepts_unobserved_address():
    crawler = mod.PublicEmailCrawler(
        mod.Target("ACME", "https://acme.example", "A"),
        verify_mx=False,
    )
    item = crawler._build_evidence(
        "firstname.lastname@acme.example",
        source_url="https://acme.example/team",
        source_type="html_text",
        source_title="Team",
        text_for_context="Firstname Lastname - Director",
    )
    assert item is None


def test_role_mailbox_prioritized():
    assert (
        mod.role_label_for(
            "presse@example.com",
            "https://example.com/espace-presse",
            "Contact presse",
        )
        == "press_media"
    )


def test_normalizes_domains():
    assert mod.registrable_domain("https://www.example.co.uk/contact") == "example.co.uk"

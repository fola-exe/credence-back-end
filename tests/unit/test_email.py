from app.integrations.email.render import render_email, substitute
from app.integrations.email.templates import TEMPLATES, get_template


def test_substitute_escapes_html():
    assert substitute("<p>{{name}}</p>", {"name": "<b>&"}) == "<p>&lt;b&gt;&amp;</p>"


def test_subject_newlines_are_removed():
    assert substitute("Hi {{name}}", {"name": "A\nB"}, subject=True) == "Hi AB"


def test_all_templates_have_subject_and_body():
    assert len(TEMPLATES) == 8

    for key in TEMPLATES:
        template = get_template(key)
        assert template["subject"]
        assert template["body"]


def test_render_email_returns_subject_and_html():
    subject, body = render_email(
        TEMPLATES["new_credit"],
        {
            "business_name": "Acme",
            "debtor_name": "Debt",
            "reference": "CRD-000001",
            "transaction_amount": "₦1,000.00",
            "description": "Goods",
            "due_date": "Wed 18 Nov 2026",
            "payment_link": "https://example.test/pay",
        },
    )

    assert subject.startswith("New credit record from Acme")
    assert "₦1,000.00" in body

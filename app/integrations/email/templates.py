TEMPLATES: dict[str, dict[str, str]] = {
    "new_credit": {
        "subject": "New credit record from {{business_name}} · {{reference}}",
        "body": (
            "<p>Hello {{debtor_name}},</p>"
            "<p>{{business_name}} has recorded a credit of {{transaction_amount}} "
            "for {{description}} ({{reference}}).</p>"
            "<p>Due date: {{due_date}}.</p>"
            "<p>You can view the invoice and pay here: "
            '<a href="{{payment_link}}">{{payment_link}}</a></p>'
        ),
    },
    "upcoming": {
        "subject": "Upcoming payment · {{reference}}",
        "body": (
            "<p>Hello {{debtor_name}},</p>"
            "<p>A payment of {{outstanding_balance}} for {{reference}} is due on "
            "{{due_date}}.</p>"
            '<p>Pay here: <a href="{{payment_link}}">{{payment_link}}</a></p>'
        ),
    },
    "due_today": {
        "subject": "Payment due today · {{reference}}",
        "body": (
            "<p>Hello {{debtor_name}},</p>"
            "<p>Your payment of {{outstanding_balance}} for {{reference}} is due today, "
            "{{due_date}}.</p>"
            '<p>Pay here: <a href="{{payment_link}}">{{payment_link}}</a></p>'
        ),
    },
    "overdue_1": {
        "subject": "Overdue payment · {{reference}}",
        "body": (
            "<p>Hello {{debtor_name}},</p>"
            "<p>The payment for {{reference}} is {{days_overdue}} day(s) overdue. "
            "Outstanding balance: {{outstanding_balance}}.</p>"
            '<p>Pay here: <a href="{{payment_link}}">{{payment_link}}</a></p>'
        ),
    },
    "overdue_followup": {
        "subject": "Follow-up on overdue payment · {{reference}}",
        "body": (
            "<p>Hello {{debtor_name}},</p>"
            "<p>We are following up on {{reference}}, now {{days_overdue}} day(s) overdue. "
            "Outstanding balance: {{outstanding_balance}}.</p>"
            '<p>Pay here: <a href="{{payment_link}}">{{payment_link}}</a></p>'
        ),
    },
    "payment_receipt": {
        "subject": "Payment received · {{reference}}",
        "body": (
            "<p>Hello {{debtor_name}},</p>"
            "<p>We received a payment of {{amount_paid}} for {{reference}}.</p>"
            "<p>Outstanding balance: {{outstanding_balance}}. "
            "Receipt: {{receipt_number}}.</p>"
            '<p>View your receipt: <a href="{{receipt_link}}">{{receipt_link}}</a></p>'
        ),
    },
    "settled": {
        "subject": "Debt settled · {{reference}}",
        "body": (
            "<p>Hello {{debtor_name}},</p>"
            "<p>The debt for {{reference}} has been fully settled. Thank you.</p>"
            '<p>View your receipt: <a href="{{receipt_link}}">{{receipt_link}}</a></p>'
        ),
    },
    "creditor_notice": {
        "subject": "Update on {{reference}} · {{debtor_name}}",
        "body": (
            "<p>Hello {{business_name}},</p>"
            "<p>{{response_summary}}</p>"
            "<p>Reference: {{reference}}.</p>"
        ),
    },
}


def get_template(key: str) -> dict[str, str]:
    try:
        return TEMPLATES[key]
    except KeyError as exc:
        raise ValueError(f"unknown email template: {key}") from exc

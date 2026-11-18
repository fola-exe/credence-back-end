from decimal import Decimal

import pytest

from app.core.money import format_naira, kobo_to_naira, naira_to_kobo


@pytest.mark.parametrize(
    ("amount_kobo", "expected"),
    [
        (0, Decimal("0.00")),
        (1, Decimal("0.01")),
        (123456, Decimal("1234.56")),
    ],
)
def test_kobo_to_naira(amount_kobo, expected):
    assert kobo_to_naira(amount_kobo) == expected


@pytest.mark.parametrize(
    ("amount", "expected"),
    [
        ("0", 0),
        ("0.01", 1),
        ("1234.56", 123456),
        (Decimal("10.005"), 1001),
        (150000, 15000000),
    ],
)
def test_naira_to_kobo(amount, expected):
    assert naira_to_kobo(amount) == expected


def test_format_naira():
    assert format_naira(123456) == "₦1,234.56"

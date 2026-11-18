from decimal import Decimal, ROUND_HALF_UP

KOBO = Decimal("100")
NAIRA_QUANTUM = Decimal("0.01")


def kobo_to_naira(amount_kobo: int) -> Decimal:
    return (Decimal(amount_kobo) / KOBO).quantize(NAIRA_QUANTUM)


def naira_to_kobo(amount: str | int | Decimal) -> int:
    return int(
        (Decimal(str(amount)) * KOBO).to_integral_value(rounding=ROUND_HALF_UP)
    )


def format_naira(amount_kobo: int) -> str:
    return f"₦{kobo_to_naira(amount_kobo):,.2f}"

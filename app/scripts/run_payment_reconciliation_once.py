from app.core.database import SessionLocal
from app.modules.payments.service import PaymentService


def main() -> None:
    with SessionLocal() as db:
        results = PaymentService.reconcile_stale_payments(db)
    for reference, outcome in results:
        print(f"{reference}: {outcome}")


if __name__ == "__main__":
    main()

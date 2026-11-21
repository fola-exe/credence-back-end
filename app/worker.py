from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import SessionLocal
from app.core.time import WAT
from app.modules.payments.service import PaymentService


def reconcile_once() -> None:
    with SessionLocal() as db:
        PaymentService.reconcile_stale_payments(db)


def main() -> None:
    scheduler = BlockingScheduler(timezone=WAT)
    scheduler.add_job(
        reconcile_once,
        IntervalTrigger(minutes=30),
        id="payment_reconciliation",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()


if __name__ == "__main__":
    main()

from app.core.database import engine


def test_engine_uses_managed_postgres_pool_options():
    assert engine.pool.__class__.__name__ == "QueuePool"
    assert getattr(engine.pool, "_pre_ping") is True
    assert engine.pool.size() == 5
    assert getattr(engine.pool, "_max_overflow") == 10
    assert getattr(engine.pool, "_recycle") == 1800

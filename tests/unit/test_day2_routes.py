from app.main import app


def test_day2_routes_are_registered():
    paths = set(app.openapi()["paths"])

    assert "/public/tx/{token}" in paths
    assert "/public/tx/{token}/acknowledge" in paths
    assert "/public/tx/{token}/pay" in paths
    assert "/public/tx/{token}/payments/{reference}" in paths
    assert "/public/tx/{token}/promise" in paths
    assert "/public/tx/{token}/dispute" in paths
    assert "/public/tx/{token}/receipts/{receipt_number}" in paths
    assert "/webhooks/kora" in paths
    assert "/demo/charges/{reference}" in paths
    assert "/transactions/{transaction_id}/payments/{payment_id}/receipt" in paths

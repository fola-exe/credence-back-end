import pytest

from app.core.errors import InvalidWebhookBody
from app.integrations.kora.signature import (
    canonical_data,
    matching_strategy,
    raw_data_slice,
    sign,
    verify_signature,
)

RAW = b'{"event": "charge.success", "data": {"reference": "CRD-000123-P1", "amount": "1500.00"}}'


def test_canonical_data_is_compact():
    assert canonical_data(RAW) == b'{"reference":"CRD-000123-P1","amount":"1500.00"}'


def test_raw_data_slice_preserves_original_bytes():
    assert raw_data_slice(RAW) == b'{"reference": "CRD-000123-P1", "amount": "1500.00"}'


def test_raw_signature_matches_first():
    signature = sign(raw_data_slice(RAW), "secret")
    assert matching_strategy(RAW, signature, "secret") == "raw"


def test_canonical_signature_is_accepted():
    signature = sign(canonical_data(RAW), "secret")
    assert matching_strategy(RAW, signature, "secret") == "canonical"


def test_strategy_can_be_pinned():
    canonical = sign(canonical_data(RAW), "secret")
    assert matching_strategy(RAW, canonical, "secret", "canonical") == "canonical"
    assert matching_strategy(RAW, canonical, "secret", "raw") is None


def test_raw_slice_handles_braces_inside_string_values():
    raw = b'{"data": {"reference": "P1", "note": "cost } then { more"}}'
    expected = b'{"reference": "P1", "note": "cost } then { more"}'

    assert raw_data_slice(raw) == expected
    assert matching_strategy(raw, sign(expected, "secret"), "secret") == "raw"


@pytest.mark.parametrize("raw", [b"not-json", b'{"event":"charge.success"}'])
def test_malformed_body_is_a_validation_error(raw):
    with pytest.raises(InvalidWebhookBody):
        canonical_data(raw)


def test_bad_signature_is_rejected():
    assert verify_signature(RAW, "bad", "secret") is False
    assert verify_signature(RAW, None, "secret") is False

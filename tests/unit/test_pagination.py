from app.core.pagination import build_meta, normalize_pagination


def test_normalize_pagination_uses_defaults():
    pagination = normalize_pagination()

    assert pagination.page == 1
    assert pagination.limit == 20
    assert pagination.offset == 0


def test_normalize_pagination_clamps_out_of_range_values():
    pagination = normalize_pagination(page=0, limit=1000)

    assert pagination.page == 1
    assert pagination.limit == 100
    assert pagination.offset == 0


def test_normalize_pagination_keeps_valid_values():
    pagination = normalize_pagination(page=3, limit=25)

    assert pagination.offset == 50


def test_build_meta_calculates_total_pages():
    assert build_meta(page=1, limit=20, total=37) == {
        "page": 1,
        "limit": 20,
        "total": 37,
        "total_pages": 2,
    }

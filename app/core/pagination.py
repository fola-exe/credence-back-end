from dataclasses import dataclass
from math import ceil

DEFAULT_PAGE = 1
DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass(frozen=True)
class Pagination:
    page: int
    limit: int

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.limit


def normalize_pagination(page: int | None = None, limit: int | None = None) -> Pagination:
    normalized_page = DEFAULT_PAGE if page is None else max(DEFAULT_PAGE, page)
    requested_limit = DEFAULT_LIMIT if limit is None else limit
    normalized_limit = min(MAX_LIMIT, max(1, requested_limit))
    return Pagination(page=normalized_page, limit=normalized_limit)


def build_meta(*, page: int, limit: int, total: int) -> dict[str, int]:
    return {
        "page": page,
        "limit": limit,
        "total": total,
        "total_pages": ceil(total / limit),
    }

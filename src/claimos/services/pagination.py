"""Cursor-based pagination for HTMX infinite-scroll endpoints.

Cursor pagination is stable across concurrent inserts (no off-by-one when a
new row lands between page fetches) and avoids the O(offset) cost of offset
pagination on Postgres. The cursor is the value of the order column from the
last row of the previous page.
"""

from typing import Any, Literal

from sqlalchemy.orm import Query


def paginate_by_cursor(
    query: Query,
    *,
    cursor_col: Any,
    cursor_value: Any | None,
    limit: int,
    order: Literal["asc", "desc"] = "desc",
) -> tuple[list, Any | None]:
    """Return `(rows, next_cursor)` for one cursor-paginated page.

    `cursor_col` is the model column to order by (must be unique-ish enough
    that ties don't cause skipped rows — id, line_number, created_at).
    `cursor_value`, if present, is the cursor returned from the previous page
    call; `None` means "first page".

    `next_cursor` is the cursor value to pass for the next page, or `None`
    when this was the last page.
    """
    if order == "desc":
        q = query.order_by(cursor_col.desc())
        if cursor_value is not None:
            q = q.filter(cursor_col < cursor_value)
    else:
        q = query.order_by(cursor_col.asc())
        if cursor_value is not None:
            q = q.filter(cursor_col > cursor_value)

    rows = q.limit(limit + 1).all()
    if len(rows) > limit:
        # We fetched one extra to know whether there's another page; drop it.
        page = rows[:limit]
        next_cursor = getattr(page[-1], cursor_col.key)
        return page, next_cursor
    return rows, None

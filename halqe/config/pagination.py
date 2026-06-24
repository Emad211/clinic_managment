"""
Shared pagination utilities for the Halqe Platform API.

Both list_patients and list_worklist return the same envelope shape:
    {items: [...], total: int, limit: int, offset: int}

Usage — in a list endpoint:
    from config.pagination import paginate

    total = MyModel.objects.filter(...).count()
    page  = list(MyModel.objects.filter(...)[offset: offset + limit])
    return SomeListResponse(**paginate(total, items_dtos, limit, offset))

The handler keeps the QuerySet logic; paginate() only fills the envelope.
"""


def paginate(total: int, items: list, limit: int, offset: int) -> dict:
    """
    Build the standard pagination envelope fields.

    Args:
        total:  Full count of matching rows BEFORE slicing.
        items:  The DTO list for the current page (already sliced).
        limit:  Page size as requested.
        offset: Starting row index as requested.

    Returns a dict with keys: items, total, limit, offset.
    Pass it as **paginate(...) to any Schema that has those four fields.
    """
    return {
        "items": items,
        "total": total,
        "limit": limit,
        "offset": offset,
    }

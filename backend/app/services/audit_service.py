"""Append-only audit records for administrator actions.

Call :func:`record_admin_action` immediately before the ``session.commit()``
that performs the change, passing the same session. The audit row then lands in
the same transaction: either the change and its record both persist, or neither
does. Never commit the audit row on its own.
"""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AdminAuditLog, User


async def record_admin_action(
    session: AsyncSession,
    admin: User,
    action: str,
    *,
    target_type: str | None = None,
    target_id: int | str | None = None,
    target_label: str | None = None,
    detail: dict[str, Any] | None = None,
) -> AdminAuditLog:
    """Stage an audit row on ``session`` for the caller's own commit.

    ``admin_username`` is snapshotted so the entry stays readable even if the
    account is later deleted. ``detail`` must not contain secrets; callers
    pass identifiers and changed field names, not credential values.
    """
    entry = AdminAuditLog(
        admin_user_id=admin.id,
        admin_username=admin.username,
        action=action,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        target_label=target_label,
        detail=detail,
    )
    session.add(entry)
    return entry

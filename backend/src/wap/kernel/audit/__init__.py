"""Audit: who changed what in a tenant, recorded in the same transaction.

Audited tables carry the ``kernel.audit_row()`` trigger, which writes the row
before and after each insert, update and delete to ``kernel.audit_log``. The
actor is read from transaction-local settings set by ``tenant_transaction``.
"""

from wap.kernel.audit.actor import Actor
from wap.kernel.audit.sql import attach_sql, detach_sql

__all__ = ["Actor", "attach_sql", "detach_sql"]

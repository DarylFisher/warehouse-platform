"""SQL that attaches the audit trigger to a table.

Used by kernel migrations now and by the platform migration engine for app
tables later, so every audited table is wired the same way.
"""

import re

_TABLE = re.compile(r"^[a-z_][a-z0-9_]*\.[a-z_][a-z0-9_]*$")
_COLUMN = re.compile(r"^[a-z_][a-z0-9_]*$")


def _check_table(table: str) -> str:
    if not _TABLE.fullmatch(table):
        raise ValueError(f"not a schema-qualified table name: {table!r}")
    return table


def attach_sql(table: str, ignored_columns: list[str] | None = None) -> str:
    """CREATE TRIGGER for ``table``; changes to only ``ignored_columns`` aren't logged."""
    _check_table(table)
    ignored = ignored_columns or []
    for column in ignored:
        if not _COLUMN.fullmatch(column):
            raise ValueError(f"not a column name: {column!r}")
    args = ", ".join(f"'{c}'" for c in ignored)
    return (
        f"CREATE TRIGGER audit AFTER INSERT OR UPDATE OR DELETE ON {table} "
        f"FOR EACH ROW EXECUTE FUNCTION kernel.audit_row({args})"
    )


def detach_sql(table: str) -> str:
    return f"DROP TRIGGER audit ON {_check_table(table)}"

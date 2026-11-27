from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True, slots=True)
class Actor:
    """Who a transaction acts for, recorded on every audit entry it causes.

    ``user_id`` is the tenant user; it is None before the user exists (the
    first sign-in creates them) and for system jobs. ``subject`` is the
    token subject, or a ``system:<job>`` name.
    """

    user_id: UUID | None
    subject: str

    @classmethod
    def system(cls, job: str) -> "Actor":
        return cls(user_id=None, subject=f"system:{job}")

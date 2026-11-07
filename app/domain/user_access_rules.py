from __future__ import annotations

from uuid import UUID

ASSIGNABLE_ROLES = frozenset({"accountant", "viewer", "auditor"})


def _role_value(role) -> str:
    return getattr(role, "value", role)


def validate_role_assignable(role) -> None:
    """Only one owner exists per tenant, so 'owner' can never be assigned."""
    if _role_value(role) not in ASSIGNABLE_ROLES:
        raise ValueError(f"Role '{_role_value(role)}' cannot be assigned.")


def validate_target_manageable(*, actor_id: UUID, target_id: UUID, target_role) -> None:
    if actor_id == target_id:
        raise ValueError("You cannot change your own role or active status.")
    if _role_value(target_role) == "owner":
        raise ValueError("The owner account cannot be modified.")
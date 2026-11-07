from datetime import date
from uuid import uuid4

import pytest

from app.domain import dashboard_rules, login_lockout_rules, user_access_rules


@pytest.mark.parametrize("failures,expected", [(0, False), (4, False), (5, True), (9, True)])
def test_lockout_threshold(failures, expected):
    assert login_lockout_rules.is_locked(failures) is expected


@pytest.mark.parametrize("role", ["accountant", "viewer", "auditor"])
def test_assignable_roles_ok(role):
    user_access_rules.validate_role_assignable(role)


@pytest.mark.parametrize("role", ["owner", "admin", ""])
def test_unassignable_roles_rejected(role):
    with pytest.raises(ValueError):
        user_access_rules.validate_role_assignable(role)


def test_cannot_manage_self():
    same = uuid4()
    with pytest.raises(ValueError):
        user_access_rules.validate_target_manageable(actor_id=same, target_id=same, target_role="viewer")


def test_cannot_manage_owner():
    with pytest.raises(ValueError):
        user_access_rules.validate_target_manageable(actor_id=uuid4(), target_id=uuid4(), target_role="owner")


def test_can_manage_staff():
    user_access_rules.validate_target_manageable(actor_id=uuid4(), target_id=uuid4(), target_role="accountant")


@pytest.mark.parametrize("today,start,end", [
    (date(2026, 11, 6), date(2026, 11, 1), date(2026, 11, 30)),
    (date(2026, 12, 31), date(2026, 12, 1), date(2026, 12, 31)),
    (date(2028, 2, 10), date(2028, 2, 1), date(2028, 2, 29)),
])
def test_month_bounds(today, start, end):
    assert dashboard_rules.month_bounds(today) == (start, end)
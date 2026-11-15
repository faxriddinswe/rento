"""Permission matrix: (actor kind, action, resource relation) -> allowed?"""

from uuid import uuid4

import pytest

from app.domain.policies import MANAGER_GRANTABLE, TENANT_ACTIONS, Action, Actor, Resource, can

OWNER, OTHER_OWNER, MANAGER, TENANT, OTHER_TENANT = (uuid4() for _ in range(5))
PROP, OTHER_PROP = uuid4(), uuid4()

owner = Actor(OWNER, "owner")
other_owner = Actor(OTHER_OWNER, "owner")
tenant = Actor(TENANT, "tenant")
other_tenant = Actor(OTHER_TENANT, "tenant")
full_manager = Actor(
    MANAGER,
    "manager",
    {PROP: frozenset(a.value for a in Action)},  # even ungrantable strings
)
limited_manager = Actor(MANAGER, "manager", {PROP: frozenset({"reading.review", "reading.read"})})
# Resource: property PROP owned by OWNER, lease tenant TENANT
res = Resource(owner_id=OWNER, property_id=PROP, tenant_id=TENANT)
other_res = Resource(owner_id=OTHER_OWNER, property_id=OTHER_PROP, tenant_id=OTHER_TENANT)


@pytest.mark.parametrize("action", [a for a in Action if a is not Action.PROPERTY_CREATE])
def test_owner_can_do_everything_on_own_property_only(action):
    assert can(owner, action, res)
    assert not can(owner, action, other_res)
    assert not can(other_owner, action, res)


def test_only_owners_can_create_properties():
    assert can(owner, Action.PROPERTY_CREATE)
    for a in (tenant, full_manager, limited_manager):
        assert not can(a, Action.PROPERTY_CREATE)


@pytest.mark.parametrize("action", list(Action))
def test_manager_limited_to_explicit_grantable_permissions(action):
    expected = action in MANAGER_GRANTABLE  # full_manager has every string
    assert can(full_manager, action, res) is expected
    assert not can(full_manager, action, other_res)  # other property
    assert can(limited_manager, action, res) is (action.value in {"reading.review", "reading.read"})


def test_ungrantable_actions_never_allowed_to_managers():
    for a in (
        Action.PAYMENT_REVERSE,
        Action.AUDIT_READ,
        Action.TEMPLATE_MANAGE,
        Action.MANAGER_MANAGE,
        Action.BILLING_RUN,
        Action.PROPERTY_UPDATE,
    ):
        assert not can(full_manager, a, res)


@pytest.mark.parametrize("action", list(Action))
def test_tenant_only_own_lease_and_only_tenant_actions(action):
    assert can(tenant, action, res) is (action in TENANT_ACTIONS)
    assert not can(other_tenant, action, res)
    assert not can(tenant, action, Resource(owner_id=OWNER, property_id=PROP))  # no lease tenant
    assert not can(tenant, action)


def test_unknown_role_denied():
    assert not can(Actor(uuid4(), "root"), Action.PROPERTY_READ, res)

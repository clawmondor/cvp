from claimos.roles import (
    OBJECT_TYPES,
    get_user_role,
    role_for_object,
)


def test_object_types_are_canonical():
    assert OBJECT_TYPES == (
        "items",
        "evidence",
        "reports",
        "exports",
        "crops",
        "audit_logs",
        "rooms",
        "item_groups",
        "comments",
        "users",
    )


def test_lawyer_and_paralegal_are_manager_on_everything():
    for key in ("lawyer", "paralegal"):
        role = get_user_role(key)
        assert role is not None
        assert role.system_role == "external_admin"
        assert all(role.profile[obj] == "manager" for obj in OBJECT_TYPES)


def test_adjuster_is_approver_on_its_objects():
    role = get_user_role("adjuster")
    assert role.system_role == "external_user"
    expected = {
        "users",
        "items",
        "evidence",
        "reports",
        "exports",
        "crops",
        "audit_logs",
        "rooms",
        "item_groups",
    }
    assert set(role.profile) == expected
    assert all(v == "approver" for v in role.profile.values())


def test_photographer_split_levels():
    assert role_for_object("photographer", "evidence") == "contributor"
    assert role_for_object("photographer", "comments") == "contributor"
    assert role_for_object("photographer", "rooms") == "contributor"
    assert role_for_object("photographer", "item_groups") == "contributor"
    assert role_for_object("photographer", "items") == "viewer"
    assert role_for_object("photographer", "exports") is None  # not in profile


def test_claimant_is_single_claim_and_viewer():
    role = get_user_role("claimant")
    assert role.single_claim_only is True
    assert set(role.profile) == {"items", "evidence", "reports", "audit_logs"}
    assert all(v == "viewer" for v in role.profile.values())


def test_valuator_profile():
    role = get_user_role("valuator")
    assert set(role.profile) == {"items", "comments", "crops", "audit_logs"}
    assert all(v == "contributor" for v in role.profile.values())


def test_role_for_object_unknown_role():
    assert role_for_object("nope", "items") is None


def test_uniform_synthetic_role():
    from claimos.roles import role_for_object

    assert role_for_object("_uniform:contributor", "items") == "contributor"
    assert role_for_object("_uniform:contributor", "exports") == "contributor"

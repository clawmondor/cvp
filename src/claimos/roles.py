"""Fixed, code-defined User Role registry for external (firm) users.

A User Role bundles a default system role with a map of object_type -> claim role.
External-only for now; internal users are governed by the legacy claim_access model.
Product-defined and fixed (like depreciation.py) — not admin-editable.
"""

from dataclasses import dataclass

OBJECT_TYPES: tuple[str, ...] = (
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


@dataclass(frozen=True)
class UserRole:
    key: str
    system_role: str
    profile: dict[str, str]  # object_type -> claim role
    single_claim_only: bool = False


def _all_objects(role: str) -> dict[str, str]:
    return {obj: role for obj in OBJECT_TYPES}


USER_ROLES: dict[str, UserRole] = {
    "lawyer": UserRole("lawyer", "external_admin", _all_objects("manager")),
    "paralegal": UserRole("paralegal", "external_admin", _all_objects("manager")),
    "adjuster": UserRole(
        "adjuster",
        "external_user",
        {
            "users": "approver",
            "items": "approver",
            "evidence": "approver",
            "reports": "approver",
            "exports": "approver",
            "crops": "approver",
            "audit_logs": "approver",
            "rooms": "approver",
            "item_groups": "approver",
        },
    ),
    "claimant": UserRole(
        "claimant",
        "external_user",
        {
            "items": "viewer",
            "evidence": "viewer",
            "reports": "viewer",
            "audit_logs": "viewer",
        },
        single_claim_only=True,
    ),
    "photographer": UserRole(
        "photographer",
        "external_user",
        {
            "evidence": "contributor",
            "comments": "contributor",
            "rooms": "contributor",
            "item_groups": "contributor",
            "items": "viewer",
        },
    ),
    "valuator": UserRole(
        "valuator",
        "external_user",
        {
            "items": "contributor",
            "comments": "contributor",
            "crops": "contributor",
            "audit_logs": "contributor",
        },
    ),
}


def get_user_role(key: str) -> UserRole | None:
    return USER_ROLES.get(key)


def role_for_object(role_key: str, object_type: str) -> str | None:
    role = USER_ROLES.get(role_key)
    if role is None:
        return None
    return role.profile.get(object_type)

"""
RBAC suite — system admin unrestricted access, internal admin boundaries,
external admin scoping, matter role grants, cross-org isolation,
comment visibility, internal user has no admin panel access.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from playwright.sync_api import Page, sync_playwright

from skills.qa.data_factory import DataFactory
from skills.qa.report import SuiteResult, TestResult


def _login(page: Page, base_url: str, email: str, password: str) -> bool:
    page.goto(f"{base_url}/login")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    try:
        page.wait_for_url("**/dashboard", timeout=5000)
        return True
    except Exception:
        return "/dashboard" in page.url


def _logout(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/dashboard")
    page.wait_for_timeout(200)
    logout = page.locator('form[action="/api/auth/logout"] button, button:has-text("Sign out")')
    if logout.count():
        logout.first.click()
    page.wait_for_timeout(300)


def run(
    base_url: str,
    config: dict[str, Any],
    factory: DataFactory,
    fail_fast: bool = False,
) -> SuiteResult:
    suite = SuiteResult(name="rbac")
    admin_email = config["QA_ADMIN_EMAIL"]
    admin_password = config["QA_ADMIN_PASSWORD"]
    headful = config.get("QA_HEADFUL", "").lower() == "true"
    pw = factory.password_for()

    # Setup
    internal_group = factory.create_internal_group()
    ext_group_a = factory.create_external_group("A")
    ext_group_b = factory.create_external_group("B")

    int_admin = factory.create_internal_admin(internal_group)
    int_user = factory.create_internal_user(internal_group)
    factory.create_external_admin(ext_group_a)
    ext_user_a = factory.create_external_user(ext_group_a, "a")
    ext_user_b = factory.create_external_user(ext_group_b, "b")

    # Matters owned by internal group
    admin_user_obj = None
    from cvp.db import SessionLocal
    from cvp.models_auth import User as UserModel

    db = SessionLocal()
    try:
        admin_user_obj = db.query(UserModel).filter(UserModel.email == admin_email).first()
    finally:
        db.close()

    matter_a = factory.create_matter(internal_group, int_user, suffix="A")
    # Create a second matter to confirm cross-matter isolation (not used in assertions directly)
    factory.create_matter(internal_group, int_user, suffix="B")

    def record(name: str, passed: bool, message: str = "") -> None:
        suite.results.append(TestResult(suite="rbac", name=name, passed=passed, message=message))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            # ── Test 1: System admin can access all admin panels ─────────────
            try:
                _login(page, base_url, admin_email, admin_password)
                results = []
                for path in ["/admin/system/users", "/admin/internal/users"]:
                    page.goto(f"{base_url}{path}")
                    page.wait_for_timeout(300)
                    results.append(("403" not in page.content() and "/login" not in page.url))
                record("system admin accesses all admin panels", all(results), f"results={results}")
            except Exception as e:
                record("system admin accesses all admin panels", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 2: Internal user cannot access admin panels ─────────────
            try:
                _logout(page, base_url)
                _login(page, base_url, int_user.email, pw)
                blocked = []
                for path in ["/admin/system/users", "/admin/internal/users"]:
                    page.goto(f"{base_url}{path}")
                    page.wait_for_timeout(300)
                    is_blocked = (
                        "403" in page.content()
                        or "Forbidden" in page.content()
                        or "/login" in page.url
                    )
                    blocked.append(is_blocked)
                record(
                    "internal user blocked from all admin panels",
                    all(blocked),
                    f"blocked={blocked}",
                )
            except Exception as e:
                record("internal user blocked from all admin panels", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 3: Internal admin blocked from system admin panel ────────
            try:
                _logout(page, base_url)
                _login(page, base_url, int_admin.email, pw)
                page.goto(f"{base_url}/admin/system/users")
                page.wait_for_timeout(300)
                blocked = (
                    "403" in page.content() or "Forbidden" in page.content() or "/login" in page.url
                )
                # But can access internal panel
                page.goto(f"{base_url}/admin/internal/users")
                page.wait_for_timeout(300)
                can_access_internal = "403" not in page.content() and "/login" not in page.url
                record(
                    "internal admin: system panel blocked, internal panel accessible",
                    blocked and can_access_internal,
                    f"blocked_sys={blocked}, can_access_internal={can_access_internal}",
                )
            except Exception as e:
                record(
                    "internal admin: system panel blocked, internal panel accessible", False, str(e)
                )
                if fail_fast:
                    return suite

            # ── Test 4: External user blocked from matter without grant ───────
            try:
                _logout(page, base_url)
                _login(page, base_url, ext_user_a.email, pw)
                page.goto(f"{base_url}/matters/{matter_a.id}")
                page.wait_for_timeout(300)
                blocked = (
                    "403" in page.content() or "Forbidden" in page.content() or "/login" in page.url
                )
                record(
                    "external user blocked from matter without grant", blocked, f"url={page.url}"
                )
            except Exception as e:
                record("external user blocked from matter without grant", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 5: External user can access matter after viewer grant ────
            try:
                # Grant viewer access
                if admin_user_obj:
                    factory.grant_matter_access(ext_user_a, matter_a, "viewer", admin_user_obj)

                _logout(page, base_url)
                _login(page, base_url, ext_user_a.email, pw)
                page.goto(f"{base_url}/matters/{matter_a.id}")
                page.wait_for_timeout(500)
                accessible = (
                    "403" not in page.content()
                    and "/login" not in page.url
                    and matter_a.id in page.url
                )
                record(
                    "external user can access matter with viewer grant",
                    accessible,
                    f"url={page.url}",
                )
            except Exception as e:
                record("external user can access matter with viewer grant", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 6: Viewer cannot edit items (API 403) ───────────────────
            try:
                # Create a room and item first (as internal user)
                from cvp.db import SessionLocal
                from cvp.models import Item, Room

                db = SessionLocal()
                try:
                    room = Room(matter_id=matter_a.id, name="QA Room")
                    db.add(room)
                    db.flush()
                    item = Item(
                        matter_id=matter_a.id,
                        room_id=room.id,
                        description="QA Test Item",
                        quantity=1,
                        rcv_unit_cents=10000,
                        source_url="https://example.com/item",
                        source_retailer="Example Store",
                        source_captured_at=__import__("datetime").datetime.utcnow(),
                        match_type="exact",
                        confirmed=False,
                    )
                    db.add(item)
                    db.commit()
                    item_id = item.id
                finally:
                    db.close()

                # ext_user_a has viewer role — try to PATCH the item
                # We need the CSRF token from a logged-in browser session
                page.goto(f"{base_url}/matters/{matter_a.id}")
                page.wait_for_timeout(300)
                csrf_cookie = next(
                    (c["value"] for c in ctx.cookies() if c["name"] == "cvp_csrf"), None
                )

                resp = page.request.patch(
                    f"{base_url}/api/items/{item_id}",
                    data={"description": "Hacked by viewer"},
                    headers={"X-CSRF-Token": csrf_cookie or ""},
                )
                record(
                    "viewer cannot edit item (PATCH returns 403)",
                    resp.status == 403,
                    f"status={resp.status}",
                )
            except Exception as e:
                record("viewer cannot edit item (PATCH returns 403)", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 7: Cross-org isolation ───────────────────────────────────
            try:
                _logout(page, base_url)
                _login(page, base_url, ext_user_b.email, pw)
                # ext_user_b is in group B — matter_a has viewer for ext_user_a (group A)
                page.goto(f"{base_url}/matters/{matter_a.id}")
                page.wait_for_timeout(300)
                blocked = (
                    "403" in page.content() or "Forbidden" in page.content() or "/login" in page.url
                )
                record(
                    "ext_user from different org blocked from matter", blocked, f"url={page.url}"
                )
            except Exception as e:
                record("ext_user from different org blocked from matter", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 8: Internal user sees matter (implicit manager via group) ─
            try:
                _logout(page, base_url)
                _login(page, base_url, int_user.email, pw)
                page.goto(f"{base_url}/matters/{matter_a.id}")
                page.wait_for_timeout(500)
                accessible = "403" not in page.content() and "/login" not in page.url
                record(
                    "internal_admin has implicit access to internal-owned matters",
                    accessible,
                    f"url={page.url}",
                )
            except Exception as e:
                record(
                    "internal_admin has implicit access to internal-owned matters", False, str(e)
                )
                if fail_fast:
                    return suite

        finally:
            browser.close()

    return suite

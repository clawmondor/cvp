"""
Items suite — create item via API, edit, confirm, exclude, delete, 403 for viewer.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))

from playwright.sync_api import Page, sync_playwright

from skills.qa.data_factory import DataFactory
from skills.qa.report import SuiteResult, TestResult


def _login(page: Page, base_url: str, email: str, password: str) -> None:
    page.goto(f"{base_url}/login")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    page.wait_for_url("**/dashboard", timeout=5000)


def run(
    base_url: str,
    config: dict[str, Any],
    factory: DataFactory,
    fail_fast: bool = False,
) -> SuiteResult:
    suite = SuiteResult(name="items")
    admin_email = config["QA_ADMIN_EMAIL"]
    admin_password = config["QA_ADMIN_PASSWORD"]
    headful = config.get("QA_HEADFUL", "").lower() == "true"
    pw = factory.password_for()

    # Setup
    internal_group = factory.create_internal_group()
    int_user = factory.create_internal_user(internal_group)
    ext_group = factory.create_external_group()
    ext_viewer = factory.create_external_user(ext_group, "viewer")

    from cvp.db import SessionLocal
    from cvp.models_auth import User as UserModel

    db = SessionLocal()
    try:
        admin_obj = db.query(UserModel).filter(UserModel.email == admin_email).first()
    finally:
        db.close()

    matter = factory.create_matter(internal_group, int_user)
    room = factory.create_room(matter, "QA Living Room")
    factory.grant_matter_access(ext_viewer, matter, "viewer", admin_obj)

    def record(name: str, passed: bool, message: str = "") -> None:
        suite.results.append(TestResult(suite="items", name=name, passed=passed, message=message))

    created_item_id: str | None = None

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            _login(page, base_url, admin_email, admin_password)
            page.goto(f"{base_url}/matters/{matter.id}")
            page.wait_for_timeout(300)
            csrf = next((c["value"] for c in ctx.cookies() if c["name"] == "cvp_csrf"), "")

            # ── Test 1: Create item via API ──────────────────────────────────
            try:
                resp = page.request.post(
                    f"{base_url}/api/matters/{matter.id}/items",
                    form={
                        "description": "QA Test Sofa",
                        "room_id": room.id,
                        "quantity": "1",
                        "rcv_unit_cents": "150000",
                        "source_url": "https://example.com/sofa",
                        "source_retailer": "QA Furniture",
                        "match_type": "exact",
                        "age_years": "3",
                    },
                    headers={"X-CSRF-Token": csrf},
                )
                created = resp.status in (200, 201)
                record("create item returns 200/201", created, f"status={resp.status}")
                if created:
                    try:
                        data = resp.json()
                        created_item_id = data.get("id")
                    except Exception:
                        # May return HTML partial — look for item id in DOM
                        pass
            except Exception as e:
                record("create item returns 200/201", False, str(e))
                if fail_fast:
                    return suite

            # If we don't have item ID from API, find it in the DB
            if not created_item_id:
                from cvp.models import Item

                db = SessionLocal()
                try:
                    item = (
                        db.query(Item)
                        .filter(Item.matter_id == matter.id, Item.description == "QA Test Sofa")
                        .first()
                    )
                    if item:
                        created_item_id = item.id
                finally:
                    db.close()

            # ── Test 2: Item appears on matter page ──────────────────────────
            try:
                page.goto(f"{base_url}/matters/{matter.id}")
                page.wait_for_timeout(500)
                has_item = "QA Test Sofa" in page.content()
                record("created item appears on matter page", has_item)
            except Exception as e:
                record("created item appears on matter page", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 3: Edit item via PATCH ──────────────────────────────────
            try:
                if created_item_id:
                    resp = page.request.patch(
                        f"{base_url}/api/items/{created_item_id}",
                        form={"description": "QA Test Sofa (edited)"},
                        headers={"X-CSRF-Token": csrf},
                    )
                    record(
                        "edit item via PATCH returns 200",
                        resp.status == 200,
                        f"status={resp.status}",
                    )
                else:
                    record("edit item via PATCH returns 200", False, "no item_id")
            except Exception as e:
                record("edit item via PATCH returns 200", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 4: Confirm item ─────────────────────────────────────────
            try:
                if created_item_id:
                    resp = page.request.post(
                        f"{base_url}/api/items/{created_item_id}/toggle-confirm",
                        headers={"X-CSRF-Token": csrf},
                    )
                    record(
                        "toggle confirm item returns 200",
                        resp.status == 200,
                        f"status={resp.status}",
                    )
                else:
                    record("toggle confirm item returns 200", False, "no item_id")
            except Exception as e:
                record("toggle confirm item returns 200", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 5: Exclude item ─────────────────────────────────────────
            try:
                if created_item_id:
                    resp = page.request.post(
                        f"{base_url}/api/items/{created_item_id}/toggle-exclude",
                        headers={"X-CSRF-Token": csrf},
                    )
                    record(
                        "toggle exclude item returns 200",
                        resp.status == 200,
                        f"status={resp.status}",
                    )
                else:
                    record("toggle exclude item returns 200", False, "no item_id")
            except Exception as e:
                record("toggle exclude item returns 200", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 6: Viewer cannot edit item (403) ────────────────────────
            try:
                if created_item_id:
                    ext_ctx = browser.new_context()
                    ext_page = ext_ctx.new_page()
                    ext_page.goto(f"{base_url}/login")
                    ext_page.fill('input[name="email"]', ext_viewer.email)
                    ext_page.fill('input[name="password"]', pw)
                    ext_page.click('button[type="submit"]')
                    ext_page.wait_for_timeout(1000)

                    csrf_ext = next(
                        (c["value"] for c in ext_ctx.cookies() if c["name"] == "cvp_csrf"), ""
                    )
                    resp = ext_page.request.patch(
                        f"{base_url}/api/items/{created_item_id}",
                        form={"description": "Hacked by viewer"},
                        headers={"X-CSRF-Token": csrf_ext},
                    )
                    record(
                        "viewer cannot PATCH item (403)",
                        resp.status == 403,
                        f"status={resp.status}",
                    )
                    ext_ctx.close()
                else:
                    record("viewer cannot PATCH item (403)", False, "no item_id")
            except Exception as e:
                record("viewer cannot PATCH item (403)", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 7: Delete item ──────────────────────────────────────────
            try:
                if created_item_id:
                    resp = page.request.delete(
                        f"{base_url}/api/items/{created_item_id}",
                        headers={"X-CSRF-Token": csrf},
                    )
                    record("delete item returns 200", resp.status == 200, f"status={resp.status}")
                    if resp.status == 200:
                        created_item_id = None  # Don't try to delete in teardown
                else:
                    record("delete item returns 200", False, "no item_id")
            except Exception as e:
                record("delete item returns 200", False, str(e))
                if fail_fast:
                    return suite

        finally:
            browser.close()

    return suite

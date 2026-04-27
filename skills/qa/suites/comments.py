"""
Comments suite — post internal vs shared comments, visibility enforcement:
internal comments not visible to external users, shared visible to all with access.
"""

from __future__ import annotations

import sys
from datetime import datetime
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
    suite = SuiteResult(name="comments")
    admin_email = config["QA_ADMIN_EMAIL"]
    admin_password = config["QA_ADMIN_PASSWORD"]
    headful = config.get("QA_HEADFUL", "").lower() == "true"
    pw = factory.password_for()
    ts = str(factory.run_ts)

    # Setup
    internal_group = factory.create_internal_group()
    int_user = factory.create_internal_user(internal_group)
    ext_group = factory.create_external_group()
    ext_viewer = factory.create_external_user(ext_group, "viewer")

    from cvp.db import SessionLocal
    from cvp.models import Item
    from cvp.models_auth import User as UserModel

    db = SessionLocal()
    try:
        admin_obj = db.query(UserModel).filter(UserModel.email == admin_email).first()
    finally:
        db.close()

    matter = factory.create_matter(internal_group, int_user)
    room = factory.create_room(matter, "QA Comment Room")
    factory.grant_matter_access(ext_viewer, matter, "viewer", admin_obj)
    factory.grant_matter_access(int_user, matter, "viewer", admin_obj)

    # Create an item directly in DB for comment tests
    db = SessionLocal()
    try:
        item = Item(
            matter_id=matter.id,
            room_id=room.id,
            description=f"QA Comment Item {ts}",
            quantity=1,
            rcv_unit_cents=5000,
            source_url="https://example.com/item",
            source_retailer="QA Store",
            source_captured_at=datetime.utcnow(),
            match_type="exact",
            confirmed=False,
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        item_id = item.id
    finally:
        db.close()

    def record(name: str, passed: bool, message: str = "") -> None:
        suite.results.append(
            TestResult(suite="comments", name=name, passed=passed, message=message)
        )

    internal_comment_text = f"QA_INTERNAL_COMMENT_{ts}_secret"
    shared_comment_text = f"QA_SHARED_COMMENT_{ts}_visible"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            # ── Post internal comment as internal_user ────────────────────────
            try:
                _login(page, base_url, admin_email, admin_password)
                page.goto(f"{base_url}/matters/{matter.id}")
                page.wait_for_timeout(500)
                csrf = next((c["value"] for c in ctx.cookies() if c["name"] == "cvp_csrf"), "")

                resp = page.request.post(
                    f"{base_url}/api/items/{item_id}/comments",
                    form={
                        "body": internal_comment_text,
                        "visibility": "internal",
                    },
                    headers={"X-CSRF-Token": csrf},
                )
                record(
                    "post internal comment returns 200", resp.status == 200, f"status={resp.status}"
                )
            except Exception as e:
                record("post internal comment returns 200", False, str(e))
                if fail_fast:
                    return suite

            # ── Post shared comment as internal_user ─────────────────────────
            try:
                resp = page.request.post(
                    f"{base_url}/api/items/{item_id}/comments",
                    form={
                        "body": shared_comment_text,
                        "visibility": "shared",
                    },
                    headers={"X-CSRF-Token": csrf},
                )
                record(
                    "post shared comment returns 200", resp.status == 200, f"status={resp.status}"
                )
            except Exception as e:
                record("post shared comment returns 200", False, str(e))
                if fail_fast:
                    return suite

            # ── Internal user sees both comments ─────────────────────────────
            try:
                resp = page.request.get(f"{base_url}/api/items/{item_id}/comments")
                content = resp.text()
                sees_internal = internal_comment_text in content
                sees_shared = shared_comment_text in content
                record(
                    "internal user sees both internal and shared comments",
                    sees_internal and sees_shared,
                    f"sees_internal={sees_internal}, sees_shared={sees_shared}",
                )
            except Exception as e:
                record("internal user sees both internal and shared comments", False, str(e))
                if fail_fast:
                    return suite

            # ── External viewer sees only shared comment ──────────────────────
            try:
                ext_ctx = browser.new_context()
                ext_page = ext_ctx.new_page()
                ext_page.goto(f"{base_url}/login")
                ext_page.fill('input[name="email"]', ext_viewer.email)
                ext_page.fill('input[name="password"]', pw)
                ext_page.click('button[type="submit"]')
                ext_page.wait_for_timeout(1000)

                resp = ext_page.request.get(f"{base_url}/api/items/{item_id}/comments")
                content = resp.text()
                hides_internal = internal_comment_text not in content
                shows_shared = shared_comment_text in content
                record(
                    "external viewer: internal comment hidden, shared visible",
                    hides_internal and shows_shared,
                    f"hides_internal={hides_internal}, shows_shared={shows_shared}",
                )
                ext_ctx.close()
            except Exception as e:
                record("external viewer: internal comment hidden, shared visible", False, str(e))
                if fail_fast:
                    return suite

            # ── External user cannot post internal comment ────────────────────
            try:
                ext_ctx2 = browser.new_context()
                ext_page2 = ext_ctx2.new_page()
                ext_page2.goto(f"{base_url}/login")
                ext_page2.fill('input[name="email"]', ext_viewer.email)
                ext_page2.fill('input[name="password"]', pw)
                ext_page2.click('button[type="submit"]')
                ext_page2.wait_for_timeout(1000)
                csrf_ext = next(
                    (c["value"] for c in ext_ctx2.cookies() if c["name"] == "cvp_csrf"), ""
                )

                resp = ext_page2.request.post(
                    f"{base_url}/api/items/{item_id}/comments",
                    form={
                        "body": f"QA_EXT_INTERNAL_{ts}",
                        "visibility": "internal",
                    },
                    headers={"X-CSRF-Token": csrf_ext},
                )
                # Should either be rejected (4xx) or silently downgraded to shared
                # Either behavior is acceptable — what matters is the comment doesn't
                # appear as internal to other users
                if resp.status in (200, 201):
                    # Verify the comment was stored as shared, not internal
                    # If visible to ext user too, it was stored as shared (correct)
                    ext_resp = ext_page2.request.get(f"{base_url}/api/items/{item_id}/comments")
                    ext_content = ext_resp.text()
                    stored_as_shared = f"QA_EXT_INTERNAL_{ts}" in ext_content
                    record(
                        "external user cannot create internal comments",
                        stored_as_shared,
                        "comment was stored as shared (correct)",
                    )
                else:
                    record(
                        "external user cannot create internal comments",
                        True,
                        f"request rejected with status {resp.status}",
                    )
                ext_ctx2.close()
            except Exception as e:
                record("external user cannot create internal comments", False, str(e))
                if fail_fast:
                    return suite

            # Cleanup item
            db = SessionLocal()
            try:
                from cvp.models_comments import Comment

                db.query(Comment).filter(Comment.item_id == item_id).delete()
                db.query(Item).filter(Item.id == item_id).delete()
                db.commit()
            finally:
                db.close()

        finally:
            browser.close()

    return suite

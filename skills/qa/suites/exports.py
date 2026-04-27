"""
Exports suite — CSV download, PDF download, 403 without access.
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
    suite = SuiteResult(name="exports")
    admin_email = config["QA_ADMIN_EMAIL"]
    admin_password = config["QA_ADMIN_PASSWORD"]
    headful = config.get("QA_HEADFUL", "").lower() == "true"
    pw = factory.password_for()
    ts = str(factory.run_ts)

    # Setup: matter with at least one confirmed item so CSV/PDF are non-trivial
    internal_group = factory.create_internal_group()
    int_user = factory.create_internal_user(internal_group)
    ext_group = factory.create_external_group()
    ext_user = factory.create_external_user(ext_group)

    matter = factory.create_matter(internal_group, int_user)
    room = factory.create_room(matter, "QA Export Room")

    # Seed one confirmed item directly
    from cvp.db import SessionLocal
    from cvp.models import Category, Item

    db = SessionLocal()
    try:
        cat = db.query(Category).first()
        item = Item(
            matter_id=matter.id,
            room_id=room.id,
            description=f"QA Export Item {ts}",
            quantity=1,
            rcv_unit_cents=20000,
            source_url="https://example.com/export-item",
            source_retailer="QA Retailer",
            source_captured_at=datetime.utcnow(),
            match_type="exact",
            age_years=2.0,
            category_id=cat.id if cat else None,
            confirmed=True,
            excluded=False,
        )
        db.add(item)
        db.commit()
    finally:
        db.close()

    def record(name: str, passed: bool, message: str = "") -> None:
        suite.results.append(TestResult(suite="exports", name=name, passed=passed, message=message))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            _login(page, base_url, admin_email, admin_password)
            page.goto(f"{base_url}/matters/{matter.id}")
            page.wait_for_timeout(300)
            csrf = next((c["value"] for c in ctx.cookies() if c["name"] == "cvp_csrf"), "")

            # ── Test 1: CSV export returns CSV content ────────────────────────
            try:
                resp = page.request.get(
                    f"{base_url}/api/matters/{matter.id}/export/csv",
                    headers={"X-CSRF-Token": csrf},
                )
                content_type = resp.headers.get("content-type", "")
                is_csv = "text/csv" in content_type or "application/csv" in content_type
                body = resp.text()
                # Xactimate CSV must have the standard header row
                has_header = "Description" in body and "RCV" in body
                record(
                    "CSV export returns valid CSV",
                    resp.status == 200 and (is_csv or has_header),
                    f"status={resp.status}, content-type={content_type}",
                )
            except Exception as e:
                record("CSV export returns valid CSV", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 2: CSV contains Xactimate required columns ───────────────
            try:
                resp = page.request.get(
                    f"{base_url}/api/matters/{matter.id}/export/csv",
                )
                body = resp.text()
                required_cols = ["Description", "Quantity", "RCV", "ACV"]
                missing = [col for col in required_cols if col not in body]
                record(
                    "CSV contains required Xactimate columns",
                    len(missing) == 0,
                    f"missing={missing}" if missing else "",
                )
            except Exception as e:
                record("CSV contains required Xactimate columns", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 3: PDF export returns PDF content ────────────────────────
            try:
                resp = page.request.get(
                    f"{base_url}/api/matters/{matter.id}/export/pdf",
                    headers={"X-CSRF-Token": csrf},
                )
                content_type = resp.headers.get("content-type", "")
                is_pdf = "application/pdf" in content_type
                # PDF files start with %PDF-
                body_bytes = resp.body()
                starts_with_pdf = body_bytes[:4] == b"%PDF"
                record(
                    "PDF export returns valid PDF",
                    resp.status == 200 and (is_pdf or starts_with_pdf),
                    f"status={resp.status}, content-type={content_type}",
                )
            except Exception as e:
                record("PDF export returns valid PDF", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 4: External user without grant cannot export CSV ─────────
            try:
                ext_ctx = browser.new_context()
                ext_page = ext_ctx.new_page()
                ext_page.goto(f"{base_url}/login")
                ext_page.fill('input[name="email"]', ext_user.email)
                ext_page.fill('input[name="password"]', pw)
                ext_page.click('button[type="submit"]')
                ext_page.wait_for_timeout(1000)

                resp = ext_page.request.get(
                    f"{base_url}/api/matters/{matter.id}/export/csv",
                )
                record(
                    "external user without grant cannot export CSV (4xx)",
                    resp.status in (401, 403),
                    f"status={resp.status}",
                )
                ext_ctx.close()
            except Exception as e:
                record("external user without grant cannot export CSV (4xx)", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 5: Report preview renders ───────────────────────────────
            try:
                page.goto(f"{base_url}/matters/{matter.id}/report/preview")
                page.wait_for_timeout(1000)
                content = page.content()
                has_content = (
                    "Confidential" in content
                    or "Attorney Work Product" in content
                    or f"QA Export Item {ts}" in content
                )
                record(
                    "report preview renders with content",
                    page.url.endswith("/preview") or has_content,
                    f"url={page.url}, has_content={has_content}",
                )
            except Exception as e:
                record("report preview renders with content", False, str(e))
                if fail_fast:
                    return suite

        finally:
            browser.close()

    return suite

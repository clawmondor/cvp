"""
Matters suite — create, view, update status, field validation.
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
    suite = SuiteResult(name="matters")
    admin_email = config["QA_ADMIN_EMAIL"]
    admin_password = config["QA_ADMIN_PASSWORD"]
    headful = config.get("QA_HEADFUL", "").lower() == "true"
    ts = str(factory.run_ts)

    def record(name: str, passed: bool, message: str = "") -> None:
        suite.results.append(TestResult(suite="matters", name=name, passed=passed, message=message))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            _login(page, base_url, admin_email, admin_password)

            # ── Test 1: New matter form loads ────────────────────────────────
            try:
                page.goto(f"{base_url}/matters/new")
                page.wait_for_timeout(300)
                has_form = page.locator("form").count() > 0
                record("new matter form loads", has_form, f"url={page.url}")
            except Exception as e:
                record("new matter form loads", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 2: Create a matter via POST ─────────────────────────────
            try:
                page.goto(f"{base_url}/matters/new")
                page.wait_for_timeout(300)

                firm_name = f"QA_Firm_{ts}_matters"
                page.fill('input[name="firm_name"]', firm_name)
                page.fill('input[name="attorney_name"]', f"QA Attorney {ts}")
                page.fill('input[name="attorney_email"]', f"qa_atty_{ts}@qa.local")
                page.fill('input[name="policyholder_name"]', f"QA Policyholder {ts}")
                page.fill('input[name="loss_location"]', "123 QA St, Test City, CA 90000")
                page.fill('input[name="carrier"]', "QA Insurance")
                page.fill('input[name="policy_number"]', f"QA-POL-{ts}")
                page.fill('input[name="claim_number"]', f"QA-CLM-{ts}")

                page.click('button[type="submit"]')
                page.wait_for_timeout(1000)

                # Should be on the matter detail page
                created = "/matters/" in page.url and "/new" not in page.url
                record("matter created via form", created, f"url={page.url}")

                # Track the created matter for teardown
                if created:
                    matter_id = page.url.rstrip("/").split("/")[-1]
                    factory._matter_ids.append(matter_id)

            except Exception as e:
                record("matter created via form", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 3: Matter detail page shows correct data ─────────────────
            try:
                page.wait_for_timeout(300)
                content = page.content()
                has_firm = f"QA Attorney {ts}" in content or f"QA_Firm_{ts}" in content
                record("matter detail shows created data", has_firm, f"has_firm={has_firm}")
            except Exception as e:
                record("matter detail shows created data", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 4: Dashboard lists matters ──────────────────────────────
            try:
                page.goto(f"{base_url}/dashboard")
                page.wait_for_timeout(500)
                content = page.content()
                has_matter = f"QA_Firm_{ts}" in content or f"QA Attorney {ts}" in content
                record("dashboard lists created matter", has_matter)
            except Exception as e:
                record("dashboard lists created matter", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 5: Matter status can be updated ─────────────────────────
            try:
                # Find the matter we created
                if factory._matter_ids:
                    matter_id = factory._matter_ids[-1]
                    csrf = next((c["value"] for c in ctx.cookies() if c["name"] == "cvp_csrf"), "")
                    resp = page.request.post(
                        f"{base_url}/api/matters/{matter_id}/status",
                        form={"status": "in_progress"},
                        headers={"X-CSRF-Token": csrf},
                    )
                    record(
                        "matter status update returns 200",
                        resp.status == 200,
                        f"status={resp.status}",
                    )
                else:
                    record("matter status update returns 200", False, "no matter created")
            except Exception as e:
                record("matter status update returns 200", False, str(e))
                if fail_fast:
                    return suite

        finally:
            browser.close()

    return suite

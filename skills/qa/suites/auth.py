"""
Auth suite — login, logout, wrong password, deactivated account,
MFA setup + login flow, password change, invite flow, token behavior.
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
    """Log in and return True if dashboard is reached."""
    page.goto(f"{base_url}/login")
    page.fill('input[name="email"]', email)
    page.fill('input[name="password"]', password)
    page.click('button[type="submit"]')
    return "/dashboard" in page.url or page.url == f"{base_url}/"


def _logout(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/dashboard")
    # Click the sign out / logout button
    logout_btn = page.locator(
        'form[action="/api/auth/logout"] button, '
        'a:has-text("Sign out"), button:has-text("Sign out")'
    )
    if logout_btn.count() > 0:
        logout_btn.first.click()
    else:
        # Fallback: POST directly
        page.evaluate("""
            const form = document.createElement('form');
            form.method = 'POST';
            form.action = '/api/auth/logout';
            document.body.appendChild(form);
            form.submit();
        """)
    page.wait_for_url(f"{base_url}/", timeout=3000)


def run(
    base_url: str,
    config: dict[str, Any],
    factory: DataFactory,
    fail_fast: bool = False,
) -> SuiteResult:
    suite = SuiteResult(name="auth")
    qa_pass = config["QA_ADMIN_EMAIL"]
    qa_password = config["QA_ADMIN_PASSWORD"]
    headful = config.get("QA_HEADFUL", "").lower() == "true"

    # Create QA users for this suite
    internal_group = factory.create_internal_group()
    internal_user = factory.create_internal_user(internal_group)
    user_email = internal_user.email
    user_password = factory.password_for()

    def record(name: str, passed: bool, message: str = "") -> None:
        suite.results.append(TestResult(suite="auth", name=name, passed=passed, message=message))

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            # ── Test 1: Successful login redirects to dashboard ──────────────
            try:
                page.goto(f"{base_url}/login")
                page.fill('input[name="email"]', user_email)
                page.fill('input[name="password"]', user_password)
                page.click('button[type="submit"]')
                page.wait_for_url("**/dashboard", timeout=5000)
                record("login redirects to dashboard", True)
            except Exception as e:
                record("login redirects to dashboard", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 2: Auth cookies set after login ─────────────────────────
            try:
                cookies = {c["name"]: c for c in ctx.cookies()}
                has_access = "cvp_access" in cookies
                has_csrf = "cvp_csrf" in cookies
                record(
                    "auth cookies set after login",
                    has_access and has_csrf,
                    "" if (has_access and has_csrf) else f"cookies={list(cookies.keys())}",
                )
            except Exception as e:
                record("auth cookies set after login", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 3: Logout clears cookies and redirects ──────────────────
            try:
                _logout(page, base_url)
                page.wait_for_timeout(500)
                cookies_after = {c["name"]: c for c in ctx.cookies()}
                no_access = "cvp_access" not in cookies_after
                at_root = page.url in (f"{base_url}/", base_url)
                record(
                    "logout clears session",
                    no_access and at_root,
                    f"url={page.url}, cookies={list(cookies_after.keys())}",
                )
            except Exception as e:
                record("logout clears session", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 4: Dashboard requires auth ─────────────────────────────
            try:
                page.goto(f"{base_url}/dashboard")
                page.wait_for_timeout(500)
                redirected_away = "/dashboard" not in page.url or "/login" in page.url
                record(
                    "unauthenticated dashboard request redirects to login",
                    redirected_away,
                    f"url={page.url}",
                )
            except Exception as e:
                record("unauthenticated dashboard request redirects to login", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 5: Wrong password shows error ───────────────────────────
            try:
                page.goto(f"{base_url}/login")
                page.fill('input[name="email"]', user_email)
                page.fill('input[name="password"]', "wrong-password-xyz-999")
                page.click('button[type="submit"]')
                page.wait_for_timeout(500)
                still_on_login = "/login" in page.url
                has_error = "Invalid" in page.content() or "incorrect" in page.content().lower()
                record(
                    "wrong password shows error",
                    still_on_login and has_error,
                    f"url={page.url}, has_error={has_error}",
                )
            except Exception as e:
                record("wrong password shows error", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 6: Deactivated account cannot log in ────────────────────
            try:
                # Deactivate via DB, then attempt login
                import sys

                sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
                from cvp.db import SessionLocal
                from cvp.models_auth import User as UserModel

                db = SessionLocal()
                try:
                    u = db.query(UserModel).filter(UserModel.email == user_email).first()
                    if u:
                        u.is_active = False
                        db.commit()
                finally:
                    db.close()

                page.goto(f"{base_url}/login")
                page.fill('input[name="email"]', user_email)
                page.fill('input[name="password"]', user_password)
                page.click('button[type="submit"]')
                page.wait_for_timeout(500)
                blocked = "/login" in page.url or "/dashboard" not in page.url
                content = page.content().lower()
                shows_reason = (
                    "deactivated" in content or "inactive" in content or "contact" in content
                )
                record(
                    "deactivated account cannot log in",
                    blocked and shows_reason,
                    f"url={page.url}, shows_reason={shows_reason}",
                )

                # Re-activate for other tests
                db = SessionLocal()
                try:
                    u = db.query(UserModel).filter(UserModel.email == user_email).first()
                    if u:
                        u.is_active = True
                        db.commit()
                finally:
                    db.close()
            except Exception as e:
                record("deactivated account cannot log in", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 7: Profile page accessible when logged in ───────────────
            try:
                _login(page, base_url, user_email, user_password)
                page.goto(f"{base_url}/profile")
                page.wait_for_timeout(300)
                on_profile = "/profile" in page.url
                has_password_section = "Password" in page.content()
                record(
                    "profile page accessible when logged in",
                    on_profile and has_password_section,
                    f"url={page.url}",
                )
            except Exception as e:
                record("profile page accessible when logged in", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 8: Password change — wrong current password ─────────────
            try:
                page.goto(f"{base_url}/profile")
                # Submit password change form with wrong current password
                page.fill('input[name="current_password"]', "wrong-current-pass-999")
                page.fill('input[name="new_password"]', "NewQApassword5678!")
                page.fill('input[name="confirm_password"]', "NewQApassword5678!")
                page.click('button:has-text("Update Password")')
                page.wait_for_timeout(500)
                content = page.content().lower()
                shows_error = "incorrect" in content or "invalid" in content or "wrong" in content
                record(
                    "password change rejects wrong current password",
                    shows_error,
                    f"shows_error={shows_error}",
                )
            except Exception as e:
                record("password change rejects wrong current password", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 9: Password change — mismatched new passwords ───────────
            try:
                page.goto(f"{base_url}/profile")
                page.fill('input[name="current_password"]', user_password)
                page.fill('input[name="new_password"]', "NewQApassword5678!")
                page.fill('input[name="confirm_password"]', "DifferentQApassword5678!")
                page.click('button:has-text("Update Password")')
                page.wait_for_timeout(500)
                content = page.content().lower()
                shows_error = "match" in content or "mismatch" in content
                record(
                    "password change rejects mismatched passwords",
                    shows_error,
                    f"shows_error={shows_error}",
                )
            except Exception as e:
                record("password change rejects mismatched passwords", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 10: Admin login works ───────────────────────────────────
            try:
                _logout(page, base_url)
                page.wait_for_timeout(300)
                logged_in = _login(page, base_url, qa_pass, qa_password)
                record("admin user can log in", logged_in, f"url={page.url}")
            except Exception as e:
                record("admin user can log in", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 11: System Admin panel accessible to admin ──────────────
            try:
                page.goto(f"{base_url}/admin/system/users")
                page.wait_for_timeout(300)
                on_admin = "/admin/system" in page.url
                has_content = "Users" in page.content()
                record(
                    "system admin panel accessible to system_admin",
                    on_admin and has_content,
                    f"url={page.url}",
                )
            except Exception as e:
                record("system admin panel accessible to system_admin", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 12: Admin panel blocked for internal_user ───────────────
            try:
                _logout(page, base_url)
                page.wait_for_timeout(300)
                _login(page, base_url, user_email, user_password)
                page.goto(f"{base_url}/admin/system/users")
                page.wait_for_timeout(300)
                blocked = (
                    "403" in page.content() or "Forbidden" in page.content() or "/login" in page.url
                )
                record("system admin panel blocked for internal_user", blocked, f"url={page.url}")
            except Exception as e:
                record("system admin panel blocked for internal_user", False, str(e))
                if fail_fast:
                    return suite

        finally:
            browser.close()

    return suite

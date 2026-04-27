"""
Evidence suite — upload photo, delete file, 403 for unauthorized user.
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


def _make_tiny_png() -> bytes:
    """Return a minimal valid PNG (1x1 white pixel)."""
    import struct
    import zlib

    def chunk(name: bytes, data: bytes) -> bytes:
        c = name + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    raw = b"\x00\xff\xff\xff"
    idat = zlib.compress(raw)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def run(
    base_url: str,
    config: dict[str, Any],
    factory: DataFactory,
    fail_fast: bool = False,
) -> SuiteResult:
    suite = SuiteResult(name="evidence")
    admin_email = config["QA_ADMIN_EMAIL"]
    admin_password = config["QA_ADMIN_PASSWORD"]
    headful = config.get("QA_HEADFUL", "").lower() == "true"
    pw = factory.password_for()

    # Setup
    internal_group = factory.create_internal_group()
    int_user = factory.create_internal_user(internal_group)
    ext_group = factory.create_external_group()
    ext_user = factory.create_external_user(ext_group)

    matter = factory.create_matter(internal_group, int_user)

    def record(name: str, passed: bool, message: str = "") -> None:
        suite.results.append(
            TestResult(suite="evidence", name=name, passed=passed, message=message)
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=not headful)
        ctx = browser.new_context()
        page = ctx.new_page()

        try:
            _login(page, base_url, admin_email, admin_password)

            # ── Test 1: Evidence tab loads on matter ─────────────────────────
            try:
                page.goto(f"{base_url}/matters/{matter.id}")
                page.wait_for_timeout(500)
                # Click Evidence tab if present
                evidence_tab = page.locator('a:has-text("Evidence"), button:has-text("Evidence")')
                if evidence_tab.count() > 0:
                    evidence_tab.first.click()
                    page.wait_for_timeout(300)
                has_upload = (
                    page.locator('input[type="file"]').count() > 0
                    or "Upload" in page.content()
                    or "evidence" in page.content().lower()
                )
                record("evidence tab loads", has_upload, f"url={page.url}")
            except Exception as e:
                record("evidence tab loads", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 2: Upload a photo ───────────────────────────────────────
            try:
                page.goto(f"{base_url}/matters/{matter.id}")
                page.wait_for_timeout(500)

                csrf = next((c["value"] for c in ctx.cookies() if c["name"] == "cvp_csrf"), "")
                png_bytes = _make_tiny_png()

                resp = page.request.post(
                    f"{base_url}/api/matters/{matter.id}/evidence",
                    multipart={
                        "file": {
                            "name": f"qa_test_{factory.run_ts}.png",
                            "mimeType": "image/png",
                            "buffer": png_bytes,
                        }
                    },
                    headers={"X-CSRF-Token": csrf},
                )
                record(
                    "upload evidence file returns 200", resp.status == 200, f"status={resp.status}"
                )

                # Track file id for deletion test
                file_id = None
                if resp.status == 200:
                    try:
                        data = resp.json()
                        file_id = data.get("id") or data.get("file_id")
                    except Exception:
                        pass

            except Exception as e:
                record("upload evidence file returns 200", False, str(e))
                file_id = None
                if fail_fast:
                    return suite

            # ── Test 3: Evidence file appears on matter page ─────────────────
            try:
                page.goto(f"{base_url}/matters/{matter.id}")
                page.wait_for_timeout(500)
                content = page.content()
                has_file = f"qa_test_{factory.run_ts}" in content or (
                    file_id and file_id in content
                )
                record("uploaded file appears on matter page", has_file)
            except Exception as e:
                record("uploaded file appears on matter page", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 4: Unauthenticated upload returns 403/401 ───────────────
            try:
                anon_ctx = browser.new_context()
                anon_page = anon_ctx.new_page()
                png_bytes = _make_tiny_png()
                resp = anon_page.request.post(
                    f"{base_url}/api/matters/{matter.id}/evidence",
                    multipart={
                        "file": {
                            "name": "anon_test.png",
                            "mimeType": "image/png",
                            "buffer": png_bytes,
                        }
                    },
                )
                record(
                    "unauthenticated upload returns 4xx",
                    resp.status in (401, 403),
                    f"status={resp.status}",
                )
                anon_ctx.close()
            except Exception as e:
                record("unauthenticated upload returns 4xx", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 5: External user without grant cannot upload ────────────
            try:
                # Log in as ext_user (no grant on this matter)
                ext_ctx = browser.new_context()
                ext_page = ext_ctx.new_page()
                ext_page.goto(f"{base_url}/login")
                ext_page.fill('input[name="email"]', ext_user.email)
                ext_page.fill('input[name="password"]', pw)
                ext_page.click('button[type="submit"]')
                ext_page.wait_for_timeout(1000)

                csrf_ext = next(
                    (c["value"] for c in ext_ctx.cookies() if c["name"] == "cvp_csrf"), ""
                )
                png_bytes = _make_tiny_png()
                resp = ext_page.request.post(
                    f"{base_url}/api/matters/{matter.id}/evidence",
                    multipart={
                        "file": {
                            "name": "ext_test.png",
                            "mimeType": "image/png",
                            "buffer": png_bytes,
                        }
                    },
                    headers={"X-CSRF-Token": csrf_ext},
                )
                record(
                    "external user without grant cannot upload (4xx)",
                    resp.status in (401, 403),
                    f"status={resp.status}",
                )
                ext_ctx.close()
            except Exception as e:
                record("external user without grant cannot upload (4xx)", False, str(e))
                if fail_fast:
                    return suite

            # ── Test 6: Delete uploaded file ─────────────────────────────────
            try:
                if file_id:
                    csrf = next((c["value"] for c in ctx.cookies() if c["name"] == "cvp_csrf"), "")
                    resp = page.request.delete(
                        f"{base_url}/api/evidence/{file_id}",
                        headers={"X-CSRF-Token": csrf},
                    )
                    record(
                        "delete evidence file returns 200",
                        resp.status == 200,
                        f"status={resp.status}",
                    )
                else:
                    record("delete evidence file returns 200", False, "no file_id from upload")
            except Exception as e:
                record("delete evidence file returns 200", False, str(e))
                if fail_fast:
                    return suite

        finally:
            browser.close()

    return suite

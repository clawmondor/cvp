"""Preflight checks: .env exists, required vars set, server is running."""

import os
import sys
from pathlib import Path

import requests


def load_env(env_path: Path) -> dict[str, str]:
    """Parse a .env file into a dict. Does not set os.environ."""
    env: dict[str, str] = {}
    if not env_path.exists():
        return env
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        # Strip inline comments and quotes
        value = value.split("#")[0].strip().strip('"').strip("'")
        env[key.strip()] = value
    return env


def run(project_root: Path) -> tuple[str, int]:
    """
    Run preflight checks. Returns (base_url, port) on success.
    Prints errors and calls sys.exit(1) on failure.
    """
    env_file = project_root / ".env"

    # 1. Check .env exists
    if not env_file.exists():
        print("ERROR: .env file not found.")
        print(f"       Expected: {env_file}")
        print("       Run: cp .env.example .env  and fill in the required values.")
        sys.exit(1)

    env = load_env(env_file)
    # Also read from os.environ (environment variables override .env for CI)
    merged = {**env, **{k: v for k, v in os.environ.items() if v}}

    # 2. Check required QA variables
    missing = []
    for key in ("QA_ADMIN_EMAIL", "QA_ADMIN_PASSWORD"):
        if not merged.get(key):
            missing.append(key)

    if missing:
        print("ERROR: Required QA environment variables are not set:")
        for key in missing:
            print(f"       {key}")
        print()
        print("Add these to your .env file:")
        print("  QA_ADMIN_EMAIL=admin@example.com")
        print("  QA_ADMIN_PASSWORD=your-admin-password")
        print()
        print("The admin user must exist and have system_admin role.")
        sys.exit(1)

    # 3. Determine port
    port_str = merged.get("PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        port = 8000

    base_url = f"http://localhost:{port}"

    # 4. Check server is running
    try:
        resp = requests.get(base_url + "/", timeout=3, allow_redirects=True)
        if resp.status_code >= 500:
            print(f"ERROR: Server at {base_url} returned HTTP {resp.status_code}.")
            print("       Check the server logs for errors.")
            sys.exit(1)
    except requests.ConnectionError:
        print(f"ERROR: Cannot connect to {base_url}.")
        print()
        print("Start the development server with:")
        print("  uv run dev")
        sys.exit(1)
    except requests.Timeout:
        print(f"ERROR: Server at {base_url} timed out.")
        print("       The server may be overloaded or stuck.")
        sys.exit(1)

    print(f"Preflight OK — server at {base_url}")

    # Return config for suites
    return base_url, port, merged

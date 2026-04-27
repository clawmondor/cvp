"""
QA test runner — entry point for the browser-based QA skill.

Usage:
  uv run python skills/qa/runner.py                    # all suites
  uv run python skills/qa/runner.py --suite auth       # one suite
  uv run python skills/qa/runner.py --fail-fast        # stop on first failure
  uv run python skills/qa/runner.py --suite items --fail-fast
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure project src is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
# Ensure skills/ is importable for relative imports within suites
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from skills.qa.preflight import run as preflight
from skills.qa.report import SuiteResult, print_suite_result, print_summary

SUITE_NAMES = ["auth", "rbac", "matters", "evidence", "items", "comments", "exports"]


def load_suite(name: str):
    """Dynamically import a suite module and return its run() function."""
    import importlib

    mod = importlib.import_module(f"skills.qa.suites.{name}")
    return mod.run


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run browser-based QA tests against the local dev server."
    )
    parser.add_argument(
        "--suite",
        choices=SUITE_NAMES,
        metavar="SUITE",
        help=f"Run only this suite. Choices: {', '.join(SUITE_NAMES)}",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop and report on first test failure.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available suites and exit.",
    )
    args = parser.parse_args()

    if args.list:
        print("Available suites:")
        for name in SUITE_NAMES:
            print(f"  {name}")
        return

    # Preflight — exits on failure
    base_url, port, config = preflight(Path(__file__).resolve().parents[2])

    # Determine which suites to run
    suites_to_run = [args.suite] if args.suite else SUITE_NAMES

    # Generate a run timestamp shared across all suites in this run
    run_ts = int(time.time())
    print(f"Run ID: {run_ts}")
    print(f"Suites: {', '.join(suites_to_run)}")
    print()

    from skills.qa.data_factory import DataFactory

    suite_results: list[SuiteResult] = []
    any_failed = False

    for suite_name in suites_to_run:
        print(f"Running suite: {suite_name} ...")
        factory = DataFactory(run_ts=run_ts)
        run_fn = load_suite(suite_name)

        try:
            result = run_fn(
                base_url=base_url,
                config=config,
                factory=factory,
                fail_fast=args.fail_fast,
            )
        except Exception as e:
            # Suite crashed — record as a single failure
            result = SuiteResult(name=suite_name)
            from skills.qa.report import TestResult

            result.results.append(
                TestResult(suite=suite_name, name="suite execution", passed=False, message=str(e))
            )
        finally:
            try:
                factory.teardown()
            except Exception as te:
                print(f"  WARNING: teardown error for suite {suite_name}: {te}")

        print_suite_result(result)
        suite_results.append(result)

        if not result.all_passed:
            any_failed = True
            if args.fail_fast:
                print("\n--fail-fast: stopping after first failing suite.")
                break

    print_summary(suite_results)
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()

"""Test result dataclass and summary reporting."""

from dataclasses import dataclass, field


@dataclass
class TestResult:
    suite: str
    name: str
    passed: bool
    message: str = ""


@dataclass
class SuiteResult:
    name: str
    results: list[TestResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for r in self.results if r.passed)

    @property
    def failed(self) -> int:
        return sum(1 for r in self.results if not r.passed)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def all_passed(self) -> bool:
        return self.failed == 0


def print_suite_result(suite_result: SuiteResult) -> None:
    print(f"\n  Suite: {suite_result.name}")
    for r in suite_result.results:
        icon = "✓" if r.passed else "✗"
        print(f"    {icon} {r.name}", end="")
        if not r.passed and r.message:
            print(f"\n      → {r.message}", end="")
        print()


def print_summary(suite_results: list[SuiteResult]) -> None:
    total_passed = sum(s.passed for s in suite_results)
    total_failed = sum(s.failed for s in suite_results)
    total = total_passed + total_failed

    print("\n" + "─" * 60)
    print("QA Summary")
    print("─" * 60)

    for sr in suite_results:
        status = "PASS" if sr.all_passed else "FAIL"
        print(f"  [{status}] {sr.name}: {sr.passed}/{sr.total}")

    print("─" * 60)
    if total_failed == 0:
        print(f"  All {total} tests passed.")
    else:
        print(f"  {total_passed}/{total} passed, {total_failed} failed.")
    print()

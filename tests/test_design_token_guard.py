import subprocess
import sys


def test_guard_passes_on_migrated_tree():
    r = subprocess.run(
        [sys.executable, "scripts/audit_design_tokens.py"], capture_output=True, text=True
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_guard_flags_a_raw_family(tmp_path, monkeypatch):
    # a raw-family utility anywhere in templates must fail the guard
    from scripts import audit_design_tokens as guard

    assert guard.find_raw_family_hits('<div class="bg-indigo-600">')  # raw family -> hit
    assert not guard.find_raw_family_hits(
        '<div class="bg-primary text-neutral-500">'
    )  # tokens -> clean

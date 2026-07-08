"""The full-scan progress fragment must expose a completion contract for app.js."""

from claimos.routers.vision import templates


def _render(**kw):
    base = dict(
        job_id="job-1",
        matter_id="m-1",
        status="done",
        progress=3,
        total=3,
        items_created=5,
        errors=[],
    )
    base.update(kw)
    return templates.get_template("_scan_progress.html").render(**base)


def test_done_state_exposes_completion_data_attrs():
    html = _render(status="done")
    assert 'data-scan-state="done"' in html
    assert 'data-job-id="job-1"' in html
    assert 'data-matter-id="m-1"' in html
    assert 'data-items-created="5"' in html


def test_error_state_exposes_completion_data_attrs():
    html = _render(status="error", items_created=2)
    assert 'data-scan-state="error"' in html
    assert 'data-items-created="2"' in html


def test_running_state_has_no_completion_attrs():
    html = _render(status="running", progress=1)
    assert "data-scan-state" not in html
    assert 'hx-trigger="every 2s"' in html  # still polling

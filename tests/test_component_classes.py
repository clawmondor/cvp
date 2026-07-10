"""The @layer components block declares the design-system component classes.

Verified against theme.css source (no Tailwind build), matching the no-build pattern
of the sibling token tests. That the classes actually COMPILE (@apply resolves) is
covered by the CI `css` build-health job and the Docker image build — both of which run
the real standalone binary, which is not available in the unit-test environment.
"""

import re
from pathlib import Path

THEME = Path("src/claimos/styles/theme.css")

COMPONENTS = [
    "card",
    "input",
    "btn-primary",
    "btn-secondary",
    "badge-success",
    "badge-error",
    "badge-warning",
]


def _components_layer() -> str:
    text = THEME.read_text()
    m = re.search(r"@layer\s+components\s*\{(.*)\n\}", text, re.DOTALL)
    assert m, "theme.css has no @layer components block"
    return m.group(1)


def test_all_component_classes_declared_with_apply():
    layer = _components_layer()
    for name in COMPONENTS:
        # e.g. `.btn-primary { ... @apply ...; }`
        pat = re.compile(rf"\.{re.escape(name)}\s*\{{[^}}]*@apply[^;]+;", re.DOTALL)
        assert pat.search(layer), f".{name} not declared with @apply in @layer components"

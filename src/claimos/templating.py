"""Single shared Jinja2Templates instance for the app (filters + globals registered once)."""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote_plus

from fastapi.templating import Jinja2Templates

from claimos.theming import theme_class_for

BASE_DIR = Path(__file__).parent

templates = Jinja2Templates(directory=BASE_DIR / "templates")
templates.env.filters["qplus"] = quote_plus
templates.env.filters["cents"] = lambda c: f"${c / 100:,.2f}" if c else "$0.00"
templates.env.filters["pretty_json"] = lambda v: json.dumps(json.loads(v), indent=2) if v else ""
templates.env.globals["theme_class"] = theme_class_for

from claimos.theming import theme_class_for


class _Req:
    def __init__(self, theme=None):
        self.cookies = {"theme": theme} if theme is not None else {}


def test_theme_class_dark():
    assert theme_class_for(_Req("dark")) == "dark"


def test_theme_class_light():
    assert theme_class_for(_Req("light")) == "light"


def test_theme_class_absent_is_system():
    assert theme_class_for(_Req()) == ""


def test_theme_class_unknown_is_system():
    assert theme_class_for(_Req("purple")) == ""

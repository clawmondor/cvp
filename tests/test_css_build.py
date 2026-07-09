from claimos import css_build


def test_build_command_default():
    cmd = css_build.build_command(watch=False, minify=False)
    assert cmd[0].endswith("bin/tailwindcss")
    assert "-i" in cmd and "-o" in cmd
    assert cmd[cmd.index("-i") + 1].endswith("src/claimos/styles/theme.css")
    assert cmd[cmd.index("-o") + 1].endswith("src/claimos/static/app.css")
    assert "--watch" not in cmd and "--minify" not in cmd


def test_build_command_watch_and_minify():
    cmd = css_build.build_command(watch=True, minify=True)
    assert "--watch" in cmd
    assert "--minify" in cmd

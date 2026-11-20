"""F in Code finds a file by name, or (Tab) a line by its text, and opens it."""

from test_code_debug_ui import debug_app
from test_tui_grouping import until
from textual.widgets import DataTable, Input, OptionList, TextArea

from debugpilot.tui.project_finder import ProjectFinder


def project(roots):
    root = roots[0]
    (root / "orders").mkdir()
    (root / "orders" / "models.py").write_text(
        "class Order:\n    total = 0\n    paid = False\n", encoding="utf-8")
    (root / "orders" / "views.py").write_text("def show(order):\n    return order\n",
                                              encoding="utf-8")
    (root / "README.md").write_text("# Shop\nThe order total includes tax.\n",
                                    encoding="utf-8")
    return root


def shown(app):
    options = app.screen.query_one("#find-results", OptionList)
    return [str(options.get_option_at_index(index).prompt)
            for index in range(options.option_count)]


def status(app):
    return str(app.screen.query_one("#find-status").render())


def modes(app):
    return str(app.screen.query_one("#find-modes").render())


async def open_finder(pilot, app):
    await pilot.click("#area-code")
    app.query_one("#code-projects", DataTable).focus()
    await pilot.press("f")
    await until(pilot, lambda: isinstance(app.screen, ProjectFinder)
                and isinstance(app.focused, Input) and app.focused.id == "find-query")
    # Ready once the files are listed.
    await until(pilot, lambda: "files" in status(app))


def editor(app):
    return app.query_one("#source-text", TextArea)


async def test_f_lists_the_files_and_typing_finds_one_by_name(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    project(roots)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_finder(pilot, app)
        assert "[Files]" in modes(app)
        assert shown(app) == ["README.md", "main.py", "orders/models.py", "orders/views.py"]
        assert status(app) == "4 files"
        await pilot.press(*"omod")
        await until(pilot, lambda: shown(app) == ["orders/models.py"])
        await pilot.press("enter")
        await until(pilot, lambda: not isinstance(app.screen, ProjectFinder))
        assert editor(app).text.startswith("class Order:")
        assert app.focused is editor(app)


async def test_tab_searches_the_text_and_enter_opens_the_line(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    project(roots)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_finder(pilot, app)
        await pilot.press("tab")
        assert "[Text]" in modes(app)
        assert status(app) == "Type at least 2 characters"
        await pilot.press(*"total")
        await until(pilot, lambda: shown(app) == [
            "README.md:2  The order total includes tax.",
            "orders/models.py:2  total = 0",
        ])
        assert status(app) == "2 matches"
        await pilot.press("down", "enter")
        await until(pilot, lambda: not isinstance(app.screen, ProjectFinder))
        assert editor(app).text.startswith("class Order:")
        assert editor(app).cursor_location == (1, 0)
        assert app.focused is editor(app)


async def test_tab_goes_back_to_files_with_the_same_query(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    project(roots)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_finder(pilot, app)
        await pilot.press("tab", *"views")
        await until(pilot, lambda: status(app) == "No line matches")
        await pilot.press("tab")
        assert "[Files]" in modes(app)
        await until(pilot, lambda: shown(app) == ["orders/views.py"])


async def test_escape_closes_without_opening_anything(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    project(roots)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_finder(pilot, app)
        await pilot.press(*"zzz")
        await until(pilot, lambda: status(app) == "No file matches")
        assert shown(app) == ["No file matches"]
        await pilot.press("enter")  # Nothing to open.
        assert isinstance(app.screen, ProjectFinder)
        await pilot.press("escape")
        await until(pilot, lambda: not isinstance(app.screen, ProjectFinder))
        assert editor(app).text == ""


async def test_f_types_in_a_text_field_instead(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.click("#area-code")
        app.query_one("#code-projects", DataTable).focus()
        await pilot.press("slash", "f")
        await pilot.pause()
        assert not isinstance(app.screen, ProjectFinder)
        assert app.query_one("#code-filter", Input).value == "f"

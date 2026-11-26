"""In Code, F finds a line by its text and Shift+F a file by its name, then opens it."""

from test_code_debug_ui import debug_app
from test_tui_grouping import until
from textual.widgets import DataTable, Input, OptionList, TextArea, Tree

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


def title(app):
    return str(app.screen.query_one("#find-title").render())


def placeholder(app):
    return app.screen.query_one("#find-query", Input).placeholder


async def open_finder(pilot, app, key="F"):
    """Shift+F finds a file, F a line of text."""
    await pilot.click("#area-code")
    app.query_one("#code-projects", DataTable).focus()
    await pilot.press(key)
    await until(pilot, lambda: isinstance(app.screen, ProjectFinder)
                and isinstance(app.focused, Input) and app.focused.id == "find-query")
    # Ready once the files are listed.
    await until(pilot, lambda: status(app) != "Listing files…")


def editor(app):
    return app.query_one("#source-text", TextArea)


async def test_shift_f_lists_the_files_and_typing_finds_one_by_name(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    project(roots)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_finder(pilot, app)
        assert title(app).startswith("Find a file in ") and placeholder(app) == "File name"
        assert "Tab" not in title(app)
        assert shown(app) == ["README.md", "main.py", "orders/models.py", "orders/views.py"]
        assert status(app) == "4 files"
        await pilot.press(*"omod")
        await until(pilot, lambda: shown(app) == ["orders/models.py"])
        await pilot.press("enter")
        await until(pilot, lambda: not isinstance(app.screen, ProjectFinder))
        assert editor(app).text.startswith("class Order:")
        assert app.focused is editor(app)


async def test_f_searches_the_text_and_enter_opens_the_line(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    project(roots)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_finder(pilot, app, "f")
        assert title(app).startswith("Find text in ") and placeholder(app) == "Text in the files"
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


async def test_tab_no_longer_switches_between_files_and_text(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    project(roots)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_finder(pilot, app, "f")
        await pilot.press(*"views", "tab")
        await until(pilot, lambda: status(app) == "No line matches")
        assert title(app).startswith("Find text in ") and placeholder(app) == "Text in the files"
        assert not app.screen.query("#find-modes")


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


def tree_cursor(app):
    node = app.query_one("#source-tree", Tree).cursor_node
    return node.data[0] if node is not None and node.data else None


async def test_the_opened_file_is_marked_in_the_tree(monkeypatch, tmp_path):
    app, roots, _store = debug_app(monkeypatch, tmp_path)
    root = project(roots)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_finder(pilot, app)
        await pilot.press(*"omod", "enter")
        await until(pilot, lambda: not isinstance(app.screen, ProjectFinder))
        # Its folder opens and the cursor sits on it, even inside a closed folder.
        await until(pilot, lambda: tree_cursor(app) == root / "orders" / "models.py")
        orders = app.query_one("#source-tree", Tree).cursor_node.parent
        assert orders.is_expanded
        # The editor keeps the keys; marking the tree never moves focus.
        assert app.focused is editor(app)
        await pilot.press("F")
        await until(pilot, lambda: isinstance(app.screen, ProjectFinder)
                    and "files" in status(app))
        await pilot.press(*"README", "enter")
        await until(pilot, lambda: tree_cursor(app) == root / "README.md")
        assert editor(app).text.startswith("# Shop")

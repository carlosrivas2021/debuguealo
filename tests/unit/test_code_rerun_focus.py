"""App shortcuts work again once the focused run pane's process has exited."""

from test_code_run_ui import setup_app
from test_tui_grouping import until


async def test_f5_reruns_from_the_focused_pane_after_the_process_exits(monkeypatch, tmp_path):
    marker = tmp_path / "runs"
    script = (
        f"from pathlib import Path; p=Path({str(marker)!r}); "
        "p.write_text(p.read_text()+'x' if p.exists() else 'x')"
    )
    app = setup_app(monkeypatch, tmp_path, script)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("f5")
        state = app.query_one("#code-run-state")
        await until(pilot, lambda: "Exited: 0" in str(state.render()))
        pane = app.query_one("#code-terminal")
        pane.focus()
        await pilot.pause()
        assert app.focused is pane and not pane.active
        assert app.check_action("debug_code", ()) is not False
        await pilot.press("f5")
        await until(pilot, lambda: marker.read_text() == "xx")


async def test_a_running_focused_pane_still_owns_the_keys(monkeypatch, tmp_path):
    app = setup_app(monkeypatch, tmp_path, "import time; time.sleep(30)")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("f5")
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: pane.active)
        pane.focus()
        await pilot.pause()
        assert app.check_action("run_code", ()) is False
        await pilot.click("#code-stop")


async def test_p_goes_to_the_running_program_terminal(monkeypatch, tmp_path):
    app = setup_app(monkeypatch, tmp_path, "import time; time.sleep(30)")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("f5")
        pane = app.query_one("#code-terminal")
        await until(pilot, lambda: pane.active)
        assert app.focused is not pane  # F5 keeps the focus on the profiles.
        await pilot.press("p")
        await until(pilot, lambda: app.focused is pane)
        await pilot.press("escape")  # Esc gives the keys back to the profiles.
        await until(pilot, lambda: app.query_one("#code-projects").has_focus)
        await pilot.click("#code-stop")

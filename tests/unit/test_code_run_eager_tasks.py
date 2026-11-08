"""Code runs must start under Textual's eager task factory, as in a real terminal."""

import asyncio

from test_code_run_ui import setup_app
from test_tui_grouping import until


async def test_f5_starts_the_process_when_the_loop_uses_eager_tasks(monkeypatch, tmp_path):
    # `debugealo` in a real terminal runs with asyncio.eager_task_factory (Textual's
    # run_async); the test harness does not, which hid this failure.
    loop = asyncio.get_running_loop()
    loop.set_task_factory(asyncio.eager_task_factory)
    try:
        app = setup_app(monkeypatch, tmp_path, "print('EAGER_OK', flush=True)")
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.click("#area-code")
            await pilot.press("f5")
            state = app.query_one("#code-run-state")
            await until(pilot, lambda: "Exited: 0" in str(state.render()))
            assert "EAGER_OK" in app.query_one("#code-terminal").render().plain
    finally:
        loop.set_task_factory(None)


async def test_a_failed_start_is_reported_instead_of_ready(monkeypatch, tmp_path):
    from debugpilot.tui.code_terminal import CodeTerminal

    async def broken(self, context):
        raise ValueError("unexpected start failure")

    monkeypatch.setattr(CodeTerminal, "start_context", broken)
    app = setup_app(monkeypatch, tmp_path, "print('never')")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.click("#area-code")
        await pilot.press("f5")
        state = app.query_one("#code-run-state")
        await until(pilot, lambda: "Unable to run" in str(state.render()))
        assert "unexpected start failure" in str(state.render())

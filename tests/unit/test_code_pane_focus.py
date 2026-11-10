"""Ctrl+Left / Ctrl+Right move focus between the Code panes, in screen order."""

from test_code_debug_ui import debug_app
from test_tui_grouping import until
from textual.widgets import TextArea, Tree

# Left to right on screen: profiles, file tree, source.


def pane(app):
    return getattr(app.focused, 'id', None)


async def press(pilot, key):
    await pilot.press(key)
    await pilot.pause()


async def test_ctrl_arrows_move_between_profiles_files_and_source(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.click('#area-code')
        app.query_one('#code-projects').focus()
        await pilot.pause()
        visited = []
        for _ in range(3):
            await press(pilot, 'ctrl+right')
            visited.append(pane(app))
        # Past the rightmost pane it wraps around to the profiles.
        assert visited == ['source-tree', 'source-text', 'code-projects']
        visited = []
        for _ in range(3):
            await press(pilot, 'ctrl+left')
            visited.append(pane(app))
        # And past the leftmost one back to the source.
        assert visited == ['source-text', 'source-tree', 'code-projects']


async def test_ctrl_left_in_the_source_moves_focus_not_the_cursor(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.click('#area-code')
        tree = app.query_one('#source-tree', Tree)
        tree.select_node(next(n for n in tree.root.children if str(n.label) == 'main.py'))
        await pilot.pause()
        editor = app.query_one('#source-text', TextArea)
        editor.focus()
        editor.move_cursor((3, 10))
        await press(pilot, 'ctrl+left')
        assert pane(app) == 'source-tree'
        assert editor.cursor_location == (3, 10)


async def test_ctrl_arrows_from_a_button_go_to_the_profiles(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.click('#area-code')
        app.query_one('#code-run').focus()
        await pilot.pause()
        await pilot.press('ctrl+right')
        await until(pilot, lambda: pane(app) == 'code-projects')


async def test_live_code_terminal_keeps_ctrl_arrows(monkeypatch, tmp_path):
    from test_code_run_ui import setup_app

    app = setup_app(monkeypatch, tmp_path, "print('READY', flush=True); input()")
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('f5')
        terminal = app.query_one('#code-terminal')
        await until(pilot, lambda: 'READY' in terminal.render().plain)
        terminal.focus()
        await pilot.pause()
        sent = []
        monkeypatch.setattr(terminal._session, 'write', sent.append)
        await press(pilot, 'ctrl+left')
        assert app.focused is terminal
        await pilot.click('#code-stop')


async def test_live_code_terminal_receives_o_instead_of_hiding_the_output(monkeypatch, tmp_path):
    from test_code_run_ui import setup_app

    app = setup_app(monkeypatch, tmp_path, "print('READY', flush=True); input()")
    async with app.run_test(size=(140, 45)) as pilot:
        await pilot.click('#area-code')
        await pilot.press('f5')
        terminal = app.query_one('#code-terminal')
        await until(pilot, lambda: 'READY' in terminal.render().plain)
        terminal.focus()
        await pilot.pause()
        sent = []
        monkeypatch.setattr(terminal._session, 'write', sent.append)
        await press(pilot, 'o')
        assert sent == ['o']
        assert app.query_one('#code-bottom').display
        await pilot.click('#code-stop')

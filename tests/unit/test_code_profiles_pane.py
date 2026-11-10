"""The Code profiles pane: count in the title, fixed spacing, and a resizable list."""

from test_code_debug_ui import debug_app
from textual.widgets import DataTable, Static


def rows(app):
    return app.query_one('#code-projects', DataTable).region.height


async def open_code(pilot, app):
    await pilot.click('#area-code')
    app.query_one('#code-projects').focus()
    await pilot.pause()


async def test_title_shows_the_count_without_header_or_status(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_code(pilot, app)
        assert str(app.query_one('#code-title', Static).render()) == 'PROFILES'
        count = app.query_one('#code-count', Static)
        assert str(count.render()) == '2'
        # The count sits against the right edge of the title row.
        row = app.query_one('#code-title-row')
        assert count.region.right == row.region.right - row.styles.padding.right
        assert not app.query_one('#code-status').display
        assert not app.query_one('#code-projects', DataTable).show_header


async def test_list_keeps_room_for_six_profiles_and_titles_have_a_blank_row(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_code(pilot, app)
        # Two profiles, but the list keeps the room of six.
        assert rows(app) == 6
        title = app.query_one('#code-title').region
        pane = app.query_one('#code-profiles-pane').region
        assert title.y - pane.y == 1
        splitter = app.query_one('#code-profiles-splitter').region
        files = app.query_one('#source-files-title').region
        assert files.y - splitter.bottom == 1


async def test_alt_arrows_resize_the_list_within_bounds(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_code(pilot, app)
        await pilot.press('alt+down')
        await pilot.pause()
        assert rows(app) == 7
        for _ in range(10):
            await pilot.press('alt+up')
        await pilot.pause()
        assert rows(app) == 2  # Never smaller than two rows.
        for _ in range(60):
            await pilot.press('alt+down')
        await pilot.pause()
        # The file tree always keeps at least four rows.
        assert app.query_one('#source-tree').region.height >= 4


async def test_dragging_the_splitter_resizes_the_list(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_code(pilot, app)
        await pilot.mouse_down('#code-profiles-splitter')
        await pilot.hover('#code-profiles-splitter', offset=(2, 3))
        await pilot.mouse_up('#code-profiles-splitter')
        await pilot.pause()
        assert rows(app) == 9
        # Dragging resizes; it never selects the handle's characters.
        assert not app.screen.selections
        handle = str(app.query_one('#code-profiles-splitter').render())
        assert set(handle) == {'─', '⇕'} and handle.count('⇕') == 1


async def test_empty_rows_of_the_list_show_the_sidebar_background(monkeypatch, tmp_path):
    app, _, _ = debug_app(monkeypatch, tmp_path)
    async with app.run_test(size=(140, 45)) as pilot:
        await open_code(pilot, app)
        # Fewer profiles than rows: the empty part must not look like a gray block.
        assert app.query_one('#code-projects', DataTable).styles.background.a == 0

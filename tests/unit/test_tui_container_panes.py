"""Ctrl+Left / Ctrl+Right in Containers: the list and the focusable view on the right."""

from test_tui_detail_cards import Fleet, start
from test_tui_grouping import ready, select_key, until
from textual.widgets import Input


def focused_id(app):
    return getattr(app.focused, 'id', None)


async def press(pilot, key):
    await pilot.press(key)
    await pilot.pause()


async def test_ctrl_arrows_switch_between_the_list_and_open_logs():
    app = start(Fleet())
    async with app.run_test(size=(160, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, 'container:shop-web')
        await pilot.pause()
        # Detail cards are text only: there is nothing on the right to focus.
        await press(pilot, 'ctrl+right')
        assert focused_id(app) == 'launch-profiles'
        await press(pilot, 'ctrl+l')
        assert focused_id(app) == 'log-entries'
        await press(pilot, 'ctrl+left')
        assert focused_id(app) == 'launch-profiles'
        await press(pilot, 'ctrl+right')
        assert focused_id(app) == 'log-entries'
        # Two panes: past either end it wraps to the other one.
        await press(pilot, 'ctrl+right')
        assert focused_id(app) == 'launch-profiles'


async def test_ctrl_right_reaches_the_project_overview():
    app = start(Fleet())
    async with app.run_test(size=(160, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, 'project:shop')
        await until(pilot, lambda: app.query_one('#project-overview').display)
        await press(pilot, 'ctrl+right')
        assert focused_id(app) == 'project-overview-table'
        await press(pilot, 'ctrl+left')
        assert focused_id(app) == 'launch-profiles'


async def test_log_filter_keeps_ctrl_arrows_for_moving_by_word():
    app = start(Fleet())
    async with app.run_test(size=(160, 40)) as pilot:
        await until(pilot, lambda: ready(app))
        select_key(app, 'container:shop-web')
        await press(pilot, 'ctrl+l')
        field = app.query_one('#filter-logs', Input)
        field.focus()
        field.value = 'error timeout'
        field.cursor_position = len(field.value)
        await press(pilot, 'ctrl+left')
        assert focused_id(app) == 'filter-logs'
        assert field.cursor_position == len('error ')

"""Terminal panes keep a scrollback: wheel and Shift+PgUp/PgDn read back, typing returns."""

from types import SimpleNamespace

import pyte
from textual.app import App

from debugpilot.tui.terminal_view import ScrollbackScreen, TerminalPane, resize_screen


def text_of(line, columns):
    return "".join(line[x].data for x in range(columns)).rstrip()


def feed(screen, count, start=0):
    pyte.Stream(screen).feed("".join(f"L{index}\r\n" for index in range(start, start + count)))


def test_lines_scrolled_off_the_top_are_kept():
    screen = ScrollbackScreen(20, 5)
    feed(screen, 12)
    # 12 lines and the empty line after them: 8 left the 5-row screen.
    assert [text_of(line, 20) for line in screen.scrollback] == [f"L{i}" for i in range(8)]
    assert screen.kept == 8


def test_a_scrolling_region_is_not_history():
    # Full-screen programs scroll a region under a fixed header; that is not output history.
    screen = ScrollbackScreen(20, 6)
    screen.set_margins(2, 6)
    screen.cursor_position(6, 1)
    pyte.Stream(screen).feed("x\r\n" * 5)
    assert not screen.scrollback


def test_shrinking_the_screen_keeps_the_rows_it_drops():
    screen = ScrollbackScreen(20, 10)
    feed(screen, 8)
    resize_screen(screen, 4, 20)
    assert [text_of(line, 20) for line in screen.scrollback] == ["L0", "L1", "L2", "L3", "L4"]


class TerminalApp(App):
    def compose(self):
        yield TerminalPane(id="pane")


def shown(pane):
    return [line.rstrip() for line in pane.render().plain.split("\n")]


async def test_reading_back_with_keys_and_wheel_while_output_continues():
    app = TerminalApp()
    async with app.run_test(size=(40, 8)) as pilot:
        pane = app.query_one(TerminalPane)
        written = []
        async def closed():
            return None

        pane._session = SimpleNamespace(write=written.append, resize=lambda *_: None,
                                        close_session=closed)
        pane._session_closed = False
        pane.on_resize()
        rows = pane._screen_size()[0]
        pane._accept_output(pane._generation, "".join(f"L{i}\r\n" for i in range(30)))
        assert shown(pane)[-2] == "L29"
        pane.focus()

        await pilot.press("shift+pageup")
        page = rows - 1
        assert shown(pane)[0].startswith(f" ↑ {page} lines back")
        # A page above the live bottom row (the empty line after L29).
        assert shown(pane)[-1] == f"L{30 - page}"
        # New output arrives below; the view stays on the same text.
        pane._accept_output(pane._generation, "L30\r\nL31\r\n")
        assert shown(pane)[-1] == f"L{30 - page}"

        pane.on_mouse_scroll_down(SimpleNamespace(stop=lambda: None))
        assert shown(pane)[-1] == f"L{30 - page + 3}"
        pane.on_mouse_scroll_up(SimpleNamespace(stop=lambda: None))
        assert shown(pane)[-1] == f"L{30 - page}"

        # Typing goes to the program and shows the live screen again.
        await pilot.press("a")
        assert written == ["a"]
        assert not shown(pane)[0].startswith(" ↑") and shown(pane)[-2] == "L31"


async def test_reading_back_works_after_the_program_ended():
    app = TerminalApp()
    async with app.run_test(size=(40, 8)) as pilot:
        pane = app.query_one(TerminalPane)
        pane._session_closed = False
        pane.on_resize()
        pane._accept_output(pane._generation, "".join(f"L{i}\r\n" for i in range(20)))
        pane._accept_exit(pane._generation)
        pane.focus()
        await pilot.press("shift+pageup", "shift+pageup", "shift+pageup", "shift+pageup")
        assert shown(pane)[1] == "L0"  # The top of the scrollback, under the notice.
        await pilot.press("shift+pagedown", "shift+pagedown", "shift+pagedown",
                          "shift+pagedown")
        assert not shown(pane)[0].startswith(" ↑")

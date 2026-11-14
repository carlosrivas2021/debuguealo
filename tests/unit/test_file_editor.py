"""The in-app editor: one or two files, Ctrl+S saves, Esc closes and guards unsaved edits."""

from textual.app import App
from textual.widgets import TextArea

from debugpilot.storage.text_files import load_text
from debugpilot.tui.file_editor import EditableFile, FileEditorScreen
from debugpilot.tui.launch_file import format_launch_text


class EditorApp(App):
    def __init__(self, files):
        super().__init__()
        self.files = files
        self.results = []

    def on_mount(self):
        self.push_screen(FileEditorScreen(self.files), self.results.append)


def _messages(app):
    return [item.message for item in app._notifications]


def _aws_files(tmp_path):
    config, credentials = tmp_path / "config", tmp_path / "credentials"
    config.write_text("[default]\nregion = us-east-1\n", encoding="utf-8")
    return [
        EditableFile("AWS config", load_text(config)),
        EditableFile("AWS credentials", load_text(credentials)),
    ], config, credentials


def _areas(app):
    return list(app.screen.query(TextArea))


def _title(app, index):
    return str(app.screen.query(".editor-title")[index].render())


async def test_two_files_open_side_by_side_with_their_contents(tmp_path):
    files, config, _ = _aws_files(tmp_path)
    app = EditorApp(files)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        left, right = _areas(app)
        assert left.text == "[default]\nregion = us-east-1\n" and right.text == ""
        assert left.region.y == right.region.y and left.region.x < right.region.x
        assert "AWS config" in _title(app, 0) and str(config) in _title(app, 0)
        assert "new file" in _title(app, 1)
        assert app.focused is left


async def test_ctrl_s_saves_every_modified_file_and_clears_the_marker(tmp_path):
    files, config, credentials = _aws_files(tmp_path)
    app = EditorApp(files)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        left, right = _areas(app)
        left.insert("# edited\n", (0, 0))
        right.insert("[default]\naws_access_key_id = X\n")
        await pilot.pause()
        assert "●" in _title(app, 0) and "●" in _title(app, 1)

        await pilot.press("ctrl+s")
        await pilot.pause()

        assert config.read_text(encoding="utf-8") == "# edited\n[default]\nregion = us-east-1\n"
        assert credentials.read_text(encoding="utf-8") == "[default]\naws_access_key_id = X\n"
        assert "●" not in _title(app, 0) and "●" not in _title(app, 1)
        assert "Saved 2 files" in _messages(app)


async def test_launch_json_is_validated_and_formatted_on_save(tmp_path):
    target = tmp_path / "launch.json"
    target.write_text('{"version": 1, "configurations": []}', encoding="utf-8")
    app = EditorApp([EditableFile("launch.json", load_text(target), language="json",
                                  normalize=format_launch_text)])
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        (area,) = _areas(app)
        area.text = '{"version": 1,\n "configurations": [\n}'
        await pilot.press("ctrl+s")
        await pilot.pause()
        assert "Invalid JSON in launch.json at line 3, column 1." in "\n".join(_messages(app))
        assert target.read_text(encoding="utf-8") == '{"version": 1, "configurations": []}'
        assert "●" in _title(app, 0) and isinstance(app.screen, FileEditorScreen)

        area.text = '{"version":1,"configurations":[]}'
        await pilot.press("ctrl+s")
        await pilot.pause()
        formatted = '{\n  "version": 1,\n  "configurations": []\n}\n'
        assert target.read_text(encoding="utf-8") == formatted
        assert area.text == formatted
        assert "●" not in _title(app, 0)


async def test_a_conflicting_save_keeps_the_edits_and_says_why(tmp_path):
    files, config, _ = _aws_files(tmp_path)
    app = EditorApp(files)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        left, _right = _areas(app)
        left.insert("# mine\n", (0, 0))
        config.write_text("newer elsewhere\n", encoding="utf-8")
        await pilot.press("ctrl+s")
        await pilot.pause()

        assert config.read_text(encoding="utf-8") == "newer elsewhere\n"
        assert any("changed on disk since it was opened" in m for m in _messages(app))
        assert "●" in _title(app, 0)


async def test_escape_closes_right_away_without_changes(tmp_path):
    files, _, _ = _aws_files(tmp_path)
    app = EditorApp(files)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, FileEditorScreen)
        assert app.results == [False]


async def test_escape_with_unsaved_changes_warns_then_discards_on_a_second_press(tmp_path):
    files, config, _ = _aws_files(tmp_path)
    app = EditorApp(files)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        _areas(app)[0].insert("# draft\n", (0, 0))
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, FileEditorScreen)
        assert any("Unsaved changes" in m for m in _messages(app))

        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, FileEditorScreen)
        assert config.read_text(encoding="utf-8") == "[default]\nregion = us-east-1\n"
        assert app.results == [False]


async def test_closing_after_a_save_reports_that_something_was_saved(tmp_path):
    files, _, _ = _aws_files(tmp_path)
    app = EditorApp(files)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        _areas(app)[0].insert("# edited\n", (0, 0))
        await pilot.press("ctrl+s")
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert app.results == [True]


async def test_editing_after_the_warning_warns_again_instead_of_discarding(tmp_path):
    files, _, _ = _aws_files(tmp_path)
    app = EditorApp(files)
    async with app.run_test(size=(120, 30)) as pilot:
        await pilot.pause()
        area = _areas(app)[0]
        area.insert("# one\n", (0, 0))
        await pilot.press("escape")
        await pilot.pause()
        area.insert("# two\n", (0, 0))
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        assert isinstance(app.screen, FileEditorScreen)
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, FileEditorScreen)

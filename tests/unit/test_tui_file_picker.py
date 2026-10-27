from test_tui_compose import Service
from textual.app import App
from textual.widgets import Button, DirectoryTree, Input, Static, TextArea

from debugpilot.docker.compose import ComposeProject
from debugpilot.tui.compose_dialog import ComposeDialog
from debugpilot.tui.file_picker import ComposeFilePicker


class InspectService(Service):
    def __init__(self):
        super().__init__()
        self.inspections = []

    async def inspect_project(self, workspace, files):
        self.inspections.append((workspace, files))
        return ComposeProject.create(workspace, files, "dp-demo-orders")


async def test_picker_path_selection_and_up_navigation(tmp_path):
    file = tmp_path / "compose.yaml"
    file.write_text("name: dp-demo-orders\nservices: {}")
    app, chosen = App(), []
    async with app.run_test(size=(100, 40)) as pilot:
        picker = ComposeFilePicker(tmp_path)
        app.push_screen(picker, chosen.append)
        await pilot.pause()
        await pilot.click("#file-up")
        await pilot.pause()
        assert picker.query_one("#file-path", Input).value == str(tmp_path.parent)
        picker.query_one("#file-path", Input).value = str(file)
        await pilot.click("#file-open")
        await pilot.pause()
        assert chosen == [file.resolve()]


async def test_browse_cancel_does_not_inspect_or_run():
    app, service = App(), InspectService()
    async with app.run_test(size=(120, 45)) as pilot:
        dialog = ComposeDialog(service, None, initial_action="start", browse_on_mount=True)
        app.push_screen(dialog)
        await pilot.pause()
        for _ in range(30):
            if isinstance(app.screen, ComposeFilePicker):
                break
            await pilot.pause(0.02)
        assert isinstance(app.screen, ComposeFilePicker)
        await pilot.press("escape")
        await pilot.pause()
        assert not service.inspections and not service.runs
        assert dialog.query_one("#compose-confirm", Button).disabled


async def test_browsed_file_identity_preview_confirm_and_pinned_rejection(tmp_path):
    file = tmp_path / "compose.yaml"
    file.write_text("name: dp-demo-orders\nservices: {}")
    app, service = App(), InspectService()
    async with app.run_test(size=(120, 45)) as pilot:
        dialog = ComposeDialog(service, None, initial_action="start")
        app.push_screen(dialog)
        await pilot.pause()
        await pilot.click("#compose-browse")
        await pilot.pause()
        app.screen.query_one("#file-path", Input).value = str(file)
        await pilot.click("#file-open")
        await pilot.pause()
        assert dialog.query_one("#compose-workspace", Input).value == str(tmp_path)
        assert dialog.query_one(TextArea).text == str(file.resolve())
        assert not service.inspections and not service.runs
        await pilot.click("#compose-preview")
        await pilot.pause()
        assert dialog.query_one("#compose-project", Input).value == "dp-demo-orders"
        assert not dialog.query_one("#compose-confirm", Button).disabled
        assert not service.runs
        await pilot.click("#compose-confirm")
        await pilot.pause()
        assert len(service.runs) == 1 and service.runs[0][0].action == "start"
        await pilot.press("escape")
        pinned = ComposeDialog(service, None, selected_project="other", initial_action="start")
        app.push_screen(pinned)
        await pilot.pause()
        pinned.query_one("#compose-workspace", Input).value = str(tmp_path)
        pinned.query_one(TextArea).text = str(file)
        await pilot.pause()
        await pilot.click("#compose-preview")
        await pilot.pause()
        assert pinned.query_one("#compose-confirm", Button).disabled
        assert "different Compose project" in str(
            pinned.query_one("#compose-status", Static).render()
        )
        assert len(service.runs) == 1


async def test_ordered_manual_overrides_after_browse_keep_preview_guard(tmp_path):
    base, override = tmp_path / "compose.yaml", tmp_path / "local.yaml"
    base.write_text("name: dp-demo-orders\nservices: {}")
    override.write_text("services: {}")
    app, service = App(), InspectService()
    async with app.run_test(size=(120, 45)) as pilot:
        dialog = ComposeDialog(service, None, initial_action="start")
        app.push_screen(dialog)
        await pilot.pause()
        dialog._file_chosen(base)
        dialog.query_one(TextArea).text += "\n" + str(override)
        await pilot.pause()
        await pilot.click("#compose-preview")
        await pilot.pause()
        assert service.inspections[-1][1] == (base, override)
        assert not dialog.query_one("#compose-confirm", Button).disabled
        dialog.query_one(TextArea).text = str(base)
        await pilot.pause()
        assert dialog.query_one("#compose-confirm", Button).disabled
        assert not service.runs


async def test_lazy_tree_selection_and_invalid_extension(tmp_path):
    file, other = tmp_path / "compose.yml", tmp_path / "notes.txt"
    file.write_text("services: {}")
    other.write_text("not yaml")
    app, chosen = App(), []
    async with app.run_test(size=(100, 40)) as pilot:
        picker = ComposeFilePicker(tmp_path)
        app.push_screen(picker, chosen.append)
        await pilot.pause()
        picker.query_one(Input).value = str(other)
        await pilot.click("#file-open")
        await pilot.pause()
        assert not chosen and app.screen is picker
        tree = picker.query_one(DirectoryTree)
        tree.post_message(DirectoryTree.FileSelected(tree.root, file))
        await pilot.pause()
        assert chosen == [file.resolve()]

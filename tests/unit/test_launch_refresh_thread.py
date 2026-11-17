"""The periodic refresh reads launch profiles off the UI thread, and never applies stale ones."""

import threading

from test_tui_grouping import Docker, until

from debugpilot.core.engine import DebugPilotEngine
from debugpilot.storage.config import Settings
from debugpilot.storage.launch_profiles import LaunchProfile, LaunchProfileStore
from debugpilot.tui.app import DebugPilotApp


async def test_periodic_profile_reads_run_outside_the_ui_thread(monkeypatch):
    ui_thread = threading.current_thread()
    readers = []
    profiles = LaunchProfileStore.profiles

    def recorded(self, *args, **kwargs):
        readers.append(threading.current_thread())
        return profiles(self, *args, **kwargs)

    monkeypatch.setattr(LaunchProfileStore, "profiles", recorded)
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: len(readers) >= 3)
        # Slow disks (a Windows drive from WSL) must never freeze moving through the list.
        assert all(reader is not ui_thread for reader in readers[-3:])
        assert app._launch_loaded


async def test_a_slower_background_read_never_overwrites_newer_profiles(monkeypatch):
    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), refresh_interval=0.05)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._launch_loaded)
        started, release = threading.Event(), threading.Event()
        read = app._read_launch_profiles
        stale = LaunchProfile("Stale", "stale-project", None, {"name": "Stale"})

        def slow(inventory):
            if threading.current_thread() is threading.main_thread():
                return read(inventory)
            started.set()
            release.wait(5)
            return [stale]

        applied = []
        update = app._update_launch_profiles

        def recorded(*args, **kwargs):
            update(*args, **kwargs)
            applied.append(list(app._launch_profiles))

        monkeypatch.setattr(app, "_update_launch_profiles", recorded)
        monkeypatch.setattr(app, "_read_launch_profiles", slow)
        await until(pilot, lambda: started.is_set())
        # Meanwhile the UI applies fresh profiles (as after saving launch.json).
        monkeypatch.setattr(app, "_read_launch_profiles", read)
        app._update_launch_profiles()
        fresh = list(app._launch_profiles)
        release.set()
        await pilot.pause(0.3)
        # The read that started before the update is dropped, never shown even briefly.
        assert not any(stale in profiles for profiles in applied)
        assert app._launch_profiles == fresh

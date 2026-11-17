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
        # Startup reads once on the UI thread on purpose; count the periodic reads after it.
        await until(pilot, lambda: sum(reader is not ui_thread for reader in readers) >= 3)
        first_periodic = next(index for index, reader in enumerate(readers)
                              if reader is not ui_thread)
        # Slow disks (a Windows drive from WSL) must never freeze moving through the list.
        assert all(reader is not ui_thread for reader in readers[first_periodic:])
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


async def test_a_single_failed_read_keeps_the_profiles_and_a_repeated_one_is_shown(monkeypatch):
    # Saving launch.json (or Windows briefly locking it) can make one read fail.
    from debugpilot.core.exceptions import ConfigurationError

    app = DebugPilotApp(DebugPilotEngine(Settings(), docker=Docker()), refresh_interval=60)
    async with app.run_test(size=(120, 40)) as pilot:
        await until(pilot, lambda: app._launch_loaded)
        # Drive the refresh by hand: a periodic pass finishing in between would reset it.
        app._ui_tasks[0].cancel()
        await pilot.pause(0.2)
        shown = list(app._launch_profiles)
        read = app._read_launch_profiles

        def broken(inventory):
            raise ConfigurationError("Invalid launch profile JSON")

        monkeypatch.setattr(app, "_read_launch_profiles", broken)
        await app._refresh_launch_profiles(None)
        assert app._launch_error is None and app._launch_profiles == shown
        await app._refresh_launch_profiles(None)  # Still broken: now it is shown.
        assert app._launch_error == "Invalid launch profile JSON"
        monkeypatch.setattr(app, "_read_launch_profiles", read)
        await app._refresh_launch_profiles(None)
        assert app._launch_error is None
        await pilot.pause()

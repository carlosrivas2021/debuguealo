import pytest


@pytest.fixture(autouse=True)
def disable_update_check(monkeypatch):
    # The dashboard checks GitHub for new releases; tests must never reach the network.
    monkeypatch.setenv("DEBUGEALO_NO_UPDATE_CHECK", "1")

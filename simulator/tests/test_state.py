import json
import uuid
from datetime import datetime, timedelta, timezone

from appliance_simulator.state import DeviceState


def command(revision=1):
    return dict(device_id="device-001", command_id=str(uuid.uuid4()), revision=revision,
                desired={"power": True, "speed_percent": 40},
                expires_at=(datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat())


def test_duplicate_and_reordered_command_do_not_regress(tmp_path):
    state = DeviceState(tmp_path / "state.sqlite", "device-001")
    first = command()
    assert state.apply(first) == "applied"
    assert state.apply(first) == "duplicate"
    conflict = dict(first, desired={"power": False, "speed_percent": 0})
    assert state.apply(conflict) == "conflict"
    assert state.apply(command(2)) == "applied"
    assert state.apply(first) == "stale"
    assert state.snapshot()["revision"] == 2
    state.close()


def test_expired_command_and_naive_time_rejected(tmp_path):
    state = DeviceState(tmp_path / "s.sqlite", "device-001")
    expired = command()
    expired["expires_at"] = "2020-01-01T00:00:00Z"
    assert state.apply(expired) == "expired"
    expired["expires_at"] = "2099-01-01T00:00:00"
    assert state.apply(expired) == "invalid"
    assert state.snapshot()["revision"] == 0
    state.close()


def test_restart_preserves_command_and_pending_but_changes_meter_epoch(tmp_path):
    path = tmp_path / "s.sqlite"
    state = DeviceState(path, "device-001")
    state.apply(command())
    event = state.sample(10)
    previous_boot = state.boot_id
    state.close()
    restored = DeviceState(path, "device-001")
    assert restored.snapshot()["revision"] == 1
    assert restored.boot_id != previous_boot
    assert restored.pending() == [event]
    restored.acknowledge(event["event_id"])
    restored.acknowledge(event["event_id"])
    assert restored.stats() == {"dropped": 0, "accepted": 1, "pending": 0}
    restored.close()


def test_overflow_is_visible_and_bounded(tmp_path):
    state = DeviceState(tmp_path / "s.sqlite", "device-001", capacity=1)
    assert state.sample(10) is not None
    assert state.sample(10) is None
    assert state.stats()["dropped"] == 1
    assert state.stats()["pending"] == 1
    state.close()

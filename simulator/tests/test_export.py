import json
from types import SimpleNamespace

import pytest

from appliance_simulator.export import publish_batch


def test_batch_replay_and_integrity(tmp_path):
    event = {"event_id": "event1", "event_time": "2026-01-01T00:00:00Z", "power_w": 2}
    records = [SimpleNamespace(value=event, topic="t", partition=0, offset=4)]
    first = publish_batch(records, tmp_path)
    assert publish_batch(records, tmp_path) == first
    assert len(list(tmp_path.iterdir())) == 1
    assert json.loads((first / "manifest.json").read_text())["row_count"] == 1
    (first / "events.jsonl").write_text("corrupted")
    with pytest.raises(ValueError, match="integrity"):
        publish_batch(records, tmp_path)


def test_empty_batch_does_not_publish(tmp_path):
    assert publish_batch([], tmp_path) is None
    assert list(tmp_path.iterdir()) == []

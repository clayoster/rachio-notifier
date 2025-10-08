import json
import pytest
from rachio_notifier import (
    write_persistent_data,
    load_persistent_data,
    notification,
    get_devicestate,
    time_magic,
    main
)

def test_write_and_load(fake_jsondata):
    write_persistent_data("2025-10-05T12:00:00Z", True)
    old_next_run, old_reminder = load_persistent_data()
    assert old_next_run == "2025-10-05T12:00:00Z"
    assert old_reminder is True

def test_notification(mock_https):
    notification("Test")
    mock_https.request.assert_called_once()
    mock_https.getresponse.assert_called_once()
    mock_https.close.assert_called_once()

def test_get_devicestate(monkeypatch, mock_https):
    mock_https.getresponse.return_value.read.return_value = json.dumps({
        "state": {"state": "IDLE", "nextRun": "2025-10-05T12:00:00Z"}
    }).encode()

    device_state, next_run = get_devicestate()
    assert device_state == "IDLE"
    assert next_run == "2025-10-05T12:00:00Z"

def test_time_magic_tomorrow(monkeypatch):
    from datetime import datetime, timedelta
    import pytz

    tz = pytz.timezone("America/Chicago")
    fixed_now = datetime(2025, 10, 1, 18, 0, tzinfo=tz)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return fixed_now

    # Replace datetime in rachio_notifier with our subclass
    monkeypatch.setattr("rachio_notifier.datetime", FixedDateTime)

    _, _, _, _, tomorrow = time_magic("2025-10-02T12:00:00Z")
    assert tomorrow is True

def test_main_idle_updates(fake_jsondata, monkeypatch):
    # Define object to capture log messages
    logs = []
    write_persistent_data("2025-10-01T12:00:00Z", False)

    monkeypatch.setattr("rachio_notifier.get_devicestate", lambda: ("IDLE", "2025-10-02T12:00:00Z"))
    monkeypatch.setattr("rachio_notifier.time_magic", lambda n: (19, "Thursday", "7:00PM", "10/2", True))
    monkeypatch.setattr("rachio_notifier.notification", lambda msg: None)
    monkeypatch.setattr("rachio_notifier.log_msg", lambda msg: logs.append(msg))
    
    main()
    with open(fake_jsondata) as f:
        data = json.load(f)
    assert data["next_run"] == "2025-10-02T12:00:00Z"
    assert data["reminder"] is True
    assert logs, "log_msg should have been called"
    assert "Irrigation Schedule Changed" in logs[0]

# Test the reminder logic when the schedule is set to run tomorrow
def test_main_idle_updates_reminder(fake_jsondata, monkeypatch):
    # Define object to capture log messages
    logs = []
    write_persistent_data("2025-10-02T12:00:00Z", False)

    monkeypatch.setattr("rachio_notifier.get_devicestate", lambda: ("IDLE", "2025-10-02T12:00:00Z"))
    monkeypatch.setattr("rachio_notifier.time_magic", lambda n: (19, "Thursday", "7:00PM", "10/2", True))
    monkeypatch.setattr("rachio_notifier.notification", lambda msg: None)
    monkeypatch.setattr("rachio_notifier.log_msg", lambda msg: logs.append(msg))
    
    main()
    with open(fake_jsondata) as f:
        data = json.load(f)
    assert data["next_run"] == "2025-10-02T12:00:00Z"
    assert data["reminder"] is True
    assert logs, "log_msg should have been called"
    assert "No change to irrigation schedule was detected" in logs[0]
    assert any("Reminder: Sprinklers will run tomorrow at" in log for log in logs)

def test_main_watering(monkeypatch, no_exit):
    # Define object to capture log messages
    logs = []

    # Mock get_devicestate and log_msg
    monkeypatch.setattr("rachio_notifier.get_devicestate", lambda: ("WATERING", None))
    monkeypatch.setattr("rachio_notifier.load_persistent_data", lambda: ("2025-10-01T12:00:00Z", False))
    monkeypatch.setattr("rachio_notifier.log_msg", lambda msg: logs.append(msg))

    # Expect sys.exit to be called
    with pytest.raises(SystemExit):
        main()

    # Confirm that log_msg was called with the expected message
    assert logs, "log_msg should have been called"
    assert logs[0] == "Sprinklers are currently running. Not evaluating the schedule at this time."

def test_main_standby(monkeypatch, no_exit):
    # Define object to capture log messages
    logs = []

    monkeypatch.setattr("rachio_notifier.get_devicestate", lambda: ("STANDBY", None))
    monkeypatch.setattr("rachio_notifier.load_persistent_data", lambda: (None, False))
    monkeypatch.setattr("rachio_notifier.log_msg", lambda msg: logs.append(msg))
    with pytest.raises(SystemExit):
        main()

    assert logs, "log_msg should have been called"
    assert logs[0] == "Controller is in hibernation mode. No schedule to evaluate."

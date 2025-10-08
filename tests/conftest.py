import os
import pytest
from unittest.mock import MagicMock

# Set Environment Variables
os.environ["RACHIO_API_TOKEN"] = "fake_token"
os.environ["RACHIO_DEVICE_ID"] = "fake_device_id"

@pytest.fixture(autouse=True)
def mock_https(monkeypatch):
    """
    Automatically mock http.client.HTTPSConnection for all tests
    so no real network calls are made.
    """
    mock_conn = MagicMock()
    mock_response = MagicMock()
    mock_response.read.return_value = b'{}'  # default empty body
    mock_conn.getresponse.return_value = mock_response

    monkeypatch.setattr("http.client.HTTPSConnection", lambda *a, **kw: mock_conn)
    return mock_conn

@pytest.fixture(autouse=True)
def fake_jsondata(tmp_path, monkeypatch):
    """
    Redirect rachio_notifier.JSONDATA into a temporary file.
    """
    testfile = tmp_path / "rachio.json"
    monkeypatch.setattr("rachio_notifier.JSONDATA", str(testfile))
    return testfile

@pytest.fixture
def no_exit(monkeypatch):
    """
    Replace sys.exit with a version that raises SystemExit (so pytest can catch it).
    """
    def fake_exit(*args, **kwargs):
        raise SystemExit
    monkeypatch.setattr("rachio_notifier.sys.exit", fake_exit)

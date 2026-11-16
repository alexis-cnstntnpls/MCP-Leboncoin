import os
import tempfile
from pathlib import Path
from lbc_mcp.cookie import get_datadome_cookie


def test_get_datadome_cookie_from_env(monkeypatch):
    monkeypatch.setenv("LBC_DATADOME_COOKIE", "test_cookie_12345")
    assert get_datadome_cookie() == "test_cookie_12345"


def test_get_datadome_cookie_from_file(monkeypatch):
    monkeypatch.delenv("LBC_DATADOME_COOKIE", raising=False)
    with tempfile.NamedTemporaryFile("w+", delete=False) as f:
        f.write("cookie_from_file_xyz\n")
        f.flush()
        monkeypatch.setenv("LBC_COOKIE_FILE", f.name)
        assert get_datadome_cookie() == "cookie_from_file_xyz"
    os.unlink(f.name)

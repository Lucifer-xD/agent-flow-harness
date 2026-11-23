"""What the phone app asks a computer for: uploads named in the address (the relay passes no
x-filename), the project file browser, @ search, and the picture of the screen."""

from __future__ import annotations

import os

import pytest

from afh import store
from tests.test_copy_key import client  # noqa: F401  (fixture)
from tests.test_engine_features import home  # noqa: F401  (fixture)


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "shop"
    (root / "src").mkdir(parents=True)
    (root / "node_modules" / "x").mkdir(parents=True)
    (root / "src" / "cart.py").write_text("total = 1\n")
    (root / "README.md").write_text("# Shop\n")
    (root / "node_modules" / "x" / "cart.js").write_text("1")
    store.replace_setting("projects", [str(root)])
    return root


def test_an_upload_takes_its_name_from_the_address(client):  # noqa: F811
    r = client.post("/api/uploads?name=receipt%20march.jpg", content=b"\xff\xd8\xff", headers={"content-type": "image/jpeg"})
    assert r.status_code == 200 and r.json()["name"] == "receipt march.jpg" and r.json()["path"].endswith("receipt march.jpg")
    assert client.post("/api/uploads", content=b"x", headers={"x-filename": "a.txt"}).json()["name"] == "a.txt"


def test_browse_and_search_a_project(client, project):  # noqa: F811
    got = client.get("/api/files/list", params={"path": str(project)}).json()
    assert [(e["name"], e["dir"]) for e in got["entries"]] == [("node_modules", True), ("src", True), ("README.md", False)]
    assert client.get("/api/files/search", params={"directory": str(project), "q": "cart"}).json()["files"] == ["src/cart.py"]
    assert "README.md" in client.get("/api/files/search", params={"directory": str(project)}).json()["files"]
    read = client.get("/api/files/read", params={"path": str(project / "src" / "cart.py")}).json()
    assert read["content"].strip() == "total = 1" and read["binary"] is False


def test_nothing_outside_the_projects(client, project):  # noqa: F811
    outside = str(project.parent)
    for path in ("/api/files/list?path=", "/api/files/read?path=", "/api/files/search?directory="):
        assert client.get(path + outside).status_code == 400
    assert client.get("/api/files/list", params={"path": str(project / ".." )}).status_code == 400


@pytest.mark.skipif(os.name != "nt", reason="Windows only")
def test_a_picture_of_the_screen(client, monkeypatch):  # noqa: F811
    from PIL import Image

    from afh.engine.computer import win

    monkeypatch.setattr(win, "capture", lambda rect: Image.new("RGB", (2400, 1200), "navy"))
    r = client.get("/api/screen?edge=800")
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg" and r.content[:2] == b"\xff\xd8"

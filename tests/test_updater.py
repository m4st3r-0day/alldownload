import io
import zipfile

import pytest

from picfinder import updater


def test_versions():
    assert updater.parse_version("v1.2.10") > updater.parse_version("1.2.9")
    assert updater.parse_version("1.0.0") > updater.parse_version("1.0.0-beta")
    assert updater.is_newer("0.2.0", "0.1.9")
    assert not updater.is_newer("v0.1.0", "0.1.0")


def test_changelog_section():
    text = "# Changelog\n\n## [0.2.0] — 2026-12-01\n### Nuovo\n- aggiornamenti dall'app\n\n## [0.1.0] — 2026-11-15\n- prima\n"
    assert updater.changelog_section(text, "v0.2.0") == "### Nuovo\n- aggiornamenti dall'app"
    assert updater.changelog_section(text, "0.1.0") == "- prima"
    assert updater.changelog_section(text, "9.9.9") == ""


def _zip(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("owner-repo-abc123/", "")
        for name, data in files.items():
            z.writestr(f"owner-repo-abc123/{name}", data)
    return buf.getvalue()


def test_apply_source_keeps_private_files(tmp_path):
    root = tmp_path / "app"
    (root / "picfinder").mkdir(parents=True)
    (root / "picfinder" / "__init__.py").write_text('__version__ = "0.1.0"')
    (root / "pyproject.toml").write_text("deps = 1")
    (root / "settings.json").write_text("SEGRETO")
    data = _zip({"picfinder/__init__.py": '__version__ = "0.2.0"', "picfinder/nuovo.py": "x = 1",
                 "pyproject.toml": "deps = 2", "settings.json": "NON DEVE ENTRARE",
                 "../fuori.txt": "no", "log/a.log": "no"})
    res = updater.apply_source(data, root=root)
    assert (root / "picfinder" / "__init__.py").read_text() == '__version__ = "0.2.0"'
    assert (root / "picfinder" / "nuovo.py").exists()
    assert (root / "settings.json").read_text() == "SEGRETO"
    assert not (tmp_path / "fuori.txt").exists() and not (root / "log").exists()
    assert res["deps_changed"] is True
    assert (res["backup"] / "picfinder" / "__init__.py").read_text() == '__version__ = "0.1.0"'
    updater.restore_backup(res["backup"], root=root)
    assert (root / "picfinder" / "__init__.py").read_text() == '__version__ = "0.1.0"'


def test_apply_source_rejects_other_zip(tmp_path):
    with pytest.raises(updater.UpdateError):
        updater.apply_source(_zip({"README.md": "altro"}), root=tmp_path)


def test_sha256(tmp_path):
    import hashlib
    data = b"ciao"
    good = f"{hashlib.sha256(data).hexdigest()}  AllDownload-mac.zip\n"
    updater.verify_sha256(data, "AllDownload-mac.zip", good)
    with pytest.raises(updater.UpdateError):
        updater.verify_sha256(b"altro", "AllDownload-mac.zip", good)


class _R:
    def __init__(self, code, js=None, text="", headers=None):
        self.status_code, self._js, self.text, self.headers = code, js, text, headers or {}

    def json(self):
        return self._js


def test_check_from_release(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "0.1.0")
    rel = {"tag_name": "v0.3.0", "name": "AllDownload 0.3", "body": "- novità", "published_at": "2026-12-01T10:00:00Z",
           "html_url": "https://github.com/x", "zipball_url": "https://api.github.com/zip",
           "assets": [{"name": "AllDownload-mac.zip", "url": "u-mac"}, {"name": "AllDownload-windows.zip", "url": "u-win"},
                      {"name": "SHA256SUMS", "url": "u-sums"}]}
    monkeypatch.setattr(updater, "_get", lambda c, url, token, raw=False: _R(200, rel))
    info = updater.check()
    assert info.version == "0.3.0" and info.notes == "- novità" and info.published == "2026-12-01"
    assert info.sums_url == "u-sums"


def test_check_from_tags_and_up_to_date(monkeypatch):
    monkeypatch.setattr(updater, "__version__", "0.1.0")

    def fake(c, url, token, raw=False):
        if "releases/latest" in url:
            return _R(404)
        if "/tags" in url:
            return _R(200, [{"name": "v0.1.0"}, {"name": "v0.2.0"}, {"name": "test"}])
        return _R(200, text="## [0.2.0]\n- da tag\n## [0.1.0]\n- vecchia\n")
    monkeypatch.setattr(updater, "_get", fake)
    info = updater.check()
    assert info.version == "0.2.0" and info.notes == "- da tag" and not info.from_release
    monkeypatch.setattr(updater, "__version__", "0.2.0")
    assert updater.check() is None

"""Plugin Python Koofr (esempio di template scritto in codice)."""
import asyncio

import pytest

from picfinder.core import Downloader, PluginError
from picfinder.plugins import koofr

from conftest import LINK, make_transport


def test_plugin_python_riconosce_link():
    assert koofr.match(LINK)
    assert koofr.match("https://app.koofr.eu/links/xyz")
    assert koofr.match("https://k00.fr/abcd")
    assert not koofr.match("https://esempio.com/foto")


def test_plugin_python_scarica_tutto(tmp_path):
    stats = asyncio.run(Downloader(tmp_path, transport=make_transport()).run(LINK, plugin=koofr))
    assert stats == {"found": 4, "skipped": 0, "done": 4, "failed": 0}
    # tutto nella cartella col nome del link condiviso, non col suo codice
    assert (tmp_path / "Foto di Anna" / "Vacanze" / "2024" / "Agosto" / "tramonto è.jpeg").exists()
    assert (tmp_path / "Foto di Anna" / "foto1.jpg").exists()


def test_plugin_python_password(tmp_path):
    with pytest.raises(PluginError, match="password"):
        asyncio.run(Downloader(tmp_path, transport=make_transport("x")).run(LINK, plugin=koofr))

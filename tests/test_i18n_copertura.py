"""Ogni testo fisso passato a tr("…") deve avere la versione inglese in lang_en.EN."""
import ast
from pathlib import Path

from picfinder.lang_en import EN

SRC = Path(__file__).resolve().parent.parent / "picfinder"
# testi che restano uguali in inglese (nomi, simboli)
SAME = {"AllDownload", "OK", "Zip (*.zip)", "{n} file", "File"}
SKIP_FILES = {"tools_dialogs.py:177"}  # esempio di template, non si traduce


def literals():
    for py in SRC.rglob("*.py"):
        if py.name == "lang_en.py":
            continue
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)):
                continue
            pos = {"tr": 0, "act": 1}.get(node.func.id)        # act(menu, "testo", ...) = voci dei menu
            if pos is None or len(node.args) <= pos:
                continue
            a = node.args[pos]
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                yield py.name, node.lineno, a.value


def test_every_tr_literal_has_english():
    missing = [f"{f}:{n}: {t!r}" for f, n, t in literals() if t not in EN and t not in SAME and t.strip()
               and f"{f}:{n}" not in SKIP_FILES]
    assert not missing, "Mancano in lang_en.py:\n" + "\n".join(missing)

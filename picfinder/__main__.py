import sys

if sys.version_info >= (3, 15) and not getattr(sys, "frozen", False):
    # Python 3.15 cambia il modo di importare (lazy import) e PySide6 non è ancora pronto:
    # su Windows dava «'lazy_import' object is not callable».
    sys.stderr.write("AllDownload funziona con Python da 3.10 a 3.14. Hai Python %d.%d: installa Python 3.13\n"
                     "da https://www.python.org/downloads/ e avvia di nuovo.\n" % sys.version_info[:2])
    sys.exit(1)

from .cli import main  # noqa: E402

sys.exit(main())

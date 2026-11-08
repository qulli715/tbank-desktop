# main.py — точка входа десктоп-приложения tbank (PySide6).

from __future__ import annotations

import logging
import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

import config
from core.logging_setup import setup_logging
from services.settings import load_settings
from storage.db import backup_db, init_db
from ui import theme


def _install_excepthook(logger: logging.Logger) -> None:
    def hook(exc_type, exc, traceback):  # noqa: ANN001
        logger.exception("Необработанная ошибка", exc_info=(exc_type, exc, traceback))
        QMessageBox.critical(None, "Ошибка", f"{exc_type.__name__}: {exc}")

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    setup_logging()
    logger = logging.getLogger("main")

    backup_db()
    init_db()

    settings = load_settings()

    app = QApplication(argv)
    app.setApplicationName("tbank")
    app.setApplicationDisplayName("tbank — пополнения")
    app.setFont(QFont("Segoe UI", 10))
    theme.apply(settings.theme, app)
    _install_excepthook(logger)

    from ui.main_window import MainWindow

    window = MainWindow(settings)

    if "--smoke" in argv:
        # Режим проверки: отрисовать окно и сохранить скриншот, не входя в цикл событий.
        index = argv.index("--smoke")
        target = argv[index + 1] if index + 1 < len(argv) else "smoke.png"
        window.resize(1380, 880)
        window.show()
        for _ in range(8):
            app.processEvents()
        window.grab().save(target)
        logger.info("smoke screenshot сохранён: %s", target)
        window.close()
        app.processEvents()
        return 0

    window.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

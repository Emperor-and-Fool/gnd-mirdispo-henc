#!/usr/bin/env python3
# Mirdispo — share a Plasma desktop on a wireless display
# Copyright (C) 2026 Mirdispo contributors
# SPDX-License-Identifier: GPL-3.0-or-later
"""Render the store screenshots from demo mode.

Demo mode shows invented receivers, so nothing about the machine that runs
this ends up in a picture. The window is rendered off screen at a fixed size,
which keeps every screenshot the same shape.

    tools/screenshot.py docs/screenshots
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")
# An empty configuration directory, so the pictures show the default Breeze
# colours rather than whatever theme the person running this has chosen.
os.environ["XDG_CONFIG_HOME"] = tempfile.mkdtemp(prefix="mirdispo-screenshot-")

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtCore import QPoint, QTimer, QUrl  # noqa: E402
from PyQt6.QtGui import QGuiApplication  # noqa: E402
from PyQt6 import sip  # noqa: E402
from PyQt6.QtQml import QQmlApplicationEngine  # noqa: E402
from PyQt6.QtQuick import QQuickWindow  # noqa: E402
from PyQt6.QtTest import QTest  # noqa: E402

from mirdispo.backend import DisplayBackend  # noqa: E402

WIDTH, HEIGHT = 900, 520


def main(out_dir: str) -> int:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    backend = DisplayBackend(demo=True, parent=engine)
    engine.rootContext().setContextProperty("displayBackend", backend)
    engine.load(QUrl.fromLocalFile(str(Path(__file__).resolve().parents[1] / "src/mirdispo/qml/Main.qml")))
    if not engine.rootObjects():
        return 2
    window = sip.cast(engine.rootObjects()[0], QQuickWindow)
    window.setWidth(WIDTH)
    window.setHeight(HEIGHT)

    def grab(name):
        window.grabWindow().save(str(out / name))
        print(out / name)

    # Keep the pointer off the controls, or a tooltip ends up in the picture.
    QTimer.singleShot(100, lambda: QTest.mouseMove(window, QPoint(WIDTH // 2, HEIGHT - 20)))
    QTimer.singleShot(0, backend.scan)
    QTimer.singleShot(2500, lambda: grab("displays.png"))
    QTimer.singleShot(2600, lambda: backend.connectToDevice("demo:living-room"))
    QTimer.singleShot(7000, lambda: grab("casting.png"))
    QTimer.singleShot(7100, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "docs/screenshots"))

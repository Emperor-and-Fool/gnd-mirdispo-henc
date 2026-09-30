# Mirdispo — share a Plasma desktop on a wireless display
# Copyright (C) 2026 Mirdispo contributors
#
# This program is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along
# with this program. If not, see <https://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from PyQt6.QtCore import QCoreApplication, QTimer, QUrl
from PyQt6.QtGui import QGuiApplication, QIcon
from PyQt6.QtQml import QQmlApplicationEngine
from PyQt6.QtWidgets import QApplication, QSystemTrayIcon

from . import __version__
from .backend import DisplayBackend
from .diagnostics import collect_diagnostics


def parser():
    result = argparse.ArgumentParser(description="KDE-native network display sender")
    result.add_argument("--demo", action="store_true", help="use deterministic virtual displays")
    result.add_argument("--diagnostics", action="store_true", help="print diagnostics as JSON and exit")
    result.add_argument("--exit-after", type=float, metavar="SECONDS", help=argparse.SUPPRESS)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if args.diagnostics:
        print(json.dumps([item.__dict__ for item in collect_diagnostics(demo=args.demo)], indent=2))
        return 0

    os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")
    # QApplication rather than QGuiApplication, for the tray icon's menu.
    app = QApplication(sys.argv[:1])
    QCoreApplication.setOrganizationName("Mirdispo")
    QCoreApplication.setApplicationName("Mirdispo")
    QCoreApplication.setApplicationVersion(__version__)
    QGuiApplication.setDesktopFileName("io.github.hencyber.Mirdispo")
    QGuiApplication.setWindowIcon(QIcon.fromTheme("io.github.hencyber.Mirdispo", QIcon.fromTheme("video-display")))

    engine = QQmlApplicationEngine()
    # Parent the context object to the engine so QML is torn down before the
    # backend. Otherwise bindings briefly see a null object during shutdown.
    backend = DisplayBackend(demo=args.demo, parent=engine)
    engine.rootContext().setContextProperty("displayBackend", backend)
    engine.rootContext().setContextProperty("tray", None)
    qml = Path(__file__).with_name("qml") / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects():
        return 2
    if QSystemTrayIcon.isSystemTrayAvailable():
        from .tray import Tray

        tray = Tray(backend, engine.rootObjects()[0], app, parent=engine)
        engine.rootContext().setContextProperty("tray", tray)
    if args.exit_after is not None:
        QTimer.singleShot(max(0, int(args.exit_after * 1000)), app.quit)
    QTimer.singleShot(0, backend.scan)
    app.aboutToQuit.connect(backend.shutdown)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

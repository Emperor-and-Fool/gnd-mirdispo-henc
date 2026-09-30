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

"""Measures the rendered position of the action buttons.

Run as its own process: creating a window needs a QGuiApplication, and the
rest of the suite has already made a QCoreApplication by the time this runs.

Exits 0 when every action button shares one column, 2 when they do not, and
77 when the interface cannot be shown in this environment.
"""

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Measure the style the application actually runs under. The first version
# of this probe used Basic, which is not what a Plasma desktop renders, so it
# was measuring something nobody sees.
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "org.kde.desktop")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def spin(app, seconds):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)


def row_fills_card(window):
    """Whether each action row spans the card it sits in.

    The fault this guards against was a row only as wide as its text: the
    cards were identical, but the button sat wherever the label ended, so a
    longer receiver name moved it.
    """
    mismatches = []

    def walk(item):
        for child in item.childItems():
            if child.metaObject().className().startswith("QQuickRowLayout"):
                parent = child.parentItem()
                if parent is not None:
                    row = round(child.property("width") or 0)
                    box = round(parent.property("width") or 0)
                    if box and abs(row - box) > 1:
                        mismatches.append((row, box))
            walk(child)

    walk(window.contentItem())
    return mismatches


def action_buttons(window):
    from PyQt6.QtCore import QPointF

    found = []

    def walk(item):
        for child in item.childItems():
            if "Button" in child.metaObject().className():
                text = child.property("text")
                if text in ("Connect", "Disconnect"):
                    found.append((text,
                                  round(child.mapToItem(None, QPointF(0, 0)).x()),
                                  round(child.property("width"))))
            walk(child)

    walk(window.contentItem())
    return found


def main():
    try:
        from PyQt6 import sip
        from PyQt6.QtGui import QGuiApplication
        from PyQt6.QtQml import QQmlApplicationEngine
        from PyQt6.QtQuick import QQuickWindow
    except ImportError as error:
        print(f"Qt QML unavailable: {error}")
        return 77

    from mirdispo.backend import DisplayBackend

    app = QGuiApplication(sys.argv[:1])
    engine = QQmlApplicationEngine()
    backend = DisplayBackend(demo=True, diagnostic_collector=lambda *_: [], parent=engine)
    engine.rootContext().setContextProperty("displayBackend", backend)
    engine.load(str(ROOT / "src/mirdispo/qml/Main.qml"))

    if not engine.rootObjects():
        print("the interface could not be loaded")
        return 77

    window = sip.cast(engine.rootObjects()[0], QQuickWindow)

    # A session in progress adds the card carrying Disconnect, so both kinds
    # of button are measured against each other.
    backend.scan()
    spin(app, 1.0)
    backend.connectToDevice("demo:living-room")
    spin(app, 1.5)

    # The fault this guards against only shows with a receiver whose name is
    # longer than the space for it: an un-elided label demands that width and
    # drags the button out of the column. The demo names are too short to
    # provoke it, so one is planted here.
    from mirdispo.models import DisplayDevice

    backend.devices.replace([
        DisplayDevice("demo:short", "TV", protocol=3),
        DisplayDevice("demo:long",
                      "Receiver with an extremely long advertised name that no "
                      "card could ever hope to show in full", protocol=3),
    ])
    spin(app, 1.0)

    buttons = action_buttons(window)
    for text, x, width in sorted(buttons, key=lambda row: row[1]):
        print(f"{text:12} x={x:<6} width={width}")

    if len(buttons) < 2:
        print("expected both kinds of button")
        return 77

    mismatches = row_fills_card(window)
    if mismatches:
        print(f"rows narrower than their card: {mismatches}")
        return 2

    left_edges = {x for _, x, _ in buttons}
    widths = {w for _, _, w in buttons}
    if len(widths) != 1:
        print(f"buttons have different widths: {sorted(widths)}")
        return 2
    if len(left_edges) != 1:
        print(f"buttons do not share a column: {sorted(left_edges)}")
        return 2

    print("aligned")
    return 0


if __name__ == "__main__":
    sys.exit(main())

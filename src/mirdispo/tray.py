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

"""The system tray entry.

A cast outlives the window: people close it and go back to what they were
sharing. The tray keeps Mirdispo reachable meanwhile, says what it is doing,
and is where a cast is stopped or the application quit. On a desktop without
a system tray none of this exists and closing the window quits, as before.
"""

from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtProperty, pyqtSlot
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon

APP_ID = "io.github.hencyber.Mirdispo"


def tray_label(status: str, device: str, status_text: str) -> str:
    """One line for the tooltip and the top of the menu."""
    if status == "streaming" and device:
        return f"Sharing your screen with {device}"
    if status == "connecting" and device:
        return f"Connecting to {device}…"
    return status_text or "Not sharing"


def can_stop(status: str) -> bool:
    return status in ("connecting", "streaming")


class Tray(QObject):
    def __init__(self, backend, window, app, parent=None):
        super().__init__(parent)
        self._backend = backend
        self._window = window
        self._app = app
        self._told_about_tray = False

        self._icon = QSystemTrayIcon(
            QIcon.fromTheme(APP_ID, QIcon.fromTheme("video-display")), self)
        self._menu = QMenu()
        self._state = self._menu.addAction("")
        self._state.setEnabled(False)
        self._menu.addSeparator()
        self._show = self._menu.addAction(QIcon.fromTheme("window"), "Show Mirdispo")
        self._show.triggered.connect(self.showWindow)
        self._stop = self._menu.addAction(QIcon.fromTheme("media-playback-stop"), "Stop sharing")
        self._stop.triggered.connect(backend.disconnect)
        self._menu.addSeparator()
        quit_action = self._menu.addAction(QIcon.fromTheme("application-exit"), "Quit Mirdispo")
        quit_action.triggered.connect(self.quit)
        self._icon.setContextMenu(self._menu)
        self._icon.activated.connect(self._activated)

        backend.statusChanged.connect(self._update)
        backend.selectedDeviceChanged.connect(self._update)
        self._update()
        self._icon.show()

    @pyqtProperty(bool, constant=True)
    def available(self):
        return True

    def _update(self):
        status = self._backend.status
        label = tray_label(status, self._backend.selectedDevice, self._backend.statusText)
        self._state.setText(label)
        self._icon.setToolTip(f"Mirdispo\n{label}")
        self._stop.setEnabled(can_stop(status))
        self._stop.setVisible(can_stop(status))

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            if self._window.isVisible():
                self._window.hide()
            else:
                self.showWindow()

    @pyqtSlot()
    def showWindow(self):
        self._window.show()
        self._window.raise_()
        self._window.requestActivate()

    @pyqtSlot()
    def windowHidden(self):
        """Called from QML when the window is closed into the tray."""
        if not self._told_about_tray:
            self._told_about_tray = True
            self._icon.showMessage(
                "Mirdispo is still running",
                "Stop sharing or quit from its icon in the system tray.",
                QIcon.fromTheme(APP_ID), 5000)

    @pyqtSlot()
    def quit(self):
        # Quitting from the tray means stopping: nothing is left behind
        # sharing the screen with no window to stop it from.
        if can_stop(self._backend.status):
            self._backend.disconnect()
        self._icon.hide()
        self._app.quit()

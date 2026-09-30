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

import time

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from .diagnostics import collect_diagnostics
from . import p2p
from .gnd import GnomeNetworkDisplaysService
from .models import DiagnosticsModel, DisplayDevice, DisplayModel


class DisplayBackend(QObject):
    statusChanged = pyqtSignal()
    scanningChanged = pyqtSignal()
    selectedDeviceChanged = pyqtSignal()
    errorChanged = pyqtSignal()

    def __init__(self, demo=False, discovery=None, diagnostic_collector=None, p2p_watcher=None,
                 scheduler=None, handshake_probe=None, parent=None):
        super().__init__(parent)
        self._demo = demo
        self._service = discovery
        self._p2p = p2p_watcher
        # How a delayed retry is scheduled. Injectable so tests can run the
        # retry immediately instead of waiting on a real timer.
        self._schedule = scheduler if scheduler is not None else (
            lambda delay_ms, callback: QTimer.singleShot(delay_ms, callback))
        # Notices wpa_supplicant giving up on the current attempt. Injectable
        # so tests do not depend on the machine's network interfaces.
        self._handshake_failed = handshake_probe if handshake_probe is not None else (
            p2p.GroupFormationProbe())
        self._diagnostic_collector = diagnostic_collector or collect_diagnostics
        self._status = "idle"
        self._status_text = "Ready to find nearby displays"
        self._scanning = False
        self._selected = ""
        self._selected_id = ""
        self._error = ""
        self._stream_unit = ""
        self._last_state = None
        self._reconnects = 0
        self._stream_seen_active = False
        self._attempt_started = 0.0
        self.devices = DisplayModel(self)
        self.diagnostics = DiagnosticsModel(self)
        if not demo and self._service is None:
            try:
                self._service = GnomeNetworkDisplaysService()
            except Exception as error:
                self._set_error(str(error))
        if not demo and self._p2p is None:
            try:
                self._p2p = p2p.P2PDeviceWatcher()
            except Exception:
                # Progress reporting is a nicety; discovery must still work.
                self._p2p = None
        self.refreshDiagnostics()
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(2000)
        self._poll_timer.timeout.connect(self._poll_displays)
        if not demo:
            self._poll_timer.start()

    @pyqtProperty(QObject, constant=True)
    def devicesModel(self):
        return self.devices

    @pyqtProperty(QObject, constant=True)
    def diagnosticsModel(self):
        return self.diagnostics

    @pyqtProperty(str, notify=statusChanged)
    def status(self):
        return self._status

    @pyqtProperty(str, notify=statusChanged)
    def statusText(self):
        return self._status_text

    @pyqtProperty(bool, notify=scanningChanged)
    def scanning(self):
        return self._scanning

    @pyqtProperty(str, notify=selectedDeviceChanged)
    def selectedDevice(self):
        return self._selected

    @pyqtProperty(str, notify=errorChanged)
    def errorText(self):
        return self._error

    @pyqtProperty(bool, constant=True)
    def demoMode(self):
        return self._demo

    @pyqtProperty(str, constant=True)
    def appVersion(self):
        from . import __version__

        return __version__

    @pyqtProperty(str, constant=True)
    def licenceText(self):
        """The GPL text, from wherever this system keeps it."""
        from . import legal

        return legal.licence_text()

    @pyqtProperty(str, constant=True)
    def sourceLocation(self):
        """Where the source and the changes to the engine can be found."""
        from . import legal

        return legal.source_location()

    def _set_status(self, status: str, text: str):
        self._status, self._status_text = status, text
        self.statusChanged.emit()

    def _set_error(self, message: str):
        self._error = message
        self.errorChanged.emit()

    @pyqtSlot()
    def scan(self):
        if self._scanning:
            return
        self._error = ""
        self.errorChanged.emit()
        self._scanning = True
        self.scanningChanged.emit()
        self._set_status("discovering", "Looking for Wi-Fi Displays…")
        if self._demo:
            QTimer.singleShot(450, self._finish_demo_scan)
            return
        if self._service is None:
            self._finish_scan_error("Cannot connect to the session D-Bus")
            return
        try:
            self._service.ensure_running()
            QTimer.singleShot(900, self._refresh_real_scan)
        except Exception as error:
            self._finish_scan_error(str(error))

    def _finish_demo_scan(self):
        self.devices.replace(
            [
                DisplayDevice("demo:living-room", "Living room TV", "00:00:5e:00:53:01",
                              "Miracast (Wi-Fi Direct)", "available", 91),
                DisplayDevice("demo:adapter", "Wireless display adapter", "00:00:5e:00:53:02",
                              "Miracast (Wi-Fi Direct)", "available", 73),
                DisplayDevice("demo:meeting", "Meeting room screen", "00:00:5e:00:53:03",
                              "Miracast over Infrastructure", "available", 54),
            ]
        )
        self._finish_scan()

    def _refresh_real_scan(self):
        try:
            self.devices.replace(self._service.displays())
            self._finish_scan()
        except Exception as error:
            self._finish_scan_error(str(error))

    def _poll_displays(self):
        if self._service is None:
            return
        try:
            if self._service.running():
                self.devices.replace(self._service.displays())
                # The helper's state is settled first, because whether it is
                # running decides how the link state should be read.
                if self._stream_unit and self._status in ("connecting", "streaming"):
                    helper_state = getattr(self._service, "stream_state", lambda _unit: None)(self._stream_unit)
                    if helper_state == "ended":
                        # Stopped from the desktop, such as Plasma's screen
                        # sharing indicator. Reconnecting would share the
                        # screen again against the user's decision.
                        self._end_by_user()
                        return
                    active = getattr(self._service, "stream_active", lambda _unit: True)(self._stream_unit)
                    if active:
                        self._stream_seen_active = True
                    elif active is None:
                        # Unknown, not dead. Acting on this started a second
                        # helper beside a running one.
                        pass
                    elif self._stream_seen_active:
                        # The helper exited. This covers a failed handshake as
                        # well as a dropped link: NetworkManager's "failed"
                        # state lasts about a millisecond, far too short for a
                        # two-second poll to catch, but the helper's exit
                        # lasts.
                        self._handle_dropped_stream(connected=self._status == "streaming")
                        return

                    # The helper can still be running while the handshake is
                    # already lost: NetworkManager waits out a 45 second
                    # timeout after wpa_supplicant has given its verdict,
                    # which measured 28 seconds of waiting for an answer that
                    # already existed.
                    if (self._status == "connecting" and self._attempt_started
                            and self._handshake_failed(self._attempt_started)):
                        self._attempt_started = 0.0
                        self._handle_dropped_stream(connected=False, fast=True)
                        return

                    # The helper says when the receiver is getting a picture.
                    # This is the only sign of success for a receiver reached
                    # over the network, where there is no Wi-Fi Direct link
                    # to watch.
                    if self._status == "connecting" and helper_state == "streaming":
                        self._stream_seen_active = True
                        self._attempt_started = 0.0
                        self._set_status("streaming", f"Sharing session active for {self._selected}")
                        return
                self._report_connection_progress()
        except Exception:
            # Polling is best-effort. Explicit user actions surface failures.
            pass

    def _finish_scan(self):
        self._scanning = False
        self.scanningChanged.emit()
        count = self.devices.rowCount()
        self._set_status("idle", f"Found {count} compatible display" + ("s" if count != 1 else ""))

    def _finish_scan_error(self, message: str):
        self._scanning = False
        self.scanningChanged.emit()
        self._set_error(message)
        self._set_status("error", "Discovery could not start")

    # A Wi-Fi Direct link can drop from a moment of beacon loss, which ended a
    # measured 11-minute session. A short glitch should cost an interruption,
    # not the whole session, so the stream is restarted a couple of times
    # before the user is told it is over.
    MAX_RECONNECTS = 2

    # A receiver that never answers the handshake is a different problem, and
    # a more stubborn one: NetworkManager spends 45 seconds on each attempt,
    # and every successful connection measured today came after one or two
    # that timed out. Retrying is therefore worth doing several times, since
    # the user would otherwise be clicking the button themselves.
    MAX_CONNECT_ATTEMPTS = 4

    # When an attempt expires without an answer, the receiver sends its own
    # negotiation request about two seconds later. Retrying instantly puts
    # both sides on the air at once, and a negotiation where both peers
    # insist on being group owner fails, so that case stands off.
    #
    # A handshake that got as far as group formation and failed there is a
    # different case: in every such failure logged so far the receiver sent
    # no request afterwards, so there is nothing to wait for and waiting only
    # adds to the time before a picture appears.
    RETRY_DELAY_MS = 9000
    FAST_RETRY_DELAY_MS = 2000
    RECONNECT_DELAY_MS = 2000

    def _handle_dropped_stream(self, connected=True, fast=False):
        name = self._selected
        budget = self.MAX_RECONNECTS if connected else self.MAX_CONNECT_ATTEMPTS

        if self._reconnects >= budget or not self._selected_id:
            self._stream_unit = ""
            self._selected = ""
            self._selected_id = ""
            self._stream_seen_active = False
            self.selectedDeviceChanged.emit()
            if connected:
                self._set_error("The connection to the receiver was lost")
                self._set_status("error", "Screen sharing stopped")
            else:
                self._set_error(f"{name} did not accept the connection")
                self._set_status("error", f"Could not connect to {name}")
            return

        self._reconnects += 1
        self._last_state = None
        self._stream_seen_active = False

        # Make sure the previous attempt is really gone before another starts.
        previous, self._stream_unit = self._stream_unit, ""
        if previous:
            try:
                self._service.stop_stream(previous)
            except Exception:
                pass
        if connected:
            self._set_status("connecting", f"Lost the connection to {name}. Reconnecting…")
            delay = self.RECONNECT_DELAY_MS
        else:
            attempt = f"({self._reconnects + 1} of {self.MAX_CONNECT_ATTEMPTS + 1})"
            if fast:
                self._set_status("connecting", f"Retrying {name} {attempt}…")
                delay = self.FAST_RETRY_DELAY_MS
            else:
                self._set_status("connecting", f"{name} did not answer. Trying again {attempt}…")
                delay = self.RETRY_DELAY_MS

        attempt = self._reconnects
        self._schedule(delay, lambda: self._start_retry(attempt, name))

    def _start_retry(self, attempt, name):
        # The user may have cancelled or reconnected while this was pending.
        if attempt != self._reconnects or not self._selected_id or self._stream_unit:
            return
        try:
            self._attempt_started = time.time()
            self._stream_unit = self._service.start_stream(self._selected_id)
            if not self._stream_unit:
                raise RuntimeError("The streaming service did not start")
        except Exception as error:
            self._stream_unit = ""
            self._set_error(str(error))
            self._set_status("error", f"Could not reach {name}")

    def _report_connection_progress(self):
        """Mirror NetworkManager's Wi-Fi Direct state into the UI.

        The handshake regularly takes half a minute and fails in ways only
        NetworkManager can see, so this is what turns a motionless
        "Connecting…" into something the user can act on.
        """
        if not self._selected_id or self._p2p is None:
            return
        if self._status not in ("connecting", "streaming"):
            return

        current = self._p2p.state()
        if current is None or current == self._last_state:
            return
        self._last_state = current
        state, reason = current

        if state == p2p.STATE_FAILED:
            if self._reconnects < self.MAX_RECONNECTS and self._selected_id:
                # Receivers regularly refuse the first handshake after a
                # previous session. Retrying is what a user would do anyway.
                self._reconnects += 1
                self._last_state = None
                self._set_status("connecting", f"Retrying {self._selected}…")
                try:
                    self._stream_unit = self._service.start_stream(self._selected_id)
                except Exception as error:
                    self._stream_unit = ""
                    self._set_error(str(error))
                    self._set_status("error", f"Could not connect to {self._selected}")
                return

            self._stream_unit = ""
            self._set_error(p2p.failure_message(reason, self._selected))
            self._set_status("error", f"Could not connect to {self._selected}")
            return

        if state == p2p.STATE_ACTIVATED:
            # Both halves have to be true: the link is up and the helper is
            # running. Otherwise a retry that starts while the previous link
            # is still reported as active would claim success immediately.
            if self._stream_seen_active:
                self._set_status("streaming", f"Sharing session active for {self._selected}")
            return

        message = p2p.progress_message(state, self._selected)
        if message:
            self._set_status("connecting", message)

    @pyqtSlot(str)
    def connectToDevice(self, device_id: str):
        # Resolve by identifier, never by row: discovery replaces the list
        # every couple of seconds, so a row index can point at a different
        # display by the time the click is handled.
        device = self.devices.by_id(device_id)
        if device is None:
            self._set_error("That display is no longer available")
            self._set_status("error", "Display no longer available")
            return
        self._selected = device.name
        self._selected_id = device.path
        self._last_state = None
        self._reconnects = 0
        self._stream_seen_active = False
        self._error = ""
        self.errorChanged.emit()
        self.selectedDeviceChanged.emit()
        self._set_status("connecting", f"Connecting to {device.name}…")
        if self._demo:
            QTimer.singleShot(900, lambda: self._set_status("streaming", f"Sharing your screen with {device.name}"))
            return
        try:
            self._attempt_started = time.time()
            self._stream_unit = self._service.start_stream(device.path)
            if not self._stream_unit:
                raise RuntimeError("The streaming service did not start")
            QTimer.singleShot(1200, lambda: self._verify_stream(device.name))
        except Exception as error:
            self._set_error(str(error))
            self._set_status("error", f"Could not connect to {device.name}")

    def _verify_stream(self, device_name: str):
        active = getattr(self._service, "stream_active", lambda _unit: True)(self._stream_unit)
        if active:
            self._stream_seen_active = True
        # Only a helper known to be gone is a failure. Unknown is not dead:
        # reading it as dead reported a failed connection while the
        # receiver was showing the picture.
        if active is not False:
            if self._p2p is None:
                # Nothing to observe the handshake with; the running helper is
                # all we know.
                self._set_status("streaming", f"Sharing session active for {device_name}")
                return
            # The helper is running, but the receiver has not accepted yet.
            self._set_status("connecting", f"Connecting to {device_name}…")
            self._report_connection_progress()
        else:
            self._stream_unit = ""
            self._set_error("The streaming service stopped before the connection completed")
            self._set_status("error", f"Could not connect to {device_name}")

    def _end_by_user(self):
        name = self._selected
        self.disconnect()
        self._set_status("idle", f"Screen sharing with {name} was stopped" if name
                         else "Screen sharing was stopped")

    def shutdown(self):
        """Called as the application quits. A running cast is left running."""
        if self._demo or self._service is None or self._status == "streaming":
            return
        release = getattr(self._service, "release", None)
        if release:
            try:
                release()
            except Exception:
                pass

    @pyqtSlot()
    def disconnect(self):
        previous = self._selected
        if not self._demo and self._stream_unit and self._service:
            try:
                self._service.stop_stream(self._stream_unit)
            except Exception as error:
                self._set_error(str(error))
        self._stream_unit = ""
        self._selected = ""
        self._selected_id = ""
        self._last_state = None
        self._reconnects = 0
        self._stream_seen_active = False
        self.selectedDeviceChanged.emit()
        self._set_status("idle", f"Disconnected from {previous}" if previous else "Ready to find nearby displays")

    @pyqtSlot()
    def refreshDiagnostics(self):
        self.diagnostics.replace(self._diagnostic_collector(self._service, self._demo))

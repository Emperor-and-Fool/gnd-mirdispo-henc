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

import os
import time
from pathlib import Path

from PyQt6.QtCore import QObject, QTimer, pyqtProperty, pyqtSignal, pyqtSlot

from .diagnostics import collect_diagnostics
from . import p2p
from .gnd import GnomeNetworkDisplaysService
from .models import DiagnosticsModel, DisplayDevice, DisplayModel
from .vscreen import VirtualScreen, VirtualScreenError


def _open_display_settings() -> None:
    """Plasma's own display settings, where a virtual screen is resized and
    moved like any other. Opened beside the window rather than waited for, so
    that the dialog that offered it is still there afterwards."""
    import subprocess

    subprocess.Popen(["kcmshell6", "kcm_kscreen"],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class DisplayBackend(QObject):
    # How long to wait for a finished cast to actually be gone before
    # starting the next one, asked every TEARDOWN_POLL_MS milliseconds.
    TEARDOWN_POLL_MS = 400
    TEARDOWN_ATTEMPTS = 25

    statusChanged = pyqtSignal()
    scanningChanged = pyqtSignal()
    selectedDeviceChanged = pyqtSignal()
    errorChanged = pyqtSignal()
    # A screen has been made and is waiting to be shared. The window asks what
    # to do about it; nothing here decides that.
    virtualScreenChanged = pyqtSignal()
    # The band this cast landed on, and whether what we send fits it.
    linkChanged = pyqtSignal()

    def __init__(self, demo=False, discovery=None, diagnostic_collector=None, p2p_watcher=None,
                 scheduler=None, handshake_probe=None, virtual_screen=None, settings_opener=None,
                 parent=None):
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
        # The screen to share when there is no second one to share, and how
        # the display settings are opened. Both injectable so tests do not
        # make a screen appear on anybody's desk.
        self._vscreen = virtual_screen if virtual_screen is not None else VirtualScreen()
        self._open_settings = settings_opener or _open_display_settings
        self._vscreen_for = ""
        # Which band the receiver put this cast on, and whether we are sending
        # what that band will carry. Read once per cast: a group does not
        # change channel while it lives.
        self._band = ""
        self._slow_link = False
        self._status = "idle"
        self._status_text = "Ready to find nearby displays"
        self._picture_text = ""
        self._notice_text = ""
        self._figures = ["", "", "", "", ""]
        self._reporting = False
        self._can_reuse_source = False
        self._scanning = False
        self._selected = ""
        self._selected_id = ""
        self._error = ""
        self._stream_unit = ""
        self._last_state = None
        self._reconnects = 0
        self._stream_seen_active = False
        self._attempt_started = 0.0
        self._discovering = True
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
        # One of the two moments the answer can have changed.
        self._refresh_reuse()
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

    @pyqtSlot(bool)
    def setReporting(self, wanted: bool):
        """Called when the figures are unfolded or folded away. Nothing is
        totalled or sent by the engine while nobody is reading them, so the
        asking and the showing are the same gesture."""
        if self._reporting == wanted:
            return
        self._reporting = wanted
        if not wanted:
            self._figures = ["", "", "", "", ""]
            self.statusChanged.emit()
        if self._demo or self._service is None or not self._stream_unit:
            return
        setter = getattr(self._service, "set_stream_report", None)
        if setter:
            try:
                setter(self._stream_unit, wanted)
            except Exception:
                pass

    @pyqtProperty(bool, notify=statusChanged)
    def canReuseSource(self):
        """Whether the desktop is holding a choice of what to share.

        Asked when the window opens and again when a cast ends, which are the
        only moments it changes, rather than before each connection: the
        answer cannot alter while a cast is running, and asking then would be
        asking at the one moment the answer is least interesting."""
        return self._can_reuse_source

    def _refresh_reuse(self):
        reuse = False
        if not self._demo and self._service is not None:
            reader = getattr(self._service, "remembered_source", None)
            if reader:
                try:
                    reuse = bool(reader())
                except Exception:
                    reuse = False
        if reuse != self._can_reuse_source:
            self._can_reuse_source = reuse
            self.statusChanged.emit()

    @pyqtProperty(bool, notify=statusChanged)
    def reporting(self):
        return self._reporting

    @pyqtProperty(list, notify=statusChanged)
    def figures(self):
        """Frames a second, megabits a second, dropped altogether, dropped
        lately, and the average gap in milliseconds. Empty strings while
        nothing has been reported."""
        return self._figures

    @pyqtProperty(str, notify=statusChanged)
    def pictureText(self):
        """What the engine settled on with the receiver, in words, or empty
        while nothing has been settled. Shown rather than kept, because the
        one thing somebody watching might want to know is what they are being
        sent."""
        return self._picture_text

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
        # Search for receivers only while neither reaching a receiver nor
        # sending a picture: the search scans other channels on the radio the
        # link uses. Reaching one needs the radio at least as much as sending
        # does, since the two ends agree on a group over the same channels the
        # search sweeps, and a search that kept running until a picture
        # arrived would stop the picture from ever arriving. It resumes as
        # soon as a link drops or fails, so the receiver can be found again.
        discover = status not in ("connecting", "streaming")
        if not self._demo and self._service is not None and discover != self._discovering:
            self._discovering = discover
            setter = getattr(self._service, "set_discover", None)
            if setter:
                try:
                    setter(discover)
                except Exception:
                    pass
        if status == "streaming":
            # The retry budget is for getting a picture back, not for the
            # whole session. Kept across a recovered drop, it let the retries
            # needed to connect, or two brief drops in a long session, end
            # the cast at the next one.
            self._reconnects = 0
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
                # A receiver that answers after the search has finished used
                # to arrive in the list while the line above it went on saying
                # how many had been found at the moment the search ended,
                # which was none. The sentence counts what is on screen now.
                if self._status == "idle":
                    found = self._found_text()
                    if found != self._status_text:
                        self._set_status("idle", found)
                # The helper's state is settled first, because whether it is
                # running decides how the link state should be read.
                if self._stream_unit and self._status in ("connecting", "streaming"):
                    # Once per cast: a group does not change channel while it
                    # lives, and reading costs a process each time.
                    if not self._band:
                        band = p2p.group_band()
                        if band:
                            self._band = band
                            self.linkChanged.emit()
                    helper_state = getattr(self._service, "stream_state", lambda _unit: None)(self._stream_unit)
                    picture = getattr(self._service, "stream_picture", lambda _unit: None)(self._stream_unit)
                    if (picture or "") != self._picture_text:
                        self._picture_text = picture or ""
                        self.statusChanged.emit()
                    # Something the helper needs read rather than matched on,
                    # such as what a virtual display needs before it can be
                    # shared. Shown once, not again, so a person who has read
                    # it and closed it is not handed it back every poll.
                    notice = getattr(self._service, "stream_notice", lambda _unit: None)(self._stream_unit)
                    if notice and notice != self._notice_text:
                        self._notice_text = notice
                        self._set_error(notice)
                    if self._reporting:
                        reader = getattr(self._service, "stream_figures", None)
                        figures = reader(self._stream_unit) if reader else None
                        parts = (figures or "").split("|")
                        if len(parts) == 5 and parts != self._figures:
                            self._figures = parts
                            self.statusChanged.emit()
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
                    # timeout after wpa_supplicant has given its verdict, close
                    # to half a minute of waiting for an answer that already
                    # exists.
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

    def _found_text(self) -> str:
        count = self.devices.rowCount()
        return f"Found {count} compatible display" + ("s" if count != 1 else "")

    def _finish_scan(self):
        self._scanning = False
        self.scanningChanged.emit()
        self._set_status("idle", self._found_text())

    def _finish_scan_error(self, message: str):
        self._scanning = False
        self.scanningChanged.emit()
        self._set_error(message)
        self._set_status("error", "Discovery could not start")

    # A Wi-Fi Direct link can drop from a moment of beacon loss, which is
    # common when the adapter also serves a network on another channel. A
    # short glitch should cost an interruption, not the whole session, so each
    # drop gets a couple of attempts to bring the picture back before the user
    # is told it is over.
    MAX_RECONNECTS = 2

    # A receiver that never answers the handshake is a different problem, and
    # a more stubborn one: NetworkManager spends 45 seconds on each attempt,
    # and receivers often accept only after one or two attempts have timed
    # out. Retrying is therefore worth doing several times, since the user
    # would otherwise be clicking the button themselves.
    MAX_CONNECT_ATTEMPTS = 4

    # When an attempt expires without an answer, the receiver sends its own
    # negotiation request about two seconds later. Retrying instantly puts
    # both sides on the air at once, and a negotiation where both peers
    # insist on being group owner fails, so that case stands off.
    #
    # A handshake that got as far as group formation and failed there is a
    # different case: the receiver sends no request afterwards, so there is
    # nothing to wait for and waiting only adds to the time before a picture
    # appears.
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
    def connectToDevice(self, device_id: str, choose_source: bool = False):
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
        # Read again for this cast. The band belongs to the group, and a new
        # cast forms a new one, which the receiver may put somewhere else.
        self._band = ""
        self.linkChanged.emit()
        self._error = ""
        # A new cast gets a clean banner, so whatever the last helper needed
        # read has to be forgotten too, or the next helper saying the same
        # thing would be taken for something already shown and shown nothing.
        self._notice_text = ""
        self.errorChanged.emit()
        self.selectedDeviceChanged.emit()
        self._set_status("connecting", f"Connecting to {device.name}…")
        if self._demo:
            QTimer.singleShot(900, lambda: self._set_status("streaming", f"Sharing your screen with {device.name}"))
            return
        try:
            self._attempt_started = time.time()
            self._stream_unit = self._service.start_stream(device.path, choose_source,
                                                           self._slow_link)
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

    @staticmethod
    def _forget_shared_source():
        """Forget which screen or window was being shared.

        The engine tells the portal it may remember what is being shared, so
        that reaching a receiver again during a cast does not interrupt it to
        ask the same question twice. That memory is meant to last the sitting
        and no longer: being asked once is how a person says what to share,
        and a choice made yesterday is not an answer to today's question.
        """
        runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime_dir:
            return
        try:
            Path(runtime_dir, "screencast-restore-token").unlink(missing_ok=True)
        except OSError:
            # Leaving a cast's last choice behind is a small matter next to
            # failing to quit over it.
            pass

    def shutdown(self):
        """Called as the application quits. A running cast is left running."""
        # Forgotten whatever else quitting does, including when a cast is
        # left running: the next start asks again either way.
        self._forget_shared_source()
        # A cast that is left running is left with something to send. Taking
        # the screen away under a cast that is still going would empty it,
        # which is the one thing this whole feature exists to prevent, so the
        # screen outlives the window exactly as far as the cast does.
        if self._status != "streaming":
            self.releaseVirtualScreen()
        if self._demo or self._service is None or self._status == "streaming":
            return
        release = getattr(self._service, "release", None)
        if release:
            try:
                release()
            except Exception:
                pass

    @pyqtSlot(str)
    def connectAndChoose(self, device_id: str):
        """Reach a receiver and be asked what to share, instead of sharing
        whatever was shared last time. The same as connecting otherwise, and
        what is chosen becomes what is offered back next time."""
        self.connectToDevice(device_id, True)

    @pyqtProperty(bool, notify=virtualScreenChanged)
    def virtualScreenReady(self):
        """Whether a screen has been made and is waiting to be shared."""
        return bool(self._vscreen_for)

    @pyqtSlot(str)
    def makeVirtualScreen(self, device_id: str):
        """Make a screen to share, for this receiver.

        Nothing is cast yet. The screen has to exist before the desktop will
        offer it, and a person has to be able to see where it was put and
        change their mind about it, so making it and sharing it are two steps
        with a dialog between them."""
        if self.devices.by_id(device_id) is None:
            self._set_error("That display is no longer available")
            return
        try:
            self._vscreen.start()
        except VirtualScreenError as error:
            self._set_error(str(error))
            return
        self._vscreen_for = device_id
        self.virtualScreenChanged.emit()

    @pyqtSlot()
    def shareVirtualScreen(self):
        """Share the screen that was made: the desktop is asked what to share
        and the new screen is there among the real ones, under its own name."""
        device_id, self._vscreen_for = self._vscreen_for, ""
        self.virtualScreenChanged.emit()
        if device_id:
            self.connectAndChoose(device_id)

    @pyqtSlot()
    def dropVirtualScreen(self):
        """Changed their mind. The screen goes away again, and nothing was
        cast, so there is nothing else to undo."""
        self.releaseVirtualScreen()

    @pyqtProperty(str, notify=linkChanged)
    def linkBand(self):
        """Which band the receiver put this cast on, or empty while unknown."""
        return self._band

    @pyqtProperty(bool, notify=linkChanged)
    def linkTooSlow(self):
        """Whether the link and what is being sent disagree.

        True only while a poor band is carrying the full picture, which is the
        one case a person can do something about. Once what is sent matches
        the band, this is false again even though the band is no better: there
        is nothing left to act on, and a control that keeps asking for an
        answer already given is noise."""
        return self._band == p2p.BAND_24 and not self._slow_link

    @pyqtProperty(bool, notify=linkChanged)
    def linkMatched(self):
        """Whether a poor band is being sent what it will carry."""
        return self._band == p2p.BAND_24 and self._slow_link

    @pyqtSlot()
    def matchLinkFormat(self):
        """Send what this link will carry, from now on.

        What was settled with the receiver cannot be changed under a running
        cast, so the cast is ended and started again. The gap is the cost of
        the answer and is why this is asked for rather than done."""
        device_id = self._selected_id
        if not device_id:
            return
        # Captured before disconnecting, which forgets it.
        unit = self._stream_unit
        # Ending the cast forgets the choice, as it should for any ordinary
        # cast, so the choice is made after that and before the next one.
        self.disconnect()
        self._slow_link = True
        self.linkChanged.emit()
        self._set_status("connecting", "Changing to what this link will carry…")
        self._start_when_torn_down(unit, device_id, self.TEARDOWN_ATTEMPTS)

    def _start_when_torn_down(self, unit: str, device_id: str, left: int):
        """Start the next cast once the last one has actually gone.

        Ending a cast asks the helper to stop; it does not wait for it. The
        helper then takes seconds to put down the group, the session with the
        receiver and its sink, and starting the next one inside that window
        puts two helpers on one receiver. Both then negotiate, and the one
        that loses takes the picture with it.

        The sink makes it worse rather than better now that it is named after
        the receiver: two casts to the same television want the same name, so
        an overlap is a collision rather than two sinks nobody notices. That
        name is the right one to have, so the overlap is what has to go.

        A helper whose state cannot be read is treated as still running, for
        the reason written on stream_active: calling unknown "gone" is how a
        second helper got started beside a live one before."""
        if not unit:
            self.connectToDevice(device_id)
            return

        active = getattr(self._service, "stream_active", lambda _unit: False)(unit)
        if active is False:
            self.connectToDevice(device_id)
            return

        if left <= 0:
            # Waited out the budget. Going ahead is still better than leaving
            # somebody looking at a window that says it is connecting and
            # never will be, and it is said rather than hidden.
            # Said after starting, because starting clears the banner.
            self.connectToDevice(device_id)
            self._set_error("The last cast did not stop cleanly; starting the next one anyway.")
            return

        self._schedule(self.TEARDOWN_POLL_MS,
                       lambda: self._start_when_torn_down(unit, device_id, left - 1))

    @pyqtSlot()
    def releaseVirtualScreen(self):
        """Take away whatever screen was made, whenever there is no longer a
        reason for it: the cast ended, or the window is closing. Harmless when
        none was made, which is the usual case."""
        had = bool(self._vscreen_for)
        self._vscreen_for = ""
        self._vscreen.stop()
        if had:
            self.virtualScreenChanged.emit()

    @pyqtSlot()
    def openDisplaySettings(self):
        """Plasma's display settings, for moving or resizing what was made."""
        try:
            self._open_settings()
        except Exception as error:
            self._set_error(str(error))

    @pyqtSlot()
    def disconnect(self):
        previous = self._selected
        # Whatever was made to be shared goes when the sharing does. A screen
        # left behind is one nobody asked for and nothing else would remove.
        self.releaseVirtualScreen()
        # Every cast starts optimistic. What the receiver did with the last
        # one says nothing about where it will put the next.
        self._band = ""
        self._slow_link = False
        self.linkChanged.emit()
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
        # The other moment the answer can change: a cast that ran leaves a
        # choice behind to be handed back, one that never started does not.
        self._refresh_reuse()
        self.selectedDeviceChanged.emit()
        self._set_status("idle", f"Disconnected from {previous}" if previous else "Ready to find nearby displays")

    @pyqtSlot()
    def refreshDiagnostics(self):
        self.diagnostics.replace(self._diagnostic_collector(self._service, self._demo))

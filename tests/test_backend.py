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

import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PyQt6.QtCore import QCoreApplication

from mirdispo import p2p
from mirdispo.backend import DisplayBackend
from mirdispo.models import Diagnostic, DisplayDevice
from mirdispo.vscreen import VirtualScreenError


class FakeDiscovery:
    def __init__(self):
        self.started = False

    daemon_path = "/fake/backend"

    def ensure_running(self):
        self.started = True

    def running(self):
        return True

    devices = [DisplayDevice("/peer/1", "Test TV", strength=80)]

    def displays(self):
        return list(self.devices)

    unit_active = True
    start_fails = False

    started_slow = None

    def start_stream(self, uuid, choose_source=False, slow_link=False):
        self.started_uuid = uuid
        self.started_choosing = choose_source
        self.started_slow = slow_link
        if self.start_fails:
            return ""
        return "knd-test.service"

    stopped = None

    def stop_stream(self, unit):
        self.stopped = unit
        return None

    def stream_active(self, unit):
        return self.unit_active

    helper_state = None

    def stream_state(self, unit):
        return self.helper_state

    released = False

    def release(self):
        self.released = True

    discover_calls = None

    def set_discover(self, discover):
        if self.discover_calls is None:
            self.discover_calls = []
        self.discover_calls.append(discover)


class FakeP2P:
    def __init__(self, value=(p2p.STATE_DISCONNECTED, 0)):
        self.value = value

    def state(self):
        return self.value


class BackendTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_real_connection_starts_backend_stream(self):
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [Diagnostic("test", "Test", True, "Ready")],
        )
        backend.scan()
        self.assertTrue(discovery.started)
        backend._refresh_real_scan()
        self.assertEqual(backend.devices.rowCount(), 1)
        backend.connectToDevice("/peer/1")
        self.assertEqual(backend.status, "connecting")
        self.assertEqual(backend._stream_unit, "knd-test.service")
        self.assertEqual(discovery.started_uuid, "/peer/1")
        # The two ends agree on a group over the same channels the search
        # sweeps, so the search stops as soon as one is being reached rather
        # than once a picture arrives, which it never would otherwise.
        self.assertEqual(discovery.discover_calls, [False])

    def test_connect_uses_the_clicked_display_after_the_list_changes(self):
        """A display that disappears must not hand the click to its neighbour.

        Discovery replaces the list every two seconds. The Miracast and
        Chromecast entries of one TV sit next to each other, so a row index
        captured when the user looked at the list can point at the other
        protocol by the time the button is pressed.
        """
        discovery = FakeDiscovery()
        chromecast = DisplayDevice("/peer/cc", "TV - Chromecast", protocol=5)
        miracast = DisplayDevice("/peer/mira", "TV", protocol=3)
        discovery.devices = [miracast, chromecast]
        backend = DisplayBackend(
            discovery=discovery,
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        self.assertEqual(backend.devices.rowCount(), 2)

        # The display the user clicked goes away just before the click lands.
        discovery.devices = [chromecast]
        backend._poll_displays()

        backend.connectToDevice(miracast.path)
        self.assertIsNone(getattr(discovery, "started_uuid", None))
        self.assertEqual(backend.status, "error")
        self.assertEqual(backend.errorText, "That display is no longer available")

    def _connected_backend(self):
        discovery = FakeDiscovery()
        watcher = FakeP2P()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=watcher,
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")
        return watcher, backend

    def test_connection_progress_names_the_handshake_step(self):
        watcher, backend = self._connected_backend()

        watcher.value = (p2p.STATE_CONFIG, 0)
        backend._poll_displays()
        self.assertEqual(backend.status, "connecting")
        self.assertIn("Wi-Fi Direct", backend.statusText)

        watcher.value = (p2p.STATE_NEED_AUTH, 0)
        backend._poll_displays()
        self.assertIn("accept the connection", backend.statusText)

        watcher.value = (p2p.STATE_ACTIVATED, 0)
        backend._poll_displays()
        self.assertEqual(backend.status, "streaming")

    def test_handshake_timeout_is_retried_then_named_with_a_remedy(self):
        watcher, backend = self._connected_backend()

        # Receivers often refuse the first handshake after a previous session,
        # so the app retries before bothering the user.
        for attempt in range(backend.MAX_RECONNECTS):
            watcher.value = (p2p.STATE_FAILED, p2p.REASON_SUPPLICANT_TIMEOUT)
            backend._poll_displays()
            self.assertEqual(backend.status, "connecting")
            watcher.value = (p2p.STATE_CONFIG, 0)
            backend._poll_displays()

        watcher.value = (p2p.STATE_FAILED, p2p.REASON_SUPPLICANT_TIMEOUT)
        backend._poll_displays()

        self.assertEqual(backend.status, "error")
        self.assertIn("did not answer the Wi-Fi Direct handshake", backend.errorText)
        self.assertIn("Close screen sharing on the receiver", backend.errorText)

    def test_unknown_failure_reason_is_still_reported(self):
        watcher, backend = self._connected_backend()
        backend._reconnects = backend.MAX_RECONNECTS

        watcher.value = (p2p.STATE_FAILED, 61)
        backend._poll_displays()

        self.assertEqual(backend.status, "error")
        self.assertIn("reason 61", backend.errorText)

    def test_streaming_is_not_claimed_before_the_handshake_completes(self):
        watcher, backend = self._connected_backend()

        watcher.value = (p2p.STATE_CONFIG, 0)
        backend._verify_stream("Test TV")

        self.assertEqual(backend.status, "connecting")

    def test_a_failed_handshake_is_retried_without_the_user_clicking(self):
        """A timed-out attempt is retried without waiting for the user to
        click again. NetworkManager's "failed" state lasts about a
        millisecond, far too short for a two-second poll to see, so the
        helper exiting is what gives it away."""
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P((p2p.STATE_CONFIG, 0)),
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")

        # The helper starts, then exits when the handshake times out.
        backend._poll_displays()
        discovery.unit_active = False
        backend._poll_displays()

        self.assertEqual(backend.status, "connecting")
        self.assertIn("did not answer", backend.statusText)
        self.assertEqual(backend._reconnects, 1)

    def test_a_helper_that_never_starts_is_not_mistaken_for_a_failure(self):
        """systemd needs a moment; an absent unit is not a dropped stream."""
        discovery = FakeDiscovery()
        discovery.unit_active = False
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P((p2p.STATE_CONFIG, 0)),
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")

        backend._poll_displays()
        backend._poll_displays()

        self.assertEqual(backend._reconnects, 0)
        self.assertEqual(backend.status, "connecting")

    def test_a_receiver_that_never_answers_is_reported_plainly(self):
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P((p2p.STATE_CONFIG, 0)),
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")

        for _ in range(backend.MAX_CONNECT_ATTEMPTS + 1):
            discovery.unit_active = True
            backend._poll_displays()
            discovery.unit_active = False
            backend._poll_displays()

        self.assertEqual(backend.status, "error")
        self.assertIn("did not accept the connection", backend.errorText)

    def test_a_formation_failure_retries_almost_at_once(self):
        """The receiver sends no invitation after a group formation failure,
        so there is nothing to stand off for."""
        delays = []
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P((p2p.STATE_CONFIG, 0)),
            scheduler=lambda ms, callback: (delays.append(ms), callback()),
            handshake_probe=lambda _since: True,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")

        backend._poll_displays()

        self.assertEqual(delays, [backend.FAST_RETRY_DELAY_MS])
        self.assertLess(backend.FAST_RETRY_DELAY_MS, backend.RETRY_DELAY_MS)

    def test_a_handshake_retry_stands_off_before_trying_again(self):
        """The receiver's own request arrives about two seconds after ours
        expires; retrying instantly puts both on the air at once."""
        delays = []
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P((p2p.STATE_CONFIG, 0)),
            scheduler=lambda ms, callback: (delays.append(ms), callback()),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")

        backend._poll_displays()
        discovery.unit_active = False
        backend._poll_displays()

        self.assertEqual(delays, [backend.RETRY_DELAY_MS])
        self.assertGreater(backend.RETRY_DELAY_MS, 5000)
        self.assertIn("2 of 5", backend.statusText)

    def test_an_unknown_unit_state_never_starts_a_second_helper(self):
        """Two helpers negotiating with one receiver collide. A lookup that
        failed used to read as "the helper died", which started one."""
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P((p2p.STATE_CONFIG, 0)),
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")
        backend._poll_displays()

        discovery.unit_active = None  # systemd could not be asked
        backend._poll_displays()
        backend._poll_displays()

        self.assertEqual(backend._reconnects, 0)
        self.assertEqual(backend.status, "connecting")

    def test_a_retry_stops_the_previous_helper_first(self):
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P((p2p.STATE_CONFIG, 0)),
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")
        backend._poll_displays()

        discovery.unit_active = False
        backend._poll_displays()

        self.assertEqual(discovery.stopped, "knd-test.service")

    def test_a_lost_handshake_is_acted_on_without_waiting_for_the_timeout(self):
        """wpa_supplicant knows a handshake has failed well before
        NetworkManager stops waiting for it."""
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P((p2p.STATE_CONFIG, 0)),
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: True,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")

        # The helper is still running; only the supplicant knows it is over.
        backend._poll_displays()

        self.assertEqual(backend._reconnects, 1)
        self.assertIn("Retrying", backend.statusText)

    def test_a_dropped_link_is_retried_before_giving_up(self):
        """A moment of beacon loss should cost an interruption, not the
        whole session."""
        discovery = FakeDiscovery()
        watcher = FakeP2P()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=watcher,
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")
        watcher.value = (p2p.STATE_ACTIVATED, 0)
        backend._poll_displays()
        backend._poll_displays()
        self.assertEqual(backend.status, "streaming")
        self.assertEqual(discovery.started_uuid, "/peer/1")

        for _ in range(backend.MAX_RECONNECTS):
            discovery.unit_active = False
            backend._poll_displays()
            self.assertEqual(backend.status, "connecting")
            self.assertIn("Reconnecting", backend.statusText)

            # The replacement helper comes up and the link is reported again.
            discovery.unit_active = True
            watcher.value = (p2p.STATE_ACTIVATED, 0)
            backend._last_state = None
            backend._poll_displays()
            backend._poll_displays()
            self.assertEqual(backend.status, "streaming")

        # Every drop above recovered, so the session is still going. It ends
        # only when a drop cannot be recovered: here each replacement helper
        # dies before the picture is back.
        watcher.value = (p2p.STATE_DISCONNECTED, 0)
        discovery.unit_active = False
        backend._poll_displays()
        for _ in range(10):
            if backend.status == "error":
                break
            discovery.unit_active = True
            backend._poll_displays()
            discovery.unit_active = False
            backend._poll_displays()
        self.assertEqual(backend.status, "error")
        self.assertNotEqual(backend.errorText, "")
        self.assertEqual(discovery.started_uuid, "/peer/1")

    def test_a_reconnect_that_cannot_start_is_reported(self):
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P((p2p.STATE_ACTIVATED, 0)),
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")
        backend._poll_displays()

        discovery.unit_active = False
        discovery.start_fails = True
        backend._poll_displays()

        self.assertEqual(backend.status, "error")
        self.assertIn("did not start", backend.errorText)

    def test_identical_poll_results_do_not_reset_the_list(self):
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        resets = []
        backend.devices.modelAboutToBeReset.connect(lambda: resets.append(1))
        backend._poll_displays()
        self.assertEqual(resets, [])


class HelperStateTests(unittest.TestCase):
    """What the stream helper reports decides success, not the route to it."""

    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def make(self):
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P(),
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        backend.connectToDevice("/peer/1")
        return discovery, backend

    def test_an_unknown_helper_is_not_reported_as_failed(self):
        # A helper started by an engine in another Flatpak sandbox instance
        # could not be seen, and the working cast was called a failure.
        discovery, backend = self.make()
        discovery.unit_active = None
        backend._verify_stream("Test TV")
        self.assertEqual(backend.errorText, "")
        self.assertEqual(backend.status, "connecting")

    def test_a_helper_known_to_be_gone_is_still_a_failure(self):
        discovery, backend = self.make()
        discovery.unit_active = False
        backend._verify_stream("Test TV")
        self.assertEqual(backend.status, "error")

    def test_a_network_receiver_is_streaming_when_the_helper_says_so(self):
        # Over the network there is no Wi-Fi Direct link to become active.
        discovery, backend = self.make()
        backend._verify_stream("Test TV")
        self.assertEqual(backend.status, "connecting")
        discovery.helper_state = "streaming"
        backend._poll_displays()
        self.assertEqual(backend.status, "streaming")

    def test_negotiating_is_not_streaming(self):
        discovery, backend = self.make()
        discovery.helper_state = "wait-streaming"
        backend._poll_displays()
        self.assertEqual(backend.status, "connecting")

    def test_stopping_from_the_desktop_is_not_reconnected(self):
        discovery, backend = self.make()
        discovery.helper_state = "streaming"
        backend._poll_displays()
        discovery.helper_state = "ended"
        backend._poll_displays()
        self.assertEqual(backend.status, "idle")
        self.assertEqual(backend.errorText, "")
        self.assertEqual(discovery.stopped, "knd-test.service")
        self.assertIn("was stopped", backend.statusText)

    def test_every_recovered_drop_gets_the_full_retry_budget(self):
        # A long session over Wi-Fi Direct can lose the link more often than
        # MAX_RECONNECTS times. Each drop that recovers starts the count over.
        discovery, backend = self.make()
        for _ in range(backend.MAX_RECONNECTS + 3):
            discovery.helper_state = "streaming"
            backend._poll_displays()
            self.assertEqual(backend.status, "streaming")
            backend._handle_dropped_stream(connected=True)
            self.assertEqual(backend.status, "connecting")
            self.assertEqual(backend.errorText, "")

    def test_the_search_pauses_while_streaming_and_resumes_after(self):
        discovery, backend = self.make()
        discovery.helper_state = "streaming"
        backend._poll_displays()
        self.assertEqual(discovery.discover_calls, [False])
        # A drop puts the backend back to reaching for the receiver, which
        # needs the radio as much as sending does, so the search stays off
        # rather than resuming between the two.
        backend._handle_dropped_stream(connected=True)
        self.assertEqual(discovery.discover_calls, [False])
        backend._poll_displays()
        backend.disconnect()
        self.assertEqual(discovery.discover_calls, [False, True])

    def test_quitting_idle_stops_the_engine_but_not_a_cast(self):
        discovery, backend = self.make()
        backend.shutdown()
        self.assertTrue(discovery.released)

        discovery, backend = self.make()
        discovery.helper_state = "streaming"
        backend._poll_displays()
        backend.shutdown()
        self.assertFalse(discovery.released)


class FakeVirtualScreen:
    """A screen that is made and taken away without anything appearing on
    anybody's desk."""

    def __init__(self, fails_with=None):
        self.running = False
        self.starts = 0
        self.stops = 0
        self._fails_with = fails_with

    def start(self, resolution=None):
        if self._fails_with:
            raise VirtualScreenError(self._fails_with)
        self.starts += 1
        self.running = True
        return "Virtual-Mirdispo"

    def stop(self):
        self.stops += 1
        self.running = False


class VirtualScreenTests(unittest.TestCase):
    """Making a screen to cast, and being sure it does not outlive its use."""

    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def make(self, screen=None):
        discovery = FakeDiscovery()
        screen = screen if screen is not None else FakeVirtualScreen()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P(),
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
            virtual_screen=screen,
            settings_opener=lambda: None,
        )
        backend._refresh_real_scan()
        return discovery, backend, screen

    def test_making_one_does_not_start_a_cast(self):
        discovery, backend, screen = self.make()
        backend.makeVirtualScreen("/peer/1")
        self.assertTrue(screen.running)
        self.assertTrue(backend.virtualScreenReady)
        self.assertEqual(backend._stream_unit, "", "nothing should be cast yet")
        self.assertEqual(backend.status, "idle")

    def test_going_on_casts_and_asks_what_to_share(self):
        discovery, backend, screen = self.make()
        backend.makeVirtualScreen("/peer/1")
        backend.shareVirtualScreen()
        self.assertFalse(backend.virtualScreenReady)
        self.assertTrue(screen.running, "the screen being cast must stay")
        self.assertEqual(backend.status, "connecting")
        # Asked rather than handed back, or the picker never appears and the
        # screen just made cannot be chosen.
        self.assertTrue(discovery.started_choosing)

    def test_changing_their_mind_takes_the_screen_away(self):
        discovery, backend, screen = self.make()
        backend.makeVirtualScreen("/peer/1")
        backend.dropVirtualScreen()
        self.assertFalse(screen.running)
        self.assertFalse(backend.virtualScreenReady)
        self.assertEqual(backend._stream_unit, "")

    def test_disconnecting_takes_the_screen_away(self):
        discovery, backend, screen = self.make()
        backend.makeVirtualScreen("/peer/1")
        backend.shareVirtualScreen()
        backend.disconnect()
        self.assertFalse(screen.running)

    def test_quitting_takes_it_away_unless_the_cast_is_left_running(self):
        discovery, backend, screen = self.make()
        backend.makeVirtualScreen("/peer/1")
        backend.shareVirtualScreen()
        backend.shutdown()
        self.assertFalse(screen.running, "nothing was casting, so nothing needs it")

        discovery, backend, screen = self.make()
        backend.makeVirtualScreen("/peer/1")
        backend.shareVirtualScreen()
        backend._set_status("streaming", "Sharing")
        backend.shutdown()
        self.assertTrue(screen.running, "a cast left running must keep its screen")

    def test_a_missing_program_is_said_and_nothing_is_cast(self):
        discovery, backend, screen = self.make(
            screen=FakeVirtualScreen(fails_with="krfb-virtualmonitor was not found."))
        backend.makeVirtualScreen("/peer/1")
        self.assertIn("krfb-virtualmonitor", backend.errorText)
        self.assertFalse(backend.virtualScreenReady)
        self.assertEqual(backend.status, "idle")

    def test_a_display_that_vanished_makes_no_screen(self):
        discovery, backend, screen = self.make()
        backend.makeVirtualScreen("/peer/gone")
        self.assertEqual(screen.starts, 0)
        self.assertFalse(backend.virtualScreenReady)
        self.assertIn("no longer available", backend.errorText)


if __name__ == "__main__":
    unittest.main()


class LinkBandTests(unittest.TestCase):
    """Noticing the band the receiver chose, and sending what it will carry."""

    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def make(self, band=None):
        discovery = FakeDiscovery()
        backend = DisplayBackend(
            discovery=discovery,
            p2p_watcher=FakeP2P(),
            scheduler=lambda _ms, callback: callback(),
            handshake_probe=lambda _since: False,
            diagnostic_collector=lambda *_: [],
        )
        backend._refresh_real_scan()
        self.bands = [band]
        p2p_group_band = p2p.group_band
        p2p.group_band = lambda: self.bands[0]
        self.addCleanup(setattr, p2p, "group_band", p2p_group_band)
        return discovery, backend

    def test_a_cast_starts_asking_for_the_full_picture(self):
        discovery, backend = self.make(band=p2p.BAND_5)
        backend.connectToDevice("/peer/1")
        self.assertIs(discovery.started_slow, False)

    def test_a_good_band_asks_nothing_of_anybody(self):
        discovery, backend = self.make(band=p2p.BAND_5)
        backend.connectToDevice("/peer/1")
        backend._poll_displays()
        self.assertEqual(backend.linkBand, p2p.BAND_5)
        self.assertFalse(backend.linkTooSlow)
        self.assertFalse(backend.linkMatched)

    def test_a_poor_band_carrying_the_full_picture_asks(self):
        discovery, backend = self.make(band=p2p.BAND_24)
        backend.connectToDevice("/peer/1")
        backend._poll_displays()
        self.assertEqual(backend.linkBand, p2p.BAND_24)
        self.assertTrue(backend.linkTooSlow, "this is the one case to act on")
        self.assertFalse(backend.linkMatched)

    def test_matching_the_format_reconnects_and_stops_asking(self):
        discovery, backend = self.make(band=p2p.BAND_24)
        backend.connectToDevice("/peer/1")
        backend._poll_displays()
        backend.matchLinkFormat()
        self.assertIs(discovery.started_slow, True, "the engine must be told")
        backend._poll_displays()
        self.assertTrue(backend.linkMatched)
        self.assertFalse(backend.linkTooSlow, "nothing left to act on")

    def test_the_next_ordinary_cast_starts_optimistic_again(self):
        discovery, backend = self.make(band=p2p.BAND_24)
        backend.connectToDevice("/peer/1")
        backend._poll_displays()
        backend.matchLinkFormat()
        self.assertIs(discovery.started_slow, True)
        backend.disconnect()
        backend.connectToDevice("/peer/1")
        self.assertIs(discovery.started_slow, False,
                      "where the receiver puts the next group is not known yet")

    def test_a_band_that_cannot_be_read_says_nothing(self):
        discovery, backend = self.make(band=None)
        backend.connectToDevice("/peer/1")
        backend._poll_displays()
        self.assertEqual(backend.linkBand, "")
        self.assertFalse(backend.linkTooSlow)
        self.assertFalse(backend.linkMatched)

    def test_the_band_is_read_once_rather_than_every_poll(self):
        discovery, backend = self.make(band=p2p.BAND_24)
        reads = []
        p2p.group_band = lambda: (reads.append(1), p2p.BAND_24)[1]
        backend.connectToDevice("/peer/1")
        for _ in range(4):
            backend._poll_displays()
        self.assertEqual(len(reads), 1, "a group does not change channel")

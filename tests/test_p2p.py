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

import shutil
import sys
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mirdispo import p2p
from mirdispo.p2p import GroupFormationProbe, group_band, group_interfaces


class GroupInterfaceTests(unittest.TestCase):
    def make_sysfs(self, interfaces):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root)
        for name, flags in interfaces.items():
            (root / name).mkdir()
            (root / name / "flags").write_text(flags + "\n")
        return root

    def test_lists_group_interfaces_that_are_up(self):
        root = self.make_sysfs({"lo": "0x9", "wlp2s0": "0x1003",
                                "p2p-wlp2s0-3": "0x1003", "p2p-dev-wlp2s0": "0x1003"})
        self.assertEqual(group_interfaces(root), {"p2p-wlp2s0-3"})

    def test_a_group_interface_left_down_does_not_count(self):
        # Created for a request the receiver never answered, and left behind.
        root = self.make_sysfs({"p2p-wlp2s0-0": "0x1002"})
        self.assertEqual(group_interfaces(root), set())

    def test_missing_sysfs_means_none(self):
        self.assertEqual(group_interfaces(Path("/nonexistent-sysfs")), set())


class GroupFormationProbeTests(unittest.TestCase):
    """Replays the interface lists seen during logged handshakes."""

    def replay(self, polls, attempt=100.0):
        state = iter(polls)
        probe = GroupFormationProbe(lambda: next(state))
        return [probe(attempt) for _ in polls]

    def test_formation_failure_is_noticed_when_the_group_disappears(self):
        verdicts = self.replay([set(), {"p2p-wlp2s0-1"}, {"p2p-wlp2s0-1"}, set()])
        self.assertEqual(verdicts, [False, False, False, True])

    def test_a_slow_successful_handshake_is_left_alone(self):
        verdicts = self.replay([set(), set(), {"p2p-wlp2s0-2"}, {"p2p-wlp2s0-2"}])
        self.assertEqual(verdicts, [False] * 4)

    def test_a_receiver_that_never_answers_is_left_to_the_timeout(self):
        self.assertEqual(self.replay([set()] * 5), [False] * 5)

    def test_a_group_created_before_the_first_poll_counts(self):
        verdicts = self.replay([{"p2p-wlp2s0-4"}, {"p2p-wlp2s0-4"}, set()])
        self.assertEqual(verdicts, [False, False, True])

    def test_a_new_attempt_starts_from_scratch(self):
        lists = iter([set(), {"p2p-wlp2s0-1"}, set(), set(), {"p2p-wlp2s0-2"}])
        probe = GroupFormationProbe(lambda: next(lists))
        self.assertEqual([probe(1.0), probe(1.0), probe(1.0)], [False, False, True])
        self.assertEqual([probe(2.0), probe(2.0)], [False, False])


if __name__ == "__main__":
    unittest.main()


class GroupBandTests(unittest.TestCase):
    """Which band the receiver put the group on, read from the kernel."""

    LINK_24 = """Connected to 42:cb:8b:51:29:24 (on p2p-wlp0s20-1)
\tSSID: DIRECT-ft
\tfreq: 2437.0
\tsignal: -52 dBm
\ttx bitrate: 39.0 MBit/s MCS 10
"""
    LINK_5 = """Connected to 42:cb:8b:51:29:24 (on p2p-wlp0s20-8)
\tSSID: DIRECT-PK
\tfreq: 5785.0
\tsignal: -63 dBm
\ttx bitrate: 263.3 MBit/s VHT-MCS 6 80MHz VHT-NSS 1
"""

    def test_a_group_on_a_social_channel_is_named(self):
        band = group_band(runner=lambda _argv: self.LINK_24,
                          interfaces=lambda: {"p2p-wlp0s20-1"})
        self.assertEqual(band, p2p.BAND_24)

    def test_a_group_on_five_gigahertz_is_named(self):
        band = group_band(runner=lambda _argv: self.LINK_5,
                          interfaces=lambda: {"p2p-wlp0s20-8"})
        self.assertEqual(band, p2p.BAND_5)

    def test_no_group_means_no_answer(self):
        self.assertIsNone(group_band(runner=lambda _argv: self.LINK_5,
                                     interfaces=lambda: set()))

    def test_a_reader_that_fails_is_not_an_answer(self):
        def explode(_argv):
            raise FileNotFoundError("iw")

        self.assertIsNone(group_band(runner=explode,
                                     interfaces=lambda: {"p2p-wlp0s20-1"}))

    def test_an_interface_with_no_link_is_not_an_answer(self):
        self.assertIsNone(group_band(runner=lambda _argv: "Not connected.\n",
                                     interfaces=lambda: {"p2p-wlp0s20-1"}))

    def test_a_frequency_in_neither_band_is_not_an_answer(self):
        # Six gigahertz is out of Wi-Fi Direct's reach; reading it as a band
        # would turn an impossibility into a warning.
        self.assertIsNone(group_band(runner=lambda _argv: "\tfreq: 6135.0\n",
                                     interfaces=lambda: {"p2p-wlp0s20-1"}))

    def test_the_interface_is_the_one_that_is_up(self):
        seen = []

        def record(argv):
            seen.append(argv)
            return self.LINK_24

        group_band(runner=record, interfaces=lambda: {"p2p-wlp0s20-3"})
        self.assertEqual(seen, [["iw", "dev", "p2p-wlp0s20-3", "link"]])

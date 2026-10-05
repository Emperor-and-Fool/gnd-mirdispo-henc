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

from mirdispo import vscreen
from mirdispo.vscreen import OUTPUT_NAME, VirtualScreen, VirtualScreenError


class FakeChild:
    """A program that is running until it is told to stop, or that was never
    running at all."""

    def __init__(self, exits_with=None):
        self._exits_with = exits_with
        self.terminated = False
        self.killed = False

    def poll(self):
        return self._exits_with

    def terminate(self):
        self.terminated = True
        self._exits_with = 0

    def kill(self):
        self.killed = True
        self._exits_with = -9

    def wait(self, timeout=None):
        return self._exits_with


def screen(outputs, child=None, installed=True):
    """A virtual screen whose machine has been replaced by a list.

    ``outputs`` is a list of the readings kscreen-doctor would give, one per
    call, so a test can say what was there before the screen appeared and what
    was there after."""
    readings = list(outputs)
    placed = []
    spawned = []

    def read():
        return readings.pop(0) if len(readings) > 1 else readings[0]

    made = VirtualScreen(spawn=lambda argv: (spawned.append(argv), child or FakeChild())[1],
                         outputs=read,
                         position=lambda name, x, y: placed.append((name, x, y)),
                         which=lambda _name: "/usr/bin/krfb-virtualmonitor" if installed else None)
    return made, placed, spawned


MONITORS = [{"name": "eDP-1", "enabled": True, "pos": {"x": 0, "y": 0},
             "size": {"width": 1920, "height": 1080}},
            {"name": "DP-1", "enabled": True, "pos": {"x": 1920, "y": 0},
             "size": {"width": 2560, "height": 1440}}]

WITH_VIRTUAL = MONITORS + [{"name": OUTPUT_NAME, "enabled": True,
                            "pos": {"x": 0, "y": 0},
                            "size": {"width": 1920, "height": 1080}}]


class MakingOneTests(unittest.TestCase):
    def test_the_output_plasma_registers_is_handed_back(self):
        made, _placed, _spawned = screen([MONITORS, WITH_VIRTUAL])
        self.assertEqual(made.start(), OUTPUT_NAME)
        self.assertTrue(made.running)

    def test_it_is_asked_for_by_name_and_size(self):
        made, _placed, spawned = screen([MONITORS, WITH_VIRTUAL])
        made.start("1280x720")
        argv = spawned[0]
        self.assertEqual(argv[0], vscreen.BINARY)
        self.assertEqual(argv[argv.index("--name") + 1], vscreen.MONITOR_NAME)
        self.assertEqual(argv[argv.index("--resolution") + 1], "1280x720")

    def test_every_screen_gets_a_password_of_its_own(self):
        # It is a VNC server on the network for as long as it exists and it
        # cannot be asked to listen here alone, so the password is the only
        # thing standing in front of it.
        first, _placed, spawned_first = screen([MONITORS, WITH_VIRTUAL])
        second, _placed, spawned_second = screen([MONITORS, WITH_VIRTUAL])
        first.start()
        second.start()
        password = spawned_first[0][spawned_first[0].index("--password") + 1]
        again = spawned_second[0][spawned_second[0].index("--password") + 1]
        self.assertNotEqual(password, again)
        self.assertGreaterEqual(len(password), 12)

    def test_it_is_put_one_screen_along_from_everything_else(self):
        made, placed, _spawned = screen([MONITORS, WITH_VIRTUAL])
        made.start()
        self.assertEqual(placed, [(OUTPUT_NAME, 4480, 0)])

    def test_a_screen_that_is_off_does_not_push_it_further_right(self):
        dark = MONITORS + [{"name": "HDMI-1", "enabled": False, "pos": {"x": 4480, "y": 0},
                            "size": {"width": 1920, "height": 1080}}]
        made, placed, _spawned = screen([dark, dark + [WITH_VIRTUAL[-1]]])
        made.start()
        self.assertEqual(placed, [(OUTPUT_NAME, 4480, 0)])

    def test_asking_twice_does_not_make_a_second_one(self):
        made, _placed, spawned = screen([MONITORS, WITH_VIRTUAL])
        made.start()
        self.assertEqual(made.start(), OUTPUT_NAME)
        self.assertEqual(len(spawned), 1)


class WhenItCannotBeMadeTests(unittest.TestCase):
    def test_a_missing_program_is_said_in_words_that_name_it(self):
        made, _placed, spawned = screen([MONITORS], installed=False)
        with self.assertRaises(VirtualScreenError) as raised:
            made.start()
        self.assertIn(vscreen.BINARY, str(raised.exception))
        self.assertIn("krfb", str(raised.exception))
        self.assertEqual(spawned, [], "nothing should have been started")

    def test_a_program_that_stops_by_itself_is_not_waited_out(self):
        made, _placed, _spawned = screen([MONITORS], child=FakeChild(exits_with=1))
        with self.assertRaises(VirtualScreenError):
            made.start()
        self.assertFalse(made.running)

    def test_a_screen_that_never_appears_is_given_up_on(self):
        made, _placed, _spawned = screen([MONITORS])
        made_appear_timeout = vscreen.APPEAR_TIMEOUT
        vscreen.APPEAR_TIMEOUT = 0.2
        self.addCleanup(setattr, vscreen, "APPEAR_TIMEOUT", made_appear_timeout)
        with self.assertRaises(VirtualScreenError):
            made.start()
        self.assertFalse(made.running)


class TakingItAwayTests(unittest.TestCase):
    def test_stopping_the_program_is_what_removes_the_screen(self):
        child = FakeChild()
        made, _placed, _spawned = screen([MONITORS, WITH_VIRTUAL], child=child)
        made.start()
        made.stop()
        self.assertTrue(child.terminated)
        self.assertFalse(made.running)

    def test_stopping_when_nothing_was_made_is_harmless(self):
        made, _placed, _spawned = screen([MONITORS])
        made.stop()
        self.assertFalse(made.running)

    def test_a_program_that_will_not_stop_politely_is_made_to(self):
        class Stubborn(FakeChild):
            def terminate(self):
                self.terminated = True

            def wait(self, timeout=None):
                if not self.killed:
                    raise TimeoutError
                return -9

        child = Stubborn()
        made, _placed, _spawned = screen([MONITORS, WITH_VIRTUAL], child=child)
        made.start()
        made.stop()
        self.assertTrue(child.killed, "a screen nobody asked for must not be left up")


if __name__ == "__main__":
    unittest.main()

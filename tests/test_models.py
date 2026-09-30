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

from PyQt6.QtCore import QCoreApplication, Qt

from mirdispo.models import DisplayDevice, DisplayModel


class DisplayModelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def test_filters_non_wfd_deduplicates_and_sorts(self):
        model = DisplayModel()
        model.replace(
            [
                DisplayDevice("a", "Weak", strength=10),
                DisplayDevice("b", "Not a display", strength=100, wfd_capable=False),
                DisplayDevice("a", "Strong", strength=90),
                DisplayDevice("c", "Middle", strength=50),
            ]
        )
        self.assertEqual(model.rowCount(), 2)
        self.assertEqual(model.data(model.index(0), Qt.ItemDataRole.DisplayRole), "Strong")
        self.assertEqual(model.at(1).name, "Middle")

class RoutePreferenceTests(unittest.TestCase):
    """A receiver often announces itself over several routes at once."""

    def test_the_network_route_wins_over_wifi_direct(self):
        model = DisplayModel()
        model.replace([
            DisplayDevice("uuid-p2p", "Living room", protocol=3),
            DisplayDevice("uuid-mice", "Living room", protocol=4),
        ])

        self.assertEqual(model.rowCount(), 1)
        device = model.at(0)
        self.assertEqual(device.protocol, 4)
        self.assertEqual(device.path, "uuid-mice")

    def test_wifi_direct_is_kept_when_it_is_the_only_route(self):
        model = DisplayModel()
        model.replace([DisplayDevice("uuid-p2p", "Living room", protocol=3)])

        self.assertEqual(model.rowCount(), 1)
        self.assertEqual(model.at(0).protocol, 3)

    def test_different_receivers_are_not_merged(self):
        model = DisplayModel()
        model.replace([
            DisplayDevice("uuid-a", "Living room", protocol=3),
            DisplayDevice("uuid-b", "Kitchen", protocol=3),
        ])

        self.assertEqual(model.rowCount(), 2)

    def test_chromecast_loses_to_both_miracast_routes(self):
        model = DisplayModel()
        model.replace([
            DisplayDevice("uuid-cc", "Living room", protocol=5),
            DisplayDevice("uuid-p2p", "Living room", protocol=3),
        ])

        self.assertEqual(model.at(0).protocol, 3)

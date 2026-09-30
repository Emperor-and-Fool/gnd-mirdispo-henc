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

from mirdispo.tray import can_stop, tray_label


class TrayTextTests(unittest.TestCase):
    def test_says_who_the_screen_is_shared_with(self):
        self.assertEqual(tray_label("streaming", "Living room TV", "Sharing session active"),
                         "Sharing your screen with Living room TV")

    def test_says_where_it_is_connecting(self):
        self.assertEqual(tray_label("connecting", "Living room TV", "Retrying…"),
                         "Connecting to Living room TV…")

    def test_otherwise_repeats_the_window_status(self):
        self.assertEqual(tray_label("idle", "", "Found 3 compatible displays"),
                         "Found 3 compatible displays")
        self.assertEqual(tray_label("idle", "", ""), "Not sharing")

    def test_stopping_is_offered_only_while_sharing_or_connecting(self):
        self.assertTrue(can_stop("streaming"))
        self.assertTrue(can_stop("connecting"))
        self.assertFalse(can_stop("idle"))
        self.assertFalse(can_stop("error"))


if __name__ == "__main__":
    unittest.main()

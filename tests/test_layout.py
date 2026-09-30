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

"""The action buttons have to line up.

A label without elide asks for as much width as its text needs, which pushed
the row wider than the card and carried the button right with it. The result
was a ragged column of buttons that differed by receiver name.

The measuring runs in its own process, because showing a window needs a
QGuiApplication and the rest of the suite has already created a plain
QCoreApplication by the time this runs.
"""

import subprocess
import sys
import unittest
from pathlib import Path

PROBE = Path(__file__).resolve().parent / "layout_probe.py"


class ActionButtonAlignmentTests(unittest.TestCase):
    def test_every_action_button_shares_one_column(self):
        result = subprocess.run([sys.executable, str(PROBE)],
                                capture_output=True, text=True, timeout=120)
        if result.returncode == 77:
            self.skipTest(f"interface not measurable here: {result.stdout.strip()}")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("aligned", result.stdout)


if __name__ == "__main__":
    unittest.main()

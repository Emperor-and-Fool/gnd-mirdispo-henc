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

from mirdispo.diagnostics import collect_diagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_demo_mode_reports_every_row(self):
        rows = collect_diagnostics(demo=True)
        self.assertTrue(all(row.ok for row in rows))
        self.assertIn("discovery", [row.key for row in rows])

    def test_rows_are_one_short_line(self):
        # The page is read at a glance; an explanation belongs on the control
        # that does the work, not in a report.
        for row in collect_diagnostics(demo=True):
            self.assertLess(len(row.detail), 80, row.key)

    def test_no_row_names_a_kernel_interface(self):
        for row in collect_diagnostics(demo=True):
            self.assertNotRegex(row.detail, r"\bwl[a-z0-9]{4,}\b")

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

"""The licence page must be true on every distribution, not just one."""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mirdispo import legal

GPL = "GNU GENERAL PUBLIC LICENSE\n Version 3, 29 June 2007\n"


def layout(root: Path, files: dict):
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


class LicenceLookupTests(unittest.TestCase):
    def test_debian_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout(root, {"usr/share/common-licenses/GPL-3": GPL})
            text = legal.licence_text(legal.licence_candidates((root,))[:-1])
            self.assertIn("GNU GENERAL PUBLIC LICENSE", text)

    def test_arch_and_fedora_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout(root, {"usr/share/licenses/mirdispo/LICENSE": GPL})
            text = legal.licence_text(legal.licence_candidates((root,))[:-1])
            self.assertIn("GNU GENERAL PUBLIC LICENSE", text)

    def test_a_system_without_the_licence_points_to_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            candidates = legal.licence_candidates((Path(tmp),))[:-1]
            text = legal.licence_text(candidates)
            self.assertIn(legal.GPL_URL, text)

    def test_an_unrelated_file_at_a_licence_path_is_not_shown(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            layout(root, {"usr/share/common-licenses/GPL-3": "something else"})
            text = legal.licence_text(legal.licence_candidates((root,))[:-1])
            self.assertIn(legal.GPL_URL, text)

    def test_the_source_tree_ships_the_licence(self):
        self.assertIn("GNU GENERAL PUBLIC LICENSE", legal.licence_text())


class SourceLocationTests(unittest.TestCase):
    def test_a_directory_with_patches_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            place = Path(tmp)
            (place / "0001-fix.patch").write_text("patch")
            self.assertEqual(legal.source_location([place]), str(place))

    def test_nothing_found_reports_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(legal.source_location([Path(tmp)]), "")


if __name__ == "__main__":
    unittest.main()

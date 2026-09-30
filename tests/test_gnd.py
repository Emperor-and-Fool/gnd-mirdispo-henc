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
import tempfile
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mirdispo.gnd import BUS_PREFIX, GnomeNetworkDisplaysService, _stream_process_running, display_from_dbus, stream_bus_name


class GndAdapterTests(unittest.TestCase):
    def test_converts_daemon_display(self):
        device = display_from_dbus({
            "uuid": "abc",
            "display-name": "Living Room",
            "priority": 80,
            "state": 0,
            "protocol": 3,
        })
        self.assertEqual(device.path, "abc")
        self.assertEqual(device.name, "Living Room")
        self.assertIn("Miracast", device.manufacturer)
        self.assertEqual(device.status, "available")

    def test_maps_all_real_protocol_ids(self):
        expected = {
            3: "Miracast (Wi-Fi Direct)",
            4: "Miracast over your network",
            5: "Chromecast",
        }
        for protocol, label in expected.items():
            with self.subTest(protocol=protocol):
                device = display_from_dbus({
                    "uuid": str(protocol),
                    "display-name": "Display",
                    "protocol": protocol,
                })
                self.assertEqual(device.manufacturer, label)


class StreamBusNameTests(unittest.TestCase):
    def test_follows_the_connection_part_of_the_unit(self):
        unit = ("gnome-network-displays-stream-11111111-2222-3333-4444-555555555555-"
                "0f1e2d3c-4b5a-6978-8796-a5b4c3d2e1f0.service")
        self.assertEqual(stream_bus_name(unit),
                         BUS_PREFIX + ".Stream_0f1e2d3c_4b5a_6978_8796_a5b4c3d2e1f0")

    def test_other_names_have_none(self):
        for unit in ("", "knd-test.service", "gnome-network-displays-stream-x"):
            self.assertIsNone(stream_bus_name(unit))


class SandboxedStreamTests(unittest.TestCase):
    """Inside Flatpak the stream helper is a child marked with ND_STREAM_UNIT."""

    def make_proc(self, processes):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(root))
        (root / "self").mkdir()
        for pid, environ in processes.items():
            (root / pid).mkdir()
            (root / pid / "environ").write_bytes(b"\0".join(environ) + b"\0")
        return root

    def test_finds_the_marked_helper(self):
        proc = self.make_proc({"12": [b"HOME=/", b"ND_STREAM_UNIT=unit-a.service"]})
        self.assertTrue(_stream_process_running("unit-a.service", proc))

    def test_another_stream_does_not_count(self):
        proc = self.make_proc({"12": [b"ND_STREAM_UNIT=unit-a.service"]})
        self.assertFalse(_stream_process_running("unit-b.service", proc))

    def test_a_prefix_of_the_name_does_not_count(self):
        proc = self.make_proc({"12": [b"ND_STREAM_UNIT=unit-a.service.old"]})
        self.assertFalse(_stream_process_running("unit-a.service", proc))

    def test_unreadable_proc_is_unknown(self):
        self.assertIsNone(_stream_process_running("x", Path("/nonexistent-proc")))


class FindDaemonTests(unittest.TestCase):
    """The engine is found next to wherever Mirdispo itself is installed."""

    def layout(self, files):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, root)
        for name in files:
            (root / name).parent.mkdir(parents=True, exist_ok=True)
            (root / name).write_text("")
        return root

    def test_any_install_prefix(self):
        for prefix in ("usr", "usr/local", "app", "home/user/.local"):
            root = self.layout([f"{prefix}/lib/mirdispo/mirdispo/gnd.py",
                                f"{prefix}/libexec/mirdispo-daemon"])
            found = GnomeNetworkDisplaysService._find_daemon(root / prefix / "lib/mirdispo/mirdispo/gnd.py")
            self.assertEqual(found, str(root / prefix / "libexec/mirdispo-daemon"))

    def test_a_checkout_after_make_backend(self):
        root = self.layout(["src/mirdispo/gnd.py", "vendor/amd64/mirdispo-daemon"])
        found = GnomeNetworkDisplaysService._find_daemon(root / "src/mirdispo/gnd.py")
        self.assertEqual(found, str(root / "vendor/amd64/mirdispo-daemon"))


if __name__ == "__main__":
    unittest.main()

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

from types import SimpleNamespace

from .models import Diagnostic


def _bus_has_name(bus, name: str) -> bool:
    import dbus

    proxy = bus.get_object("org.freedesktop.DBus", "/org/freedesktop/DBus")
    return bool(dbus.Interface(proxy, "org.freedesktop.DBus").NameHasOwner(name))


H264_ENCODERS = ("x264enc", "openh264enc", "vah264enc", "vaapih264enc")


def _gstreamer_elements() -> tuple[bool, str]:
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
        required = ("pipewiresrc", "rtph264pay", "mpegtsmux")
        missing = [name for name in required if Gst.ElementFactory.find(name) is None]
        # The engine takes whichever H.264 encoder the distribution ships.
        if not any(Gst.ElementFactory.find(name) for name in H264_ENCODERS):
            missing.append("an H.264 encoder (" + ", ".join(H264_ENCODERS) + ")")
        if missing:
            return False, "Missing: " + ", ".join(missing)
        return True, Gst.version_string() + "; video pipeline available"
    except Exception as error:
        return False, str(error)


def collect_diagnostics(discovery=None, demo=False) -> list[Diagnostic]:
    if discovery is None and not demo:
        # Called without the running service, as `--diagnostics` does: look the
        # backend up the same way the service would.
        from .gnd import GnomeNetworkDisplaysService

        discovery = SimpleNamespace(daemon_path=GnomeNetworkDisplaysService._find_daemon())
    if demo:
        return [
            Diagnostic("network-manager", "NetworkManager", True, "Demo provider"),
            Diagnostic("p2p", "Wi-Fi Direct", True, "Virtual P2P adapter"),
            Diagnostic("portal", "ScreenCast portal", True, "Virtual portal"),
            Diagnostic("gstreamer", "GStreamer video", True, "Virtual H.264 pipeline"),
            Diagnostic("discovery", "Network discovery", True, "Virtual network"),
        ]

    system_bus = None
    session_bus = None
    try:
        import dbus

        system_bus = dbus.SystemBus()
        nm_ok = _bus_has_name(system_bus, "org.freedesktop.NetworkManager")
        nm_detail = "Service available" if nm_ok else "Service is not running"
    except Exception as error:
        nm_ok, nm_detail = False, str(error)

    try:
        if discovery and getattr(discovery, "daemon_path", None):
            p2p_ok = True
            p2p_detail = "Casting backend installed"
        else:
            p2p_ok = False
            p2p_detail = "Casting backend is not installed"
    except Exception as error:
        p2p_ok, p2p_detail = False, str(error)

    try:
        import dbus

        session_bus = dbus.SessionBus()
        portal_ok = _bus_has_name(session_bus, "org.freedesktop.portal.Desktop")
        portal_detail = "Service available" if portal_ok else "Desktop portal is not running"
    except Exception as error:
        portal_ok, portal_detail = False, str(error)

    try:
        avahi_ok = _bus_has_name(system_bus, "org.freedesktop.Avahi")
        avahi_detail = (
            "Receivers on this network can be found"
            if avahi_ok
            else "Avahi is not running, so only Wi-Fi Direct receivers are found"
        )
    except Exception as error:
        avahi_ok, avahi_detail = False, str(error)

    gst_ok, gst_detail = _gstreamer_elements()
    return [
        Diagnostic("network-manager", "NetworkManager", nm_ok, nm_detail),
        Diagnostic("p2p", "Wi-Fi Direct", p2p_ok, p2p_detail),
        Diagnostic("portal", "ScreenCast portal", portal_ok, portal_detail),
        Diagnostic("gstreamer", "GStreamer video", gst_ok, gst_detail),
        Diagnostic("wfd-engine", "WFD session engine", p2p_ok, p2p_detail),
        Diagnostic("discovery", "Network discovery", avahi_ok, avahi_detail),
    ]

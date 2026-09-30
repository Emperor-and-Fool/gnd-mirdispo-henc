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

"""Live Wi-Fi Direct state, read straight from NetworkManager.

The casting daemon exposes a ``state`` for every display it knows about, but
that state belongs to the daemon's own sink object and stays at "available"
while a separate stream helper does the actual connecting. Measuring it during
real connection attempts showed it never moves, so it cannot drive any UI.

NetworkManager's Wi-Fi P2P device does move, and its failure reasons are the
ones that matter to a user: a receiver that never answers the handshake shows
up here as a supplicant timeout.
"""

from __future__ import annotations

from pathlib import Path

NM_SERVICE = "org.freedesktop.NetworkManager"
NM_PATH = "/org/freedesktop/NetworkManager"
NM_DEVICE = "org.freedesktop.NetworkManager.Device"
PROPERTIES = "org.freedesktop.DBus.Properties"

DEVICE_TYPE_WIFI_P2P = 30

# NMDeviceState
STATE_DISCONNECTED = 30
STATE_PREPARE = 40
STATE_CONFIG = 50
STATE_NEED_AUTH = 60
STATE_IP_CONFIG = 70
STATE_IP_CHECK = 80
STATE_ACTIVATED = 100
STATE_FAILED = 120

# NMDeviceStateReason values worth naming.
REASON_SUPPLICANT_TIMEOUT = 12
REASON_SUPPLICANT_FAILED = 10
REASON_SUPPLICANT_DISCONNECT = 8
REASON_NO_SECRETS = 7

PROGRESS = {
    STATE_PREPARE: "Preparing the Wi-Fi Direct connection…",
    STATE_CONFIG: "Negotiating Wi-Fi Direct with {name}. This can take up to a minute.",
    STATE_NEED_AUTH: "Waiting for {name} to accept the connection…",
    STATE_IP_CONFIG: "Setting up the direct link…",
    STATE_IP_CHECK: "Starting the stream…",
}

FAILURE_REASONS = {
    REASON_SUPPLICANT_TIMEOUT: (
        "{name} did not answer the Wi-Fi Direct handshake in time. "
        "Close screen sharing on the receiver, open it again, and retry."
    ),
    REASON_SUPPLICANT_FAILED: "The Wi-Fi Direct handshake with {name} failed.",
    REASON_SUPPLICANT_DISCONNECT: "{name} dropped the Wi-Fi Direct connection.",
    REASON_NO_SECRETS: "{name} asked for a PIN, which this receiver should not need.",
}


def _properties(bus, path):
    import dbus

    return dbus.Interface(bus.get_object(NM_SERVICE, path), PROPERTIES)


def _devices_of_type(bus, device_type):
    import dbus

    manager = dbus.Interface(bus.get_object(NM_SERVICE, NM_PATH), NM_SERVICE)
    for path in manager.GetDevices():
        props = _properties(bus, path)
        if int(props.Get(NM_DEVICE, "DeviceType")) == device_type:
            yield props


class P2PDeviceWatcher:
    """Reads the Wi-Fi P2P device's state and the reason it last changed."""

    def __init__(self, bus=None):
        if bus is None:
            import dbus

            bus = dbus.SystemBus()
        self.bus = bus

    def state(self) -> tuple[int, int] | None:
        """Return (state, reason), or None when there is no P2P device."""
        try:
            for props in _devices_of_type(self.bus, DEVICE_TYPE_WIFI_P2P):
                state, reason = props.Get(NM_DEVICE, "StateReason")
                return int(state), int(reason)
        except Exception:
            return None
        return None



SYS_CLASS_NET = Path("/sys/class/net")


IFF_UP = 0x1


def group_interfaces(root=SYS_CLASS_NET) -> set[str]:
    """The Wi-Fi Direct group interfaces that are up right now.

    wpa_supplicant names them p2p-<interface>-<n>. The P2P device itself,
    p2p-dev-<interface>, is not a network interface and never appears here.

    Only interfaces that are up count. wpa_supplicant creates the group
    interface, down, as soon as a connection is requested, and when the
    receiver never answers it can stay behind like that into the next attempt.
    It is brought up once group owner negotiation succeeds.
    """
    found = set()
    try:
        entries = list(root.iterdir())
    except OSError:
        return found
    for entry in entries:
        name = entry.name
        if not name.startswith("p2p-") or name.startswith("p2p-dev-"):
            continue
        try:
            if int((entry / "flags").read_text().strip(), 16) & IFF_UP:
                found.add(name)
        except (OSError, ValueError):
            continue
    return found


class GroupFormationProbe:
    """Tells a lost handshake apart from a slow one, without the journal.

    Once group owner negotiation succeeds, wpa_supplicant brings up a group
    interface for the rest of the handshake, and when group formation fails it
    removes that interface in the same moment it reports
    P2P-GROUP-FORMATION-FAILURE. NetworkManager then still waits out its
    45 second timeout. The verdict typically comes about 16 seconds after the
    negotiation, which leaves close to half a minute of waiting for nothing.

    A group interface that comes up during an attempt and is gone or down
    again while the attempt is still connecting is that verdict. Network interfaces can be
    listed by any user and from inside a Flatpak sandbox, unlike the system
    journal, which only administrators can read.

    Called once per poll with the time the current attempt started. Interfaces
    that already exist on the first call of an attempt count as part of it,
    since the negotiation can finish before the first poll.
    """

    def __init__(self, list_interfaces=group_interfaces):
        self._list = list_interfaces
        self._attempt = None
        self._seen: set[str] = set()

    def __call__(self, attempt_started: float) -> bool:
        current = self._list()
        if attempt_started != self._attempt:
            self._attempt = attempt_started
            self._seen = set(current)
            return False
        self._seen |= current
        return bool(self._seen - current)


def progress_message(state: int, name: str) -> str | None:
    message = PROGRESS.get(state)
    return message.format(name=name) if message else None


def failure_message(reason: int, name: str) -> str:
    message = FAILURE_REASONS.get(reason)
    if message:
        return message.format(name=name)
    return f"The Wi-Fi Direct connection to {name} failed (NetworkManager reason {reason})."

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

from dataclasses import asdict, dataclass

from PyQt6.QtCore import QAbstractListModel, QModelIndex, Qt


@dataclass(frozen=True)
class DisplayDevice:
    path: str
    name: str
    address: str = ""
    manufacturer: str = ""
    model: str = ""
    strength: int = 0
    wfd_capable: bool = True
    status: str = "available"
    protocol: int = 1

    @property
    def description(self) -> str:
        identity = " ".join(part for part in (self.manufacturer, self.model) if part)
        signal = f"{self.strength}% signal" if self.strength else "signal unknown"
        return " · ".join(part for part in (identity, signal) if part)


class DisplayModel(QAbstractListModel):
    Roles = {
        Qt.ItemDataRole.UserRole + 1: b"deviceId",
        Qt.ItemDataRole.UserRole + 2: b"name",
        Qt.ItemDataRole.UserRole + 3: b"description",
        Qt.ItemDataRole.UserRole + 4: b"address",
        Qt.ItemDataRole.UserRole + 5: b"strength",
        Qt.ItemDataRole.UserRole + 6: b"deviceStatus",
        Qt.ItemDataRole.UserRole + 7: b"protocol",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._devices: list[DisplayDevice] = []

    def roleNames(self):
        return self.Roles

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._devices)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._devices):
            return None
        device = self._devices[index.row()]
        values = {
            Qt.ItemDataRole.DisplayRole: device.name,
            Qt.ItemDataRole.UserRole + 1: device.path,
            Qt.ItemDataRole.UserRole + 2: device.name,
            Qt.ItemDataRole.UserRole + 3: device.description,
            Qt.ItemDataRole.UserRole + 4: device.address,
            Qt.ItemDataRole.UserRole + 5: device.strength,
            Qt.ItemDataRole.UserRole + 6: device.status,
            Qt.ItemDataRole.UserRole + 7: device.protocol,
        }
        return values.get(role)

    def replace(self, devices: list[DisplayDevice]):
        from .gnd import protocol_rank

        unique = {device.path: device for device in devices if device.wfd_capable}

        # A receiver often announces itself over more than one route. Showing
        # each route as its own row leaves the user guessing which to press,
        # and the slow one looks identical to the fast one. Keep the best
        # route per receiver.
        best: dict[str, DisplayDevice] = {}
        for device in unique.values():
            current = best.get(device.name)
            if current is None or protocol_rank(device.protocol) < protocol_rank(current.protocol):
                best[device.name] = device

        ordered = sorted(best.values(), key=lambda d: (-d.strength, d.name.casefold()))
        if ordered == self._devices:
            # Discovery polls continuously. Resetting the model when nothing
            # changed makes the list flicker and drops the user's selection.
            return
        self.beginResetModel()
        self._devices = ordered
        self.endResetModel()

    def at(self, row: int) -> DisplayDevice | None:
        return self._devices[row] if 0 <= row < len(self._devices) else None

    def by_id(self, device_id: str) -> DisplayDevice | None:
        """Look a display up by its stable identifier.

        Rows move as displays appear and disappear, so anything that acts on
        a user's choice has to resolve it by identifier, never by row.
        """
        return next((device for device in self._devices if device.path == device_id), None)

    def as_dicts(self):
        return [asdict(device) for device in self._devices]


@dataclass(frozen=True)
class Diagnostic:
    key: str
    label: str
    ok: bool
    detail: str


class DiagnosticsModel(QAbstractListModel):
    Roles = {
        Qt.ItemDataRole.UserRole + 1: b"label",
        Qt.ItemDataRole.UserRole + 2: b"ok",
        Qt.ItemDataRole.UserRole + 3: b"detail",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items: list[Diagnostic] = []

    def roleNames(self):
        return self.Roles

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._items)

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._items):
            return None
        item = self._items[index.row()]
        return {
            Qt.ItemDataRole.DisplayRole: item.label,
            Qt.ItemDataRole.UserRole + 1: item.label,
            Qt.ItemDataRole.UserRole + 2: item.ok,
            Qt.ItemDataRole.UserRole + 3: item.detail,
        }.get(role)

    def replace(self, items: list[Diagnostic]):
        self.beginResetModel()
        self._items = items
        self.endResetModel()

    def as_dicts(self):
        return [asdict(item) for item in self._items]

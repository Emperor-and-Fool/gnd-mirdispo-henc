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

"""Where the licence and the source live on whatever system this runs on.

The GPL requires telling users how to read the licence and where the source
is. Distributions keep both in different places: Debian and Ubuntu put the
licence in /usr/share/common-licenses, Arch and Fedora in /usr/share/licenses,
and a checkout of the source has it at the top of the tree. Naming one of
those paths in the interface is correct on some systems and false on the
rest, so the locations are looked up instead.
"""

from __future__ import annotations

from pathlib import Path

PACKAGE = "mirdispo"
APP_ID = "io.github.hencyber.Mirdispo"
_SOURCE_TREE = Path(__file__).resolve().parents[2]
GPL_URL = "https://www.gnu.org/licenses/gpl-3.0.html"


def licence_candidates(roots=(Path("/"),)) -> list[Path]:
    paths = []
    for root in roots:
        paths += [
            root / f"usr/share/licenses/{PACKAGE}/LICENSE",   # Arch, Fedora, openSUSE
            root / f"usr/share/doc/{PACKAGE}/LICENSE",        # this project's own .deb
            root / f"app/share/licenses/{APP_ID}/LICENSE",    # Flatpak
            root / "usr/share/common-licenses/GPL-3",          # Debian, Ubuntu
            root / "usr/share/licenses/common/GPL3/license.txt",
        ]
    paths.append(_SOURCE_TREE / "LICENSE")                     # running from a checkout
    return paths


def licence_text(candidates=None) -> str:
    for path in candidates if candidates is not None else licence_candidates():
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        if "GNU GENERAL PUBLIC LICENSE" in text and "Version 3" in text:
            return text
    return ("The GNU General Public License, version 3, was not found on this "
            f"system. It can be read at {GPL_URL}.")


def source_location(candidates=None) -> str:
    places = candidates if candidates is not None else [
        Path(f"/usr/share/doc/{PACKAGE}"),
        Path(f"/app/share/doc/{PACKAGE}"),                    # Flatpak
        _SOURCE_TREE / "packaging" / "patches",
    ]
    for place in places:
        if place.is_dir() and any(place.glob("*.patch")):
            return str(place)
    return ""

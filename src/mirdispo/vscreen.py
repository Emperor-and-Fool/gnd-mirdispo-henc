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

"""A screen to share when there is no second screen to share.

Casting the only screen there is leaves the person casting with nowhere to
work. The desktop will not make them another one: asking the portal for a
virtual screen gets an output that is registered, sized, placed and entirely
empty, because nothing is drawing on it. Measured here, a cast negotiated
against one completes every step and sends no picture at all.

A screen with something behind it has to be made by something that gives it a
surface, and krfb-virtualmonitor does exactly that. What it makes is not a
special case the rest of Mirdispo has to know about: Plasma registers it as an
ordinary monitor named after whatever it was called, which the portal then
offers beside the real ones. Everything downstream of the picker therefore
carries on as if a second screen had been plugged in.

Measured on Plasma 6, the output appears about two tenths of a second after
the program is started and is gone less than a tenth of a second after it is
stopped. The waiting here is far longer than either, because a machine under
load is still entitled to be slow, and waiting costs nothing when the thing
being waited for usually arrives before the first check.
"""

from __future__ import annotations

import json
import secrets
import shutil
import socket
import subprocess
import time

BINARY = "krfb-virtualmonitor"

# What Plasma calls the output, which is the name it was asked for behind a
# prefix of Plasma's own. The portal offers it under this name too, so it is
# also what a person is looking for in the picker.
MONITOR_NAME = "Mirdispo"
OUTPUT_NAME = f"Virtual-{MONITOR_NAME}"

DEFAULT_RESOLUTION = "1920x1080"

# How long the output is waited for, and how long the program is given to
# stop before it is made to. Both are far longer than anything measured.
APPEAR_TIMEOUT = 10.0
DISAPPEAR_TIMEOUT = 5.0
POLL_SECONDS = 0.05

MISSING_MESSAGE = (
    f"A virtual screen needs {BINARY}, which was not found. On Debian/Ubuntu it "
    "ships in the krfb package; other distributions may name it differently."
)


class VirtualScreenError(RuntimeError):
    """Something a person has to be told, in words they can act on."""


def _read_outputs() -> list[dict]:
    """Every output Plasma currently has, as kscreen-doctor reports them.

    An empty list where kscreen-doctor is missing or unhappy, because the only
    thing this is used for is looking for an output that has just appeared,
    and not finding one is the same answer either way."""
    try:
        done = subprocess.run(["kscreen-doctor", "-j"], capture_output=True, text=True, timeout=5)
        return json.loads(done.stdout)["outputs"]
    except Exception:
        return []


def _set_position(name: str, x: int, y: int) -> None:
    try:
        subprocess.run(["kscreen-doctor", f"output.{name}.position.{x},{y}"],
                       capture_output=True, text=True, timeout=5)
    except Exception:
        # Where it sits is worth having and not worth failing over: Plasma has
        # already placed it somewhere usable by the time this runs.
        pass


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class VirtualScreen:
    """One virtual screen, made on request and taken away again.

    Only one at a time, because a second would be made under the same name and
    neither Plasma nor the person picking one in the portal could tell them
    apart.

    The parts that touch the machine are injectable so that tests can watch
    what would have been done without a screen appearing on anybody's desk."""

    def __init__(self, spawn=None, outputs=None, position=None, which=None):
        self._spawn = spawn or (lambda argv: subprocess.Popen(
            argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        self._outputs = outputs or _read_outputs
        self._position = position or _set_position
        self._which = which or (lambda name: shutil.which(name))
        self._child = None

    @property
    def running(self) -> bool:
        return self._child is not None and self._child.poll() is None

    def available(self) -> str | None:
        """Where the program is, or None when it is not installed."""
        return self._which(BINARY)

    def start(self, resolution: str = DEFAULT_RESOLUTION) -> str:
        """Make the screen and hand back the name Plasma knows it by.

        Raises VirtualScreenError with something readable where the program is
        missing, or where the output never turns up."""
        if self.running:
            return OUTPUT_NAME

        if not self.available():
            raise VirtualScreenError(MISSING_MESSAGE)

        # The screen it makes is also a VNC server, reachable from the network
        # for as long as it exists, and there is no way to ask it to listen on
        # this machine alone. A password nobody has seen before, made fresh
        # every time and never written down, is what can be done about that
        # from here: the screen is a local one and nothing is meant to connect
        # to it over the wire.
        argv = [BINARY,
                "--name", MONITOR_NAME,
                "--resolution", resolution,
                "--password", secrets.token_urlsafe(12),
                "--port", str(_free_port())]

        self._child = self._spawn(argv)

        deadline = time.monotonic() + APPEAR_TIMEOUT
        while time.monotonic() < deadline:
            if any(output.get("name") == OUTPUT_NAME for output in self._outputs()):
                self._place_to_the_right()
                return OUTPUT_NAME
            if self._child.poll() is not None:
                self._child = None
                raise VirtualScreenError(
                    f"{BINARY} stopped before a screen appeared.")
            time.sleep(POLL_SECONDS)

        self.stop()
        raise VirtualScreenError(
            f"{BINARY} was started but no screen appeared within "
            f"{APPEAR_TIMEOUT:.0f} seconds.")

    def _place_to_the_right(self) -> None:
        """One screen along from everything else.

        Plasma puts it there already. Saying so anyway costs one call and
        covers the arrangements where it does not."""
        edge = 0
        for output in self._outputs():
            if output.get("name") == OUTPUT_NAME or not output.get("enabled"):
                continue
            pos, size = output.get("pos") or {}, output.get("size") or {}
            edge = max(edge, pos.get("x", 0) + size.get("width", 0))
        self._position(OUTPUT_NAME, edge, 0)

    def stop(self) -> None:
        """Take the screen away, and be sure it has gone.

        Stopping the program is what removes the output, so a program that
        will not stop politely is made to, rather than left holding a screen
        nobody asked for any more."""
        child, self._child = self._child, None
        if child is None or child.poll() is not None:
            return

        child.terminate()
        try:
            child.wait(timeout=DISAPPEAR_TIMEOUT)
        except Exception:
            child.kill()
            try:
                child.wait(timeout=DISAPPEAR_TIMEOUT)
            except Exception:
                pass

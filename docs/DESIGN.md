# How Mirdispo works

Notes for anyone changing Mirdispo: how it is put together, and why the less
obvious decisions were made. What changed in each release is in the
`<releases>` section of `io.github.hencyber.Mirdispo.metainfo.xml`.

## Parts

- **The front end** (`src/mirdispo`, Python and QML) is the window, the tray
  icon and the diagnostics. `DisplayBackend` in `backend.py` is a small state
  machine exposed to QML: idle, connecting, streaming, error.
- **The engine** is GNOME Network Displays 0.99.0, built without its GTK
  interface and with the patches in `packaging/patches/`. Its daemon
  discovers receivers and starts streams. It is installed as
  `libexec/mirdispo-daemon` and owns `io.github.hencyber.Mirdispo.Manager` on
  the session bus. Each stream runs in its own helper process,
  `libexec/gnome-network-displays-stream`, which captures the screen through
  the ScreenCast portal and does the Wi-Fi Display or Chromecast session.
- `gnd.py` is the front end's only contact with the engine: the Manager's
  D-Bus interface, plus the state each stream helper publishes.

The engine is started by the front end when needed, in its own session, so a
cast keeps going when the window is closed. When the application quits with
nothing being cast, it stops the engine it started.

## Discovery

The daemon finds Miracast receivers over Wi-Fi Direct through NetworkManager,
and Miracast over Infrastructure and Chromecast receivers on the local network
through Avahi. A receiver that is reachable more than one way is listed once,
on the route that connects fastest (`gnd.PROTOCOL_PREFERENCE`): over the
network a session starts in about a second, while Wi-Fi Direct first has to
negotiate a group and a channel.

## A connection

1. `StartStream` returns a unit name. Outside a sandbox the helper runs as a
   transient systemd user unit of that name. Inside Flatpak the daemon runs it
   as a child process instead (patch 0009), because systemd would start it on
   the host, where it is not installed.
2. The helper takes a D-Bus name derived from the unit name and publishes its
   state there as a GAction (patch 0012). The front end reads it to know
   whether the helper is alive and when the receiver is getting a picture.
   Session names are visible across sandbox instances, which `/proc` is not.
3. For Wi-Fi Direct, NetworkManager's P2P device state is shown as progress.
4. The session counts as streaming when the helper reports `streaming`,
   whatever the route.

A helper whose state cannot be read is treated as unknown, never as dead:
reading unknown as dead once reported a working cast as failed, and starting
a second helper beside a running one makes the two collide at the receiver.

## Retries

Receivers often refuse the first Wi-Fi Direct handshake, especially just after
a previous session, so Mirdispo retries before telling the user anything.

- NetworkManager gives up on a handshake after 45 seconds, but wpa_supplicant
  knows much sooner when group formation has failed. It brings up a group
  interface (`p2p-<interface>-<n>`) once owner negotiation succeeds and
  removes it when formation fails. `p2p.GroupFormationProbe` watches for that
  in `/sys/class/net`, which any user and any sandbox can read, and retries
  about 16 seconds in instead of 45.
- Interfaces that are down are ignored. One is created down for every
  request and can outlive a request that was never answered.
- After a plain timeout the receiver tends to send its own negotiation request
  about two seconds later, and two peers negotiating at once fail, so that
  retry waits longer than one after a failed group formation.
- A cast the user stopped from the desktop, for instance with Plasma's screen
  sharing indicator, is not a dropped link. The helper reports `ended`
  (patch 0013) and the front end stops rather than reconnecting.

## Picture

- **Encoder.** The engine prefers software H.264 from x264 over VA-API
  (patch 0001). VA-API and then OpenH264 remain as fallbacks. VA-API encoders have been seen to abort inside the
  graphics driver when a stream is torn down. Software encoding costs more
  processor time, but it does not take the session down.
- **Mode.** The engine picks the streamed resolution from what the receiver
  advertises and what is being shared (patch 0007). Television timings (CEA)
  are preferred when a receiver lists them, because televisions have been
  seen to accept computer monitor timings (VESA) and then flicker. Among the
  remaining modes it takes the one that shows the shared screen largest,
  without preferring frame rate or sharpness on the viewer's behalf.

## Sound

The stream helper creates a virtual output named after the receiver and sends
what plays into it to the receiver as AAC. For the length of the cast that
output is made the default, so the desktop's sound goes to the receiver
without the user choosing a device, and the previous default is restored when
the cast ends (patch 0015). The sound is captured in 40 ms periods (patch
0016): with the default 10 ms the sound server ran the graph in periods too
short for the capture and the players to keep up with, and the receiver's
sound stuttered.

## Motion

A receiver's highest frame rate at a given resolution is a hard limit. Many
televisions take 1080p at 30 frames per second only, so motion there can never
be as smooth as on a 120 Hz laptop screen without a lower resolution, which
Mirdispo does not choose on the user's behalf. Within that limit:

- A receiver lists its modes per H.264 profile, and a television can offer
  1080p at 60 Hz in the constrained high profile while its constrained
  baseline entry stops at 30 Hz. Baseline is used unless another entry the
  encoder can produce shows the source better (patch 0024). With the high
  profile x264 uses CABAC and the 8x8 transform, which compress better at the
  same bitrate. Every entry a receiver offers is logged.
- Scaling, colour conversion and x264 run in parallel (patch 0018). x264
  encodes as many slices as the receiver takes, up to four, which adds no
  frame of delay; a receiver that takes one slice gets one (patch 0023).
- A frame that leaves the encoder too late makes the pipeline drop frames to
  catch up, which is seen as the picture jumping. With x264 that happens only
  from 100 ms after capture, since packets are sent 150 ms after capture
  anyway (patch 0019). Dropped frames are reported in the journal.
- x264 encodes at constant quality held under a bitrate limit (patch 0026).
  Upstream's setting was a constant quantizer that ignored the bitrate
  entirely, and a busy picture came out at hundreds of Mbit/s in bursts no
  Wi-Fi link carries; the backlog then reached the sound. The limit is
  10 Mbit/s (patch 0020) and grows with the refresh rate, so a 60 Hz frame
  gets as many bits as a 30 Hz one (patch 0024).
- While a picture is being sent the app pauses the search for receivers
  (patch 0029). A Wi-Fi Direct search scans other channels on the radio that
  carries the stream every 20 seconds. It resumes as soon as a link drops.

## Delay

Every packet leaves a fixed pipeline latency after it was captured, so that
latency is how far the receiver trails the desktop. It is 500 ms for OpenH264,
whose latency spikes after scene changes, and 120 ms for x264, which is
configured for zero latency (patches 0017 and 0027). Lower is worse, not
better: the muxer holds the last packets of each frame until its next input,
and below about 100 ms those tails leave whenever it lets them go, so frames
reach the receiver unevenly. `tests/video_pipeline.c` measures when each
frame's last packet leaves and fails if frames are not evenly spaced.

The PCR is carried by the video stream (patch 0028); left to the muxer it can
end up on the audio stream, whose packets come in bursts.

The receiver adds its own delay on top. GStreamer's MPEG-TS muxer stamps
every frame to be shown 125 ms after the clock reference it sends, a fixed
value in the muxer, and the television then spends its own time decoding and
processing the picture. The 125 ms is left alone: it is the receiver's margin
for a Wi-Fi link that delivers a packet late now and then, and taking it away
turns such a moment into a visible stutter.

## Screen sharing permission

Every cast is a new helper process, so without help the portal would ask which
screen to share on every attempt, including automatic retries. The helper asks
for a persistent session and keeps the portal's restore token for the login
session (patch 0006): in `$XDG_RUNTIME_DIR/mirdispo/`, or inside Flatpak in
`$XDG_RUNTIME_DIR/app/$FLATPAK_ID/` (patch 0011), since the sandbox's own
runtime directory does not outlive the application.

## Packaging and releases

- `packaging/build-deb.sh` builds the Debian package from `vendor/amd64/`,
  which `make backend` fills from the pristine upstream tarball and the
  patches. The package is reproducible and carries the engine's complete
  source.
- `flatpak/io.github.hencyber.Mirdispo.yml` builds everything from source on
  the KDE runtime.
- A GitHub release runs `.github/workflows/flatpak-repo.yml`, which publishes a
  signed Flatpak repository on GitHub Pages. Installed copies update from it.
- `make audit` reports anything in the tree that identifies the machine or
  account it was built on. Run it before publishing.

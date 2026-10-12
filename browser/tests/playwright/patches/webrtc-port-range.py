"""
Verify WebRTC's UDP sockets bind in the identity's OS ephemeral port range.

A UDP candidate's port is the ephemeral port the OS gave its socket: 32768-60999
on Linux (the kernel's ip_local_port_range), 49152-65535 on Windows and macOS.
The host kernel picked it, so a Windows or macOS identity on a Linux host bound
Linux ports, which reach the page in every candidate that carries them: ports
the claimed OS could not have used. NrSocketBase::CreateSocket now picks the
port from the spoofed OS's range.

The port is read at the STUN server, not from candidates. camoufox.cfg sets
media.peerconnection.ice.no_host, so host candidates never reach the page, and
the fork fabricates no srflx candidate; but nICEr still opens a UDP socket per
local address and sends a STUN Binding Request from it (no_host only hides the
host candidate). The probe owns that server: a socket that never answers, so
the run needs no network, and whose recvfrom source port is the bound port.
It listens on the host's default-route address, because nICEr skips a loopback
STUN server unless media.peerconnection.ice.loopback is set, and the browser is
measured with the prefs it ships.

Twelve connections per identity: 49152-65535 overlaps Linux's 32768-60999, so a
single Linux-range port can still land inside it, while twelve fall below 49152
almost every run.

What PASS means: for a Windows, a macOS and a Linux identity, the STUN server
received Binding Requests from at least one socket per connection, and every
source port is inside that OS's range. No arrivals at all is SETUP-INVALID, not
a pass: nothing was measured.

On a Linux host the Linux arm is not a control, since the host range is the
claimed range; the Windows and macOS arms are the test. The red proof is main's
browser, which lacks the CreateSocket hunk: its Windows arm reports ports below
49152.

    python browser/tests/playwright/patches/webrtc-port-range.py
"""

import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import launch_kwargs  # noqa: E402

RANGES = {"windows": (49152, 65535), "macos": (49152, 65535), "linux": (32768, 60999)}
CONNECTIONS = 12
STUN_COOKIE = b"\x21\x12\xa4\x42"

PROBE = """async ([stun, count]) => {
  const gather = async () => {
    const pc = new RTCPeerConnection({iceServers: [{urls: stun}]});
    const done = new Promise(resolve => {
      setTimeout(resolve, 30000);
      pc.onicecandidate = e => { if (!e.candidate) resolve(); };
    });
    pc.createDataChannel('probe');
    await pc.setLocalDescription(await pc.createOffer());
    await done;
    pc.close();
  };
  await Promise.all(Array.from({length: count}, gather));
}"""


def silent_stun_server() -> socket.socket:
    """A UDP socket on the default-route address that never answers. Connecting
    a throwaway socket to a routed address sends nothing; it only picks the
    source address, as nICEr's default-address lookup does."""
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.connect(("8.8.8.8", 53))
    addr = probe.getsockname()[0]
    probe.close()
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind((addr, 0))
    server.setblocking(False)
    return server


def drain_binding_requests(server: socket.socket) -> list:
    """Source ports of every STUN Binding Request queued at the server."""
    ports = []
    while True:
        try:
            data, (_, port) = server.recvfrom(2048)
        except BlockingIOError:
            return ports
        if data[:2] == b"\x00\x01" and data[4:8] == STUN_COOKIE:
            ports.append(port)


def judge(os_name: str, lo: int, hi: int, ports: list, failures: list) -> None:
    if not ports:
        failures.append(f"SETUP-INVALID {os_name}: no STUN Binding Request reached the server")
        return
    distinct = sorted(set(ports))
    outside = [p for p in distinct if not lo <= p <= hi]
    if len(distinct) < CONNECTIONS:
        failures.append(f"{os_name}: {len(distinct)} sockets from {CONNECTIONS} connections")
    if outside:
        failures.append(f"{os_name}: ports outside {lo}-{hi}: {outside}")
    print(f"  {os_name}: {len(ports)} requests from {len(distinct)} ports, "
          f"min {distinct[0]} max {distinct[-1]}, outside {lo}-{hi}: {len(outside)}")


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox

    failures = []
    try:
        server = silent_stun_server()
    except OSError as e:
        print(f"  FAIL SETUP-INVALID: no default-route address for the STUN server ({e})")
        return 1
    host, port = server.getsockname()
    stun = f"stun:{host}:{port}"

    for os_name, (lo, hi) in RANGES.items():
        async with AsyncCamoufox(**launch_kwargs(os=os_name, i_know_what_im_doing=True)) as browser:
            page = await browser.new_page()
            await page.goto("about:blank")
            await page.evaluate(PROBE, [stun, CONNECTIONS])
        # The browser is closed, so every request it sent is already queued.
        judge(os_name, lo, hi, drain_binding_requests(server), failures)
    server.close()

    if failures:
        for f in failures:
            print(f"  FAIL {f}")
        return 1
    print("  PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

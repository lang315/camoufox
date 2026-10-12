"""
Verify each context's WebRTC IP replaces the real address in its srflx candidate.

This guards the fork's WebRTC model (#178, D1): NewContext(webrtc_ip=...) hands
the IP to setWebRTCIPv4, WebRTCIPManager stores it for that context, and
PeerConnectionImpl::SpoofCandidateIP masks every address in that context's
candidates and SDP with it. The fork fabricates no srflx candidate, and
camoufox.cfg sets media.peerconnection.ice.no_host, so the page sees only the
srflx candidate a real STUN answer produces. Upstream's version of this guard
read a srflx candidate its patch fabricated against a silent STUN server; that
candidate does not exist here.

The probe runs a minimal STUN server that answers each Binding Request with the
request's own source address. With no NAT, that is the host's default-route
address, so an unmasked srflx carries the host's real IP and the run needs no
network. The server listens on that address because nICEr skips a loopback
STUN server under the shipped prefs.

What PASS means, in one browser:
    * control: a page in a context with no WebRTC IP gets a srflx candidate
      carrying the host's real address. Without it the leak check below could
      not go red, so a miss is SETUP-INVALID;
    * two contexts, both open, each see exactly their own IP in every srflx
      candidate. A context reading the other's IP, or the real one, is red;
    * the host's real address appears in no candidate and no SDP of either
      context. An unmasked candidate, raddr or SDP line is red;
    * every candidate arrives before end-of-candidates;
    * each context gets at least one srflx candidate. None is SETUP-INVALID: the
      responder was not reached and nothing was measured.

The launch-level `webrtc:ipv4` key is not asserted: no browser code reads it, so
a plain page with only that key still shows the real address (#163, open).

    python browser/tests/playwright/patches/webrtc-context-ip.py
"""

import asyncio
import socket
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from helpers import binding_success, default_route_ipv4, is_binding_request, launch_kwargs  # noqa: E402

CONTEXT_IPS = ("203.0.113.7", "203.0.113.8")

PROBE = """async (stun) => {
  const pc = new RTCPeerConnection({iceServers: [{urls: stun}]});
  const out = {srflx: [], candidates: [], late: [], sdp: ''};
  let ended = false;
  const done = new Promise(resolve => {
    setTimeout(resolve, 30000);
    pc.onicecandidate = e => {
      if (!e.candidate) {
        ended = true;
        // Long past any STUN round trip, so a straggler would show up here.
        return setTimeout(resolve, 1000);
      }
      const c = e.candidate.candidate;
      if (ended) return out.late.push(c);
      out.candidates.push(c);
      const m = c.match(/ (\\S+) \\d+ typ srflx/);
      if (m) out.srflx.push(m[1]);
    };
  });
  pc.createDataChannel('probe');
  await pc.setLocalDescription(await pc.createOffer());
  await done;
  out.sdp = pc.localDescription.sdp;
  pc.close();
  return out;
}"""


def answer_binding_requests(server: socket.socket, stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            data, source = server.recvfrom(2048)
        except socket.timeout:
            continue
        if is_binding_request(data):
            server.sendto(binding_success(data, source), source)


async def gather(context, stun: str) -> dict:
    page = await context.new_page()
    await page.goto("about:blank")
    return await page.evaluate(PROBE, stun)


async def main() -> int:
    from camoufox.async_api import AsyncCamoufox, AsyncNewContext

    failures = []
    try:
        host_ip = default_route_ipv4()
    except OSError as e:
        print(f"  FAIL SETUP-INVALID: no default-route address for the STUN server ({e})")
        return 1
    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind((host_ip, 0))
    server.settimeout(0.2)
    stop = threading.Event()
    responder = threading.Thread(target=answer_binding_requests, args=(server, stop), daemon=True)
    responder.start()
    stun = f"stun:{host_ip}:{server.getsockname()[1]}"

    try:
        async with AsyncCamoufox(**launch_kwargs(os="linux", i_know_what_im_doing=True)) as browser:
            control = await gather(await browser.new_context(), stun)
            contexts = [await AsyncNewContext(browser, os="linux", webrtc_ip=ip) for ip in CONTEXT_IPS]
            results = [await gather(context, stun) for context in contexts]
    finally:
        stop.set()
        responder.join()
        server.close()

    print(f"  control (no WebRTC IP): srflx {control['srflx']}")
    if host_ip not in control["srflx"]:
        failures.append(f"SETUP-INVALID control: srflx {control['srflx']} does not carry the host "
                        f"address {host_ip}, so the leak check below cannot fail")

    for ip, got in zip(CONTEXT_IPS, results):
        print(f"  context {ip}: srflx {got['srflx']}")
        if not got["srflx"]:
            failures.append(f"SETUP-INVALID context {ip}: no srflx candidate, the STUN responder was not reached")
        elif set(got["srflx"]) != {ip}:
            failures.append(f"context {ip}: srflx {got['srflx']}, expected only {ip}")
        leaked = [c for c in got["candidates"] + got["late"] if host_ip in c.split()]
        if leaked:
            failures.append(f"context {ip}: host address {host_ip} in candidates {leaked}")
        if host_ip in got["sdp"].replace("\r\n", " ").split():
            failures.append(f"context {ip}: host address {host_ip} in the SDP")
        if got["late"]:
            failures.append(f"context {ip}: candidates after end-of-candidates: {got['late']}")

    if failures:
        for f in failures:
            print(f"  FAIL {f}")
        return 1
    print("  PASS")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

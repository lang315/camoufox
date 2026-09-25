"""A minimal RFC 6455 echo endpoint, enough for a page to open, send and receive."""

import base64
import hashlib
import struct

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def is_upgrade(headers) -> bool:
    return (headers.get("Upgrade") or "").lower() == "websocket"


def serve_echo(handler) -> None:
    accept = base64.b64encode(hashlib.sha1((handler.headers["Sec-WebSocket-Key"] + GUID).encode()).digest()).decode()
    handler.send_response(101)
    handler.send_header("Upgrade", "websocket")
    handler.send_header("Connection", "Upgrade")
    handler.send_header("Sec-WebSocket-Accept", accept)
    handler.end_headers()
    handler.wfile.flush()
    r, w = handler.rfile, handler.wfile
    while True:
        head = r.read(2)
        if len(head) < 2:
            break
        op, n = head[0] & 0x0F, head[1] & 0x7F
        if n == 126:
            n = struct.unpack(">H", r.read(2))[0]
        elif n == 127:
            n = struct.unpack(">Q", r.read(8))[0]
        mask = r.read(4)  # client frames are always masked
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(r.read(n)))
        if op == 8:
            w.write(b"\x88\x00")
            break
        if op in (1, 2):
            # ponytail: echo frames are short; add the 64-bit length form if a page ever sends >64 KiB
            size = bytes([n]) if n < 126 else b"\x7e" + struct.pack(">H", n)
            w.write(bytes([0x80 | op]) + size + data)
            w.flush()
    handler.close_connection = True

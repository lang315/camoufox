"""A STUN binding responder (RFC 5389): enough for a browser to gather a
server-reflexive candidate, and a record that it asked."""

import socket
import struct
import threading

MAGIC = 0x2112A442


class Stun:
    def __init__(self, host: str = "0.0.0.0") -> None:
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, 0))
        self.port = self.sock.getsockname()[1]
        self.seen: list = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                data, (ip, port) = self.sock.recvfrom(2048)
            except OSError:
                return
            if len(data) < 20 or struct.unpack(">H", data[:2])[0] != 0x0001:
                continue
            self.seen.append(ip)
            xip = struct.unpack(">I", socket.inet_aton(ip))[0] ^ MAGIC
            attr = struct.pack(">HHBBHI", 0x0020, 8, 0, 1, port ^ (MAGIC >> 16), xip)
            self.sock.sendto(struct.pack(">HHI", 0x0101, len(attr), MAGIC) + data[8:20] + attr, (ip, port))

    def stop(self) -> None:
        self.sock.close()

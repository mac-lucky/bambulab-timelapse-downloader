"""Printer certificate pinning (FTP_CERT_SHA256).

The TLS tests run real handshakes against a local listener with a throwaway
self-signed certificate made by the openssl CLI, and are skipped without it.
"""

import contextlib
import ftplib
import hashlib
import shutil
import socket
import ssl
import subprocess
import threading

import pytest

import timelapse_downloader as tld

FINGERPRINT = (
    "08:2E:7D:44:3E:BD:90:34:DA:3A:14:70:86:AD:F6:90:"
    "C0:D6:93:F7:32:08:B7:3E:96:4E:9C:73:1F:7A:8B:76"
)
DIGEST = FINGERPRINT.replace(":", "").lower()
OTHER = "11" * 32


def test_parse_cert_pins_accepts_openssl_and_bare_hex():
    pins = tld.parse_cert_pins(f" {FINGERPRINT} , {OTHER.upper()},")
    assert pins == {DIGEST, OTHER}


def test_parse_cert_pins_empty_means_unpinned():
    assert tld.parse_cert_pins("") == frozenset()
    assert tld.parse_cert_pins(" , ") == frozenset()


@pytest.mark.parametrize(
    "bad", ["abc", "zz" * 32, DIGEST + "00", "sha256 Fingerprint=AB"]
)
def test_parse_cert_pins_rejects_a_malformed_entry(bad):
    # A typo must fail loudly, not leave the connection unpinned.
    with pytest.raises(ValueError):
        tld.parse_cert_pins(f"{DIGEST},{bad}")


def test_format_fingerprint_matches_openssl():
    assert tld.format_fingerprint(DIGEST) == FINGERPRINT


class FakeTLSConn:
    def __init__(self, der):
        self.der = der
        self.closed = False

    def getpeercert(self, binary_form=False):
        assert binary_form
        return self.der

    def close(self):
        self.closed = True


def test_check_pin_records_the_fingerprint_when_unpinned():
    client = tld.ImplicitFTP_TLS(cert_pins=frozenset())
    conn = FakeTLSConn(b"cert")
    assert client.check_pin(conn) is conn
    assert client.peer_fingerprint == hashlib.sha256(b"cert").hexdigest()
    assert not conn.closed


def test_check_pin_closes_and_raises_on_a_mismatch():
    client = tld.ImplicitFTP_TLS(cert_pins=frozenset({OTHER}))
    conn = FakeTLSConn(b"cert")
    with pytest.raises(tld.CertificatePinError):
        client.check_pin(conn)
    assert conn.closed


def test_check_pin_refuses_a_peer_without_a_certificate():
    client = tld.ImplicitFTP_TLS(cert_pins=frozenset({OTHER}))
    conn = FakeTLSConn(None)
    with pytest.raises(tld.CertificatePinError, match="no certificate"):
        client.check_pin(conn)
    assert conn.closed


class TLSListener:
    """Implicit-TLS listener on localhost: greets with 220, records what each client sent."""

    def __init__(self, cert, key):
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(cert, key)
        self.sock = socket.create_server(("127.0.0.1", 0))
        self.port = self.sock.getsockname()[1]
        self.received = []
        self.handlers = []
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                raw, _ = self.sock.accept()
            except OSError:
                return
            handler = threading.Thread(target=self._handle, args=(raw,), daemon=True)
            self.handlers.append(handler)
            handler.start()

    def _handle(self, raw):
        data = b""
        # A client that refuses the certificate drops the connection mid-session.
        with contextlib.suppress(OSError):
            conn = self.ctx.wrap_socket(raw, server_side=True)
            conn.sendall(b"220 ready\r\n")
            while chunk := conn.recv(1024):
                data += chunk
            conn.close()
        raw.close()
        self.received.append(data)

    def raw_connection(self):
        return socket.create_connection(("127.0.0.1", self.port), timeout=5)

    def wait(self):
        for handler in self.handlers:
            handler.join(timeout=5)
        return self.received


@pytest.fixture
def listener(tmp_path):
    if shutil.which("openssl") is None:
        pytest.skip("openssl CLI not available")
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "ec",
            "-pkeyopt",
            "ec_paramgen_curve:prime256v1",
            "-nodes",
            "-keyout",
            str(key),
            "-out",
            str(cert),
            "-days",
            "1",
            "-subj",
            "/CN=printer",
        ],
        check=True,
        capture_output=True,
    )
    server = TLSListener(cert, key)
    server.digest = hashlib.sha256(
        ssl.PEM_cert_to_DER_cert(cert.read_text())
    ).hexdigest()
    yield server
    server.sock.close()


def test_pinned_certificate_connects(listener):
    client = tld.ImplicitFTP_TLS(cert_pins=frozenset({listener.digest}))
    assert client.connect("127.0.0.1", listener.port, timeout=5).startswith("220")
    assert client.peer_fingerprint == listener.digest
    client.close()


def test_wrong_certificate_is_refused_before_anything_is_sent(listener):
    client = tld.ImplicitFTP_TLS(cert_pins=frozenset({OTHER}))
    with pytest.raises(tld.CertificatePinError):
        client.connect("127.0.0.1", listener.port, timeout=5)
    # Nothing, the USER and PASS commands included, reached the server.
    assert listener.wait() == [b""]


def test_data_connections_are_pinned_too(listener, monkeypatch):
    client = tld.ImplicitFTP_TLS(cert_pins=frozenset({listener.digest}))
    client.connect("127.0.0.1", listener.port, timeout=5)
    client._prot_p = True
    # Stand in for PASV + RETR: hand back a fresh TCP connection to the listener.
    monkeypatch.setattr(
        ftplib.FTP,
        "ntransfercmd",
        lambda self, cmd, rest=None: (listener.raw_connection(), None),
    )

    # Reuses the control session (as P2S printers require) and still checks the
    # certificate the resumed session carries.
    conn, _ = client.ntransfercmd("RETR a.mp4")
    conn.close()

    client.cert_pins = frozenset({OTHER})
    with pytest.raises(tld.CertificatePinError):
        client.ntransfercmd("RETR a.mp4")
    client.close()


def test_ftp_download_stops_on_a_pin_mismatch(listener, monkeypatch, tmp_path):
    monkeypatch.setattr(tld, "FTP_HOST", "127.0.0.1")
    monkeypatch.setattr(tld, "FTP_PORT", listener.port)
    monkeypatch.setattr(tld, "FTP_CERT_PINS", frozenset({OTHER}))
    monkeypatch.setattr(tld, "DOWNLOAD_FOLDER", str(tmp_path))
    tld.ftp_download()
    assert listener.wait() == [b""]

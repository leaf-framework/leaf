"""End-to-end check of OPCWatcher against a local OPC UA server that only allows encrypted connections."""

import datetime
import socket
import tempfile
import unittest
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from opcua import Client, Server, ua  # pyright: ignore[reportMissingTypeStubs]

from leaf.modules.input_modules.opc_watcher import OPCWatcher
from leaf.register.metadata import MetadataManager

# opcua's Server() builds a ~37k-line standard address space, which can pass the 30s default on a busy CI runner.
pytestmark = pytest.mark.timeout(120)


def _write_cert(folder: Path, name: str) -> tuple[str, str]:
    """Write a self-signed certificate and key, returning their paths."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"leaf-{name}")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.UniformResourceIdentifier(f"urn:leaf:{name}")]), False)
        .sign(key, hashes.SHA256())
    )
    cert_path = folder / f"{name}.pem"
    key_path = folder / f"{name}_key.pem"
    _ = cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    _ = key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
        )
    )
    return str(cert_path), str(key_path)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port: int = s.getsockname()[1]
        return port


class TestOPCSecurity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp = tempfile.TemporaryDirectory()
        folder = Path(cls.tmp.name)
        server_cert, server_key = _write_cert(folder, "server")
        cls.client_cert, cls.client_key = _write_cert(folder, "client")
        cls.user_cert, cls.user_key = _write_cert(folder, "user")
        cls.port = _free_port()

        cls.server = Server()
        cls.server.set_endpoint(f"opc.tcp://127.0.0.1:{cls.port}/")
        cls.server.load_certificate(server_cert)
        cls.server.load_private_key(server_key)
        # Only an encrypted endpoint, so a plain client must be refused.
        cls.server.set_security_policy([ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt])
        cls.server.set_security_IDs(["Username", "Basic256Sha256"])
        ns = cls.server.register_namespace("leaf")
        cls.server.get_objects_node().add_object(ns, "Reactor").add_variable("ns=2;s=temperature", "temperature", 21.5)
        cls.server.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        cls.tmp.cleanup()

    def _watcher(
        self,
        username: str | None = None,
        password: str | None = None,
        certificate: str | None = None,
        private_key: str | None = None,
    ) -> OPCWatcher:
        return OPCWatcher(
            metadata_manager=MetadataManager(),
            host="127.0.0.1",
            port=self.port,
            topics={"temperature"},
            exclude_topics=[],
            security=f"Basic256Sha256,SignAndEncrypt,{self.client_cert},{self.client_key}",
            username=username,
            password=password,
            certificate=certificate,
            private_key=private_key,
        )

    def _read_temperature(self, watcher: OPCWatcher) -> float:
        client = watcher._new_client()
        client.connect()
        try:
            value: float = client.get_node("ns=2;s=temperature").get_value()
            return value
        finally:
            client.disconnect()

    def test_plain_connection_refused(self) -> None:
        """Without a secure channel the server does not let the client in."""
        client = Client(f"opc.tcp://127.0.0.1:{self.port}/")
        with self.assertRaises(Exception):
            client.connect()
            client.disconnect()

    def test_encrypted_with_password(self) -> None:
        self.assertEqual(self._read_temperature(self._watcher(username="leaf", password="secret")), 21.5)

    def test_encrypted_with_certificate_login(self) -> None:
        watcher = self._watcher(certificate=self.user_cert, private_key=self.user_key)
        self.assertEqual(self._read_temperature(watcher), 21.5)


if __name__ == "__main__":
    unittest.main()

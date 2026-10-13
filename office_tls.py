"""2.9.94: an office certificate for the shared server (several PCs on the office network).

The server computer makes it once:  python run_server.py --make-certificate SERVER-NAME,192.168.1.10
That writes server-cert.pem and server-key.pem in the Saber data folder. Copy server-cert.pem (never the key)
to each office PC as  <data folder>/office-server-cert.pem  - the program then trusts that server over HTTPS
(passwords and data are encrypted on the network). Everything stays inside the office."""
from __future__ import annotations

import datetime
import ipaddress
import os
from pathlib import Path

TRUSTED_CERT_NAME = "office-server-cert.pem"


def trusted_certificate(folder: Path | None = None) -> Path | None:
    """The office server certificate this PC trusts (SABER_SERVER_CERT, or office-server-cert.pem in the data folder)."""
    override = os.environ.get("SABER_SERVER_CERT")
    if override:
        return Path(override) if Path(override).is_file() else None
    if folder is None:
        import app_runtime
        folder = app_runtime.data_dir()
    path = Path(folder) / TRUSTED_CERT_NAME
    return path if path.is_file() else None


def make_certificate(folder, names, days=3650):
    """Self-signed certificate for the server's names / IP addresses. Returns (cert_path, key_path)."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
    names = [n.strip() for n in (names.split(",") if isinstance(names, str) else names) if n and n.strip()]
    if not names:
        raise ValueError("Give the server computer name and/or its IP address, e.g. OFFICE-PC,192.168.1.10")
    alt = []
    for name in names:
        try: alt.append(x509.IPAddress(ipaddress.ip_address(name)))
        except ValueError: alt.append(x509.DNSName(name))
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, names[0]), x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Saber Accounting office server")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=days))
            .add_extension(x509.SubjectAlternativeName(alt), critical=False)
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .sign(key, hashes.SHA256()))
    folder = Path(folder); folder.mkdir(parents=True, exist_ok=True)
    cert_path, key_path = folder / "server-cert.pem", folder / "server-key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    try: os.chmod(key_path, 0o600)
    except OSError: pass
    return cert_path, key_path

"""2.9.103: the licence of an installation - a code signed by the seller (Saber for Audit), instead of a hidden account.

How it works
- Every installation has an Installation ID (Settings > Users > Licence, and the sign-in screen when the licence ends).
- The client sends that ID to the seller. The seller makes a licence code on his own computer with the seller key file
  (Licence > Make a licence...): company name, Installation ID, valid until. The code is signed with the seller's private key.
- The client's administrator pastes the code. The program checks the signature with the public key below: a code cannot be
  made or changed without the seller key file, and a code works only on the installation it was made for.
- A new installation works 30 days without a code (trial). When the licence (or the trial) has ended nobody can sign in;
  the sign-in screen offers to enter a new code.
- The seller key file is protected by a password the seller chooses and can change; it never leaves his computer.
- There is no hidden account and no shared password: the seller has no access to a client's books unless the client's
  administrator gives him a user (which the audit trail records)."""
from __future__ import annotations
import logging

import base64
import json
import uuid
from datetime import date, timedelta

from database_common import display_date, iso_date, utcnow

PUBLIC_KEY = "imEz4ijtJxbTF6SnrGWoMPNOfAttnOrfUJPyIgS8m5A"  # the seller's public key (Ed25519, raw, base64)
SELLER = "Saber for Audit"
TRIAL_DAYS = 30
PREFIX = "SABER1"
ID_KEY, CODE_KEY, TRIAL_KEY, SEEN_KEY = "installation_id", "licence_code", "trial_started", "licence_last_seen"
CLOCK_TOLERANCE_DAYS = 2  # 2.9.104: a computer date more than 2 days before the latest date already seen is refused


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _get(connection, key):
    row = connection.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return row[0] if row else None


def _put(connection, key, value):
    connection.execute("INSERT INTO app_settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))


def installation_id(connection):
    value = _get(connection, ID_KEY)
    if not value:
        raw = uuid.uuid4().hex.upper()[:16]
        value = "-".join(raw[i:i + 4] for i in range(0, 16, 4))
        _put(connection, ID_KEY, value)
    return value


def read_code(code, public_key=None):
    """The licence in a code, after checking the seller's signature. ValueError when the code is not genuine."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    text = "".join(str(code or "").split())
    try:
        prefix, payload, signature = text.split(".")
        if prefix != PREFIX: raise ValueError
        key = Ed25519PublicKey.from_public_bytes(_unb64(public_key or PUBLIC_KEY))
        key.verify(_unb64(signature), (prefix + "." + payload).encode())
        licence = json.loads(_unb64(payload))
        iso_date(licence["valid_until"])
        return licence
    except (ValueError, KeyError, TypeError, InvalidSignature):
        raise ValueError("This licence code is not valid - copy the whole code exactly as received from " + SELLER)


def latest_seen(connection, licence=None):
    """2.9.104: the latest date this installation has already seen - the date saved at each use, the day the licence code was
    made, and the latest line of the audit trail (which cannot be changed or deleted). Turning the computer's date back
    cannot go before it."""
    seen = []
    for value in (_get(connection, SEEN_KEY), (licence or {}).get("issued")):
        try: seen.append(date.fromisoformat(str(value)[:10]))
        except (TypeError, ValueError): pass
    if not _get(connection, SEEN_KEY):  # only when the saved date is missing (deleted): the audit trail is read once
        try:
            row = connection.execute("SELECT created_at FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
            if row and row[0]: seen.append(date.fromisoformat(str(row[0])[:10]))
        except Exception: logging.getLogger("saber").debug("ignored error", exc_info=True)  # 2.9.105
    return max(seen) if seen else None


def status(connection, today=None):
    """{installation_id, licensed, company, valid_until, trial, expired, days, message, clock_back}."""
    today = today or date.today()
    ident = installation_id(connection)
    result = {"installation_id": ident, "licensed": False, "company": None, "valid_until": None, "trial": False, "expired": False, "days": None, "message": None}
    code = _get(connection, CODE_KEY)
    licence = None
    if code:
        try:
            licence = read_code(code)
            if licence.get("installation") != ident: licence = None
        except ValueError:
            licence = None
    if licence:
        until = iso_date(licence["valid_until"])
        result.update(licensed=True, company=licence.get("company"), valid_until=until)
    else:
        started = _get(connection, TRIAL_KEY)
        if not started:
            started = today.isoformat(); _put(connection, TRIAL_KEY, started)
        until = (date.fromisoformat(started) + timedelta(days=TRIAL_DAYS)).isoformat()
        result.update(trial=True, valid_until=until)
    days = (date.fromisoformat(until) - today).days
    result.update(days=days, expired=days < 0, clock_back=False)
    latest = latest_seen(connection, licence)
    if latest and today < latest - timedelta(days=CLOCK_TOLERANCE_DAYS):  # 2.9.104: the computer's date was turned back
        result.update(expired=True, clock_back=True,
                      message=f"The date of this computer ({display_date(today.isoformat())}) is earlier than a date Nanza Accounting has already used "
                              f"({display_date(latest.isoformat())}). Correct the date and time of the computer (Windows Settings > Time & language), "
                              "then sign in again.")
        return result
    if not latest or today > latest: _put(connection, SEEN_KEY, today.isoformat())
    if result["expired"]:
        what = "trial period" if result["trial"] else "licence"
        result["message"] = (f"The {what} of Nanza Accounting ended on {display_date(until)}. Send the Installation ID {ident} "
                             f"to {SELLER} and enter the new licence code.")
    return result


def install(connection, code, user_id=None):
    licence = read_code(code)
    ident = installation_id(connection)
    if licence.get("installation") != ident:
        raise ValueError(f"This code was made for another installation ({licence.get('installation')}); this one is {ident}")
    _put(connection, CODE_KEY, "".join(str(code).split()))
    connection.execute("INSERT INTO audit_log(user_id,action,entity,details,created_at) VALUES(?,?,?,?,?)",
                       (user_id, "licence", "installation", json.dumps({"company": licence.get("company"), "valid_until": licence["valid_until"]}), utcnow()))
    return status(connection)


# ---------------------------------------------------------------- the seller's side (runs only on the seller's computer)
def _private_key(key_file_bytes, password):
    from cryptography.hazmat.primitives import serialization
    try: return serialization.load_pem_private_key(key_file_bytes, password=str(password or "").encode() or None)
    except (ValueError, TypeError): raise ValueError("Wrong password for the seller key file (or not a seller key file)")


def make_code(key_file_bytes, password, installation, company, valid_until):
    """A licence code for one installation, signed with the seller key file."""
    key = _private_key(key_file_bytes, password)
    installation = str(installation or "").strip().upper()
    if len(installation.replace("-", "")) != 16: raise ValueError("Enter the Installation ID shown on the client's screen (16 letters / digits)")
    if not str(company or "").strip(): raise ValueError("Enter the company name")
    payload = {"installation": installation, "company": str(company).strip(), "valid_until": iso_date(valid_until, "Valid until"), "issued": date.today().isoformat()}
    body = PREFIX + "." + _b64(json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode())
    return body + "." + _b64(key.sign(body.encode()))


def change_key_password(key_file_bytes, old_password, new_password):
    from cryptography.hazmat.primitives import serialization
    if len(str(new_password or "")) < 10: raise ValueError("The new password must have at least 10 characters")
    key = _private_key(key_file_bytes, old_password)
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.BestAvailableEncryption(str(new_password).encode()))


def new_key_pair(password):
    """(seller key file bytes, public key text) - made once; the public key goes into PUBLIC_KEY above."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.BestAvailableEncryption(str(password).encode()))
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, _b64(public)

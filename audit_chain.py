"""2.9.97: a tamper-evident audit trail.

Every line of the audit trail carries a fingerprint (HMAC-SHA256) of its own content and of the line before it, made with a
key kept OUTSIDE the company file (audit.key in the Saber data folder, on the computer that runs the data service). Changing,
removing or inserting a line in the company file breaks the chain, and "Verify Audit Trail" shows where. The program itself
can no longer change or delete audit lines (database triggers refuse it).

Limits, said plainly: someone who has BOTH the company file and the key and removes the triggers could rebuild the chain; and
removing the very latest lines is only seen by comparing with an earlier verification or a backup."""
from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from pathlib import Path

log = logging.getLogger("saber.audit")
KEY_FILE = "audit.key"
_key_cache = {}


def _key_path() -> Path:
    override = os.environ.get("SABER_AUDIT_KEY")
    if override: return Path(override)
    import app_runtime
    return app_runtime.data_dir() / KEY_FILE


def key() -> bytes:
    path = _key_path()
    cached = _key_cache.get(str(path))
    if cached: return cached
    try:
        if path.is_file():
            value = bytes.fromhex(path.read_text(encoding="ascii").strip())
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            value = secrets.token_bytes(32)
            temporary = path.with_suffix(".tmp"); temporary.write_text(value.hex(), encoding="ascii"); os.replace(temporary, path)
            try: os.chmod(path, 0o600)
            except OSError: pass
    except (OSError, ValueError) as exc:  # no writable data folder: an unkeyed chain still shows careless edits
        log.warning("Audit key not available (%s): the audit chain is not keyed on this computer", exc)
        value = b""
    _key_cache[str(path)] = value
    return value


def key_id() -> str:
    return hashlib.sha256(b"saber-audit-key|" + key()).hexdigest()[:16]


def fingerprint(previous, row_id, user_id, action, entity, entity_id, details, created_at):
    text = "|".join("" if v is None else str(v) for v in (previous, row_id, user_id, action, entity, entity_id, details, created_at))
    return hmac.new(key(), text.encode("utf-8"), hashlib.sha256).hexdigest()


def register(connection):
    connection.create_function("SABER_AUDIT_HASH", 8, fingerprint, deterministic=True)


_PREVIOUS = "(SELECT row_hash FROM audit_log WHERE id<NEW.id AND row_hash IS NOT NULL ORDER BY id DESC LIMIT 1)"
TRIGGERS = (
    f"""CREATE TRIGGER IF NOT EXISTS audit_log_chain AFTER INSERT ON audit_log BEGIN
        UPDATE audit_log SET prev_hash={_PREVIOUS},
            row_hash=SABER_AUDIT_HASH({_PREVIOUS},NEW.id,NEW.user_id,NEW.action,NEW.entity,NEW.entity_id,NEW.details,NEW.created_at)
        WHERE id=NEW.id; END""",
    """CREATE TRIGGER IF NOT EXISTS audit_log_no_edit BEFORE UPDATE OF user_id,action,entity,entity_id,details,created_at ON audit_log
        BEGIN SELECT RAISE(ABORT,'The audit trail cannot be changed'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_log_no_reseal BEFORE UPDATE OF row_hash,prev_hash ON audit_log WHEN OLD.row_hash IS NOT NULL
        BEGIN SELECT RAISE(ABORT,'The audit trail cannot be changed'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT,'The audit trail cannot be deleted'); END""",
)


def migrate(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(audit_log)")}
    for column in ("prev_hash", "row_hash"):
        if column not in columns: connection.execute(f"ALTER TABLE audit_log ADD COLUMN {column} TEXT")
    for statement in TRIGGERS: connection.execute(statement)
    connection.execute("INSERT OR IGNORE INTO app_settings(key,value) VALUES('audit_key_id',?)", (key_id(),))
    seal_existing(connection)


def seal_existing(connection):
    """Lines written before 2.9.97 (or by a program without the chain) are sealed in order, from the last sealed line."""
    rows = connection.execute("SELECT id,user_id,action,entity,entity_id,details,created_at FROM audit_log WHERE row_hash IS NULL ORDER BY id").fetchall()
    if not rows: return 0
    for row in rows:
        previous = connection.execute("SELECT row_hash FROM audit_log WHERE id<? AND row_hash IS NOT NULL ORDER BY id DESC LIMIT 1", (row[0],)).fetchone()
        previous = previous[0] if previous else None
        connection.execute("UPDATE audit_log SET prev_hash=?,row_hash=? WHERE id=?", (previous, fingerprint(previous, *row), row[0]))
    connection.execute("INSERT INTO app_settings(key,value) VALUES('audit_sealed_from',?) ON CONFLICT(key) DO NOTHING", (str(rows[0][0]),))
    return len(rows)


def verify(db):
    """Recompute the whole chain. Returns {"ok", "checked", "broken": [first problems], "sealed_by_this_computer", "message"}."""
    with db.connect() as connection:
        stored_key = connection.execute("SELECT value FROM app_settings WHERE key='audit_key_id'").fetchone()
        rows = connection.execute("SELECT id,user_id,action,entity,entity_id,details,created_at,prev_hash,row_hash FROM audit_log ORDER BY id").fetchall()
    same_key = stored_key is None or stored_key[0] == key_id()
    broken, previous = [], None
    for row in rows:
        expected = fingerprint(previous, *row[:7])
        if row["row_hash"] is None: broken.append({"id": row["id"], "problem": "line without fingerprint (added outside the program)"})
        elif row["prev_hash"] != previous: broken.append({"id": row["id"], "problem": "a line before it was removed or inserted"})
        elif row["row_hash"] != expected: broken.append({"id": row["id"], "problem": "the line was changed after it was written"})
        previous = row["row_hash"]
        if len(broken) >= 50: break
    if not same_key:
        message = ("This audit trail was sealed on another computer: copy audit.key from the Saber data folder of the computer that runs "
                   "the data service to check it here.")
    elif broken: message = f"{len(broken)} problem(s): the audit trail was changed outside the program (first at line {broken[0]['id']})."
    else: message = f"Audit trail intact: {len(rows)} line(s) checked, none changed, removed or inserted."
    return {"ok": same_key and not broken, "checked": len(rows), "broken": broken, "sealed_by_this_computer": same_key, "message": message}

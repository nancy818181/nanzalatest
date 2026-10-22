"""2.9.101 - 2.9.103: the hidden owner account of 2.9.101 is removed (see licence.py: a signed licence code instead).

On upgrade the old hidden account is switched off and its sessions are ended, so it can no longer sign in anywhere.
The 'hidden' column is kept so that the switched-off row stays out of the client's list of users."""
from __future__ import annotations

OWNER_USERNAME = "saber-owner"


def migrate(connection):
    columns = {row[1] for row in connection.execute("PRAGMA table_info(users)")}
    if not columns: return
    if "hidden" not in columns: connection.execute("ALTER TABLE users ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0")
    for row in connection.execute("SELECT id FROM users WHERE hidden=1 AND active=1").fetchall():  # 2.9.103: switched off
        # Disable the obsolete account without changing its stored credential. Password
        # preservation applies to every user row, including accounts disabled by migration.
        connection.execute("UPDATE users SET active=0 WHERE id=?", (row[0],))
        connection.execute("DELETE FROM sessions WHERE user_id=?", (row[0],))

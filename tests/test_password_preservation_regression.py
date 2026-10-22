"""Password hashes must remain byte-for-byte stable across Nanza upgrades/startup."""
import io
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest import mock

from database import Database
from database_common import hash_password, utcnow, verify_password
import owner_access
import server


class PasswordPreservationRegressionTests(unittest.TestCase):
    def test_existing_admin_hash_survives_schema_upgrade_and_login(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "company.db"
            database = Database(path)
            database.initialize("ChangeMe123!")
            with database.connect() as connection:
                before = connection.execute(
                    "SELECT password_hash FROM users WHERE username='admin'"
                ).fetchone()[0]
                connection.execute(
                    "UPDATE app_settings SET value='old' WHERE key='startup_schema_version'"
                )

            upgraded = Database(path)
            upgraded.initialize_if_needed("Different-Seed-Value")
            with upgraded.connect() as connection:
                after = connection.execute(
                    "SELECT password_hash FROM users WHERE username='admin'"
                ).fetchone()[0]

            self.assertEqual(after, before)
            self.assertTrue(verify_password("ChangeMe123!", after))
            self.assertIsNotNone(upgraded.login("admin", "ChangeMe123!"))

    def test_disabling_legacy_hidden_user_does_not_change_hash(self):
        with TemporaryDirectory() as folder:
            database = Database(Path(folder) / "company.db")
            database.initialize("ChangeMe123!")
            password_hash = hash_password("Legacy-Owner-Password")
            with database.connect() as connection:
                connection.execute(
                    "INSERT INTO users(username,password_hash,role,language,active,hidden,created_at) "
                    "VALUES('saber-owner',?,'admin','en',1,1,?)",
                    (password_hash, utcnow()),
                )
                owner_access.migrate(connection)
                row = connection.execute(
                    "SELECT active,password_hash FROM users WHERE username='saber-owner'"
                ).fetchone()

            self.assertEqual(row["active"], 0)
            self.assertEqual(row["password_hash"], password_hash)

    def test_server_startup_preserves_existing_admin_hash_and_does_not_print_password(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "company.db"
            database = Database(path)
            database.initialize("ChangeMe123!")
            with database.connect() as connection:
                before = connection.execute(
                    "SELECT password_hash FROM users WHERE username='admin'"
                ).fetchone()[0]

            fake_http = mock.Mock()
            fake_http.server_address = ("127.0.0.1", 8765)
            output = io.StringIO()
            handler = server.ApiHandler
            previous = {
                name: getattr(handler, name)
                for name in ("db", "master_db", "company_manager", "local_key")
            }
            try:
                with mock.patch.object(server, "ThreadingHTTPServer", return_value=fake_http), \
                     mock.patch.object(server, "CompanyManager") as manager, \
                     redirect_stdout(output):
                    manager.return_value.organize_files.return_value = []
                    manager.return_value.discover_files.return_value = []
                    server.run_server(
                        host="127.0.0.1", port=0, database=str(path),
                        admin_password="Different-Seed-Value",
                    )
            finally:
                running_db = handler.db
                if running_db is not None and running_db is not previous["db"]:
                    running_db.release()
                for name, value in previous.items():
                    setattr(handler, name, value)

            with database.connect() as connection:
                after = connection.execute(
                    "SELECT password_hash FROM users WHERE username='admin'"
                ).fetchone()[0]
            self.assertEqual(after, before)
            self.assertTrue(verify_password("ChangeMe123!", after))
            self.assertNotIn("Different-Seed-Value", output.getvalue())

    def test_new_database_requires_an_explicit_initial_password(self):
        with TemporaryDirectory() as folder:
            path = Path(folder) / "new.db"
            with self.assertRaisesRegex(ValueError, "initial admin password"):
                server.run_server(database=str(path))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()

"""One encrypted OAuth snapshot; one process owns the database at a time."""
import fcntl
import json
import os
import sqlite3
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from .core import SafeError


class EncryptedStore:
    def __init__(self, path, key):
        try:
            self.cipher = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, TypeError):
            raise SafeError("CONFIGURATION", "Configure MCP_CREDENTIALS_KEY com uma chave Fernet válida.") from None
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.lock = open(str(self.path) + ".lock", "a+b")
        os.chmod(self.lock.name, 0o600)
        try:
            fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self.lock.close()
            raise SafeError("CONFIGURATION", "Use somente um processo/réplica para este banco OAuth.") from None
        try:
            self.db = sqlite3.connect(self.path)
            os.chmod(self.path, 0o600)
            self.db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)")
        except BaseException:
            self.lock.close()
            raise

    def load(self):
        row = self.db.execute("SELECT payload FROM state WHERE id=1").fetchone()
        if row is None:
            return None
        try:
            return json.loads(self.cipher.decrypt(row[0]))
        except (InvalidToken, ValueError, TypeError):
            raise SafeError("CONFIGURATION", "Banco OAuth inválido ou chave incorreta; preserve o banco e confira a chave.") from None

    def save(self, state):
        payload = self.cipher.encrypt(json.dumps(state, separators=(",", ":")).encode())
        with self.db:
            self.db.execute("INSERT INTO state VALUES(1, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload", (payload,))

    def close(self):
        self.db.close()
        self.lock.close()

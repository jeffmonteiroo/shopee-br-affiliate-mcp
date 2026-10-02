import os
import tempfile
import unittest
from pathlib import Path

from cryptography.fernet import Fernet

from shopee_mcp.core import SafeError
from shopee_mcp.storage import EncryptedStore


class StorageTests(unittest.TestCase):
    def test_ciphertext_only_and_wrong_key_preserves_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'oauth.sqlite3'
            key = Fernet.generate_key()
            state = {'secret': 'synthetic-secret-only-in-encrypted-payload', 'token': 'synthetic-oauth-token'}
            store = EncryptedStore(path, key)
            store.save(state)
            self.assertEqual(store.load(), state)
            self.assertEqual(os.stat(path).st_mode & 0o777, 0o600)
            for file in Path(directory).iterdir():
                content = file.read_bytes()
                self.assertNotIn(state['secret'].encode(), content)
                self.assertNotIn(state['token'].encode(), content)
            store.close()
            before = path.read_bytes()
            wrong = EncryptedStore(path, Fernet.generate_key())
            try:
                with self.assertRaises(SafeError):
                    wrong.load()
            finally:
                wrong.close()
            self.assertEqual(before, path.read_bytes())
            correct = EncryptedStore(path, key)
            self.assertEqual(correct.load(), state)
            correct.close()

    def test_second_process_owner_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'oauth.sqlite3'
            key = Fernet.generate_key()
            first = EncryptedStore(path, key)
            try:
                with self.assertRaises(SafeError):
                    EncryptedStore(path, key)
            finally:
                first.close()

    def test_missing_key_rejected_before_creating_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'oauth.sqlite3'
            with self.assertRaises(SafeError):
                EncryptedStore(path, '')
            self.assertFalse(path.exists())

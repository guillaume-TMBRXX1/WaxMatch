"""Chiffrement des jetons OAuth avant stockage en base."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

__all__ = ["TokenCipher", "InvalidToken", "hash_session_id"]


class TokenCipher:
    def __init__(self, secret: str):
        # Clé dérivée du secret de l'application (WAXMATCH_SECRET) : la base seule ne suffit pas à lire les jetons.
        key = hashlib.sha256(b"waxmatch-oauth-tokens:" + secret.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(key))

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, value: str) -> str:
        return self._fernet.decrypt(value.encode()).decode()


def hash_session_id(session_id: str) -> str:
    return hashlib.sha256(session_id.encode()).hexdigest()

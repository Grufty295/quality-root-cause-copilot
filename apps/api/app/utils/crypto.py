"""Utilidades criptograficas puras: sin base de datos ni HTTP."""

import hashlib
import secrets

TOKEN_BYTES = 32  # 256 bits de entropia


def new_token() -> str:
    """Token opaco para la cookie. Se entrega al cliente una sola vez."""
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> bytes:
    """Lo unico que se guarda en la base. Un volcado de la tabla no sirve como sesion."""
    return hashlib.sha256(token.encode("ascii")).digest()

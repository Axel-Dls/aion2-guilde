"""
Chiffrement des données du site (data/db.enc.json).

Le dépôt et le site étant publics, les données sont chiffrées avec le mot de
passe du site, stocké dans les secrets GitHub (SITE_PASSWORD) et jamais écrit
dans le dépôt. Le navigateur les déchiffre avec le même mot de passe
(assets/common.js, WebCrypto).

Format : AES-256-GCM, clé dérivée du mot de passe par PBKDF2-SHA256.
    {"v": 1, "kdf": {"name": "PBKDF2", "hash": "SHA-256", "iterations": N, "salt": b64},
     "iv": b64, "ct": b64}      # ct = texte chiffré + tag GCM (16 octets), comme WebCrypto
"""

import base64
import hashlib
import json
import os

ITERATIONS = 250_000


class WrongPassword(Exception):
    pass


def _b64(b):
    return base64.b64encode(b).decode("ascii")


def derive_key(password, salt, iterations=ITERATIONS):
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, dklen=32)


def encrypt(obj, password, salt=None):
    """Chiffre un objet JSON. Réutiliser le sel d'un mot de passe inchangé permet
    au navigateur de garder la clé mémorisée d'un passage à l'autre."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = salt or os.urandom(16)
    iv = os.urandom(12)
    data = json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ct = AESGCM(derive_key(password, salt)).encrypt(iv, data, None)
    return {"v": 1, "kdf": {"name": "PBKDF2", "hash": "SHA-256", "iterations": ITERATIONS, "salt": _b64(salt)},
            "iv": _b64(iv), "ct": _b64(ct)}


def decrypt(box, password):
    """Renvoie (objet, sel). Lève WrongPassword si le mot de passe ne correspond pas."""
    from cryptography.exceptions import InvalidTag
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    salt = base64.b64decode(box["kdf"]["salt"])
    key = derive_key(password, salt, box["kdf"].get("iterations", ITERATIONS))
    try:
        data = AESGCM(key).decrypt(base64.b64decode(box["iv"]), base64.b64decode(box["ct"]), None)
    except InvalidTag:
        raise WrongPassword() from None
    return json.loads(data.decode("utf-8")), salt

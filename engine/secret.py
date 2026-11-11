# -*- coding: utf-8 -*-
import os
import subprocess

from engine.config import DATA_DIR

_KEY_PATH = os.path.join(DATA_DIR, "secret.key")
_PREFIX = "enc:v1:"


def ensure_key():
    if not os.path.isdir(DATA_DIR):
        os.makedirs(DATA_DIR, 0o700)
    if not os.path.isfile(_KEY_PATH):
        with open(_KEY_PATH, "wb") as handle:
            handle.write(os.urandom(32).hex().encode("ascii"))
    os.chmod(DATA_DIR, 0o700)
    os.chmod(_KEY_PATH, 0o600)


def seal(plain):
    text = "" if plain is None else str(plain)
    ensure_key()
    proc = subprocess.run(
        [
            "openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "100000",
            "-salt", "-pass", "file:" + _KEY_PATH, "-base64", "-A",
        ],
        input=text.encode("utf-8"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError("Parola korunamadı.")
    return _PREFIX + proc.stdout.decode("ascii").strip()


def seal_stored(stored):
    text = "" if stored is None else str(stored)
    if text.startswith(_PREFIX):
        return text
    return seal(text)


def reveal(stored):
    if stored is None:
        return ""
    text = str(stored)
    if not text.startswith(_PREFIX):
        return text
    ensure_key()
    proc = subprocess.run(
        [
            "openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "100000",
            "-salt", "-pass", "file:" + _KEY_PATH, "-base64", "-A",
        ],
        input=text[len(_PREFIX):].encode("ascii"),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise RuntimeError("Kayıtlı parola açılamadı.")
    return proc.stdout.decode("utf-8")

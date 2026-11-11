# -*- coding: utf-8 -*-
"""Tam paketten seçilen parçayı açar. restorepkg çağrılmaz."""
import os
import pwd
import shutil
import subprocess
import tarfile

from engine.config import USER_DIR


def account_home(account):
    home = "/home/%s" % account
    path = os.path.join(USER_DIR, account)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("HOMEDIR="):
                    value = line.strip().split("=", 1)[1]
                    if value.startswith("/") and ".." not in value.split("/"):
                        home = value
    except OSError:
        pass
    return home


def contact_email(account):
    path = os.path.join(USER_DIR, account)
    found = ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("CONTACTEMAIL=") or (not found and line.startswith("EMAIL=")):
                    found = line.strip().split("=", 1)[1]
                    if line.startswith("CONTACTEMAIL=") and "@" in found:
                        return found
    except OSError:
        return ""
    return found if "@" in found else ""


def apply_selection(archive_path, account, selection):
    home = account_home(account)
    if not os.path.isdir(home):
        raise ValueError("Ev dizini bulunamadı.")
    preview = bool(selection.get("preview"))
    items = selection.get("items") or []
    if not items:
        raise ValueError("Geri yüklenecek parça seçilmedi.")
    wanted = []
    for item in items:
        kind = str(item.get("kind") or "")
        path = _safe_rel(item.get("path"))
        if kind not in ("file", "dir", "database", "mailbox") or not path:
            raise ValueError("Seçilen parça geçersiz.")
        if kind in ("file", "dir") and not path.startswith("homedir/"):
            raise ValueError("Ev dizini dışındaki dosya geri yüklenemez.")
        wanted.append((kind, path))
    root = os.path.join(home, "cpbackup-onizleme") if preview else home
    if preview:
        os.makedirs(root, 0o755)
    mode = "r:gz" if archive_path.endswith(".gz") else "r:"
    applied = []
    with tarfile.open(archive_path, mode) as archive:
        members = archive.getmembers()
        for kind, path in wanted:
            if kind == "database" and not preview:
                _import_database(archive, members, path)
            else:
                _extract_match(archive, members, path, root, preview, account)
            applied.append(path)
    return applied


def _safe_rel(value):
    text = str(value or "").replace("\\", "/").lstrip("/")
    parts = [part for part in text.split("/") if part]
    if not parts or any(part in (".", "..") for part in parts):
        return ""
    return "/".join(parts)


def _member_rel(name):
    text = str(name or "").replace("\\", "/").lstrip("./")
    if text.startswith("cpmove-"):
        bits = text.split("/", 1)
        text = bits[1] if len(bits) == 2 else ""
    return text


def _extract_match(archive, members, wanted, root, preview, account):
    prefix = wanted.rstrip("/")
    found = False
    for member in members:
        rel = _member_rel(member.name)
        if rel != prefix and not rel.startswith(prefix + "/"):
            continue
        found = True
        target = os.path.join(root, rel) if preview or rel.startswith("homedir/") else os.path.join(root, rel)
        if not preview and rel.startswith("homedir/"):
            target = os.path.join(root, rel[len("homedir/"):])
        target = os.path.realpath(target)
        if not target.startswith(os.path.realpath(root) + os.sep) and target != os.path.realpath(root):
            raise ValueError("Hedef ev dizininin dışında.")
        if member.isdir():
            os.makedirs(target, 0o755)
            _own(account, target)
            continue
        os.makedirs(os.path.dirname(target), 0o755)
        source = archive.extractfile(member)
        if source is None:
            continue
        with open(target, "wb") as handle:
            shutil.copyfileobj(source, handle)
        _own(account, target)
    if not found:
        raise ValueError("Arşivde parça yok: %s" % wanted)


def _import_database(archive, members, wanted):
    member = None
    for item in members:
        if _member_rel(item.name) == wanted and item.isfile():
            member = item
            break
    if member is None:
        raise ValueError("Veritabanı dökümü bulunamadı.")
    name = os.path.basename(wanted)
    if name.endswith(".sql"):
        name = name[:-4]
    if not name.replace("_", "").isalnum():
        raise ValueError("Veritabanı adı geçersiz.")
    source = archive.extractfile(member)
    proc = subprocess.run(
        ["mysql", "-e", "CREATE DATABASE IF NOT EXISTS `%s`" % name],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        raise ValueError("Veritabanı hazırlanamadı.")
    load = subprocess.run(
        ["mysql", name],
        input=source.read(),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if load.returncode != 0:
        raise ValueError("Veritabanı içeri alınamadı.")


def _own(account, path):
    try:
        user = pwd.getpwnam(account)
        os.chown(path, user.pw_uid, user.pw_gid)
    except (KeyError, OSError):
        return

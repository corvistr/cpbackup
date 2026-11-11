# -*- coding: utf-8 -*-
import json
import os
import subprocess
import time

from engine.config import USER_DIR, WHMAPI

_CACHE = {"at": 0, "rows": None}
_DIR_CACHE = {"at": 0, "rows": None}


def whm_json(args):
    cmd = [WHMAPI] + list(args) + ["--output=json"]
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        universal_newlines=True,
    )
    if proc.returncode != 0:
        reason = (proc.stderr or proc.stdout or "whmapi1 hatası").strip()
        raise RuntimeError(reason)
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        raise RuntimeError("whmapi1 yanıtı okunamadı")
    meta = data.get("metadata") or {}
    if meta.get("result") != 1:
        raise RuntimeError(meta.get("reason") or "whmapi1 hatası")
    return data


def is_suspended(user):
    path = os.path.join(USER_DIR, str(user or ""))
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("SUSPENDED="):
                    return line.strip().split("=", 1)[1] == "1"
    except OSError:
        return False
    return False


def list_accounts(force=False):
    cached = _CACHE["rows"]
    if not force and cached is not None and (time.time() - _CACHE["at"]) < 30:
        return cached
    data = whm_json([
        "listaccts",
        "want=user,domain,diskused,suspended,plan",
        "api.columns.enable=1",
        "api.columns.a=user",
        "api.columns.b=domain",
        "api.columns.c=diskused",
        "api.columns.d=suspended",
        "api.columns.e=plan",
    ])
    rows = (data.get("data") or {}).get("acct") or []
    accounts = []
    for row in rows:
        user = str(row.get("user") or "")
        if not user or not os.path.isfile(os.path.join(USER_DIR, user)):
            continue
        suspended = bool(int(row.get("suspended") or 0)) or is_suspended(user)
        if suspended:
            continue
        accounts.append({
            "user": user,
            "domain": row.get("domain") or "",
            "diskused": row.get("diskused") or "0",
            "suspended": False,
            "plan": row.get("plan") or "",
        })
    accounts.sort(key=lambda item: (item["domain"] or item["user"]).lower())
    _CACHE["at"] = time.time()
    _CACHE["rows"] = accounts
    return accounts


def list_directory(force=False):
    cached = _DIR_CACHE["rows"]
    if not force and cached is not None and (time.time() - _DIR_CACHE["at"]) < 30:
        return cached
    data = whm_json([
        "listaccts",
        "want=user,domain,diskused,disklimit,suspended,plan,ip,owner",
        "api.columns.enable=1",
        "api.columns.a=user",
        "api.columns.b=domain",
        "api.columns.c=diskused",
        "api.columns.d=disklimit",
        "api.columns.e=suspended",
        "api.columns.f=plan",
        "api.columns.g=ip",
        "api.columns.h=owner",
    ])
    rows = (data.get("data") or {}).get("acct") or []
    accounts = []
    for row in rows:
        user = str(row.get("user") or "")
        if not user or not os.path.isfile(os.path.join(USER_DIR, user)):
            continue
        home, file_suspended = _user_meta(user)
        suspended = bool(int(row.get("suspended") or 0)) or file_suspended
        limit = str(row.get("disklimit") or "unlimited")
        accounts.append({
            "user": user,
            "domain": row.get("domain") or "",
            "diskused": row.get("diskused") or "0",
            "disk_bytes": parse_cpanel_size(row.get("diskused")),
            "disklimit": limit,
            "limit_bytes": 0 if limit.lower() == "unlimited" else parse_cpanel_size(limit),
            "suspended": suspended,
            "plan": row.get("plan") or "",
            "ip": row.get("ip") or "",
            "owner": row.get("owner") or "",
            "home": home,
        })
    accounts.sort(key=lambda item: (item["domain"] or item["user"]).lower())
    _DIR_CACHE["at"] = time.time()
    _DIR_CACHE["rows"] = accounts
    return accounts


def _user_meta(user):
    home = "/home/" + user
    suspended = False
    path = os.path.join(USER_DIR, user)
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("HOMEDIRPATHS="):
                    raw = line.split("=", 1)[1].strip()
                    if raw:
                        home = raw.split()[0]
                elif line.startswith("SUSPENDED=") and line.strip().endswith("=1"):
                    suspended = True
    except OSError:
        pass
    return home, suspended


def parse_cpanel_size(value):
    text = str(value or "0").strip().upper().replace(",", "")
    if text in ("", "NONE", "UNLIMITED", "N/A"):
        return 0
    units = (
        ("TB", 1024 ** 4),
        ("GB", 1024 ** 3),
        ("MB", 1024 ** 2),
        ("KB", 1024),
        ("T", 1024 ** 4),
        ("G", 1024 ** 3),
        ("M", 1024 ** 2),
        ("K", 1024),
        ("B", 1),
    )
    for suffix, mult in units:
        if text.endswith(suffix):
            number = text[: -len(suffix)].strip() or "0"
            return int(float(number) * mult)
    return int(float(text))

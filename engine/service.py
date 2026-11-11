# -*- coding: utf-8 -*-
import datetime
import errno
import fcntl
import hashlib
import hmac
import json
import os
import shutil
import socket
import subprocess
import time

from engine.accounts import is_suspended, list_accounts, list_directory, parse_cpanel_size
from engine.config import (
    CRON_LOG,
    LOCK_PATH,
    LOG_FILE,
    PKGACCT,
    RESTOREPKG,
    SPOOL,
    USER_DIR,
    VERSION,
)
from engine.contents import (
    CERTS,
    CONFIG,
    CRON,
    DATABASES,
    DB_USERS,
    DOMAINS,
    EMAILS,
    FTP,
    FULL,
    HOMEDIR,
    effective_contains,
    email_contents_on,
    excluded_databases,
    is_legacy_scope,
    junk_excluded,
    member_skipped,
    needs_repack,
    pkgacct_skip_args,
    archive_name,
    group_tag,
)
from engine.db import connect, get_setting, set_setting
from engine.ftpclient import FTPError
from engine.indexpkg import build_rows, repack_skipping
from engine.partialrest import apply_selection, contact_email
from engine.secret import ensure_key, reveal, seal, seal_stored
from engine.stores import StoreError, auth_url, dest_kind, exchange_code, extra_of, open_store, public_extra

_ACTIVE = ("queued", "running", "packaging", "packaged", "uploading")
_GB = 1024 ** 3

BOOL_JOB = (
    "all_accounts",
    "enabled",
    "include_homedir",
    "include_db",
    "include_dns",
    "include_mailconfig",
    "skip_logs",
    "skip_suspended",
)


def now_dt():
    return datetime.datetime.now().replace(microsecond=0)


def now_text(when=None):
    return (when or now_dt()).strftime("%Y-%m-%d %H:%M:%S")


def log_line(message):
    if not os.path.isdir(os.path.dirname(LOG_FILE)):
        os.makedirs(os.path.dirname(LOG_FILE), 0o700)
    _trim(LOG_FILE, 5 * 1024 * 1024)
    with open(LOG_FILE, "a") as handle:
        handle.write("%s %s\n" % (now_text(), message))


def ensure_runtime():
    os.umask(0o077)
    for path in (SPOOL, os.path.dirname(LOG_FILE), os.path.dirname(LOCK_PATH)):
        if not os.path.isdir(path):
            os.makedirs(path, 0o700)
    os.chmod(SPOOL, 0o700)
    ensure_key()
    conn = connect()
    try:
        if get_setting(conn, "max_load") is None:
            set_setting(conn, "max_load", str(os.cpu_count() or 4))
        if get_setting(conn, "notify_email") is None:
            set_setting(conn, "notify_email", "")
        if get_setting(conn, "allow_user_restore") is None:
            set_setting(conn, "allow_user_restore", "1")
        if get_setting(conn, "summary_mail") is None:
            set_setting(conn, "summary_mail", "1")
        if get_setting(conn, "history_days") is None:
            set_setting(conn, "history_days", "90")
        if get_setting(conn, "account_gap") is None:
            set_setting(conn, "account_gap", "2")
        if get_setting(conn, "nice_level") is None:
            set_setting(conn, "nice_level", "10")
        if get_setting(conn, "ionice_level") is None:
            set_setting(conn, "ionice_level", "7")
        if get_setting(conn, "restore_times") is None:
            set_setting(conn, "restore_times", "0")
        if get_setting(conn, "restore_hours") is None:
            set_setting(conn, "restore_hours", "24")
        if get_setting(conn, "owner_fail_mail") is None:
            set_setting(conn, "owner_fail_mail", "0")
        if get_setting(conn, "owner_ok_mail") is None:
            set_setting(conn, "owner_ok_mail", "0")
        rows = conn.execute("SELECT id, password FROM destinations").fetchall()
        for row in rows:
            if not str(row["password"]).startswith("enc:v1:"):
                conn.execute(
                    "UPDATE destinations SET password=? WHERE id=?",
                    (seal_stored(row["password"]), row["id"]),
                )
        conn.commit()
    finally:
        conn.close()


def destination_public(row):
    kind = dest_kind(row)
    extra = public_extra(row)
    return {
        "id": row["id"],
        "name": row["name"],
        "kind": kind,
        "host": row["host"],
        "port": row["port"],
        "username": row["username"],
        "path": row["path"],
        "passive": bool(row["passive"]),
        "tls": bool(row["tls"]),
        "has_password": True,
        "region": extra["region"],
        "prefix": extra["prefix"],
        "has_refresh": extra["has_refresh"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def job_public(row):
    data = {
        "id": row["id"],
        "name": row["name"],
        "destination_id": row["destination_id"],
        "accounts": json.loads(row["accounts"] or "[]"),
        "schedule": row["schedule"],
        "hour": row["hour"],
        "minute": row["minute"],
        "weekday": row["weekday"],
        "retention": row["retention"],
        "last_run": row["last_run"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "active": 0,
        "max_account_gb": round(float(row["max_account_bytes"] or 0) / _GB, 1),
        "contains": effective_contains(row),
        "exclude_databases": excluded_databases(row),
        "email_contents": email_contents_on(row),
        "exclude_junk": junk_excluded(row),
    }
    for key in BOOL_JOB:
        data[key] = bool(row[key])
    return data


def run_public(row):
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "destination_id": row["destination_id"],
        "account": row["account"],
        "kind": row["kind"],
        "status": row["status"],
        "remote_path": row["remote_path"],
        "size_bytes": row["size_bytes"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error": row["error"],
        "force": bool(row["force"]),
        "created_at": row["created_at"],
        "locked": bool(row["locked"]) if "locked" in row.keys() and row["locked"] else False,
    }


def account_directory():
    rows = list_directory()
    conn = connect()
    try:
        counts = conn.execute(
            """SELECT account,
                      SUM(CASE WHEN status='uploaded' THEN 1 ELSE 0 END) AS backups,
                      MAX(CASE WHEN status='uploaded' THEN finished_at END) AS last_at
               FROM runs WHERE kind='backup' GROUP BY account"""
        ).fetchall()
        latest = conn.execute(
            """SELECT r.account, r.status FROM runs r
               INNER JOIN (
                 SELECT account, MAX(id) AS id FROM runs WHERE kind='backup' GROUP BY account
               ) newest ON newest.id=r.id"""
        ).fetchall()
        limit_row = conn.execute(
            "SELECT MIN(max_account_bytes) AS n FROM jobs WHERE enabled=1 AND max_account_bytes>0"
        ).fetchone()
    finally:
        conn.close()
    by_count = {row["account"]: row for row in counts}
    by_status = {row["account"]: row["status"] for row in latest}
    limit = int(limit_row["n"] or 0) if limit_row else 0
    data = []
    for row in rows:
        stat = by_count.get(row["user"])
        data.append({
            "user": row["user"],
            "domain": row["domain"],
            "ip": row["ip"],
            "owner": row["owner"],
            "plan": row["plan"],
            "home": row["home"],
            "suspended": row["suspended"],
            "disk_bytes": row["disk_bytes"],
            "limit_bytes": row["limit_bytes"],
            "backups": int(stat["backups"] or 0) if stat else 0,
            "last_at": stat["last_at"] if stat else None,
            "last_status": by_status.get(row["user"]),
            "oversized": bool(limit and row["disk_bytes"] > limit),
        })
    return data


def account_backups(user, limit=8):
    name = _account_name(user)
    limit = _as_int(limit or 8, "Adet", 1, 40)
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT * FROM runs WHERE account=? AND kind='backup'
               ORDER BY id DESC LIMIT ?""",
            (name, limit),
        ).fetchall()
    finally:
        conn.close()
    return [run_public(row) for row in rows]


def backup_download_info(run_id):
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Yedek kaydı bulunamadı.")
        if row["kind"] != "backup" or row["status"] != "uploaded" or not row["remote_path"]:
            raise ValueError("Yalnızca FTP'ye yüklenmiş bir yedek indirilebilir.")
        dest = conn.execute("SELECT * FROM destinations WHERE id=?", (row["destination_id"],)).fetchone()
    finally:
        conn.close()
    if dest is None:
        raise ValueError("FTP hedefi artık yok.")
    raw = row["remote_path"].replace("\\", "/").rsplit("/", 1)[-1]
    safe = "".join(char for char in raw if char.isalnum() or char in "._-")
    if not safe or safe.startswith("."):
        raise ValueError("Dosya adı geçersiz.")
    return {"remote_path": row["remote_path"], "filename": safe, "destination": dest}


def _account_name(value):
    text = str(value or "").strip().lower()
    if not text or len(text) > 32 or any(char not in "abcdefghijklmnopqrstuvwxyz0123456789_" for char in text):
        raise ValueError("Hesap adı geçersiz.")
    if not os.path.isfile(os.path.join(USER_DIR, text)):
        raise ValueError("Hesap bulunamadı.")
    return text


def status_payload():
    ensure_runtime()
    conn = connect()
    try:
        destinations = conn.execute("SELECT COUNT(*) AS c FROM destinations").fetchone()["c"]
        jobs = conn.execute("SELECT COUNT(*) AS c FROM jobs WHERE enabled=1").fetchone()["c"]
        queue = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE status IN ('queued','packaged')"
        ).fetchone()["c"]
        running = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE status IN ('running','packaging','uploading')"
        ).fetchone()["c"]
        since = (now_dt() - datetime.timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
        success = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE status IN ('uploaded','restored') AND finished_at>=?",
            (since,),
        ).fetchone()["c"]
        failed = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE status='failed' AND finished_at>=?",
            (since,),
        ).fetchone()["c"]
        recent_batches = _query_batches(conn, limit=5, offset=0, query="")
        max_load = float(get_setting(conn, "max_load") or (os.cpu_count() or 4))
        notify_email = get_setting(conn, "notify_email") or ""
        allow_user_restore = get_setting(conn, "allow_user_restore") != "0"
        summary_mail = get_setting(conn, "summary_mail") != "0"
        history_days = _setting_int(conn, "history_days", 90, 0, 3650)
        account_gap = _setting_int(conn, "account_gap", 2, 0, 120)
        nice_level = _setting_int(conn, "nice_level", 10, 0, 19)
        ionice_level = _setting_int(conn, "ionice_level", 7, 0, 7)
        restore_times = _setting_int(conn, "restore_times", 0, 0, 50)
        restore_hours = _setting_int(conn, "restore_hours", 24, 1, 168)
        owner_fail_mail = get_setting(conn, "owner_fail_mail") == "1"
        owner_ok_mail = get_setting(conn, "owner_ok_mail") == "1"
        cloud_ready = get_setting(conn, "cloud_ready") == "1"
        next_run = _soonest_job(conn, now_dt())
        active_batch, oversized = _status_focus(conn)
        last_error = _last_error(conn, active_batch["id"] if active_batch else None)
    finally:
        conn.close()
    free = _free_bytes(SPOOL)
    disk_total, disk_used, disk_percent = _disk_ratio()
    load = os.getloadavg()
    return {
        "ok": True,
        "version": VERSION,
        "hostname": socket.gethostname(),
        "accounts": len(list_accounts()),
        "destinations": destinations,
        "jobs": jobs,
        "queue": queue,
        "running": running,
        "success_24h": success,
        "failed_24h": failed,
        "spool_free": free,
        "spool": SPOOL,
        "disk_total": disk_total,
        "disk_used": disk_used,
        "disk_percent": disk_percent,
        "load": [round(load[0], 2), round(load[1], 2), round(load[2], 2)],
        "max_load": max_load,
        "notify_email": notify_email,
        "allow_user_restore": allow_user_restore,
        "summary_mail": summary_mail,
        "history_days": history_days,
        "account_gap": account_gap,
        "nice_level": nice_level,
        "ionice_level": ionice_level,
        "restore_times": restore_times,
        "restore_hours": restore_hours,
        "owner_fail_mail": owner_fail_mail,
        "owner_ok_mail": owner_ok_mail,
        "cloud_ready": cloud_ready,
        "timezone": time.tzname[0],
        "now": now_text(),
        "recent_batches": recent_batches,
        "next_run": next_run,
        "active_batch": active_batch,
        "last_error": last_error,
        "oversized": oversized,
    }


_MONTHS = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def _next_slot(job, current):
    hour = int(job["hour"] or 0)
    minute = int(job["minute"] or 0)
    slot = current.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if job["schedule"] == "daily":
        if slot <= current:
            slot += datetime.timedelta(days=1)
        return slot
    if job["schedule"] != "weekly":
        return None
    weekday = int(job["weekday"] if job["weekday"] is not None else 0)
    slot += datetime.timedelta(days=(weekday - current.weekday()) % 7)
    if slot <= current:
        slot += datetime.timedelta(days=7)
    return slot


def _soonest_job(conn, current):
    rows = conn.execute(
        "SELECT * FROM jobs WHERE enabled=1 AND schedule!='manual'"
    ).fetchall()
    chosen = None
    when = None
    for job in rows:
        slot = _next_slot(job, current)
        if slot is None:
            continue
        if when is None or slot < when:
            chosen = job
            when = slot
    if chosen is None or when is None:
        return {"manual": True, "label": "Elle", "at": None, "job": None}
    label = "%d %s %02d:%02d" % (when.day, _MONTHS[when.month - 1], when.hour, when.minute)
    return {"manual": False, "label": label, "at": now_text(when), "job": chosen["name"]}


def _status_focus(conn):
    row = conn.execute(
        """SELECT id FROM batches
           WHERE EXISTS (
             SELECT 1 FROM runs r WHERE r.batch_id=batches.id
               AND r.status IN ('queued','running','packaging','packaged','uploading')
           )
           ORDER BY id DESC LIMIT 1"""
    ).fetchone()
    live = row is not None
    if row is None:
        row = conn.execute(
            "SELECT id FROM batches WHERE kind='backup' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None, []
    summary = _query_batches(conn, limit=1, offset=0, query="", batch_id=row["id"])
    if not summary:
        return None, []
    batch = summary[0]
    size = conn.execute(
        "SELECT COALESCE(SUM(size_bytes),0) AS s FROM runs WHERE batch_id=? AND status='uploaded'",
        (row["id"],),
    ).fetchone()["s"]
    batch["live"] = live
    batch["bytes"] = int(size or 0)
    names = conn.execute(
        """SELECT account FROM runs
           WHERE batch_id=? AND status='skipped' AND error LIKE 'Hesap boyutu%'
           ORDER BY account COLLATE NOCASE""",
        (row["id"],),
    ).fetchall()
    return batch, [item["account"] for item in names]


def _last_error(conn, batch_id):
    sql = """SELECT account, error, finished_at FROM runs
             WHERE status='failed' AND error IS NOT NULL AND error!=''"""
    args = []
    if batch_id:
        sql += " AND batch_id=?"
        args.append(batch_id)
    sql += " ORDER BY COALESCE(finished_at, created_at) DESC, id DESC LIMIT 1"
    row = conn.execute(sql, args).fetchone()
    if row is None and batch_id:
        return _last_error(conn, None)
    if row is None:
        return None
    text = (row["error"] or "").strip().replace("\n", " ")
    if len(text) > 180:
        text = text[:177] + "..."
    return {"account": row["account"], "error": text, "finished_at": row["finished_at"]}


def list_destinations():
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM destinations ORDER BY name COLLATE NOCASE").fetchall()
        return [destination_public(row) for row in rows]
    finally:
        conn.close()


def save_destination(payload):
    kind = str(payload.get("kind") or "ftp").strip().lower()
    if kind not in ("ftp", "s3", "s3compat", "gdrive", "dropbox", "onedrive"):
        raise ValueError("Hedef türü geçersiz.")
    name = _clean_text(payload.get("name"), "Hedef adı", 80)
    host = str(payload.get("host") or "").strip()
    if kind == "ftp":
        host = _clean_text(host, "Sunucu", 255)
        if any(char in host for char in " /\\"):
            raise ValueError("Sunucu adı geçersiz.")
        path = _clean_text(payload.get("path") or "/", "Uzak dizin", 400)
        if not path.startswith("/"):
            path = "/" + path
        username = _clean_text(payload.get("username"), "Kullanıcı", 128)
        port = _as_int(payload.get("port") or 21, "Port", 1, 65535)
    elif kind in ("s3", "s3compat"):
        host = host or "s3.amazonaws.com"
        if any(char in host for char in " /\\"):
            raise ValueError("Uç nokta geçersiz.")
        path = _clean_text(payload.get("path") or payload.get("bucket") or "", "Kova", 200).strip("/")
        username = _clean_text(payload.get("username"), "Erişim anahtarı", 128)
        port = 443
    else:
        host = host or kind
        path = _clean_text(payload.get("path") or "cPBackup", "Klasör", 200).strip("/") or "cPBackup"
        username = _clean_text(payload.get("username"), "İstemci kimliği", 200)
        port = 443
    passive = 1 if payload.get("passive", True) else 0
    tls = 1 if payload.get("tls") else 0
    password = payload.get("password") or ""
    if password and kind == "ftp" and _has_bad_chars(password):
        raise ValueError("Parola geçersiz karakter içeriyor.")
    dest_id = payload.get("id")
    conn = connect()
    try:
        stamp = now_text()
        if dest_id:
            dest_id = _as_int(dest_id, "Kimlik", 1, 10 ** 9)
            current = conn.execute("SELECT * FROM destinations WHERE id=?", (dest_id,)).fetchone()
            if current is None:
                raise ValueError("Hedef bulunamadı.")
            if not password:
                password = seal_stored(current["password"])
            else:
                password = seal(password)
            extra = _destination_extra(payload, current)
            conn.execute(
                """UPDATE destinations
                   SET name=?, host=?, port=?, username=?, password=?, path=?, passive=?, tls=?, kind=?, extra=?, updated_at=?
                   WHERE id=?""",
                (name, host, port, username, password, path, passive, tls, kind, extra, stamp, dest_id),
            )
        else:
            if not str(password):
                raise ValueError("Parola gerekli.")
            password = seal(password)
            extra = _destination_extra(payload, None)
            cur = conn.execute(
                """INSERT INTO destinations
                   (name, host, port, username, password, path, passive, tls, kind, extra, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (name, host, port, username, password, path, passive, tls, kind, extra, stamp, stamp),
            )
            dest_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM destinations WHERE id=?", (dest_id,)).fetchone()
        return destination_public(row)
    finally:
        conn.close()


def delete_destination(dest_id):
    dest_id = _as_int(dest_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        used = conn.execute("SELECT COUNT(*) AS c FROM jobs WHERE destination_id=?", (dest_id,)).fetchone()["c"]
        if used:
            raise ValueError("Bu hedef bir göreve bağlı. Önce görevi silin.")
        conn.execute("DELETE FROM destinations WHERE id=?", (dest_id,))
        conn.commit()
    finally:
        conn.close()


def test_destination(payload):
    row = _destination_for_test(payload)
    store = open_store(row, timeout=25)
    try:
        store.connect()
    finally:
        store.close()
    kind = dest_kind(row)
    if kind == "ftp":
        mode = "FTPS" if row["tls"] else "FTP"
        passive = "pasif" if row["passive"] else "aktif"
        return {"ok": True, "message": "Bağlantı başarılı. %s, %s mod, dizin hazır: %s" % (mode, passive, row["path"])}
    return {"ok": True, "message": "Bağlantı başarılı. %s hazır." % kind}


def oauth_redirect_uri():
    host = (os.environ.get("HTTP_HOST") or "").strip()
    if not host or any(char in host for char in " /\\"):
        host = socket.getfqdn() + ":2087"
    return "https://%s/cgi/cpbackup/api.cgi?action=destination.oauth" % host


def _oauth_key():
    from engine.secret import ensure_key
    from engine.config import DATA_DIR
    ensure_key()
    with open(os.path.join(DATA_DIR, "secret.key"), "r", encoding="ascii") as handle:
        return handle.read().strip().encode("ascii")


def _oauth_state(dest_id):
    raw = "%s.%s" % (int(dest_id), int(time.time()))
    sig = hmac.new(_oauth_key(), raw.encode("ascii"), hashlib.sha256).hexdigest()
    return "%s.%s" % (raw, sig)


def _oauth_dest(state):
    parts = str(state or "").split(".")
    if len(parts) != 3 or not parts[0].isdigit() or not parts[1].isdigit():
        raise ValueError("Bağlantı oturumu geçersiz. Yeniden bağlan.")
    raw = "%s.%s" % (parts[0], parts[1])
    expected = hmac.new(_oauth_key(), raw.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, parts[2]):
        raise ValueError("Bağlantı oturumu geçersiz. Yeniden bağlan.")
    if abs(int(time.time()) - int(parts[1])) > 900:
        raise ValueError("Bağlantı oturumu zaman aşımına uğradı. Yeniden bağlan.")
    return int(parts[0])


def destination_auth_url(payload):
    dest_id = _as_int(payload.get("id"), "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM destinations WHERE id=?", (dest_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("Hedef bulunamadı. Önce kaydedin.")
    redirect = oauth_redirect_uri()
    return {
        "ok": True,
        "url": auth_url(dest_kind(row), row["username"], redirect, _oauth_state(dest_id)),
        "redirect": redirect,
    }


def finish_oauth(code, state):
    dest_id = _oauth_dest(state)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM destinations WHERE id=?", (dest_id,)).fetchone()
        if row is None:
            raise ValueError("Hedef bulunamadı.")
        refresh = exchange_code(dest_kind(row), row["username"], reveal(row["password"]), code, oauth_redirect_uri())
        data = extra_of(row)
        data["refresh"] = seal(refresh)
        conn.execute(
            "UPDATE destinations SET extra=?, updated_at=? WHERE id=?",
            (json.dumps(data), now_text(), dest_id),
        )
        conn.commit()
    finally:
        conn.close()
    return dest_id


def destination_exchange(payload):
    dest_id = _as_int(payload.get("id"), "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM destinations WHERE id=?", (dest_id,)).fetchone()
        if row is None:
            raise ValueError("Hedef bulunamadı.")
        refresh = exchange_code(dest_kind(row), row["username"], reveal(row["password"]), payload.get("code"), oauth_redirect_uri())
        data = extra_of(row)
        data["refresh"] = seal(refresh)
        conn.execute(
            "UPDATE destinations SET extra=?, updated_at=? WHERE id=?",
            (json.dumps(data), now_text(), dest_id),
        )
        conn.commit()
        saved = conn.execute("SELECT * FROM destinations WHERE id=?", (dest_id,)).fetchone()
        return destination_public(saved)
    finally:
        conn.close()


def list_jobs():
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM jobs ORDER BY name COLLATE NOCASE").fetchall()
        active = {}
        for item in conn.execute(
            """SELECT job_id, COUNT(*) AS c FROM runs
               WHERE status IN ('queued','running','packaging','packaged','uploading') GROUP BY job_id"""
        ):
            active[item["job_id"]] = item["c"]
        result = []
        for row in rows:
            data = job_public(row)
            data["active"] = active.get(row["id"], 0)
            result.append(data)
        return result
    finally:
        conn.close()


def save_job(payload):
    name = _clean_text(payload.get("name"), "Görev adı", 80)
    destination_id = _as_int(payload.get("destination_id"), "Hedef", 1, 10 ** 9)
    schedule = payload.get("schedule") or "manual"
    if schedule not in ("manual", "daily", "weekly"):
        raise ValueError("Zamanlama geçersiz.")
    hour = _as_int(payload.get("hour", 2), "Saat", 0, 23)
    minute = _as_int(payload.get("minute", 30), "Dakika", 0, 59)
    weekday = payload.get("weekday")
    if schedule == "weekly":
        weekday = _as_int(0 if weekday is None else weekday, "Gün", 0, 6)
    else:
        weekday = None
    retention = _as_int(payload.get("retention", 7), "Saklama", 1, 365)
    max_bytes = _gb_to_bytes(payload.get("max_account_gb", 0))
    all_accounts = 1 if payload.get("all_accounts", True) else 0
    accounts = payload.get("accounts") or []
    if not isinstance(accounts, list):
        raise ValueError("Hesap listesi geçersiz.")
    clean_accounts = []
    for account in accounts:
        user = str(account or "").strip()
        if not _valid_user(user) or is_suspended(user):
            continue
        if user not in clean_accounts:
            clean_accounts.append(user)
    if not all_accounts and not clean_accounts:
        raise ValueError("En az bir hesap seçin veya tüm hesapları kullanın.")
    conn = connect()
    try:
        dest = conn.execute("SELECT * FROM destinations WHERE id=?", (destination_id,)).fetchone()
        if dest is None:
            raise ValueError("Hedef bulunamadı.")
        contains = _contains_from_payload(payload)
        exclude = _database_name_list(payload.get("exclude_databases"))
        email_contents = 0 if payload.get("email_contents") in (False, 0, "0") else 1
        exclude_junk = 1 if payload.get("exclude_junk") in (True, 1, "1") else 0
        enabled = 1 if payload.get("enabled", True) else 0
        scope = {
            "contains": contains,
            "exclude_databases": json.dumps(exclude),
            "email_contents": email_contents,
            "exclude_junk": exclude_junk,
            "include_homedir": 1,
            "include_db": 1,
            "include_dns": 1,
            "include_mailconfig": 1,
            "skip_logs": 1 if payload.get("skip_logs", True) else 0,
        }
        if enabled and not _advanced_ready(conn, dest, scope):
            raise ValueError("Parça seçimi ve bulut hedefi, çalışan yedek turu bitince açılır.")
        stamp = now_text()
        values = (
            name,
            destination_id,
            all_accounts,
            json.dumps(clean_accounts),
            schedule,
            hour,
            minute,
            weekday,
            retention,
            1 if contains & HOMEDIR else 0,
            1 if contains & DATABASES else 0,
            1 if contains & DOMAINS else 0,
            1 if contains & EMAILS else 0,
            scope["skip_logs"],
            1,
            enabled,
            max_bytes,
            contains,
            json.dumps(exclude),
            email_contents,
            exclude_junk,
            stamp,
        )
        job_id = payload.get("id")
        if job_id:
            job_id = _as_int(job_id, "Kimlik", 1, 10 ** 9)
            current = conn.execute("SELECT id FROM jobs WHERE id=?", (job_id,)).fetchone()
            if current is None:
                raise ValueError("Görev bulunamadı.")
            conn.execute(
                """UPDATE jobs SET name=?, destination_id=?, all_accounts=?, accounts=?, schedule=?,
                   hour=?, minute=?, weekday=?, retention=?, include_homedir=?, include_db=?,
                   include_dns=?, include_mailconfig=?, skip_logs=?, skip_suspended=?, enabled=?,
                   max_account_bytes=?, contains=?, exclude_databases=?, email_contents=?, exclude_junk=?, updated_at=?
                   WHERE id=?""",
                values + (job_id,),
            )
        else:
            cur = conn.execute(
                """INSERT INTO jobs
                   (name, destination_id, all_accounts, accounts, schedule, hour, minute, weekday,
                    retention, include_homedir, include_db, include_dns, include_mailconfig,
                    skip_logs, skip_suspended, enabled, max_account_bytes, contains, exclude_databases,
                    email_contents, exclude_junk, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                values[:-1] + (stamp, stamp),
            )
            job_id = cur.lastrowid
        conn.commit()
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return job_public(row)
    finally:
        conn.close()


def delete_job(job_id):
    job_id = _as_int(job_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        active = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE job_id=? AND status IN ('queued','running','packaging','packaged','uploading')",
            (job_id,),
        ).fetchone()["c"]
        if active:
            raise ValueError("Bu görevin kuyrukta veya çalışan bir işlemi var.")
        conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        conn.commit()
    finally:
        conn.close()


def enqueue_job(job_id):
    job_id = _as_int(job_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if job is None:
            raise ValueError("Görev bulunamadı.")
        dest = conn.execute("SELECT * FROM destinations WHERE id=?", (job["destination_id"],)).fetchone()
    finally:
        conn.close()
    if dest is None:
        raise ValueError("FTP hedefi bulunamadı.")
    _probe_destination(dest)
    conn = connect()
    try:
        if not _advanced_ready(conn, dest, job):
            raise ValueError("Parça seçimi ve bulut hedefi, çalışan yedek turu bitince açılır.")
        created, skipped = _enqueue_accounts(conn, job)
        conn.execute("UPDATE jobs SET last_run=?, updated_at=? WHERE id=?", (now_text(), now_text(), job_id))
        conn.commit()
        log_line("görev kuyruğa alındı id=%s adet=%s atlanan=%s" % (job_id, created, skipped))
        return {"ok": True, "queued": created, "skipped": skipped}
    finally:
        conn.close()


def set_batch_stop(batch_id, stop):
    batch_id = _as_int(batch_id, "Kimlik", 1, 10 ** 9)
    flag = 1 if stop else 0
    conn = connect()
    try:
        found = conn.execute("SELECT id FROM batches WHERE id=?", (batch_id,)).fetchone()
        if found is None:
            raise ValueError("Çalıştırma bulunamadı.")
        conn.execute("UPDATE batches SET stop_requested=? WHERE id=?", (flag, batch_id))
        conn.commit()
    finally:
        conn.close()
    if flag:
        _announced_stop.discard(batch_id)
        log_line("çalıştırma durdurma istendi batch=%s" % batch_id)
    else:
        log_line("çalıştırma sürdürülecek batch=%s" % batch_id)
    return {"ok": True, "stop_requested": bool(flag)}


def list_runs(limit=100, offset=0):
    limit = _as_int(limit or 100, "Limit", 1, 300)
    offset = _as_int(offset or 0, "Offset", 0, 10 ** 9)
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        return [run_public(row) for row in rows]
    finally:
        conn.close()


def list_batches(limit=50, offset=0, query=""):
    limit = _as_int(limit or 50, "Limit", 1, 200)
    offset = _as_int(offset or 0, "Offset", 0, 10 ** 9)
    text = str(query or "").strip()
    if len(text) > 80:
        text = text[:80]
    conn = connect()
    try:
        return _query_batches(conn, limit, offset, text)
    finally:
        conn.close()


def batch_detail(batch_id):
    batch_id = _as_int(batch_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        found = conn.execute("SELECT id FROM batches WHERE id=?", (batch_id,)).fetchone()
        if found is None:
            raise ValueError("Çalıştırma bulunamadı.")
        summary = _query_batches(conn, limit=1, offset=0, query="", batch_id=batch_id)
        runs = conn.execute(
            "SELECT * FROM runs WHERE batch_id=? ORDER BY id ASC",
            (batch_id,),
        ).fetchall()
    finally:
        conn.close()
    if not summary:
        raise ValueError("Çalıştırma bulunamadı.")
    return {"batch": summary[0], "runs": [run_public(row) for row in runs]}


def _query_batches(conn, limit, offset, query, batch_id=None):
    where = []
    args = []
    if batch_id is not None:
        where.append("b.id=?")
        args.append(batch_id)
    if query:
        like = "%" + query.replace("%", "").replace("_", "") + "%"
        where.append(
            "(b.title LIKE ? OR EXISTS (SELECT 1 FROM runs s WHERE s.batch_id=b.id AND s.account LIKE ?))"
        )
        args.extend([like, like])
    sql = (
        """SELECT b.id, b.job_id, b.destination_id, b.title, b.kind, b.created_at,
                  b.stop_requested AS stop_requested,
                  COUNT(r.id) AS total,
                  COALESCE(SUM(CASE WHEN r.status='uploaded' THEN 1 ELSE 0 END), 0) AS uploaded,
                  COALESCE(SUM(CASE WHEN r.status='failed' THEN 1 ELSE 0 END), 0) AS failed,
                  COALESCE(SUM(CASE WHEN r.status='skipped' THEN 1 ELSE 0 END), 0) AS skipped,
                  COALESCE(SUM(CASE WHEN r.status IN ('queued','packaged') THEN 1 ELSE 0 END), 0) AS queued,
                  COALESCE(SUM(CASE WHEN r.status IN ('running','packaging','uploading') THEN 1 ELSE 0 END), 0) AS running,
                  COALESCE(SUM(CASE WHEN r.status='restored' THEN 1 ELSE 0 END), 0) AS restored,
                  COALESCE(SUM(CASE WHEN r.status='deleted' THEN 1 ELSE 0 END), 0) AS deleted,
                  MAX(r.finished_at) AS finished_at
           FROM batches b
           LEFT JOIN runs r ON r.batch_id=b.id"""
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " GROUP BY b.id ORDER BY b.id DESC LIMIT ? OFFSET ?"
    args.extend([limit, offset])
    rows = conn.execute(sql, args).fetchall()
    return [_batch_public(row) for row in rows]


def _batch_public(row):
    return {
        "id": row["id"],
        "job_id": row["job_id"],
        "destination_id": row["destination_id"],
        "title": row["title"],
        "kind": row["kind"],
        "created_at": row["created_at"],
        "finished_at": row["finished_at"],
        "total": int(row["total"] or 0),
        "uploaded": int(row["uploaded"] or 0),
        "failed": int(row["failed"] or 0),
        "skipped": int(row["skipped"] or 0),
        "queued": int(row["queued"] or 0),
        "running": int(row["running"] or 0),
        "restored": int(row["restored"] or 0),
        "deleted": int(row["deleted"] or 0),
        "stop_requested": bool(row["stop_requested"]),
    }


def _open_batch(conn, job_id, destination_id, title, kind):
    stamp = now_text()
    cur = conn.execute(
        """INSERT INTO batches (job_id, destination_id, title, kind, created_at)
           VALUES (?,?,?,?,?)""",
        (job_id, destination_id, title, kind, stamp),
    )
    return cur.lastrowid, stamp


def run_log(run_id):
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Kayıt bulunamadı.")
        data = run_public(row)
        data["log"] = row["log"] or ""
        return data
    finally:
        conn.close()


def delete_remote(run_id):
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Kayıt bulunamadı.")
        if row["status"] in ("queued", "running"):
            raise ValueError("Kuyruktaki veya çalışan kayıt silinemez.")
        if not row["remote_path"]:
            raise ValueError("Uzak dosya yolu yok.")
        dest = conn.execute("SELECT * FROM destinations WHERE id=?", (row["destination_id"],)).fetchone()
        if dest is None:
            raise ValueError("FTP hedefi artık yok.")
    finally:
        conn.close()
    store = open_store(dest, timeout=60)
    try:
        store.connect()
        store.delete_file(row["remote_path"])
    finally:
        store.close()
    conn = connect()
    try:
        conn.execute(
            "UPDATE runs SET status='deleted', finished_at=?, error=NULL WHERE id=?",
            (now_text(), run_id),
        )
        conn.commit()
    finally:
        conn.close()
    log_line("uzak dosya silindi run=%s" % run_id)
    return {"ok": True}


def delete_batch_remote(batch_id, confirm, sure):
    if str(confirm or "").strip().lower() != "evet" or str(sure or "").strip().lower() != "evet":
        raise ValueError("Silmek için her iki onay da evet olmalı.")
    batch_id = _as_int(batch_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        found = conn.execute("SELECT id, title FROM batches WHERE id=?", (batch_id,)).fetchone()
        if found is None:
            raise ValueError("Çalıştırma bulunamadı.")
        rows = conn.execute(
            """SELECT * FROM runs
               WHERE batch_id=? AND kind='backup' AND status='uploaded' AND remote_path IS NOT NULL
               ORDER BY id""",
            (batch_id,),
        ).fetchall()
        busy = conn.execute(
            """SELECT COUNT(*) AS c FROM runs
               WHERE batch_id=? AND status IN ('queued','running','packaging','packaged','uploading')""",
            (batch_id,),
        ).fetchone()["c"]
    finally:
        conn.close()
    if not rows:
        raise ValueError("Bu çalıştırmada silinecek yüklenmiş yedek yok.")
    by_dest = {}
    for row in rows:
        by_dest.setdefault(row["destination_id"], []).append(row)
    deleted = 0
    for dest_id, items in by_dest.items():
        conn = connect()
        try:
            dest = conn.execute("SELECT * FROM destinations WHERE id=?", (dest_id,)).fetchone()
        finally:
            conn.close()
        if dest is None:
            raise ValueError("FTP hedefi artık yok.")
        store = open_store(dest, timeout=120)
        try:
            store.connect()
            for item in items:
                store.delete_file(item["remote_path"])
                conn = connect()
                try:
                    conn.execute(
                        "UPDATE runs SET status='deleted', finished_at=?, error=NULL WHERE id=?",
                        (now_text(), item["id"]),
                    )
                    conn.commit()
                finally:
                    conn.close()
                deleted += 1
        finally:
            store.close()
    log_line("çalıştırma uzak yedekleri silindi batch=%s adet=%s" % (batch_id, deleted))
    return {"ok": True, "deleted": deleted, "busy": busy, "title": found["title"]}


def enqueue_restore(run_id, confirm, force):
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise ValueError("Yedek kaydı bulunamadı.")
        if row["kind"] != "backup" or row["status"] != "uploaded" or not row["remote_path"]:
            raise ValueError("Yalnızca yüklenmiş bir yedek geri yüklenebilir.")
        if str(confirm or "") != row["account"]:
            raise ValueError("Onay için hesap adını aynen yazın.")
        active = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE account=? AND kind='restore' AND status IN ('queued','running')",
            (row["account"],),
        ).fetchone()["c"]
        if active:
            raise ValueError("Bu hesap için zaten bir geri yükleme var.")
        _restore_allowed(conn, row["account"])
        batch_id, stamp = _open_batch(
            conn,
            row["job_id"],
            row["destination_id"],
            "Geri yükleme · %s" % row["account"],
            "restore",
        )
        cur = conn.execute(
            """INSERT INTO runs
               (job_id, destination_id, account, kind, status, remote_path, force, log, created_at, batch_id)
               VALUES (?,?,?,?, 'queued', ?, ?, ?, ?, ?)""",
            (
                row["job_id"],
                row["destination_id"],
                row["account"],
                row["remote_path"],
                1 if force else 0,
                "Geri yükleme kuyruğa alındı. Kaynak kayıt #%s\n" % row["id"],
                stamp,
                batch_id,
            ),
        )
        conn.commit()
        log_line("geri yükleme kuyruğa alındı hesap=%s run=%s" % (row["account"], cur.lastrowid))
        return {"ok": True, "id": cur.lastrowid}
    finally:
        conn.close()


def save_settings(payload):
    email = str(payload.get("notify_email") or "").strip()
    if email and ("@" not in email or _has_bad_chars(email) or " " in email):
        raise ValueError("E-posta adresi geçersiz.")
    max_load = payload.get("max_load")
    try:
        max_load = float(max_load)
    except (TypeError, ValueError):
        raise ValueError("Yük sınırı geçersiz.")
    if max_load < 1 or max_load > 1000:
        raise ValueError("Yük sınırı 1 ile 1000 arasında olmalı.")
    history_days = _as_int(payload.get("history_days", 90), "Geçmiş süresi", 0, 3650)
    account_gap = _as_int(payload.get("account_gap", 2), "Hesap arası bekleme", 0, 120)
    nice_level = _as_int(payload.get("nice_level", 10), "CPU önceliği", 0, 19)
    ionice_level = _as_int(payload.get("ionice_level", 7), "Disk önceliği", 0, 7)
    restore_times = _as_int(payload.get("restore_times", 0), "Geri yükleme adedi", 0, 50)
    restore_hours = _as_int(payload.get("restore_hours", 24), "Geri yükleme süresi", 1, 168)
    conn = connect()
    try:
        set_setting(conn, "notify_email", email)
        set_setting(conn, "max_load", str(max_load))
        set_setting(conn, "summary_mail", "1" if payload.get("summary_mail", True) else "0")
        set_setting(conn, "history_days", str(history_days))
        set_setting(conn, "account_gap", str(account_gap))
        set_setting(conn, "nice_level", str(nice_level))
        set_setting(conn, "ionice_level", str(ionice_level))
        set_setting(conn, "restore_times", str(restore_times))
        set_setting(conn, "restore_hours", str(restore_hours))
        if "allow_user_restore" in payload:
            set_setting(conn, "allow_user_restore", "1" if payload.get("allow_user_restore") else "0")
        if "owner_fail_mail" in payload:
            set_setting(conn, "owner_fail_mail", "1" if payload.get("owner_fail_mail") else "0")
        if "owner_ok_mail" in payload:
            set_setting(conn, "owner_ok_mail", "1" if payload.get("owner_ok_mail") else "0")
        conn.commit()
    finally:
        conn.close()
    removed = _prune_history()
    return {"ok": True, "pruned": removed}


def list_own(account):
    _require_account(account)
    ensure_runtime()
    _expire_manual()
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT id, kind, status, size_bytes, started_at, finished_at, created_at, error,
                      manual, expires_at
               FROM runs WHERE account=? ORDER BY id DESC LIMIT 100""",
            (account,),
        ).fetchall()
        allow = get_setting(conn, "allow_user_restore") != "0"
    finally:
        conn.close()
    return {
        "ok": True,
        "account": account,
        "allow_restore": allow,
        "items": [_own_item(row) for row in rows],
    }


def enqueue_own(account, contains=None, email_contents=None, exclude_junk=None, exclude_databases=None):
    _require_account(account)
    if is_suspended(account):
        raise ValueError("Askıdaki hesap yedeklenemez.")
    ensure_runtime()
    conn = connect()
    try:
        job = conn.execute(
            """SELECT * FROM jobs
               WHERE enabled=1 AND destination_id IS NOT NULL
               ORDER BY all_accounts DESC, id ASC LIMIT 1"""
        ).fetchone()
        if job is None:
            raise ValueError("Yedek hedefi tanımlı değil. Yöneticinize bildirin.")
        active = conn.execute(
            """SELECT id FROM runs
               WHERE account=? AND kind='backup'
                 AND status IN ('queued','running','packaging','packaged','uploading')""",
            (account,),
        ).fetchone()
        if active:
            raise ValueError("Bu hesap için zaten bir yedek sürüyor.")
        known = {item["user"]: item for item in list_accounts(force=True)}
        if account not in known:
            raise ValueError("Hesap bulunamadı.")
        limit = int(job["max_account_bytes"] or 0)
        used = parse_cpanel_size(known[account]["diskused"])
        if limit and used > limit:
            raise ValueError("Hesabınız yedek boyut sınırının üstünde.")
        expires = (now_dt() + datetime.timedelta(hours=48)).strftime("%Y-%m-%d %H:%M:%S")
        scope = _manual_scope(job, contains, email_contents, exclude_junk, exclude_databases)
        dest = conn.execute("SELECT * FROM destinations WHERE id=?", (job["destination_id"],)).fetchone()
        if dest is None:
            raise ValueError("Yedek hedefi tanımlı değil. Yöneticinize bildirin.")
        if not _advanced_ready(conn, dest, scope):
            raise ValueError("Parça seçimi, çalışan yedek turu bitince açılır.")
        batch_id, stamp = _open_batch(conn, job["id"], job["destination_id"], "Elle yedek · %s" % account, "backup")
        cur = conn.execute(
            """INSERT INTO runs
               (job_id, destination_id, account, kind, status, log, created_at, batch_id, manual, expires_at, scope_json)
               VALUES (?, ?, ?, 'backup', 'queued', ?, ?, ?, 1, ?, ?)""",
            (
                job["id"],
                job["destination_id"],
                account,
                "Elle yedek kuyruğa alındı. 48 saat sonra silinir.\n",
                stamp,
                batch_id,
                expires,
                _scope_json(scope),
            ),
        )
        conn.commit()
        log_line("elle yedek kuyruğa alındı hesap=%s run=%s" % (account, cur.lastrowid))
        return {"ok": True, "id": cur.lastrowid, "expires_at": expires}
    finally:
        conn.close()


def log_own(account, run_id):
    _require_account(account)
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=? AND account=?", (run_id, account)).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError("Kayıt bulunamadı.")
    item = _own_item(row)
    item["ok"] = True
    item["summary"] = _own_summary(row)
    return item


def restore_own(account, run_id, confirm):
    _require_account(account)
    if str(confirm or "") != account:
        raise ValueError("Onay için hesap adını aynen yazın.")
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    ensure_runtime()
    conn = connect()
    try:
        if get_setting(conn, "allow_user_restore") == "0":
            raise ValueError("Geri yükleme yönetici tarafından kapatıldı.")
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["account"] != account:
            raise ValueError("Yedek bulunamadı.")
        if row["kind"] != "backup" or row["status"] != "uploaded":
            raise ValueError("Yalnızca tamamlanmış bir yedek geri yüklenebilir.")
        active = conn.execute(
            "SELECT COUNT(*) AS c FROM runs WHERE account=? AND kind='restore' AND status IN ('queued','running')",
            (account,),
        ).fetchone()["c"]
        if active:
            raise ValueError("Bu hesap için zaten bir geri yükleme var.")
        _restore_allowed(conn, account)
        batch_id, stamp = _open_batch(
            conn,
            row["job_id"],
            row["destination_id"],
            "Geri yükleme · %s" % account,
            "restore",
        )
        cur = conn.execute(
            """INSERT INTO runs
               (job_id, destination_id, account, kind, status, remote_path, force, log, created_at, batch_id)
               VALUES (?,?,?,?, 'queued', ?, 1, ?, ?, ?)""",
            (
                row["job_id"],
                row["destination_id"],
                account,
                row["remote_path"],
                "Kullanıcı geri yüklemeyi kuyruğa aldı. Kaynak kayıt #%s\n" % row["id"],
                stamp,
                batch_id,
            ),
        )
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()
    log_line("kullanıcı geri yükleme hesap=%s run=%s" % (account, new_id))
    return {"ok": True, "id": new_id}


def delete_own(account, run_id):
    _require_account(account)
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["account"] != account:
            raise ValueError("Yedek bulunamadı.")
        if not _run_manual(row) or row["kind"] != "backup":
            raise ValueError("Yalnızca sizin aldığınız yedek silinebilir.")
        if row["status"] != "uploaded" or not row["remote_path"]:
            raise ValueError("Yalnızca yüklenmiş bir yedek silinebilir.")
        busy = conn.execute(
            """SELECT COUNT(*) AS c FROM runs
               WHERE account=? AND remote_path=?
                 AND kind IN ('restore','partial')
                 AND status IN ('queued','running','packaging','packaged','uploading')""",
            (account, row["remote_path"]),
        ).fetchone()["c"]
        if busy:
            raise ValueError("Bu yedek geri yüklemede kullanılıyor. Bitince silebilirsiniz.")
        dest = conn.execute("SELECT * FROM destinations WHERE id=?", (row["destination_id"],)).fetchone()
        if dest is None:
            raise ValueError("Yedek hedefi artık yok.")
        remote_path = row["remote_path"]
    finally:
        conn.close()
    store = open_store(dest, timeout=60)
    try:
        try:
            store.connect()
            store.delete_file(remote_path)
        except Exception:
            log_line("kullanıcı yedek silemedi id=%s hesap=%s" % (run_id, account))
            raise ValueError("Yedek uzak sunucudan silinemedi. Bir süre sonra yeniden deneyin.")
    finally:
        store.close()
    conn = connect()
    try:
        conn.execute(
            """UPDATE runs SET status='deleted', error=NULL, finished_at=?
               WHERE id=? AND account=? AND manual=1 AND status='uploaded'""",
            (now_text(), run_id, account),
        )
        conn.execute("DELETE FROM backup_entries WHERE run_id=?", (run_id,))
        conn.commit()
    finally:
        conn.close()
    log_line("kullanıcı yedeği sildi id=%s hesap=%s" % (run_id, account))
    return {"ok": True}


def _require_account(account):
    if not _valid_user(account) or not os.path.isfile(os.path.join(USER_DIR, account)):
        raise ValueError("Hesap bulunamadı.")


def _own_item(row):
    keys = row.keys() if hasattr(row, "keys") else []
    manual = bool(row["manual"]) if "manual" in keys and row["manual"] else False
    expires = row["expires_at"] if "expires_at" in keys else None
    return {
        "id": row["id"],
        "kind": row["kind"],
        "status": row["status"],
        "size_bytes": row["size_bytes"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "created_at": row["created_at"],
        "error": _public_error(row["error"]) if row["status"] == "failed" else None,
        "manual": manual,
        "expires_at": expires,
    }


def _run_manual(row):
    try:
        return bool(row["manual"])
    except (KeyError, IndexError):
        return False


def _expire_manual():
    now = now_text()
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT * FROM runs
               WHERE manual=1 AND status='uploaded' AND remote_path IS NOT NULL
                 AND expires_at IS NOT NULL AND expires_at<=?""",
            (now,),
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        try:
            conn = connect()
            try:
                dest = conn.execute(
                    "SELECT * FROM destinations WHERE id=?",
                    (row["destination_id"],),
                ).fetchone()
            finally:
                conn.close()
            if dest is not None:
                store = open_store(dest, timeout=60)
                try:
                    store.connect()
                    store.delete_file(row["remote_path"])
                finally:
                    store.close()
            conn = connect()
            try:
                conn.execute(
                    """UPDATE runs SET status='deleted', error=NULL, finished_at=?
                       WHERE id=? AND status='uploaded'""",
                    (now_text(), row["id"]),
                )
                conn.commit()
            finally:
                conn.close()
            log_line("elle yedek süresi doldu id=%s hesap=%s" % (row["id"], row["account"]))
        except Exception as exc:
            log_line("elle yedek silinemedi id=%s hata=%s" % (row["id"], exc))


def _own_summary(row):
    labels = {
        "queued": "İşlem kuyrukta.",
        "running": "İşlem sürüyor.",
        "uploaded": "Yedek hazır.",
        "restored": "Hesap bu yedekten geri yüklendi.",
        "failed": _public_error(row["error"]) or "İşlem tamamlanamadı.",
        "deleted": "Bu yedek artık kullanılamaz.",
        "skipped": "Askıdaki hesap atlandı.",
    }
    return labels.get(row["status"], "Durum bilinmiyor.")


def _public_error(text):
    if not text:
        return None
    kept = []
    for line in str(text).splitlines():
        lowered = line.lower()
        if any(word in lowered for word in ("ftp", "parola", "password", "cpmove", "remote", "stor ")):
            continue
        if "/" in line or "\\" in line:
            continue
        cleaned = line.strip()
        if cleaned:
            kept.append(cleaned)
    if not kept:
        return "İşlem tamamlanamadı."
    return " ".join(kept)[:300]


def run_worker(service=False):
    ensure_runtime()
    _trim(CRON_LOG, 2 * 1024 * 1024)
    lock_fd = open(LOCK_PATH, "a")
    if service:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
    else:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, OSError) as exc:
            err = getattr(exc, "errno", None)
            if isinstance(exc, BlockingIOError) or err in (errno.EAGAIN, errno.EACCES):
                lock_fd.close()
                return
            raise
    try:
        ready = connect()
        try:
            set_setting(ready, "cloud_ready", "1")
            ready.commit()
        finally:
            ready.close()
        _recover_stale()
        while True:
            _drop_suspended_queued()
            _enqueue_due_jobs()
            hold = _FtpHold()
            try:
                while _process_one(hold):
                    pass
            finally:
                hold.drop()
            _send_summaries()
            _prune_history()
            _expire_manual()
            if not service:
                break
            time.sleep(5)
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


def _enqueue_due_jobs():
    conn = connect()
    try:
        rows = conn.execute("SELECT * FROM jobs WHERE enabled=1 AND schedule!='manual'").fetchall()
        current = now_dt()
        for job in rows:
            if not _job_due(job, current):
                continue
            dest = conn.execute("SELECT * FROM destinations WHERE id=?", (job["destination_id"],)).fetchone()
            if dest is None or not _probe_quiet(dest):
                continue
            if not _advanced_ready(conn, dest, job):
                continue
            created, skipped = _enqueue_accounts(conn, job)
            conn.execute(
                "UPDATE jobs SET last_run=?, updated_at=? WHERE id=?",
                (now_text(current), now_text(current), job["id"]),
            )
            log_line("zamanlanmış görev id=%s kuyruk=%s atlanan=%s" % (job["id"], created, skipped))
        conn.commit()
    finally:
        conn.close()


def _job_due(job, current):
    scheduled = current.replace(hour=job["hour"], minute=job["minute"], second=0, microsecond=0)
    if job["schedule"] == "weekly" and current.weekday() != job["weekday"]:
        return False
    if current < scheduled:
        return False
    if job["last_run"]:
        try:
            last = datetime.datetime.strptime(job["last_run"], "%Y-%m-%d %H:%M:%S")
        except ValueError:
            last = None
        if last and last >= scheduled:
            return False
    return True


def _enqueue_accounts(conn, job):
    accounts = list_accounts(force=True)
    if job["all_accounts"]:
        chosen = accounts
    else:
        wanted = set(json.loads(job["accounts"] or "[]"))
        chosen = [item for item in accounts if item["user"] in wanted]
    chosen = [item for item in chosen if not item["suspended"] and not is_suspended(item["user"])]
    pending = []
    for item in chosen:
        existing = conn.execute(
            """SELECT id FROM runs
               WHERE job_id=? AND account=? AND kind='backup'
                 AND status IN ('queued','running','packaging','packaged','uploading')""",
            (job["id"], item["user"]),
        ).fetchone()
        if existing:
            continue
        pending.append(item)
    if not pending:
        return 0, 0
    limit = int(job["max_account_bytes"] or 0)
    batch_id, stamp = _open_batch(conn, job["id"], job["destination_id"], job["name"], "backup")
    created = 0
    skipped = 0
    for item in pending:
        size = parse_cpanel_size(item["diskused"])
        if limit and size > limit:
            conn.execute(
                """INSERT INTO runs
                   (job_id, destination_id, account, kind, status, error, log, created_at, finished_at, batch_id)
                   VALUES (?, ?, ?, 'backup', 'skipped', ?, ?, ?, ?, ?)""",
                (
                    job["id"],
                    job["destination_id"],
                    item["user"],
                    "Hesap boyutu sınırı aşıyor.",
                    "Kuyruğa alınmadı. Hesap boyutu sınırı aşıyor.\n",
                    stamp,
                    stamp,
                    batch_id,
                ),
            )
            skipped += 1
            continue
        conn.execute(
            """INSERT INTO runs (job_id, destination_id, account, kind, status, log, created_at, batch_id, scope_json)
               VALUES (?, ?, ?, 'backup', 'queued', ?, ?, ?, ?)""",
            (job["id"], job["destination_id"], item["user"], "Kuyruğa alındı.\n", stamp, batch_id, _scope_json(job)),
        )
        created += 1
    return created, skipped


def _recover_stale():
    conn = connect()
    keep = set()
    try:
        rows = conn.execute(
            """SELECT id, account, local_path FROM runs
               WHERE status IN ('running','packaging','uploading')"""
        ).fetchall()
        for row in rows:
            local = row["local_path"]
            if local and os.path.isfile(local) and os.path.getsize(local) > 128:
                conn.execute(
                    """UPDATE runs SET status='packaged', stage='packaged', error=NULL
                       WHERE id=?""",
                    (row["id"],),
                )
                _append_log(conn, row["id"], "Yerel paket duruyor. Yükleme kaldığı yerden sürecek.")
                keep.add(os.path.dirname(os.path.realpath(local)))
                log_line("yarım yükleme paket olarak duruyor run=%s hesap=%s" % (row["id"], row["account"]))
            else:
                conn.execute(
                    """UPDATE runs SET status='queued', stage=NULL, local_path=NULL, error=NULL
                       WHERE id=?""",
                    (row["id"],),
                )
                _append_log(conn, row["id"], "Paket bulunamadı. Hesap yeniden hazırlanacak.")
                log_line("yarım paket yeniden kuyruğa alındı run=%s hesap=%s" % (row["id"], row["account"]))
        parked = conn.execute(
            "SELECT local_path FROM runs WHERE status='packaged' AND local_path IS NOT NULL"
        ).fetchall()
        for row in parked:
            if row["local_path"] and os.path.isfile(row["local_path"]):
                keep.add(os.path.dirname(os.path.realpath(row["local_path"])))
        conn.commit()
    finally:
        conn.close()
    if not os.path.isdir(SPOOL):
        return
    for name in os.listdir(SPOOL):
        if not (name.startswith("run-") or name.startswith("restore-")):
            continue
        path = os.path.realpath(os.path.join(SPOOL, name))
        if path in keep:
            continue
        shutil.rmtree(path, ignore_errors=True)


def _drop_suspended_queued():
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT id, account FROM runs WHERE kind='backup' AND status='queued'"
        ).fetchall()
        for row in rows:
            if not is_suspended(row["account"]):
                continue
            conn.execute("DELETE FROM runs WHERE id=? AND status='queued'", (row["id"],))
            log_line("askıdaki hesap kuyruktan çıkarıldı run=%s hesap=%s" % (row["id"], row["account"]))
        conn.commit()
    finally:
        conn.close()


def _process_one(hold):
    conn = connect()
    try:
        row = conn.execute(
            "SELECT * FROM runs WHERE status='queued' ORDER BY id ASC LIMIT 1"
        ).fetchone()
        if row is not None and _batch_stopped(conn, row["batch_id"]):
            _note_stop(row["batch_id"])
            return False
        resume = False
        if row is None:
            cutoff = (now_dt() - datetime.timedelta(seconds=120)).strftime("%Y-%m-%d %H:%M:%S")
            row = conn.execute(
                """SELECT * FROM runs WHERE status='packaged'
                   AND (finished_at IS NULL OR finished_at<=?)
                   ORDER BY id ASC LIMIT 1""",
                (cutoff,),
            ).fetchone()
            if row is not None and _batch_stopped(conn, row["batch_id"]):
                _note_stop(row["batch_id"])
                return False
            resume = row is not None
        if row is None:
            return False
        if not resume:
            max_load = float(get_setting(conn, "max_load") or (os.cpu_count() or 4))
            if os.getloadavg()[0] >= max_load:
                log_line("yük yüksek (%.2f / %.2f), kuyruk bekletildi" % (os.getloadavg()[0], max_load))
                return False
            changed = conn.execute(
                """UPDATE runs SET status='running', started_at=COALESCE(started_at, ?), error=NULL
                   WHERE id=? AND status='queued'""",
                (now_text(), row["id"]),
            ).rowcount
        else:
            changed = conn.execute(
                "UPDATE runs SET status='uploading', error=NULL WHERE id=? AND status='packaged'",
                (row["id"],),
            ).rowcount
        if not changed:
            conn.commit()
            return True
        conn.commit()
        run_id = row["id"]
        kind = row["kind"]
    finally:
        conn.close()
    if kind == "restore":
        _perform_restore(run_id, hold)
    elif kind == "partial":
        _perform_partial(run_id, hold)
    else:
        _perform_backup(run_id, hold)
    time.sleep(_gap_seconds())
    return True


def _perform_backup(run_id, hold):
    conn = connect()
    try:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (run["job_id"],)).fetchone()
        dest = conn.execute("SELECT * FROM destinations WHERE id=?", (run["destination_id"],)).fetchone()
    finally:
        conn.close()
    if job is None or dest is None:
        _finish(run_id, "failed", "Görev veya FTP hedefi bulunamadı.")
        return
    account = run["account"]
    if not _valid_user(account):
        _finish(run_id, "failed", "Hesap adı geçersiz.")
        return
    if is_suspended(account):
        _note(run_id, "Askıdaki hesap atlandı.")
        _finish(run_id, "skipped", None)
        return
    local = run["local_path"] if run["local_path"] else ""
    have_package = bool(local) and os.path.isfile(local) and os.path.getsize(local) > 128
    workdir = os.path.dirname(local) if have_package else os.path.join(SPOOL, "run-%s" % run_id)
    keep = False
    try:
        if not have_package:
            known = {item["user"]: item for item in list_accounts(force=True)}
            if account not in known:
                _finish(run_id, "failed", "Hesap sunucuda yok.")
                return
            used = parse_cpanel_size(known[account]["diskused"])
            limit = int(job["max_account_bytes"] or 0)
            if limit and used > limit:
                _note(run_id, "Hesap boyutu sınırı aşıyor.")
                _finish(run_id, "skipped", "Hesap boyutu sınırı aşıyor.")
                return
            needed = used + (1024 ** 3)
            free = _free_bytes(SPOOL)
            if free < max(needed, 1024 ** 3):
                _finish(
                    run_id,
                    "failed",
                    "Spool alanında yer yok. Boş: %s, gereken yaklaşık: %s" % (_human_bytes(free), _human_bytes(needed)),
                )
                return
            os.makedirs(workdir, 0o700)
            _set_stage(run_id, "packaging")
            _note(run_id, "%s için hesap paketi hazırlanıyor." % account)
            scope = _scope_from_run(job, run)
            cmd = _priority_prefix() + [PKGACCT, "--backup", "--skipbwdata", "--skipapitokens"]
            if is_legacy_scope(scope):
                if not int(scope.get("include_homedir", 1)):
                    cmd.append("--skiphomedir")
                if not int(scope.get("include_db", 1)):
                    cmd.extend(["--skipmysql", "--skippgsql"])
                if not int(scope.get("include_dns", 1)):
                    cmd.append("--skipdnszones")
                if not int(scope.get("include_mailconfig", 1)):
                    cmd.extend(["--skipmailconfig", "--skipmailman"])
                if int(scope.get("skip_logs", 1)):
                    cmd.append("--skiplogs")
            else:
                cmd.extend(pkgacct_skip_args(scope))
            cmd.extend([account, workdir])
            code, output = _run_cmd(cmd)
            _note(run_id, output.strip()[-4000:] if output.strip() else "pkgacct çıktı üretmedi.")
            if code != 0:
                _finish(run_id, "failed", "Hesap paketi oluşturulamadı (kod %s)." % code)
                return
            package = _find_package(workdir, account) or _package_from_output(output, workdir, account)
            if not package:
                _finish(run_id, "failed", "Hesap paketi bulunamadı.")
                return
            stamp = now_dt().strftime("%Y%m%d%H%M%S")
            scope = _scope_from_run(job, run)
            if is_legacy_scope(scope):
                remote_name = "cpmove-%s-%s-%s.tar.gz" % (account, stamp, run_id)
            else:
                remote_name = archive_name(account, effective_contains(scope), stamp, run_id)
            local = os.path.join(workdir, remote_name)
            os.rename(package, local)
            _remember_package(run_id, local)
        remote_name = os.path.basename(local)
        scope = _scope_from_run(job, run)
        if needs_repack(scope):
            _note(run_id, "Seçilmeyen parçalar paketten çıkarılıyor.")
            repack_skipping(local, lambda name, scope=scope: member_skipped(name, scope))
        size = os.path.getsize(local)
        manual = _run_manual(run)
        _set_stage(run_id, "uploading")
        _note(run_id, "FTP'ye yükleniyor (%s)." % _human_bytes(size))
        remote_path = _upload_verified(hold, dest, local, account, remote_name, "manual" if manual else None)
        _note(run_id, "Yüklendi ve boyut doğrulandı: %s" % remote_path)
        try:
            _write_index(run_id, local)
            _note(run_id, "Paket içeriği indekslendi.")
        except Exception as exc:
            _note(run_id, "İçerik indeksi yazılamadı.")
            log_line("indeks hata id=%s %s" % (run_id, exc))
        _remove_file(local)
        _note(run_id, "Sunucudaki geçici yedek dosyası silindi.")
        if manual:
            _note(run_id, "Elle alınan yedek 48 saat tutulur, sonra silinir.")
        else:
            try:
                removed = _prune(hold.get(dest), account, job["retention"], _locked_names(account))
                if removed:
                    _note(run_id, "Eski yedek silindi: %s" % ", ".join(removed))
            except Exception as exc:
                hold.drop()
                _note(run_id, "Eski yedekler silinemedi: %s" % exc)
        _clear_local(run_id)
        _finish(run_id, "uploaded", None, remote_path=remote_path, size_bytes=size)
        log_line("yedek tamam id=%s hesap=%s boyut=%s" % (run_id, account, size))
    except Exception as exc:
        if local and os.path.isfile(local) and os.path.getsize(local) > 128:
            keep = True
            _remember_package(run_id, local)
            _park_upload(run_id, str(exc))
            log_line("yükleme bekletildi id=%s hesap=%s hata=%s" % (run_id, account, exc))
        else:
            _finish(run_id, "failed", str(exc))
            log_line("yedek hata id=%s hesap=%s hata=%s" % (run_id, account, exc))
    finally:
        if not keep:
            shutil.rmtree(workdir, ignore_errors=True)


def _perform_restore(run_id, hold):
    conn = connect()
    try:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        dest = conn.execute("SELECT * FROM destinations WHERE id=?", (run["destination_id"],)).fetchone()
    finally:
        conn.close()
    if dest is None or not run["remote_path"]:
        _finish(run_id, "failed", "FTP hedefi veya uzak dosya yok.")
        return
    workdir = os.path.join(SPOOL, "restore-%s" % run_id)
    os.makedirs(workdir, 0o700)
    local_name = run["remote_path"].rsplit("/", 1)[-1]
    local_path = os.path.join(workdir, local_name)
    try:
        _note(run_id, "Yedek FTP'den indiriliyor.")
        _download_with_retry(hold, dest, run["remote_path"], local_path)
        if not os.path.isfile(local_path) or os.path.getsize(local_path) < 128:
            _finish(run_id, "failed", "İndirilen arşiv boş veya eksik.")
            return
        cmd = [RESTOREPKG]
        if run["force"]:
            cmd.append("--force")
        cmd.append(local_path)
        _note(run_id, "restorepkg başlatıldı.")
        code, output = _run_cmd(cmd)
        _note(run_id, output.strip()[-5000:] if output.strip() else "restorepkg çıktı üretmedi.")
        if code != 0:
            _finish(run_id, "failed", "Geri yükleme tamamlanamadı (kod %s)." % code)
            _notify("cPBackup geri yükleme başarısız: %s" % run["account"], "çıkış kodu %s" % code)
            return
        _finish(run_id, "restored", None, size_bytes=os.path.getsize(local_path))
        log_line("geri yükleme tamam id=%s hesap=%s" % (run_id, run["account"]))
        _notify("cPBackup geri yükleme tamam: %s" % run["account"], "Kayıt #%s geri yüklendi." % run_id)
    except Exception as exc:
        _finish(run_id, "failed", str(exc))
        _notify("cPBackup geri yükleme başarısız: %s" % run["account"], str(exc))
        log_line("geri yükleme hata id=%s hata=%s" % (run_id, exc))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


class _FtpHold(object):
    def __init__(self):
        self.client = None
        self.key = None

    def get(self, dest):
        updated = dest["updated_at"] if "updated_at" in dest.keys() else ""
        ident = dest["id"] if "id" in dest.keys() else None
        key = (
            ident,
            updated,
            dest["host"],
            int(dest["port"]),
            dest["username"],
            int(dest["passive"]),
            int(dest["tls"]),
            dest["path"],
        )
        if self.client is not None and self.key == key:
            try:
                self.client.ping()
                return self.client
            except Exception:
                self.drop()
        self.drop()
        client = open_store(dest, timeout=600)
        client.connect()
        self.client = client
        self.key = key
        return self.client

    def drop(self):
        if self.client is not None:
            self.client.close()
            self.client = None
            self.key = None


def _upload_verified(hold, dest, local_path, account, remote_name, folder=None):
    def action(client):
        remote = client.upload(local_path, account, remote_name, folder)
        remote_size = client.remote_size(remote)
        local_size = os.path.getsize(local_path)
        if remote_size is None or int(remote_size) != int(local_size):
            raise FTPError("Uzak boyut yerel boyutla aynı değil.")
        return remote

    return _transfer_with_retry(hold, dest, account, action)


def _upload_with_retry(hold, dest, local_path, account, remote_name):
    return _transfer_with_retry(
        hold,
        dest,
        account,
        lambda client: client.upload(local_path, account, remote_name),
    )


def _download_with_retry(hold, dest, remote_path, local_path):
    _transfer_with_retry(
        hold,
        dest,
        remote_path.rsplit("/", 1)[-1],
        lambda client: client.download(remote_path, local_path),
    )


def _transfer_with_retry(hold, dest, label, action):
    waits = (0, 8, 20, 45)
    last = None
    for attempt, wait in enumerate(waits, 1):
        if wait:
            time.sleep(wait)
        try:
            return action(hold.get(dest))
        except FTPError as exc:
            last = exc
            hold.drop()
            if attempt == len(waits) or not (getattr(exc, "retryable", False) or _retryable_ftp(str(exc))):
                raise
            log_line("ftp yeniden deneme hedef=%s deneme=%s" % (label, attempt + 1))
    raise last


def _retryable_ftp(text):
    lowered = text.lower()
    needles = (
        "425",
        "426",
        "421",
        "450",
        "boyut",
        "zaman aşımı",
        "timed out",
        "timeout",
        "broken pipe",
        "connection reset",
        "eof",
    )
    return any(needle in lowered for needle in needles)


def _remove_file(path):
    if path and os.path.isfile(path):
        os.remove(path)


def _prune(client, account, retention, locked=None):
    locked = set(locked or [])
    prefix = "cpmove-%s-" % account
    names = [name for name in client.list_names(account) if name.startswith(prefix) and name.endswith(".tar.gz")]
    groups = {}
    for name in names:
        if name in locked:
            continue
        groups.setdefault(group_tag(account, name) or "full", []).append(name)
    removed = []
    for group_names in groups.values():
        group_names.sort()
        if len(group_names) <= retention:
            continue
        for name in group_names[: len(group_names) - retention]:
            client.delete_named(account, name)
            removed.append(name)
    return removed


def _find_package(workdir, account):
    if not os.path.isdir(workdir):
        return None
    exact = {
        "%s.tar.gz" % account,
        "%s.tar" % account,
        "cpmove-%s.tar.gz" % account,
        "cpmove-%s.tar" % account,
    }
    prefix = "cpmove-%s" % account
    found = []
    for name in os.listdir(workdir):
        path = os.path.join(workdir, name)
        if not os.path.isfile(path) or os.path.getsize(path) < 128:
            continue
        if name in exact or (name.startswith(prefix) and (name.endswith(".tar.gz") or name.endswith(".tar"))):
            found.append(path)
    if not found:
        return None
    found.sort(key=lambda path: os.path.getmtime(path), reverse=True)
    return found[0]


def _package_from_output(output, workdir, account):
    root = os.path.realpath(workdir)
    marker = "pkgacctfile is:"
    for line in (output or "").splitlines():
        if marker not in line:
            continue
        raw = line.split(marker, 1)[1].strip()
        if not raw:
            continue
        path = os.path.realpath(raw)
        base = os.path.basename(path)
        allowed = base in ("%s.tar.gz" % account, "%s.tar" % account) or base.startswith("cpmove-%s" % account)
        if not allowed:
            continue
        try:
            inside = os.path.commonpath([root, path]) == root
        except ValueError:
            inside = False
        if inside and os.path.isfile(path) and os.path.getsize(path) >= 128:
            return path
    return None


def _run_cmd(cmd):
    env = os.environ.copy()
    env["PATH"] = "/usr/local/cpanel/bin:/usr/local/cpanel/scripts:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin"
    env["HOME"] = "/root"
    env["LANG"] = "C"
    proc = subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        universal_newlines=True,
        cwd="/root",
        env=env,
    )
    return proc.returncode, proc.stdout or ""


def _destination_extra(payload, current):
    data = extra_of(current) if current is not None else {}
    if "region" in payload:
        data["region"] = str(payload.get("region") or "")[:40]
    if "prefix" in payload:
        data["prefix"] = str(payload.get("prefix") or "").strip("/")[:200]
    return json.dumps(data)


def _contains_from_payload(payload):
    if payload.get("contains") is not None and str(payload.get("contains")) != "":
        return int(payload.get("contains")) & FULL
    value = CONFIG | CRON | CERTS | FTP
    if payload.get("include_homedir", True):
        value |= HOMEDIR | EMAILS
    if payload.get("include_db", True):
        value |= DATABASES | DB_USERS
    if payload.get("include_dns", True):
        value |= DOMAINS
    if payload.get("include_mailconfig", True):
        value |= EMAILS
    return value


def _database_name_list(value):
    if not isinstance(value, list):
        return []
    names = []
    for item in value:
        name = str(item or "").strip()
        if name and all(char.isalnum() or char == "_" for char in name) and name not in names:
            names.append(name)
    return names[:40]


def _advanced_ready(conn, dest, scope):
    if dest is not None and dest_kind(dest) == "ftp" and is_legacy_scope(scope):
        return True
    return get_setting(conn, "cloud_ready") == "1"


def _scope_json(scope):
    if is_legacy_scope(scope):
        return None
    contains = effective_contains(scope)
    return json.dumps({
        "contains": contains,
        "exclude_databases": json.dumps(excluded_databases(scope)),
        "email_contents": 1 if email_contents_on(scope) else 0,
        "exclude_junk": 1 if junk_excluded(scope) else 0,
        "include_homedir": 1 if contains & HOMEDIR else 0,
        "include_db": 1 if contains & DATABASES else 0,
        "include_dns": 1 if contains & DOMAINS else 0,
        "include_mailconfig": 1 if contains & EMAILS else 0,
        "skip_logs": int(scope["skip_logs"]) if "skip_logs" in scope.keys() else 1,
    })


def _manual_scope(job, contains, email_contents, exclude_junk, exclude_databases):
    if contains is None:
        return job
    data = {key: job[key] for key in job.keys()}
    data["contains"] = int(contains) & FULL
    if email_contents is not None:
        data["email_contents"] = 1 if int(email_contents) else 0
    if exclude_junk is not None:
        data["exclude_junk"] = 1 if int(exclude_junk) else 0
    if exclude_databases is not None:
        data["exclude_databases"] = json.dumps(_database_name_list(exclude_databases))
    return data


def _scope_from_run(job, run):
    data = {key: job[key] for key in job.keys()}
    raw = ""
    try:
        raw = run["scope_json"] or ""
    except (KeyError, IndexError):
        raw = ""
    if not raw:
        return data
    try:
        parsed = json.loads(raw)
    except ValueError:
        return data
    if isinstance(parsed, dict):
        data.update(parsed)
    return data


def _write_index(run_id, path):
    rows = build_rows(path)
    conn = connect()
    try:
        conn.execute("DELETE FROM backup_entries WHERE run_id=?", (run_id,))
        conn.executemany(
            "INSERT INTO backup_entries (run_id, kind, path, size_bytes) VALUES (?,?,?,?)",
            [(run_id, kind, item_path, size) for kind, item_path, size in rows],
        )
        conn.commit()
    finally:
        conn.close()


def _locked_names(account):
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT remote_path FROM runs WHERE account=? AND locked=1 AND remote_path IS NOT NULL",
            (account,),
        ).fetchall()
    finally:
        conn.close()
    return [str(row["remote_path"]).replace("\\", "/").rsplit("/", 1)[-1] for row in rows]


def list_backup_entries(run_id, kind="", query="", index=True):
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        count = conn.execute("SELECT COUNT(*) AS c FROM backup_entries WHERE run_id=?", (run_id,)).fetchone()["c"]
    finally:
        conn.close()
    if count == 0 and not index:
        return {
            "ok": True,
            "items": [],
            "pending": True,
            "message": "Bu yedeğin iç listesi henüz yok. WHM geri yükleme ekranından bir kez açılınca hazırlanır; büyük hesapta indirme uzun sürer.",
        }
    if count == 0:
        ensure_backup_index(run_id)
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT kind, path, size_bytes FROM backup_entries WHERE run_id=? ORDER BY kind, path LIMIT 800",
            (run_id,),
        ).fetchall()
    finally:
        conn.close()
    needle = str(query or "").strip().lower()
    items = []
    for row in rows:
        if kind and row["kind"] != kind:
            continue
        if needle and needle not in row["path"].lower():
            continue
        items.append({"kind": row["kind"], "path": row["path"], "size_bytes": row["size_bytes"]})
        if len(items) >= 400:
            break
    return {"ok": True, "items": items, "pending": False}


def ensure_backup_index(run_id):
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None or not row["remote_path"]:
            raise ValueError("İndekslenecek yedek yok.")
        dest = conn.execute("SELECT * FROM destinations WHERE id=?", (row["destination_id"],)).fetchone()
    finally:
        conn.close()
    if dest is None:
        raise ValueError("Hedef bulunamadı.")
    workdir = os.path.join(SPOOL, "index-%s" % run_id)
    os.makedirs(workdir, 0o700)
    local = os.path.join(workdir, os.path.basename(str(row["remote_path"]).replace("\\", "/")))
    if not local.endswith(".tar.gz"):
        local += ".tar.gz"
    store = open_store(dest, timeout=600)
    try:
        store.connect()
        store.download(row["remote_path"], local)
        _write_index(run_id, local)
    finally:
        store.close()
        shutil.rmtree(workdir, ignore_errors=True)
    return {"ok": True}


def enqueue_partial(run_id, confirm, preview, items):
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    if not isinstance(items, list) or not items:
        raise ValueError("Geri yüklenecek parça seçilmedi.")
    clean = []
    for item in items[:40]:
        if not isinstance(item, dict):
            continue
        kind = str(item.get("kind") or "")
        path = str(item.get("path") or "").replace("\\", "/").lstrip("/")
        if kind not in ("file", "dir", "database", "mailbox"):
            continue
        if not path or ".." in path.split("/"):
            continue
        if kind in ("file", "dir") and not path.startswith("homedir/"):
            continue
        clean.append({"kind": kind, "path": path})
    if not clean:
        raise ValueError("Geri yüklenecek parça seçilmedi.")
    conn = connect()
    try:
        if get_setting(conn, "cloud_ready") != "1":
            raise ValueError("Parça geri yükleme, çalışan yedek turu bitince açılır.")
        row = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["kind"] != "backup" or row["status"] != "uploaded" or not row["remote_path"]:
            raise ValueError("Yalnızca yüklenmiş bir yedek kullanılabilir.")
        if not preview and str(confirm or "") != row["account"]:
            raise ValueError("Üzerine yazmak için hesap adını aynen yazın.")
        _restore_allowed(conn, row["account"])
        batch_id, stamp = _open_batch(conn, row["job_id"], row["destination_id"], "Parça geri yükleme · %s" % row["account"], "partial")
        cur = conn.execute(
            """INSERT INTO runs
               (job_id, destination_id, account, kind, status, remote_path, log, created_at, batch_id, selection)
               VALUES (?, ?, ?, 'partial', 'queued', ?, ?, ?, ?, ?)""",
            (
                row["job_id"],
                row["destination_id"],
                row["account"],
                row["remote_path"],
                "Parça geri yükleme kuyruğa alındı.\n",
                stamp,
                batch_id,
                json.dumps({"preview": bool(preview), "items": clean}),
            ),
        )
        conn.commit()
        return {"ok": True, "id": cur.lastrowid}
    finally:
        conn.close()


def set_run_lock(run_id, locked):
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        row = conn.execute("SELECT id, status FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is None or row["status"] != "uploaded":
            raise ValueError("Yalnızca yüklenmiş bir yedek kilitlenir.")
        conn.execute("UPDATE runs SET locked=? WHERE id=?", (1 if locked else 0, run_id))
        conn.commit()
    finally:
        conn.close()
    return {"ok": True, "locked": bool(locked)}


def retry_failed(batch_id):
    batch_id = _as_int(batch_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT * FROM runs
               WHERE batch_id=? AND kind='backup' AND status='failed'
               ORDER BY id""",
            (batch_id,),
        ).fetchall()
        if not rows:
            raise ValueError("Yeniden denenecek hatalı hesap yok.")
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (rows[0]["job_id"],)).fetchone()
        dest = None
        if job is not None:
            dest = conn.execute("SELECT * FROM destinations WHERE id=?", (job["destination_id"],)).fetchone()
        if job is None or dest is None:
            raise ValueError("Görev veya hedef bulunamadı.")
        if not _advanced_ready(conn, dest, job):
            raise ValueError("Parça seçimi ve bulut hedefi, çalışan yedek turu bitince açılır.")
        batch_new, stamp = _open_batch(conn, job["id"], dest["id"], "Yeniden deneme · %s" % (job["name"] or "Yedek"), "backup")
        created = 0
        for row in rows:
            active = conn.execute(
                """SELECT id FROM runs
                   WHERE account=? AND kind='backup'
                     AND status IN ('queued','running','packaging','packaged','uploading')""",
                (row["account"],),
            ).fetchone()
            if active:
                continue
            conn.execute(
                """INSERT INTO runs (job_id, destination_id, account, kind, status, log, created_at, batch_id, scope_json)
                   VALUES (?, ?, ?, 'backup', 'queued', ?, ?, ?, ?)""",
                (
                    job["id"],
                    dest["id"],
                    row["account"],
                    "Hata sonrası yeniden kuyruğa alındı.\n",
                    stamp,
                    batch_new,
                    row["scope_json"] if "scope_json" in row.keys() else None,
                ),
            )
            created += 1
        conn.commit()
        return {"ok": True, "queued": created}
    finally:
        conn.close()


def _perform_partial(run_id, hold):
    conn = connect()
    try:
        run = conn.execute("SELECT * FROM runs WHERE id=?", (run_id,)).fetchone()
        dest = conn.execute("SELECT * FROM destinations WHERE id=?", (run["destination_id"],)).fetchone()
    finally:
        conn.close()
    if dest is None or not run["remote_path"]:
        _finish(run_id, "failed", "Hedef veya uzak dosya yok.")
        return
    try:
        selection = json.loads(run["selection"] or "{}")
    except ValueError:
        selection = {}
    workdir = os.path.join(SPOOL, "partial-%s" % run_id)
    os.makedirs(workdir, 0o700)
    local_path = os.path.join(workdir, "archive.tar.gz")
    try:
        _note(run_id, "Seçilen parça için arşiv indiriliyor.")
        _download_with_retry(hold, dest, run["remote_path"], local_path)
        applied = apply_selection(local_path, run["account"], selection)
        label = "önizleme klasörüne" if selection.get("preview") else "canlı hesaba"
        _note(run_id, "Parçalar %s yazıldı: %s" % (label, ", ".join(applied)[:500]))
        _finish(run_id, "restored", None, size_bytes=os.path.getsize(local_path))
    except Exception as exc:
        _finish(run_id, "failed", str(exc))
        log_line("parça geri yükleme hata id=%s hata=%s" % (run_id, exc))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _owner_mail(account, status):
    if status not in ("uploaded", "failed"):
        return
    conn = connect()
    try:
        fail_on = get_setting(conn, "owner_fail_mail") == "1"
        ok_on = get_setting(conn, "owner_ok_mail") == "1"
    finally:
        conn.close()
    if status == "failed" and not fail_on:
        return
    if status == "uploaded" and not ok_on:
        return
    email = contact_email(account)
    if not email or _has_bad_chars(email) or " " in email:
        return
    if status == "uploaded":
        subject = "cPBackup yedek hazır"
        body = "Hesabınızın yedeği tamamlandı."
    else:
        subject = "cPBackup yedek hatası"
        body = "Hesabınızın yedeği tamamlanamadı. Ayrıntı için panele bakın."
    message = "To: %s\nSubject: %s\nContent-Type: text/plain; charset=UTF-8\n\n%s\n" % (email, subject, body)
    try:
        proc = subprocess.Popen(["/usr/sbin/sendmail", "-t"], stdin=subprocess.PIPE)
        proc.communicate(message.encode("utf-8"))
    except Exception as exc:
        log_line("hesap postası gönderilemedi: %s" % exc)


def _finish(run_id, status, error, remote_path=None, size_bytes=None):
    conn = connect()
    try:
        if error:
            _append_log(conn, run_id, error)
        fields = ["status=?", "finished_at=?", "error=?"]
        values = [status, now_text(), error]
        if remote_path is not None:
            fields.append("remote_path=?")
            values.append(remote_path)
        if size_bytes is not None:
            fields.append("size_bytes=?")
            values.append(int(size_bytes))
        values.append(run_id)
        conn.execute("UPDATE runs SET %s WHERE id=?" % ", ".join(fields), values)
        conn.commit()
        account = None
        kind = ""
        row = conn.execute("SELECT account, kind FROM runs WHERE id=?", (run_id,)).fetchone()
        if row is not None:
            account = row["account"]
            kind = row["kind"]
    finally:
        conn.close()
    if account and kind == "backup":
        _owner_mail(account, status)


def _note(run_id, text):
    if not text:
        return
    conn = connect()
    try:
        _append_log(conn, run_id, text)
        conn.commit()
    finally:
        conn.close()


def _append_log(conn, run_id, text):
    row = conn.execute("SELECT log FROM runs WHERE id=?", (run_id,)).fetchone()
    current = (row["log"] if row else "") or ""
    merged = (current + text.strip() + "\n")[-100000:]
    conn.execute("UPDATE runs SET log=? WHERE id=?", (merged, run_id))


def _notify(subject, body):
    conn = connect()
    try:
        email = (get_setting(conn, "notify_email") or "").strip()
    finally:
        conn.close()
    if not email:
        return
    message = "To: %s\nSubject: %s\nContent-Type: text/plain; charset=UTF-8\n\n%s\n" % (email, subject, body)
    try:
        proc = subprocess.Popen(["/usr/sbin/sendmail", "-t"], stdin=subprocess.PIPE)
        proc.communicate(message.encode("utf-8"))
    except Exception as exc:
        log_line("eposta gönderilemedi: %s" % exc)


def _destination_for_test(payload):
    dest_id = payload.get("id")
    stored = None
    if dest_id:
        conn = connect()
        try:
            stored = conn.execute(
                "SELECT * FROM destinations WHERE id=?",
                (_as_int(dest_id, "Kimlik", 1, 10 ** 9),),
            ).fetchone()
        finally:
            conn.close()
        if stored is None:
            raise ValueError("Hedef bulunamadı.")
    if not payload.get("host"):
        if stored is None:
            raise ValueError("Hedef bulunamadı.")
        return stored
    password = payload.get("password") or (stored["password"] if stored is not None else "")
    if not password:
        raise ValueError("Parola gerekli.")
    path = payload.get("path") or "/"
    if not str(path).startswith("/"):
        path = "/" + str(path)
    return {
        "host": _clean_text(payload.get("host"), "Sunucu", 255),
        "port": _as_int(payload.get("port") or 21, "Port", 1, 65535),
        "username": _clean_text(payload.get("username"), "Kullanıcı", 128),
        "password": password,
        "path": path,
        "passive": 1 if payload.get("passive", True) else 0,
        "tls": 1 if payload.get("tls") else 0,
    }


def _free_bytes(path):
    stats = os.statvfs(path)
    return int(stats.f_bavail * stats.f_frsize)


def _disk_ratio():
    total = 0
    used = 0
    seen = set()
    for path in ("/", "/home"):
        if not os.path.isdir(path):
            continue
        device = os.stat(path).st_dev
        if device in seen:
            continue
        seen.add(device)
        stats = os.statvfs(path)
        size = int(stats.f_blocks * stats.f_frsize)
        avail = int(stats.f_bavail * stats.f_frsize)
        total += size
        used += max(0, size - avail)
    percent = int(round((used * 100.0) / total)) if total else 0
    return total, used, percent


def _human_bytes(size):
    value = float(size or 0)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            if unit == "B":
                return "%d %s" % (int(value), unit)
            return "%.1f %s" % (value, unit)
        value /= 1024.0
    return "%s B" % size


def _trim(path, limit):
    try:
        if os.path.isfile(path) and os.path.getsize(path) > limit:
            with open(path, "rb") as handle:
                handle.seek(-limit // 2, os.SEEK_END)
                data = handle.read()
            with open(path, "wb") as handle:
                handle.write(data)
    except Exception:
        pass


def _clean_text(value, label, limit):
    text = str(value or "").strip()
    if not text:
        raise ValueError("%s gerekli." % label)
    if _has_bad_chars(text):
        raise ValueError("%s geçersiz karakter içeriyor." % label)
    if len(text) > limit:
        raise ValueError("%s çok uzun." % label)
    return text


def _has_bad_chars(value):
    return any(ord(char) < 32 for char in str(value))


_announced_stop = set()
_probe_quiet_until = {}


def _gb_to_bytes(value):
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        raise ValueError("Hesap boyutu sınırı sayı olmalı.")
    if number < 0 or number > 10000:
        raise ValueError("Hesap boyutu sınırı 0 ile 10000 GB arasında olmalı.")
    return int(number * _GB)


def _probe_destination(dest):
    try:
        if dest_kind(dest) == "ftp":
            store = open_store(dest, timeout=30)
            try:
                store.connect()
                store.client.probe()
            finally:
                store.close()
        else:
            store = open_store(dest, timeout=30)
            try:
                store.connect()
            finally:
                store.close()
    except Exception as exc:
        raise ValueError("Hedef hazır değil: %s" % exc)


def _probe_quiet(dest):
    key = dest["id"] if "id" in dest.keys() else dest["host"]
    now = time.time()
    if _probe_quiet_until.get(key, 0) > now:
        return False
    try:
        _probe_destination(dest)
        return True
    except Exception as exc:
        _probe_quiet_until[key] = now + 60
        log_line("hedef yoklanamadı id=%s %s" % (key, exc))
        return False


def _batch_stopped(conn, batch_id):
    if not batch_id:
        return False
    row = conn.execute("SELECT stop_requested FROM batches WHERE id=?", (batch_id,)).fetchone()
    return bool(row and row["stop_requested"])


def _note_stop(batch_id):
    if batch_id in _announced_stop:
        return
    _announced_stop.add(batch_id)
    log_line("durdurma: mevcut hesap bitti, kuyruk bekliyor batch=%s" % batch_id)


def _set_stage(run_id, stage):
    conn = connect()
    try:
        conn.execute("UPDATE runs SET status=?, stage=? WHERE id=?", (stage, stage, run_id))
        conn.commit()
    finally:
        conn.close()


def _remember_package(run_id, path):
    conn = connect()
    try:
        conn.execute(
            "UPDATE runs SET local_path=?, status='packaged', stage='packaged' WHERE id=?",
            (path, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _clear_local(run_id):
    conn = connect()
    try:
        conn.execute("UPDATE runs SET local_path=NULL, stage=NULL WHERE id=?", (run_id,))
        conn.commit()
    finally:
        conn.close()


def _park_upload(run_id, error):
    conn = connect()
    try:
        _append_log(conn, run_id, error)
        conn.execute(
            """UPDATE runs SET status='packaged', stage='packaged', finished_at=?, error=?
               WHERE id=?""",
            (now_text(), error, run_id),
        )
        conn.commit()
    finally:
        conn.close()


def _send_summaries():
    conn = connect()
    pending = []
    try:
        mail = get_setting(conn, "summary_mail") != "0"
        rows = conn.execute(
            """SELECT * FROM batches
               WHERE summary_sent=0 AND kind='backup'
                 AND EXISTS (SELECT 1 FROM runs WHERE runs.batch_id=batches.id)
                 AND NOT EXISTS (
                     SELECT 1 FROM runs
                     WHERE runs.batch_id=batches.id
                       AND runs.status IN ('queued','running','packaging','packaged','uploading')
                 )"""
        ).fetchall()
        for batch in rows:
            counts = conn.execute(
                """SELECT
                       SUM(CASE WHEN status='uploaded' THEN 1 ELSE 0 END) AS uploaded,
                       SUM(CASE WHEN status='failed' THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN status='skipped' THEN 1 ELSE 0 END) AS skipped
                   FROM runs WHERE batch_id=?""",
                (batch["id"],),
            ).fetchone()
            conn.execute("UPDATE batches SET summary_sent=1 WHERE id=?", (batch["id"],))
            if mail:
                pending.append((batch, counts))
        conn.commit()
    finally:
        conn.close()
    for batch, counts in pending:
        _notify(
            "cPBackup bitti: %s" % batch["title"],
            "%s\nBaşarılı: %s\nHata: %s\nAtlanan: %s\n"
            % (
                batch["title"],
                int(counts["uploaded"] or 0),
                int(counts["failed"] or 0),
                int(counts["skipped"] or 0),
            ),
        )


def _restore_allowed(conn, account):
    times = _setting_int(conn, "restore_times", 0, 0, 50)
    hours = _setting_int(conn, "restore_hours", 24, 1, 168)
    if times <= 0:
        return
    cutoff = (now_dt() - datetime.timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM runs WHERE account=? AND kind='restore' AND created_at>=?",
        (account, cutoff),
    ).fetchone()["c"]
    if count >= times:
        raise ValueError("Bu hesap %s saat içinde %s kez geri yüklenebilir." % (hours, times))


def _prune_history():
    conn = connect()
    try:
        days = _setting_int(conn, "history_days", 90, 0, 3650)
        if days <= 0:
            return 0
        cutoff = (now_dt() - datetime.timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        cur = conn.execute(
            """DELETE FROM runs
               WHERE status NOT IN ('queued','running','packaging','packaged','uploading')
                 AND COALESCE(finished_at, created_at) < ?""",
            (cutoff,),
        )
        conn.commit()
        return cur.rowcount
    finally:
        conn.close()


def _gap_seconds():
    conn = connect()
    try:
        return _setting_int(conn, "account_gap", 2, 0, 120)
    finally:
        conn.close()


def _priority_prefix():
    conn = connect()
    try:
        nice = _setting_int(conn, "nice_level", 10, 0, 19)
        ionice = _setting_int(conn, "ionice_level", 7, 0, 7)
    finally:
        conn.close()
    return ["nice", "-n", str(nice), "ionice", "-c", "2", "-n", str(ionice)]


def _setting_int(conn, key, default, low, high):
    raw = get_setting(conn, key)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        number = int(float(raw))
    except (TypeError, ValueError):
        return default
    return max(low, min(high, number))


def _as_int(value, label, low, high):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError("%s sayı olmalı." % label)
    if number < low or number > high:
        raise ValueError("%s aralık dışında." % label)
    return number


def _valid_user(user):
    if not user or len(user) > 32:
        return False
    for char in user:
        if not (char.isalnum() or char == "_"):
            return False
    return True

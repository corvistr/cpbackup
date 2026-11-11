# -*- coding: utf-8 -*-
"""JetBackup hesap parçaları. Hepsi açıkken bugünkü pkgacct komutu değişmez."""

CONFIG = 1 << 0
HOMEDIR = 1 << 1
DATABASES = 1 << 2
EMAILS = 1 << 3
CRON = 1 << 4
DOMAINS = 1 << 5
CERTS = 1 << 6
DB_USERS = 1 << 7
FTP = 1 << 8
FULL = CONFIG | HOMEDIR | DATABASES | EMAILS | CRON | DOMAINS | CERTS | DB_USERS | FTP

LABELS = (
    (CONFIG, "Panel yapılandırması"),
    (HOMEDIR, "Ana dizin dosyaları"),
    (DATABASES, "Veritabanları"),
    (DB_USERS, "Veritabanı kullanıcıları"),
    (EMAILS, "E-posta hesapları"),
    (FTP, "FTP hesapları"),
    (CRON, "Cron işleri"),
    (DOMAINS, "Alan adları"),
    (CERTS, "SSL sertifikaları"),
)


def _cell(row, key, default=None):
    try:
        value = row[key]
    except (KeyError, IndexError, TypeError):
        return default
    return default if value is None else value


def effective_contains(job):
    raw = _cell(job, "contains", None)
    if raw is not None and str(raw) != "":
        return int(raw) & FULL
    value = CONFIG | CRON | CERTS | FTP
    if int(_cell(job, "include_homedir", 1)):
        value |= HOMEDIR | EMAILS
    if int(_cell(job, "include_db", 1)):
        value |= DATABASES | DB_USERS
    if int(_cell(job, "include_dns", 1)):
        value |= DOMAINS
    if int(_cell(job, "include_mailconfig", 1)):
        value |= EMAILS
    return value


def email_contents_on(job):
    return int(_cell(job, "email_contents", 1)) != 0


def junk_excluded(job):
    return int(_cell(job, "exclude_junk", 0)) != 0


def excluded_databases(job):
    import json
    raw = _cell(job, "exclude_databases", "[]") or "[]"
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    names = []
    for item in data:
        name = str(item or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def is_legacy_scope(job):
    return (
        effective_contains(job) == FULL
        and email_contents_on(job)
        and not junk_excluded(job)
        and not excluded_databases(job)
    )


def tag_for(contains):
    if contains == FULL:
        return ""
    if contains == DATABASES or contains == (DATABASES | DB_USERS):
        return "db"
    if contains == EMAILS:
        return "mail"
    if contains == HOMEDIR:
        return "files"
    return "c%x" % (contains & FULL)


def archive_name(account, contains, stamp, run_id):
    tag = tag_for(contains)
    if not tag:
        return "cpmove-%s-%s-%s.tar.gz" % (account, stamp, run_id)
    return "cpmove-%s-%s-%s-%s.tar.gz" % (account, tag, stamp, run_id)


def group_tag(account, name):
    prefix = "cpmove-%s-" % account
    if not name.startswith(prefix) or not name.endswith(".tar.gz"):
        return None
    rest = name[len(prefix):-7]
    head = rest.split("-", 1)[0]
    if len(head) == 14 and head.isdigit():
        return "full"
    return head or "full"


def pkgacct_skip_args(job):
    """Ek --skip bayrakları. Eski tam paket yolunda boş döner; çağıran eski komutu kurar."""
    if is_legacy_scope(job) and int(_cell(job, "include_homedir", 1)) and int(_cell(job, "include_db", 1)) and int(_cell(job, "include_dns", 1)) and int(_cell(job, "include_mailconfig", 1)):
        args = []
        if int(_cell(job, "skip_logs", 1)):
            args.append("--skiplogs")
        return args
    contains = effective_contains(job)
    args = []
    if int(_cell(job, "skip_logs", 1)):
        args.append("--skiplogs")
    if not (contains & CONFIG):
        args.append("--skipuserdata")
    if not (contains & HOMEDIR):
        args.append("--skiphomedir")
    if not (contains & DATABASES) and not (contains & DB_USERS):
        args.extend(["--skipmysql", "--skippgsql"])
    if not (contains & EMAILS):
        args.extend(["--skipmail", "--skipmailconfig", "--skipmailman"])
    elif not email_contents_on(job):
        args.append("--skipmail")
    if not (contains & FTP):
        args.append("--skipftpusers")
    if not (contains & CRON):
        args.append("--skipcron")
    if not (contains & DOMAINS):
        args.extend(["--skipdnszones", "--skipdomains"])
    if not (contains & CERTS):
        args.append("--skipssl")
    return args


def needs_repack(job):
    contains = effective_contains(job)
    if excluded_databases(job):
        return True
    if junk_excluded(job) and (contains & EMAILS) and email_contents_on(job):
        return True
    if not (contains & DATABASES) and (contains & DB_USERS):
        return True
    return False


def member_skipped(name, job):
    lowered = name.replace("\\", "/").lower()
    contains = effective_contains(job)
    if not (contains & DATABASES) and (contains & DB_USERS):
        if "/mysql/" in "/" + lowered and lowered.endswith(".sql") and not lowered.endswith("/mysql.sql"):
            return True
    for db_name in excluded_databases(job):
        needle = "/mysql/%s.sql" % db_name.lower()
        if needle in "/" + lowered:
            return True
    if junk_excluded(job):
        parts = [part for part in lowered.split("/") if part]
        junk = {"trash", "spam", "junk", ".trash", ".spam", ".junk", ".drafts", "drafts"}
        if "mail" in parts and any(part in junk for part in parts):
            return True
    return False

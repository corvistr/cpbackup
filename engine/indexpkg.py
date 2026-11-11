# -*- coding: utf-8 -*-
import os
import re
import tarfile

_MAILBOX = re.compile(r"(?:^|/)homedir/mail/([^/]+)/([^/]+)(?:/|$)", re.IGNORECASE)
_DB = re.compile(r"(?:^|/)mysql/([^/]+)\.sql$", re.IGNORECASE)


def _rel(name):
    text = name.replace("\\", "/").lstrip("./")
    if text.startswith("cpmove-"):
        parts = text.split("/", 1)
        text = parts[1] if len(parts) == 2 else ""
    return text


def list_members(path):
    mode = "r:gz" if path.endswith(".gz") else "r:"
    with tarfile.open(path, mode) as archive:
        for member in archive:
            yield member


def build_rows(path):
    rows = []
    mailboxes = {}
    for member in list_members(path):
        rel = _rel(member.name)
        if not rel or rel.startswith("/") or ".." in rel.split("/"):
            continue
        db_match = _DB.search(rel)
        if db_match and member.isfile():
            rows.append(("database", rel, int(member.size or 0)))
            continue
        mail_match = _MAILBOX.search(rel)
        if mail_match:
            key = "%s/%s" % (mail_match.group(1), mail_match.group(2))
            current = mailboxes.get(key, 0)
            if member.isfile():
                current += int(member.size or 0)
            mailboxes[key] = current
            continue
        kind = "dir" if member.isdir() else "file"
        rows.append((kind, rel, int(member.size or 0)))
    for key, size in sorted(mailboxes.items()):
        rows.append(("mailbox", "homedir/mail/" + key, size))
    return rows


def repack_skipping(path, skip_fn):
    temporary = path + ".repack"
    mode = "r:gz" if path.endswith(".gz") else "r:"
    with tarfile.open(path, mode) as source, tarfile.open(temporary, "w:gz") as target:
        for member in source:
            if skip_fn(member.name):
                continue
            if member.isfile():
                handle = source.extractfile(member)
                target.addfile(member, handle)
            else:
                target.addfile(member)
    os.replace(temporary, path)

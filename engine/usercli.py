#!/usr/bin/python3
# -*- coding: utf-8 -*-
import json
import os
import sys

os.umask(0o077)
sys.path.insert(0, "/opt/cpbackup")

from engine.service import delete_own, enqueue_own, enqueue_partial, list_backup_entries, list_own, log_own, restore_own
from engine.partialrest import account_home


def main():
    if os.geteuid() != 0:
        _fail("yetkisiz")
    if len(sys.argv) < 3:
        _fail("eksik istek")
    action = sys.argv[1]
    account = sys.argv[2]
    try:
        if action == "list":
            payload = list_own(account)
        elif action == "log":
            payload = log_own(account, sys.argv[3])
        elif action == "restore":
            payload = restore_own(account, sys.argv[3], sys.argv[4])
        elif action == "delete":
            payload = delete_own(account, sys.argv[3])
        elif action == "backup":
            body = _request_body(account)
            payload = enqueue_own(
                account,
                body.get("contains"),
                body.get("email_contents"),
                body.get("exclude_junk"),
                body.get("exclude_databases"),
            )
        elif action == "entries":
            _own_backup(account, sys.argv[3])
            payload = list_backup_entries(sys.argv[3], index=False)
        elif action == "partial":
            body = _request_body(account)
            _own_backup(account, body.get("id"))
            payload = enqueue_partial(body.get("id"), body.get("confirm"), body.get("preview"), body.get("items") or [])
        else:
            _fail("bilinmeyen işlem")
            return
    except ValueError as exc:
        _fail(str(exc))
        return
    except Exception:
        _fail("İşlem tamamlanamadı.")
        return
    _write(payload)


def _write(payload):
    sys.stdout.buffer.write(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    sys.stdout.buffer.flush()


def _request_body(account):
    import json
    import os
    path = os.path.join(account_home(account), ".cpbackup-request")
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.loads(handle.read() or "{}")
    except ValueError:
        data = {}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    return data if isinstance(data, dict) else {}


def _own_backup(account, run_id):
    from engine.db import connect
    from engine.service import _as_int
    run_id = _as_int(run_id, "Kimlik", 1, 10 ** 9)
    conn = connect()
    try:
        row = conn.execute("SELECT account FROM runs WHERE id=?", (run_id,)).fetchone()
    finally:
        conn.close()
    if row is None or row["account"] != account:
        _fail("Yedek bulunamadı.")


def _fail(message):
    _write({"ok": False, "error": message})
    raise SystemExit(0)


if __name__ == "__main__":
    main()

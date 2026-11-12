# -*- coding: utf-8 -*-
import json
import os
import sys
import traceback
from urllib.parse import parse_qs

from engine.guard import browser_request, mutation_allowed, root_session, security_headers
from engine.service import log_line
from engine.service import (
    delete_batch_remote,
    delete_destination,
    delete_job,
    delete_remote,
    batch_detail,
    account_backups,
    account_directory,
    backup_download_info,
    destination_auth_url,
    destination_exchange,
    finish_oauth,
    enqueue_job,
    enqueue_partial,
    enqueue_restore,
    list_backup_entries,
    list_accounts,
    list_batches,
    list_destinations,
    list_jobs,
    list_runs,
    run_log,
    save_destination,
    save_job,
    retry_failed,
    save_settings,
    set_batch_stop,
    set_run_lock,
    status_payload,
    test_destination,
)
from engine.stores import open_store


def main():
    try:
        params = parse_qs(os.environ.get("QUERY_STRING") or "", keep_blank_values=False)
        action = (params.get("action") or ["status"])[0]
        if action == "destination.oauth":
            _oauth_return(params)
            return
        if not root_session() or not browser_request():
            _send({"ok": False, "error": "Bu işlem yalnızca root WHM oturumuyla yapılabilir."}, 403)
            return
        if action == "backup.download":
            _stream_download((params.get("id") or [None])[0])
            return
        if not mutation_allowed(action):
            _send({"ok": False, "error": "Bu işlem POST ile yapılmalıdır."}, 405)
            return
        payload = _body()
        result = _dispatch(action, payload, params)
        if not isinstance(result, dict) or "ok" not in result:
            result = {"ok": True, "data": result}
        _send(result)
    except ValueError as exc:
        _send({"ok": False, "error": str(exc)}, 400)
    except Exception as exc:
        sys.stderr.write(traceback.format_exc())
        log_line("api hata: %s" % exc)
        _send({"ok": False, "error": "İşlem tamamlanamadı."}, 500)


def _dispatch(action, payload, params):
    if action == "status":
        return status_payload()
    if action == "destinations":
        return list_destinations()
    if action == "destination.save":
        return save_destination(payload)
    if action == "destination.delete":
        delete_destination(payload.get("id"))
        return {"ok": True}
    if action == "destination.test":
        return test_destination(payload)
    if action == "destination.auth_url":
        return destination_auth_url(payload)
    if action == "destination.exchange":
        return destination_exchange(payload)
    if action == "accounts":
        return list_accounts(force=True)
    if action == "accounts.directory":
        return account_directory()
    if action == "account.backups":
        return account_backups((params.get("user") or [""])[0], (params.get("limit") or [8])[0])
    if action == "jobs":
        return list_jobs()
    if action == "job.save":
        return save_job(payload)
    if action == "job.delete":
        delete_job(payload.get("id"))
        return {"ok": True}
    if action == "job.run":
        return enqueue_job(payload.get("id"))
    if action == "runs":
        limit = (params.get("limit") or [100])[0]
        offset = (params.get("offset") or [0])[0]
        return list_runs(limit, offset)
    if action == "batches":
        limit = (params.get("limit") or [50])[0]
        offset = (params.get("offset") or [0])[0]
        query = (params.get("q") or [""])[0]
        return list_batches(limit, offset, query)
    if action == "batch":
        return batch_detail((params.get("id") or [None])[0])
    if action == "batch.stop":
        return set_batch_stop(payload.get("id"), payload.get("stop"))
    if action == "batch.delete_remote":
        return delete_batch_remote(payload.get("id"), payload.get("confirm"), payload.get("sure"))
    if action == "run.log":
        return run_log(payload.get("id") or (params.get("id") or [None])[0])
    if action == "run.delete_remote":
        return delete_remote(payload.get("id"))
    if action == "restore":
        return enqueue_restore(payload.get("id"), payload.get("confirm"), payload.get("force"))
    if action == "restore.partial":
        return enqueue_partial(payload.get("id"), payload.get("confirm"), payload.get("preview"), payload.get("items") or [])
    if action == "backup.entries":
        return list_backup_entries((params.get("id") or [None])[0], (params.get("kind") or [""])[0], (params.get("q") or [""])[0])
    if action == "run.lock":
        return set_run_lock(payload.get("id"), payload.get("locked"))
    if action == "batch.retry_failed":
        return retry_failed(payload.get("id"))
    if action == "settings.save":
        return save_settings(payload)
    raise ValueError("Bilinmeyen işlem.")


def _oauth_return(params):
    if not root_session():
        _page("WHM oturumu gelmedi. Panele root olarak girip yeniden bağlan.")
        return
    if (params.get("error") or [""])[0]:
        _page("Hesap bağlanmayı reddetti.")
        return
    try:
        finish_oauth((params.get("code") or [""])[0], (params.get("state") or [""])[0])
    except ValueError as exc:
        _page(str(exc))
        return
    _page("Hesap bağlandı. Yedekler bu panele döndü.", ok=True)


def _page(message, ok=False):
    safe = (message.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    color = "#166534" if ok else "#991b1b"
    body = (
        "<!doctype html><html lang=\"tr\"><head><meta charset=\"utf-8\"><title>cPBackup</title></head>"
        "<body style=\"font-family:sans-serif;padding:2rem\">"
        "<p style=\"color:%s\">%s</p>"
        "<p><a href=\"/cgi/cpbackup/index.cgi\">Panele dön</a></p>"
        "</body></html>"
    ) % (color, safe)
    data = body.encode("utf-8")
    header = (
        "Status: 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Content-Length: %s\r\n"
        "%s"
        "\r\n"
    ) % (len(data), security_headers())
    sys.stdout.buffer.write(header.encode("ascii"))
    sys.stdout.buffer.write(data)


def _stream_download(run_id):
    info = backup_download_info(run_id)
    client = open_store(info["destination"], timeout=600)
    client.connect()
    header = (
        "Status: 200 OK\r\n"
        "Content-Type: application/octet-stream\r\n"
        "Content-Disposition: attachment; filename=\"%s\"\r\n"
        "Cache-Control: no-store\r\n"
        "X-Content-Type-Options: nosniff\r\n"
        "\r\n"
    ) % info["filename"]
    sys.stdout.buffer.write(header.encode("ascii"))
    sys.stdout.buffer.flush()
    log_line("yedek indiriliyor dosya=%s" % info["filename"])
    try:
        client.retr_to(info["remote_path"], sys.stdout.buffer)
    except Exception as exc:
        log_line("indirme koptu dosya=%s hata=%s" % (info["filename"], exc))
    finally:
        client.close()


def _body():
    length = int(os.environ.get("CONTENT_LENGTH") or 0)
    if length <= 0:
        return {}
    if length > 1000000:
        raise ValueError("İstek çok büyük.")
    raw = sys.stdin.buffer.read(length).decode("utf-8", "replace")
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("JSON okunamadı.")
    if not isinstance(data, dict):
        raise ValueError("İstek gövdesi nesne olmalı.")
    return data


def _send(payload, code=200):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    reason = {200: "OK", 400: "Bad Request", 403: "Forbidden", 405: "Method Not Allowed", 500: "Error"}.get(code, "OK")
    header = (
        "Status: %s %s\r\n"
        "Content-Type: application/json; charset=utf-8\r\n"
        "Content-Length: %s\r\n"
        "%s"
        "\r\n"
    ) % (code, reason, len(body), security_headers())
    sys.stdout.buffer.write(header.encode("ascii"))
    sys.stdout.buffer.write(body)

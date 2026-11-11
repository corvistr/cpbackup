# -*- coding: utf-8 -*-
import os

_MUTATIONS = {
    "destination.save",
    "destination.delete",
    "destination.test",
    "destination.auth_url",
    "destination.exchange",
    "restore.partial",
    "run.lock",
    "batch.retry_failed",
    "job.save",
    "job.delete",
    "job.run",
    "batch.stop",
    "batch.delete_remote",
    "run.delete_remote",
    "restore",
    "settings.save",
}


def root_session():
    if os.geteuid() != 0:
        return False
    return os.environ.get("REMOTE_USER") == "root"


def browser_request():
    return os.environ.get("HTTP_X_CPBACKUP") == "1"


def mutation_allowed(action):
    if action not in _MUTATIONS:
        return True
    return os.environ.get("REQUEST_METHOD", "GET").upper() == "POST"


def security_headers():
    return (
        "X-Content-Type-Options: nosniff\r\n"
        "X-Frame-Options: SAMEORIGIN\r\n"
        "Referrer-Policy: same-origin\r\n"
        "Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'\r\n"
        "Cache-Control: no-store\r\n"
    )

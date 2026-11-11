#!/usr/bin/python3
# -*- coding: utf-8 -*-
import os
import sys

sys.path.insert(0, "/opt/cpbackup")

from urllib.parse import parse_qs

from engine.config import UI_DIST
from engine.guard import root_session, security_headers
from engine.publish import publish_assets

_MIMES = {
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".map": "application/json; charset=utf-8",
    ".woff2": "font/woff2",
    ".png": "image/png",
}


def main():
    if not root_session():
        sys.stdout.buffer.write(
            b"Status: 403 Forbidden\r\nContent-Type: text/plain; charset=utf-8\r\nX-Content-Type-Options: nosniff\r\n\r\nYetkisiz\n"
        )
        return
    params = parse_qs(os.environ.get("QUERY_STRING") or "")
    asset = (params.get("asset") or [""])[0]
    if asset:
        _asset(asset)
        return
    _index()


def _index():
    try:
        publish_assets()
    except OSError:
        pass
    path = os.path.join(UI_DIST, "index.html")
    if not os.path.isfile(path):
        sys.stdout.buffer.write(b"Status: 503 Error\r\nContent-Type: text/plain; charset=utf-8\r\n\r\nArayuz henuz derlenmedi.\n")
        return
    with open(path, "r", encoding="utf-8") as handle:
        html = handle.read()
    html = html.replace("./assets/", "../../cpbackup/assets/")
    html = html.replace('src="assets/', 'src="../../cpbackup/assets/')
    html = html.replace('href="assets/', 'href="../../cpbackup/assets/')
    body = html.encode("utf-8")
    header = (
        "Status: 200 OK\r\n"
        "Content-Type: text/html; charset=utf-8\r\n"
        "Content-Length: %s\r\n"
        "%s\r\n"
    ) % (len(body), security_headers())
    sys.stdout.buffer.write(header.encode("ascii"))
    sys.stdout.buffer.write(body)


def _asset(name):
    if not name or "/" in name or "\\" in name or ".." in name:
        sys.stdout.buffer.write(b"Status: 404 Not Found\r\nContent-Type: text/plain\r\n\r\n")
        return
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
    if any(char not in allowed for char in name):
        sys.stdout.buffer.write(b"Status: 404 Not Found\r\nContent-Type: text/plain\r\n\r\n")
        return
    path = os.path.join(UI_DIST, "assets", name)
    if not os.path.isfile(path):
        sys.stdout.buffer.write(b"Status: 404 Not Found\r\nContent-Type: text/plain\r\n\r\n")
        return
    ext = os.path.splitext(name)[1].lower()
    mime = _MIMES.get(ext, "application/octet-stream")
    with open(path, "rb") as handle:
        data = handle.read()
    header = (
        "Status: 200 OK\r\nContent-Type: %s\r\nContent-Length: %s\r\nCache-Control: public, max-age=86400\r\n\r\n"
        % (mime, len(data))
    )
    sys.stdout.buffer.write(header.encode("ascii"))
    sys.stdout.buffer.write(data)


if __name__ == "__main__":
    main()

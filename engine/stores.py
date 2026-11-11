# -*- coding: utf-8 -*-
"""Hedef sürücüleri. FTP yolu FtpClient ile aynı uzak yolu üretir."""
import hashlib
import hmac
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from xml.etree import ElementTree

from engine.ftpclient import FTPError, from_destination
from engine.secret import reveal, seal


class StoreError(FTPError):
    def __init__(self, message, status=None, retryable=False, body=b""):
        FTPError.__init__(self, message)
        self.status = status
        self.retryable = bool(retryable)
        self.body = body or b""


_MB = 1024 * 1024
_CHUNK = 8 * _MB
_S3_MAX_PARTS = 9000
# Microsoft Graph upload sessions require fragments in multiples of 320 KiB.
_ONEDRIVE_CHUNK = 320 * 1024 * 32
_RETRY_CODES = (429, 500, 502, 503, 504)
_NET_ERRORS = (OSError, http.client.HTTPException)


def dest_kind(row):
    try:
        kind = row["kind"]
    except (KeyError, IndexError, TypeError):
        kind = None
    text = str(kind or "ftp").strip().lower()
    if text in ("ftp", "s3", "s3compat", "gdrive", "dropbox", "onedrive"):
        return text
    return "ftp"


def extra_of(row):
    try:
        raw = row["extra"]
    except (KeyError, IndexError, TypeError):
        raw = "{}"
    try:
        data = json.loads(raw or "{}")
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


def public_extra(row):
    data = extra_of(row)
    refresh = str(data.get("refresh") or "")
    return {
        "region": data.get("region") or "",
        "prefix": data.get("prefix") or "",
        "has_refresh": bool(refresh),
    }


def open_store(dest, timeout=600):
    kind = dest_kind(dest)
    if kind == "ftp":
        return FtpStore(dest, timeout)
    if kind in ("s3", "s3compat"):
        return S3Store(dest, timeout)
    if kind == "gdrive":
        return GoogleDriveStore(dest, timeout)
    if kind == "dropbox":
        return DropboxStore(dest, timeout)
    if kind == "onedrive":
        return OneDriveStore(dest, timeout)
    raise StoreError("Hedef türü desteklenmiyor.")


def auth_url(kind, client_id, redirect, state):
    client_id = str(client_id or "").strip()
    if not client_id:
        raise StoreError("İstemci kimliği gerekli.")
    if kind == "gdrive":
        query = urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": "https://www.googleapis.com/auth/drive.file",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        })
        return "https://accounts.google.com/o/oauth2/v2/auth?" + query
    if kind == "dropbox":
        query = urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "token_access_type": "offline",
            "state": state,
        })
        return "https://www.dropbox.com/oauth2/authorize?" + query
    if kind == "onedrive":
        query = urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect,
            "response_type": "code",
            "scope": "offline_access Files.ReadWrite",
            "state": state,
        })
        return "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?" + query
    raise StoreError("Bu hedef türünde bağlanma adımı yok.")


_TOKEN_URLS = {
    "gdrive": "https://oauth2.googleapis.com/token",
    "dropbox": "https://api.dropboxapi.com/oauth2/token",
    "onedrive": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
}


def exchange_code(kind, client_id, client_secret, code, redirect):
    code = str(code or "").strip()
    if not code:
        raise StoreError("Yetki kodu gerekli.")
    if kind not in _TOKEN_URLS:
        raise StoreError("Bu hedef türünde yetki kodu yok.")
    payload = _form(_TOKEN_URLS[kind], {
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    })
    refresh = payload.get("refresh_token") or ""
    if not refresh:
        raise StoreError("Sağlayıcı yenileme jetonu vermedi. Bağlanırken çevrimdışı erişimi onaylayın.")
    return refresh


def _refresh(kind, client_id, client_secret, refresh):
    if kind not in _TOKEN_URLS:
        raise StoreError("Jeton yenilenemedi.")
    payload = _form(_TOKEN_URLS[kind], {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh,
        "grant_type": "refresh_token",
    })
    token = payload.get("access_token")
    if not token:
        raise StoreError("Erişim jetonu alınamadı. Hedefi yeniden bağlayın.")
    try:
        expires_in = int(payload.get("expires_in") or 3600)
    except (TypeError, ValueError):
        expires_in = 3600
    return token, expires_in, str(payload.get("refresh_token") or "")


def _persist_refresh(dest_id, refresh):
    if not dest_id:
        return
    try:
        from engine.db import connect
        conn = connect()
        try:
            row = conn.execute("SELECT extra FROM destinations WHERE id=?", (dest_id,)).fetchone()
            if row is None:
                return
            data = extra_of(row)
            data["refresh"] = seal(refresh)
            conn.execute("UPDATE destinations SET extra=? WHERE id=?", (json.dumps(data), dest_id))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        return


def _http_error(label, exc):
    try:
        body = exc.read()[:2000]
    except Exception:
        body = b""
    return StoreError(
        "%s yanıtı %s." % (label, exc.code),
        status=exc.code,
        retryable=exc.code in _RETRY_CODES,
        body=body,
    )


def _open(request, timeout, label):
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise _http_error(label, exc) from None
    except _NET_ERRORS as exc:
        raise StoreError("%s bağlantısı kurulamadı." % label, retryable=True) from exc


def _read_all(response, label):
    try:
        return response.read()
    except _NET_ERRORS as exc:
        raise StoreError("%s yanıtı yarıda kesildi." % label, retryable=True) from exc
    finally:
        response.close()


def _copy(response, handle, label):
    try:
        while True:
            chunk = response.read(_CHUNK)
            if not chunk:
                break
            handle.write(chunk)
    except _NET_ERRORS as exc:
        raise StoreError("%s indirmesi yarıda kesildi." % label, retryable=True) from exc
    finally:
        response.close()


def _parse_json(raw):
    if not raw:
        return {}
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return {"raw": raw}


def _form(url, fields):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    request.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        response = urllib.request.urlopen(request, timeout=60)
    except urllib.error.HTTPError as exc:
        raise StoreError(
            "Yetki doğrulanamadı.", status=exc.code, retryable=exc.code in _RETRY_CODES,
        ) from None
    except _NET_ERRORS as exc:
        raise StoreError("Yetki servisine ulaşılamadı.", retryable=True) from exc
    payload = _parse_json(_read_all(response, "Yetki servisi"))
    return payload if isinstance(payload, dict) else {}


def _json_request(url, method, token, body=None, headers=None, label="Bulut"):
    data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode("utf-8"))
    request = urllib.request.Request(url, data=data, method=method)
    if token:
        request.add_header("Authorization", "Bearer " + token)
    if body is not None and not isinstance(body, bytes):
        request.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        request.add_header(key, value)
    return _parse_json(_read_all(_open(request, 120, label), label))


class FtpStore(object):
    def __init__(self, dest, timeout):
        self.client = from_destination(dest, timeout=timeout)

    def connect(self):
        self.client.connect()

    def close(self):
        self.client.close()

    def ping(self):
        self.client.ftp.voidcmd("NOOP")

    def ensure_base(self):
        self.client.ensure_base()

    def upload(self, local_path, account, remote_name, folder=None):
        return self.client.upload(local_path, account, remote_name, folder)

    def remote_size(self, remote_path):
        return self.client.remote_size(remote_path)

    def list_names(self, account):
        return self.client.list_names(account)

    def delete_file(self, remote_path):
        self.client.delete_file(remote_path)

    def delete_named(self, account, name):
        remote = self.client.base.rstrip("/") + "/cpbackup/" + account + "/" + name
        self.client.delete_file(remote)

    def download(self, remote_path, local_path):
        self.client.download(remote_path, local_path)

    def retr_to(self, remote_path, handle):
        self.client.retr_to(remote_path, handle)


class S3Store(object):
    def __init__(self, dest, timeout):
        self.timeout = int(timeout)
        self.kind = dest_kind(dest)
        self.access = dest["username"]
        self.secret = reveal(dest["password"])
        data = extra_of(dest)
        self.region = str(data.get("region") or "us-east-1")
        self.prefix = str(data.get("prefix") or "cpbackup").strip("/")
        self.bucket = str(dest["path"] or "").strip().strip("/")
        if not self.bucket:
            raise StoreError("Kova adı gerekli.")
        host = str(dest["host"] or "").strip()
        if self.kind == "s3" and (not host or host == "s3.amazonaws.com"):
            self.endpoint = "s3.%s.amazonaws.com" % self.region
            self.path_style = False
        else:
            self.endpoint = host or "s3.amazonaws.com"
            self.path_style = True

    def connect(self):
        self.ensure_base()

    def close(self):
        return None

    def ping(self):
        self._request("HEAD", self.bucket, "")

    def ensure_base(self):
        self._request("HEAD", self.bucket, "")

    def upload(self, local_path, account, remote_name, folder=None):
        key = self._key(account, remote_name, folder)
        size = os.path.getsize(local_path)
        if size <= _CHUNK:
            with open(local_path, "rb") as handle:
                self._request("PUT", self.bucket, key, body=handle.read())
        else:
            self._multipart(key, local_path, size)
        return self._remote(key)

    def remote_size(self, remote_path):
        key = self._key_from_remote(remote_path)
        try:
            status, headers, _body = self._raw("HEAD", self.bucket, key)
        except StoreError:
            return None
        if status >= 300:
            return None
        try:
            return int(headers.get("Content-Length") or headers.get("content-length") or 0)
        except ValueError:
            return None

    def list_names(self, account):
        prefix = self._key(account, "", None).rstrip("/") + "/"
        names = []
        token = ""
        while True:
            query = {"list-type": "2", "prefix": prefix}
            if token:
                query["continuation-token"] = token
            _status, _headers, body = self._raw("GET", self.bucket, "", query=query)
            root = _xml(body)
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}", 1)[0] + "}"
            for item in root.findall(ns + "Contents"):
                key = (item.findtext(ns + "Key") or "")
                if key.startswith(prefix):
                    name = key[len(prefix):]
                    if name and "/" not in name:
                        names.append(name)
            if (root.findtext(ns + "IsTruncated") or "").lower() != "true":
                break
            token = root.findtext(ns + "NextContinuationToken") or ""
            if not token:
                break
        return names

    def delete_file(self, remote_path):
        key = self._key_from_remote(remote_path)
        self._request("DELETE", self.bucket, key)

    def delete_named(self, account, name):
        self.delete_file(self._remote(self._key(account, name, None)))

    def download(self, remote_path, local_path):
        with open(local_path, "wb") as handle:
            self.retr_to(remote_path, handle)

    def retr_to(self, remote_path, handle):
        key = self._key_from_remote(remote_path)
        _status, _headers, response = self._raw("GET", self.bucket, key, stream=True)
        _copy(response, handle, "S3")

    def _multipart(self, key, local_path, size):
        _status, _headers, body = self._raw("POST", self.bucket, key, query={"uploads": ""})
        upload_id = ""
        for item in _xml(body).iter():
            if item.tag.endswith("UploadId"):
                upload_id = item.text or ""
        if not upload_id:
            raise StoreError("Parçalı yükleme başlatılamadı.")
        part_size = _s3_part_size(size)
        try:
            parts = []
            number = 1
            with open(local_path, "rb") as handle:
                while True:
                    chunk = handle.read(part_size)
                    if not chunk:
                        break
                    _part_status, part_headers, _part_body = self._raw(
                        "PUT", self.bucket, key, body=chunk, query={"partNumber": str(number), "uploadId": upload_id},
                    )
                    etag = part_headers.get("ETag") or part_headers.get("etag") or ""
                    if not etag:
                        raise StoreError("Parça yüklenemedi.", retryable=True)
                    parts.append((number, etag))
                    number += 1
            xml = ["<CompleteMultipartUpload>"]
            for part_number, etag in parts:
                xml.append("<Part><PartNumber>%s</PartNumber><ETag>%s</ETag></Part>" % (part_number, etag))
            xml.append("</CompleteMultipartUpload>")
            done = self._request(
                "POST", self.bucket, key,
                body="".join(xml).encode("utf-8"),
                query={"uploadId": upload_id},
                content_type="application/xml",
            )
            if b"<Error>" in done:
                raise StoreError("Parçalı yükleme tamamlanamadı.", retryable=True)
        except Exception:
            try:
                self._raw("DELETE", self.bucket, key, query={"uploadId": upload_id})
            except Exception:
                pass
            raise

    def _key(self, account, name, folder):
        parts = [self.prefix]
        if folder:
            parts.append(folder)
        parts.append(account)
        if name:
            parts.append(name)
        return "/".join(part.strip("/") for part in parts if part)

    def _remote(self, key):
        return "s3:%s/%s" % (self.bucket, key)

    def _key_from_remote(self, remote_path):
        text = str(remote_path or "")
        marker = "s3:%s/" % self.bucket
        if text.startswith(marker):
            return text[len(marker):]
        if text.startswith("s3:"):
            rest = text[3:]
            if "/" in rest:
                return rest.split("/", 1)[1]
        return text.lstrip("/")

    def _request(self, method, bucket, key, body=b"", query=None, content_type="application/octet-stream"):
        status, _headers, payload = self._raw(method, bucket, key, body, query, content_type)
        if status >= 300:
            raise StoreError("S3 yanıtı %s." % status, status=status, retryable=status in _RETRY_CODES)
        return payload

    def _raw(self, method, bucket, key, body=b"", query=None, content_type="application/octet-stream", stream=False):
        if body is None:
            body = b""
        payload_hash = hashlib.sha256(body).hexdigest()
        now = datetime.now(timezone.utc)
        amz_date = now.strftime("%Y%m%dT%H%M%SZ")
        day = now.strftime("%Y%m%d")
        if self.path_style:
            host = self.endpoint
            canonical_uri = _s3_path(bucket, key)
        else:
            host = "%s.%s" % (bucket, self.endpoint)
            canonical_uri = _s3_path(key)
        canonical_qs = ""
        if query:
            pairs = []
            for name, value in sorted(query.items()):
                pairs.append("%s=%s" % (_aws_quote(name), _aws_quote(value)))
            canonical_qs = "&".join(pairs)
        canonical_headers = "host:%s\nx-amz-content-sha256:%s\nx-amz-date:%s\n" % (host, payload_hash, amz_date)
        signed_headers = "host;x-amz-content-sha256;x-amz-date"
        canonical = "\n".join([method, canonical_uri, canonical_qs, canonical_headers, signed_headers, payload_hash])
        scope = "%s/%s/s3/aws4_request" % (day, self.region)
        string_to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
        signing_key = _sign_key(self.secret, day, self.region, "s3")
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = "AWS4-HMAC-SHA256 Credential=%s/%s, SignedHeaders=%s, Signature=%s" % (
            self.access, scope, signed_headers, signature,
        )
        url = "https://%s%s" % (host, canonical_uri)
        if canonical_qs:
            url += "?" + canonical_qs
        request = urllib.request.Request(url, data=body if method not in ("GET", "HEAD") else None, method=method)
        request.add_header("Host", host)
        request.add_header("x-amz-date", amz_date)
        request.add_header("x-amz-content-sha256", payload_hash)
        request.add_header("Authorization", authorization)
        if method not in ("GET", "HEAD"):
            request.add_header("Content-Type", content_type)
        try:
            response = _open(request, self.timeout, "S3")
        except StoreError as exc:
            if method == "DELETE" and exc.status == 404:
                return 204, {}, b""
            raise
        if stream:
            return response.status, dict(response.headers), response
        headers = dict(response.headers)
        return response.status, headers, _read_all(response, "S3")


def _s3_part_size(size):
    need = -(-int(size) // _S3_MAX_PARTS)
    return max(_CHUNK, -(-need // _MB) * _MB)


def _s3_path(*segments):
    bits = []
    for segment in segments:
        for bit in str(segment or "").split("/"):
            if bit:
                bits.append(_aws_quote(bit))
    return "/" + "/".join(bits)


def _xml(body):
    try:
        return ElementTree.fromstring(body)
    except ElementTree.ParseError as exc:
        raise StoreError("S3 yanıtı okunamadı.", retryable=True) from exc


def _aws_quote(value):
    return urllib.parse.quote(str(value), safe="-_.~")


def _sign_key(secret, day, region, service):
    date_key = hmac.new(("AWS4" + secret).encode("utf-8"), day.encode("utf-8"), hashlib.sha256).digest()
    region_key = hmac.new(date_key, region.encode("utf-8"), hashlib.sha256).digest()
    service_key = hmac.new(region_key, service.encode("utf-8"), hashlib.sha256).digest()
    return hmac.new(service_key, b"aws4_request", hashlib.sha256).digest()


class _TokenStore(object):
    label = "Bulut"

    def __init__(self, dest, timeout):
        self.timeout = int(timeout)
        self.kind = dest_kind(dest)
        self.client_id = dest["username"]
        self.client_secret = reveal(dest["password"])
        data = extra_of(dest)
        refresh = str(data.get("refresh") or "")
        if refresh.startswith("enc:v1:"):
            refresh = reveal(refresh)
        self.refresh = refresh
        self.folder = str(dest["path"] or "cPBackup").strip("/") or "cPBackup"
        try:
            self.dest_id = dest["id"]
        except (KeyError, IndexError, TypeError):
            self.dest_id = None
        self.token = ""
        self.expires_at = 0.0

    def connect(self):
        if not self.refresh:
            raise StoreError("Hedef henüz bağlanmadı.")
        self._renew()
        self.ensure_base()

    def close(self):
        self.token = ""
        self.expires_at = 0.0

    def ping(self):
        self._token()

    def _token(self):
        if not self.token or time.time() > self.expires_at - 300:
            self._renew()
        return self.token

    def _renew(self):
        token, expires_in, refresh = _refresh(self.kind, self.client_id, self.client_secret, self.refresh)
        self.token = token
        self.expires_at = time.time() + expires_in
        if refresh and refresh != self.refresh:
            self.refresh = refresh
            _persist_refresh(self.dest_id, refresh)

    def _call(self, url, method="GET", body=None, headers=None):
        try:
            return _json_request(url, method, self._token(), body, headers, self.label)
        except StoreError as exc:
            if exc.status != 401:
                raise
        self._renew()
        return _json_request(url, method, self.token, body, headers, self.label)

    def _open_auth(self, build):
        try:
            return _open(build(self._token()), self.timeout, self.label)
        except StoreError as exc:
            if exc.status != 401:
                raise
        self._renew()
        return _open(build(self.token), self.timeout, self.label)


class GoogleDriveStore(_TokenStore):
    label = "Drive"

    def ensure_base(self):
        self._folder("root", self.folder)

    def upload(self, local_path, account, remote_name, folder=None):
        parent = self._account_folder(account, folder)
        meta = {"name": remote_name, "parents": [parent]}
        location = self._start_resumable(meta)
        total = os.path.getsize(local_path)
        with open(local_path, "rb") as handle:
            while True:
                chunk = handle.read(_CHUNK)
                if not chunk:
                    break
                self._put_chunk(location, chunk, handle.tell() - len(chunk), total)
        listed = self._find(parent, remote_name)
        if not listed:
            raise StoreError("Yüklenen dosya Drive'da görünmedi.", retryable=True)
        return "gdrive:%s/%s" % (listed, remote_name)

    def remote_size(self, remote_path):
        file_id = _drive_id(remote_path)
        data = self._call("https://www.googleapis.com/drive/v3/files/%s?fields=size" % urllib.parse.quote(file_id))
        try:
            return int(data.get("size") or 0)
        except (TypeError, ValueError):
            return None

    def list_names(self, account):
        parent = self._account_folder(account, None)
        names = []
        page = ""
        while True:
            query = {
                "q": "'%s' in parents and trashed=false" % parent,
                "fields": "nextPageToken,files(name)",
                "pageSize": "1000",
            }
            if page:
                query["pageToken"] = page
            data = self._call("https://www.googleapis.com/drive/v3/files?" + urllib.parse.urlencode(query))
            names.extend(item.get("name") for item in data.get("files") or [] if item.get("name"))
            page = data.get("nextPageToken") or ""
            if not page:
                return names

    def delete_file(self, remote_path):
        file_id = _drive_id(remote_path)
        try:
            self._call("https://www.googleapis.com/drive/v3/files/%s" % urllib.parse.quote(file_id), "DELETE")
        except StoreError as exc:
            if exc.status != 404:
                raise

    def delete_named(self, account, name):
        parent = self._account_folder(account, None)
        file_id = self._find(parent, name)
        if file_id:
            self.delete_file("gdrive:" + file_id)

    def download(self, remote_path, local_path):
        with open(local_path, "wb") as handle:
            self.retr_to(remote_path, handle)

    def retr_to(self, remote_path, handle):
        url = "https://www.googleapis.com/drive/v3/files/%s?alt=media" % urllib.parse.quote(_drive_id(remote_path))

        def build(token):
            request = urllib.request.Request(url)
            request.add_header("Authorization", "Bearer " + token)
            return request

        _copy(self._open_auth(build), handle, self.label)

    def _account_folder(self, account, folder):
        root = self._folder("root", self.folder)
        if folder:
            root = self._folder(root, folder)
        return self._folder(root, account)

    def _folder(self, parent, name):
        query = "name='%s' and mimeType='application/vnd.google-apps.folder' and '%s' in parents and trashed=false" % (name.replace("'", ""), parent)
        data = self._call("https://www.googleapis.com/drive/v3/files?q=%s&fields=files(id)" % urllib.parse.quote(query))
        files = data.get("files") or []
        if files:
            return files[0]["id"]
        created = self._call(
            "https://www.googleapis.com/drive/v3/files",
            "POST",
            {"name": name, "mimeType": "application/vnd.google-apps.folder", "parents": [parent]},
        )
        if not created.get("id"):
            raise StoreError("Drive klasörü oluşturulamadı.")
        return created["id"]

    def _find(self, parent, name):
        query = "name='%s' and '%s' in parents and trashed=false" % (name.replace("'", ""), parent)
        data = self._call("https://www.googleapis.com/drive/v3/files?q=%s&fields=files(id)" % urllib.parse.quote(query))
        files = data.get("files") or []
        return files[0]["id"] if files else ""

    def _start_resumable(self, meta):
        body = json.dumps(meta).encode("utf-8")

        def build(token):
            request = urllib.request.Request(
                "https://www.googleapis.com/upload/drive/v3/files?uploadType=resumable",
                data=body,
                method="POST",
            )
            request.add_header("Authorization", "Bearer " + token)
            request.add_header("Content-Type", "application/json; charset=UTF-8")
            return request

        response = self._open_auth(build)
        location = response.headers.get("Location")
        _read_all(response, self.label)
        if not location:
            raise StoreError("Drive yüklemesi başlatılamadı.", retryable=True)
        return location

    def _put_chunk(self, location, chunk, start, total):
        end = start + len(chunk) - 1
        request = urllib.request.Request(location, data=chunk, method="PUT")
        request.add_header("Content-Length", str(len(chunk)))
        request.add_header("Content-Range", "bytes %s-%s/%s" % (start, end, total))
        try:
            _read_all(_open(request, self.timeout, self.label), self.label)
        except StoreError as exc:
            if exc.status != 308:
                raise


class DropboxStore(_TokenStore):
    label = "Dropbox"

    def ensure_base(self):
        self._mkdir("/" + self.folder)

    def upload(self, local_path, account, remote_name, folder=None):
        remote = self._path(account, remote_name, folder)
        size = os.path.getsize(local_path)
        if size <= _CHUNK:
            with open(local_path, "rb") as handle:
                self._rpc("https://content.dropboxapi.com/2/files/upload", handle.read(), {
                    "path": remote,
                    "mode": "overwrite",
                })
            return "dropbox:" + remote
        session = self._rpc("https://content.dropboxapi.com/2/files/upload_session/start", b"", {"close": False})
        session_id = session.get("session_id")
        if not session_id:
            raise StoreError("Dropbox yükleme oturumu açılmadı.", retryable=True)
        offset = 0
        with open(local_path, "rb") as handle:
            while True:
                chunk = handle.read(_CHUNK)
                if not chunk:
                    break
                last = offset + len(chunk) >= size
                if last:
                    self._rpc("https://content.dropboxapi.com/2/files/upload_session/finish", chunk, {
                        "cursor": {"session_id": session_id, "offset": offset},
                        "commit": {"path": remote, "mode": "overwrite"},
                    })
                else:
                    self._rpc("https://content.dropboxapi.com/2/files/upload_session/append_v2", chunk, {
                        "cursor": {"session_id": session_id, "offset": offset},
                        "close": False,
                    })
                offset += len(chunk)
        return "dropbox:" + remote

    def remote_size(self, remote_path):
        data = self._call(
            "https://api.dropboxapi.com/2/files/get_metadata",
            "POST", {"path": _dropbox_path(remote_path)},
        )
        try:
            return int(data.get("size") or 0)
        except (TypeError, ValueError):
            return None

    def list_names(self, account):
        data = self._call(
            "https://api.dropboxapi.com/2/files/list_folder",
            "POST", {"path": self._path(account, "", None).rstrip("/")},
        )
        names = []
        while True:
            names.extend(item.get("name") for item in data.get("entries") or [] if item.get("name"))
            if not data.get("has_more") or not data.get("cursor"):
                return names
            data = self._call(
                "https://api.dropboxapi.com/2/files/list_folder/continue",
                "POST", {"cursor": data["cursor"]},
            )

    def delete_file(self, remote_path):
        try:
            self._call(
                "https://api.dropboxapi.com/2/files/delete_v2",
                "POST", {"path": _dropbox_path(remote_path)},
            )
        except StoreError as exc:
            if exc.status != 409 or b"not_found" not in exc.body:
                raise

    def delete_named(self, account, name):
        self.delete_file("dropbox:" + self._path(account, name, None))

    def download(self, remote_path, local_path):
        with open(local_path, "wb") as handle:
            self.retr_to(remote_path, handle)

    def retr_to(self, remote_path, handle):
        arg = json.dumps({"path": _dropbox_path(remote_path)})

        def build(token):
            request = urllib.request.Request("https://content.dropboxapi.com/2/files/download", method="POST")
            request.add_header("Authorization", "Bearer " + token)
            request.add_header("Dropbox-API-Arg", arg)
            return request

        _copy(self._open_auth(build), handle, self.label)

    def _path(self, account, name, folder):
        parts = ["", self.folder]
        if folder:
            parts.append(folder)
        parts.append(account)
        if name:
            parts.append(name)
        return "/".join(parts)

    def _mkdir(self, path):
        try:
            self._call("https://api.dropboxapi.com/2/files/create_folder_v2", "POST", {"path": path, "autorename": False})
        except StoreError as exc:
            if exc.status != 409:
                raise

    def _rpc(self, url, body, arg):
        header = json.dumps(arg)

        def build(token):
            request = urllib.request.Request(url, data=body, method="POST")
            request.add_header("Authorization", "Bearer " + token)
            request.add_header("Dropbox-API-Arg", header)
            request.add_header("Content-Type", "application/octet-stream")
            return request

        return _parse_json(_read_all(self._open_auth(build), self.label))


class OneDriveStore(_TokenStore):
    label = "OneDrive"

    def ensure_base(self):
        self._mkdir(self.folder, "")

    def upload(self, local_path, account, remote_name, folder=None):
        remote = self._path(account, remote_name, folder)
        size = os.path.getsize(local_path)
        if size <= _ONEDRIVE_CHUNK:
            with open(local_path, "rb") as handle:
                self._put_small(remote, handle.read())
            return "onedrive:" + remote
        session = self._call(
            "https://graph.microsoft.com/v1.0/me/drive/root:%s:/createUploadSession" % urllib.parse.quote(remote),
            "POST", {"item": {"name": remote_name}},
        )
        upload_url = session.get("uploadUrl")
        if not upload_url:
            raise StoreError("OneDrive oturumu açılmadı.", retryable=True)
        offset = 0
        with open(local_path, "rb") as handle:
            while True:
                chunk = handle.read(_ONEDRIVE_CHUNK)
                if not chunk:
                    break
                end = offset + len(chunk) - 1
                request = urllib.request.Request(upload_url, data=chunk, method="PUT")
                request.add_header("Content-Length", str(len(chunk)))
                request.add_header("Content-Range", "bytes %s-%s/%s" % (offset, end, size))
                _read_all(_open(request, self.timeout, self.label), self.label)
                offset += len(chunk)
        return "onedrive:" + remote

    def remote_size(self, remote_path):
        path = _cloud_path(remote_path, "onedrive:")
        data = self._call("https://graph.microsoft.com/v1.0/me/drive/root:%s" % urllib.parse.quote(path))
        try:
            return int(data.get("size") or 0)
        except (TypeError, ValueError):
            return None

    def list_names(self, account):
        path = self._path(account, "", None).rstrip("/")
        url = "https://graph.microsoft.com/v1.0/me/drive/root:%s:/children?$select=name&$top=1000" % urllib.parse.quote(path)
        names = []
        while url:
            data = self._call(url)
            names.extend(item.get("name") for item in data.get("value") or [] if item.get("name"))
            url = data.get("@odata.nextLink") or ""
        return names

    def delete_file(self, remote_path):
        path = _cloud_path(remote_path, "onedrive:")
        try:
            self._call("https://graph.microsoft.com/v1.0/me/drive/root:%s" % urllib.parse.quote(path), "DELETE")
        except StoreError as exc:
            if exc.status != 404:
                raise

    def delete_named(self, account, name):
        self.delete_file("onedrive:" + self._path(account, name, None))

    def download(self, remote_path, local_path):
        with open(local_path, "wb") as handle:
            self.retr_to(remote_path, handle)

    def retr_to(self, remote_path, handle):
        url = "https://graph.microsoft.com/v1.0/me/drive/root:%s:/content" % urllib.parse.quote(
            _cloud_path(remote_path, "onedrive:"),
        )

        def build(token):
            request = urllib.request.Request(url)
            request.add_header("Authorization", "Bearer " + token)
            return request

        _copy(self._open_auth(build), handle, self.label)

    def _path(self, account, name, folder):
        parts = ["/" + self.folder]
        if folder:
            parts.append(folder)
        parts.append(account)
        if name:
            parts.append(name)
        return "/".join(parts)

    def _mkdir(self, name, parent):
        url = "https://graph.microsoft.com/v1.0/me/drive/root/children" if not parent else (
            "https://graph.microsoft.com/v1.0/me/drive/root:%s:/children" % urllib.parse.quote(parent)
        )
        try:
            self._call(url, "POST", {
                "name": name,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "fail",
            })
        except StoreError as exc:
            if exc.status != 409:
                raise

    def _put_small(self, remote, body):
        url = "https://graph.microsoft.com/v1.0/me/drive/root:%s:/content" % urllib.parse.quote(remote)

        def build(token):
            request = urllib.request.Request(url, data=body, method="PUT")
            request.add_header("Authorization", "Bearer " + token)
            request.add_header("Content-Type", "application/octet-stream")
            return request

        _read_all(self._open_auth(build), self.label)


def _drive_id(remote_path):
    text = str(remote_path or "")
    if text.startswith("gdrive:"):
        return text.split(":", 1)[1].split("/", 1)[0]
    raise StoreError("Drive dosya kimliği yok.")


def _dropbox_path(remote_path):
    return _cloud_path(remote_path, "dropbox:")


def _cloud_path(remote_path, prefix):
    text = str(remote_path or "")
    if text.startswith(prefix):
        text = text[len(prefix):]
    if not text.startswith("/"):
        text = "/" + text
    return text

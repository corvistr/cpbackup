# -*- coding: utf-8 -*-
import ftplib
import os
import ssl


class FTPError(Exception):
    pass


class ExplicitFTP_TLS(ftplib.FTP_TLS):
    """Reuse the TLS session on the data connection."""

    def ntransfercmd(self, cmd, rest=None):
        conn, size = ftplib.FTP.ntransfercmd(self, cmd, rest)
        if self._prot_p:
            conn = self.context.wrap_socket(
                conn,
                server_hostname=self.host,
                session=self.sock.session,
            )
        return conn, size


class FtpClient(object):
    def __init__(self, host, port, username, password, path, passive=True, tls=False, timeout=120):
        self.host = host
        self.port = int(port)
        self.username = username
        self.password = password
        self.base = _normalize_dir(path or "/")
        self.passive = bool(passive)
        self.tls = bool(tls)
        self.timeout = int(timeout)
        self.ftp = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()
        return False

    def connect(self):
        try:
            if self.tls:
                context = ssl.create_default_context()
                self.ftp = ExplicitFTP_TLS(context=context)
            else:
                self.ftp = ftplib.FTP()
            self.ftp.connect(self.host, self.port, timeout=self.timeout)
            self.ftp.set_pasv(True if self.passive else False)
            if self.tls:
                self.ftp.auth()
                self.ftp.prot_p()
            self.ftp.login(self.username, self.password)
        except Exception as exc:
            self.close()
            raise FTPError(_humanize(exc))

    def close(self):
        if self.ftp is not None:
            try:
                self.ftp.quit()
            except Exception:
                try:
                    self.ftp.close()
                except Exception:
                    pass
            self.ftp = None

    def ensure_base(self):
        self._cwd_abs(self.base, create=True)

    def reconnect(self):
        self.close()
        self.connect()

    def probe(self):
        self.ensure_base()
        self._prepare_data()
        try:
            self.ftp.nlst()
        except ftplib.error_perm as exc:
            if "550" not in str(exc):
                raise FTPError(_humanize(exc))
        except Exception as exc:
            raise FTPError(_humanize(exc))

    def upload(self, local_path, account, remote_name, folder=None):
        remote_dir = _join(self.base, "cpbackup", folder, account) if folder else _join(self.base, "cpbackup", account)
        self._cwd_abs(remote_dir, create=True)
        self._prepare_data()
        local_size = os.path.getsize(local_path)
        rest = _nonneg(self._size_here(remote_name))
        if rest > local_size:
            rest = 0
        remote = _join(remote_dir, remote_name)
        if rest == local_size and local_size > 0:
            return remote
        try:
            self._store(remote_name, local_path, rest)
        except Exception as exc:
            if not rest:
                raise FTPError(_humanize(exc))
            try:
                self._prepare_data()
                self._store(remote_name, local_path, 0)
            except Exception as second:
                raise FTPError(_humanize(second))
        return remote

    def _store(self, remote_name, local_path, rest):
        with open(local_path, "rb") as handle:
            if rest:
                handle.seek(rest)
            self.ftp.storbinary(
                "STOR " + remote_name,
                handle,
                blocksize=512 * 1024,
                rest=rest if rest else None,
            )

    def _size_here(self, name):
        try:
            return self.ftp.size(name)
        except Exception:
            return None

    def list_names(self, account):
        remote_dir = _join(self.base, "cpbackup", account)
        try:
            self._cwd_abs(remote_dir, create=False)
        except FTPError:
            return []
        self._prepare_data()
        try:
            names = self.ftp.nlst()
        except ftplib.error_perm as exc:
            if "550" in str(exc):
                return []
            raise FTPError(_humanize(exc))
        except Exception as exc:
            raise FTPError(_humanize(exc))
        cleaned = []
        for name in names:
            base = name.replace("\\", "/").rsplit("/", 1)[-1]
            if base in (".", "..", ""):
                continue
            cleaned.append(base)
        return cleaned

    def delete_file(self, remote_path):
        directory, name = _split(remote_path)
        try:
            self._cwd_abs(directory, create=False)
            self._prepare_data()
            self.ftp.delete(name)
        except ftplib.error_perm as exc:
            if "550" in str(exc):
                return
            raise FTPError(_humanize(exc))
        except Exception as exc:
            raise FTPError(_humanize(exc))

    def download(self, remote_path, local_path):
        with open(local_path, "wb") as handle:
            self.retr_to(remote_path, handle)

    def retr_to(self, remote_path, handle):
        directory, name = _split(remote_path)
        try:
            self._cwd_abs(directory, create=False)
            self._prepare_data()

            def _write(chunk):
                handle.write(chunk)
                flush = getattr(handle, "flush", None)
                if flush:
                    flush()

            self.ftp.retrbinary("RETR " + name, _write, blocksize=512 * 1024)
        except Exception as exc:
            raise FTPError(_humanize(exc))

    def remote_size(self, remote_path):
        directory, name = _split(remote_path)
        try:
            self._cwd_abs(directory, create=False)
            return self.ftp.size(name)
        except Exception:
            return None

    def _prepare_data(self):
        if self.ftp is None:
            raise FTPError("FTP bağlantısı yok.")
        self.ftp.set_pasv(True if self.passive else False)

    def _cwd_abs(self, directory, create):
        parts = [part for part in directory.split("/") if part]
        try:
            self.ftp.cwd("/")
            for part in parts:
                self._cwd_one(part, create)
        except FTPError:
            raise
        except Exception as exc:
            raise FTPError(_humanize(exc))

    def _cwd_one(self, part, create):
        try:
            self.ftp.cwd(part)
            return
        except Exception:
            if not create:
                raise FTPError("Uzak dizin bulunamadı: %s" % part)
        try:
            self.ftp.mkd(part)
            self.ftp.cwd(part)
        except Exception as exc:
            raise FTPError(_humanize(exc))


def _normalize_dir(path):
    text = (path or "/").strip().replace("\\", "/")
    if not text.startswith("/"):
        text = "/" + text
    while "//" in text:
        text = text.replace("//", "/")
    if len(text) > 1 and text.endswith("/"):
        text = text[:-1]
    return text or "/"


def _join(*parts):
    pieces = []
    for part in parts:
        for bit in str(part).replace("\\", "/").split("/"):
            if bit and bit != ".":
                pieces.append(bit)
    return "/" + "/".join(pieces)


def _split(remote_path):
    path = _normalize_dir(remote_path)
    if path == "/":
        raise FTPError("Uzak dosya yolu geçersiz.")
    directory, _, name = path.rpartition("/")
    return (directory or "/"), name


def _nonneg(value):
    try:
        number = int(value)
    except (TypeError, ValueError):
        return 0
    if number < 0:
        return 0
    return number


def _humanize(exc):
    text = str(exc).strip() or exc.__class__.__name__
    lowered = text.lower()
    if "530" in text:
        return "FTP girişi reddedildi. Kullanıcı adı veya parola hatalı."
    if "timed out" in lowered or "timeout" in lowered:
        return "FTP zaman aşımı. Adres, port ve güvenlik duvarını kontrol edin."
    if "name or service not known" in lowered or "temporary failure in name resolution" in lowered:
        return "FTP sunucu adı çözülemedi."
    if "certificate" in lowered or "ssl" in lowered or "tls" in lowered:
        return "FTPS el sıkışması başarısız: %s" % text
    if text.startswith("FTP hatası") or text.startswith("Uzak dizin"):
        return text
    return "FTP hatası: %s" % text


def from_destination(row, timeout=120):
    from engine.secret import reveal
    return FtpClient(
        host=row["host"],
        port=row["port"],
        username=row["username"],
        password=reveal(row["password"]),
        path=row["path"],
        passive=bool(row["passive"]),
        tls=bool(row["tls"]),
        timeout=timeout,
    )

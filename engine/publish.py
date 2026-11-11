# -*- coding: utf-8 -*-
import os

from engine.config import UI_DIST

PUBLIC_ASSETS = "/usr/local/cpanel/whostmgr/docroot/cpbackup/assets"
CPANEL_ROOT = "/usr/local/cpanel/base/3rdparty/cpbackup"


def publish_assets():
    src_dir = os.path.join(UI_DIST, "assets")
    if not os.path.isdir(src_dir):
        return
    _sync_dir(src_dir, PUBLIC_ASSETS)
    _sync_dir(src_dir, os.path.join(CPANEL_ROOT, "assets"))
    user_html = os.path.join(UI_DIST, "user.html")
    if os.path.isfile(user_html):
        if not os.path.isdir(CPANEL_ROOT):
            os.makedirs(CPANEL_ROOT, 0o755)
        _copy_file(user_html, os.path.join(CPANEL_ROOT, "user.html"))


def _sync_dir(src_dir, dst_dir):
    if not os.path.isdir(dst_dir):
        os.makedirs(dst_dir, 0o755)
    names = [name for name in os.listdir(src_dir) if os.path.isfile(os.path.join(src_dir, name))]
    wanted = set(names)
    for name in os.listdir(dst_dir):
        path = os.path.join(dst_dir, name)
        if name not in wanted and os.path.isfile(path):
            os.remove(path)
    for name in names:
        _copy_file(os.path.join(src_dir, name), os.path.join(dst_dir, name))


def _copy_file(src, dst):
    src_stat = os.stat(src)
    if os.path.isfile(dst):
        dst_stat = os.stat(dst)
        if dst_stat.st_size == src_stat.st_size and int(dst_stat.st_mtime) >= int(src_stat.st_mtime):
            return
    with open(src, "rb") as handle:
        data = handle.read()
    tmp = dst + ".tmp"
    with open(tmp, "wb") as handle:
        handle.write(data)
    os.chmod(tmp, 0o644)
    os.rename(tmp, dst)

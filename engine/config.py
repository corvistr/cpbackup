# -*- coding: utf-8 -*-
import os

VERSION = "1.1.1"
ROOT = "/opt/cpbackup"
DATA_DIR = os.path.join(ROOT, "data")
LOG_DIR = os.path.join(ROOT, "logs")
DB_PATH = os.path.join(DATA_DIR, "cpbackup.db")
SPOOL = "/home/cpbackup-spool"
LOCK_PATH = os.path.join(SPOOL, "worker.lock")
UI_DIST = os.path.join(ROOT, "ui", "dist")
PKGACCT = "/usr/local/cpanel/bin/pkgacct"
RESTOREPKG = "/usr/local/cpanel/bin/restorepkg"
WHMAPI = "/usr/sbin/whmapi1"
LOG_FILE = os.path.join(LOG_DIR, "cpbackup.log")
CRON_LOG = os.path.join(LOG_DIR, "cron.log")
USER_DIR = "/var/cpanel/users"

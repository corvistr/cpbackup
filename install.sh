#!/bin/bash
# cPBackup kurulumu. Root olarak çalıştırın.
# /opt/cpbackup/data ve secret.key silinmez.
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Kurulum root ile çalışmalı."
  exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 bulunamadı."
  exit 1
fi
if ! command -v rsync >/dev/null 2>&1; then
  echo "rsync bulunamadı."
  exit 1
fi
if [[ ! -x /usr/local/cpanel/bin/pkgacct || ! -x /usr/local/cpanel/bin/restorepkg ]]; then
  echo "Bu paket cPanel/WHM sunucusu ister. pkgacct veya restorepkg yok."
  exit 1
fi

ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "Dosyalar kopyalanıyor."
mkdir -p /opt/cpbackup /opt/cpbackup/data /opt/cpbackup/logs /opt/cpbackup/docs /home/cpbackup-spool
chmod 700 /opt/cpbackup /opt/cpbackup/data /opt/cpbackup/logs /home/cpbackup-spool

rsync -a --delete \
  --exclude '__pycache__/' --exclude '*.pyc' \
  "$ROOT/engine/" /opt/cpbackup/engine/
rsync -a --delete \
  --exclude 'node_modules/' --exclude '__pycache__/' \
  "$ROOT/ui/" /opt/cpbackup/ui/
install -m 644 "$ROOT/README.md" /opt/cpbackup/README.md
install -m 644 "$ROOT/CHANGELOG.md" /opt/cpbackup/CHANGELOG.md
install -m 644 "$ROOT/docs/kurulum.md" /opt/cpbackup/docs/kurulum.md
install -m 644 "$ROOT/docs/kullanim.md" /opt/cpbackup/docs/kullanim.md

find /opt/cpbackup/engine /opt/cpbackup/ui /opt/cpbackup/docs -type d -exec chmod 700 {} \;
find /opt/cpbackup/engine /opt/cpbackup/ui /opt/cpbackup/docs -type f -exec chmod 600 {} \;
chmod 755 /opt/cpbackup/engine/worker.py /opt/cpbackup/engine/usercli.py

install -d -m 755 /usr/local/cpanel/whostmgr/docroot/cgi/cpbackup
install -m 700 "$ROOT/panel/whm/index.cgi" /usr/local/cpanel/whostmgr/docroot/cgi/cpbackup/index.cgi
install -m 700 "$ROOT/panel/whm/api.cgi" /usr/local/cpanel/whostmgr/docroot/cgi/cpbackup/api.cgi

install -d -m 755 /usr/local/cpanel/base/3rdparty/cpbackup
install -m 755 "$ROOT/panel/user/index.cgi" /usr/local/cpanel/base/3rdparty/cpbackup/index.cgi
install -m 644 "$ROOT/ui/dist/user.html" /usr/local/cpanel/base/3rdparty/cpbackup/user.html
rm -rf /usr/local/cpanel/base/3rdparty/cpbackup/assets
cp -a "$ROOT/ui/dist/assets" /usr/local/cpanel/base/3rdparty/cpbackup/assets
chmod 755 /usr/local/cpanel/base/3rdparty/cpbackup/assets
chmod 644 /usr/local/cpanel/base/3rdparty/cpbackup/assets/*

install -d -m 755 /usr/local/cpanel/whostmgr/docroot/cpbackup
rm -rf /usr/local/cpanel/whostmgr/docroot/cpbackup/assets
cp -a "$ROOT/ui/dist/assets" /usr/local/cpanel/whostmgr/docroot/cpbackup/assets
chmod 755 /usr/local/cpanel/whostmgr/docroot/cpbackup/assets
chmod 644 /usr/local/cpanel/whostmgr/docroot/cpbackup/assets/*

install -d -m 700 /usr/local/cpanel/bin/admin/Cpanel
install -m 700 "$ROOT/panel/admin/cpbackup" /usr/local/cpanel/bin/admin/Cpanel/cpbackup
install -m 644 "$ROOT/panel/admin/cpbackup.conf" /usr/local/cpanel/bin/admin/Cpanel/cpbackup.conf

install -d -m 755 /usr/local/cpanel/whostmgr/docroot/addon_plugins
install -m 644 "$ROOT/panel/icons/whm-cpbackup.svg" /usr/local/cpanel/whostmgr/docroot/addon_plugins/cpbackup.svg
install -d -m 755 /usr/local/cpanel/base/frontend/jupiter/assets/application_icons
install -m 644 "$ROOT/panel/icons/jupiter-cpbackup.svg" /usr/local/cpanel/base/frontend/jupiter/assets/application_icons/cpbackup.svg

install -d -m 755 /usr/local/cpanel/whostmgr/addonfeatures
install -m 644 "$ROOT/panel/feature/cpbackup" /usr/local/cpanel/whostmgr/addonfeatures/cpbackup

install -d -m 755 /var/cpanel/apps
install -m 644 "$ROOT/panel/apps/cpbackup.conf" /var/cpanel/apps/cpbackup.conf
install -m 644 "$ROOT/panel/apps/cpbackup_cpanel.conf" /var/cpanel/apps/cpbackup_cpanel.conf

install -m 644 "$ROOT/panel/systemd/cpbackup.service" /etc/systemd/system/cpbackup.service
systemctl daemon-reload
systemctl enable cpbackup.service
systemctl restart cpbackup.service

python3 -m py_compile /opt/cpbackup/engine/service.py /opt/cpbackup/engine/worker.py
echo "Kurulum bitti. WHM sol menüde cPBackup görünür. Ayrıntı: docs/kullanim.md"

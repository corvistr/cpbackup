#!/bin/bash
# Servisi ve panel dosyalarını kaldırır.
# /opt/cpbackup/data ve uzak yedekler durur.
# Veritabanını da silmek için: bash uninstall.sh --purge
set -euo pipefail

if [[ "$(id -u)" -ne 0 ]]; then
  echo "Kaldırma root ile çalışmalı."
  exit 1
fi

systemctl disable --now cpbackup.service 2>/dev/null || true
rm -f /etc/systemd/system/cpbackup.service
systemctl daemon-reload

rm -rf /usr/local/cpanel/whostmgr/docroot/cgi/cpbackup
rm -rf /usr/local/cpanel/base/3rdparty/cpbackup
rm -f /usr/local/cpanel/bin/admin/Cpanel/cpbackup /usr/local/cpanel/bin/admin/Cpanel/cpbackup.conf
rm -f /usr/local/cpanel/whostmgr/docroot/addon_plugins/cpbackup.svg
rm -f /usr/local/cpanel/base/frontend/jupiter/assets/application_icons/cpbackup.svg
rm -f /usr/local/cpanel/whostmgr/addonfeatures/cpbackup
rm -f /var/cpanel/apps/cpbackup.conf /var/cpanel/apps/cpbackup_cpanel.conf
rm -rf /usr/local/cpanel/whostmgr/docroot/cpbackup/assets

if [[ "${1:-}" == "--purge" ]]; then
  rm -rf /opt/cpbackup /home/cpbackup-spool
  echo "Program, veritabanı ve spool silindi. Uzaktaki yedek dosyaları durur."
else
  rm -rf /opt/cpbackup/engine /opt/cpbackup/ui /opt/cpbackup/logs /opt/cpbackup/docs
  rm -f /opt/cpbackup/README.md /opt/cpbackup/CHANGELOG.md
  echo "Program kalktı. /opt/cpbackup/data duruyor. Onu da silmek için: bash uninstall.sh --purge"
fi

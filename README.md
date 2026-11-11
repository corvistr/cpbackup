# cPBackup

JetBackup alternative for cPanel and WHM. It backs up accounts, uploads them to FTP, S3, or cloud storage, and restores them from the panel. Version **1.1.1**.

cPanel ve WHM sunucusunda hesap yedeği alan, hedefe yükleyen ve panelden geri yükleyen eklenti. Sürüm **1.1.1**.

WHM yöneticisi görev ve hedef tanımlar. Müşteri cPanel içinden tam veya parça yedek alır, kendi elle aldığı yedeği silebilir ve izin varsa geri yükler. Paketler cPanel’in `pkgacct` ve `restorepkg` araçlarıyla üretilir. Varsayılan dosya sıkıştırılmış `tar.gz` arşividir.

## İçindekiler

- [English](#english)
- [Özellikler](#özellikler)
- [Gereksinimler](#gereksinimler)
- [Kurulum](#kurulum)
- [Dizin yapısı](#dizin-yapısı)
- [Güvenlik](#güvenlik)
- [Arayüzü yeniden derlemek](#arayüzü-yeniden-derlemek)
- [Sürümleme](#sürümleme)
- [Sınırlar](#sınırlar)

Ayrıntılı adımlar:

- [Kurulum kılavuzu](docs/kurulum.md)
- [Kullanım kılavuzu](docs/kullanim.md)
- [Değişiklik günlüğü](CHANGELOG.md)

## Özellikler

- Günlük ve haftalık görev, elle çalıştırma, hesap seçimi ve saklama adedi.
- Dokuz içerik kutusu. Hepsi açıkken tam `cpmove` paketi alınır. Kapalı kutu o parçayı paket dışında bırakır.
- FTP ve FTPS, Amazon S3, S3 uyumlu depo, Google Drive, Dropbox, OneDrive.
- WHM ve cPanel’den tam geri yükleme. Parça geri yüklemede dosya, veritabanı veya posta kutusu seçilir. Önizleme canlı sitenin üzerine yazmaz.
- Geçmişte kilit, hatalı hesapları yeniden deneme ve uzak dosyayı silme.
- Müşteri, yüklenmiş elle yedeği siler. Dosya hedefte de kalkar.
- Elle yedek 48 saat sonra kendiliğinden silinir. Zamanlanmış yedek, görevin saklama adedine bağlıdır.
- Aynı anda tek hesap. Askıdaki hesap yedeklenmez.

## Gereksinimler

| Parça | Koşul |
| --- | --- |
| Panel | cPanel/WHM, root kabuğu |
| Python | `/usr/bin/python3` |
| rsync | `/usr/bin/rsync`. Kurulum betiği dosyaları bununla kopyalar |
| Paketleme | `/usr/local/cpanel/bin/pkgacct` ve `restorepkg` |
| Hedef | FTP, S3 veya bir bulut hesabı |
| Node.js | Yalnızca arayüz yeniden derlenecekse. Kurulum derlenmiş `ui/dist` kullanır. |

## Kurulum

Root kabuğunda:

```bash
unzip cpbackup-kurulum.zip -d /root/cpbackup
cd /root/cpbackup
bash install.sh
```

Kurulum dosyaları `/opt/cpbackup` altına koyar, WHM menüsüne **cPBackup**, cPanel menüsüne **cPBackup Yedekler** ekler ve `cpbackup.service` servisini başlatır. Aynı sunucuda tekrar çalıştırılırsa program dosyaları yenilenir. `/opt/cpbackup/data` ve `secret.key` silinmez. Servis yeniden başlar. O sırada süren bir hesap paketlemesi kesilir.

Müşteri simgesi görünmezse WHM → Feature Manager içinde **cPBackup Yedekler** özelliğini ilgili pakete açın.

Kaldırma:

```bash
bash uninstall.sh
bash uninstall.sh --purge
```

İlki programı kaldırır, kayıt veritabanını bırakır. `--purge` veritabanını ve spool dizinini de siler. Uzaktaki yedek dosyaları iki komutta da durur.

## Dizin yapısı

```text
.
├── README.md
├── CHANGELOG.md
├── install.sh
├── uninstall.sh
├── docs/
│   ├── kurulum.md
│   └── kullanim.md
├── engine/          Python işçisi, API ve hedef sürücüleri
├── ui/              React kaynağı ve derlenmiş dist
└── panel/           WHM CGI, cPanel CGI, AdminBin, systemd, simgeler
```

Kurulu sunucuda:

| Yol | İş |
| --- | --- |
| `/opt/cpbackup/engine` | İşçi ve API |
| `/opt/cpbackup/ui/dist` | WHM’nin okuduğu arayüz |
| `/opt/cpbackup/data/cpbackup.db` | Görev, hedef ve geçmiş |
| `/opt/cpbackup/data/secret.key` | Parola mühürleme anahtarı |
| `/opt/cpbackup/logs/cpbackup.log` | İşçi günlüğü |
| `/home/cpbackup-spool` | Yükleme bitene kadar geçici paket |
| `/etc/systemd/system/cpbackup.service` | Servis |

## Güvenlik

Bu arşiv parola, FTP bilgisi, `secret.key` ve `cpbackup.db` içermez. Her sunucu kurulumda kendi anahtarını üretir. Hedef parolaları `enc:v1:` ön ekiyle mühürlenir ve arayüze geri yazılmaz.

Depoya şunlar girmez: `data/`, `logs/`, `secret.key`, `ui/node_modules/`. Ayrıntı `.gitignore` dosyasındadır.

Müşteri yalnız kendi hesabının kayıtlarını görür. Uzak dosyayı silme, elle alınmış ve yüklenmiş yedeğe bağlıdır. Zamanlanmış yedeği müşteri silemez. Tam geri yükleme hesap adının yazılmasını ister.

## Arayüzü yeniden derlemek

Node.js 20 ve `ui/` altında bağımlılıklar gerekir. Üretilen dosyalar `ui/dist` içine yazılır. Kurulum betiği bu dizini panele kopyalar. WHM sayfası açılınca `engine/publish.py` aynı dosyaları bir kez daha yayınlar.

```bash
cd ui
npm ci
npm run build
```

## Sürümleme

Sürüm `engine/config.py` içindeki `VERSION` değeridir. Günlük [CHANGELOG.md](CHANGELOG.md) dosyasındadır. Yama, düzeltmedir. Küçük sürüm, geriye uyumlu özellik ekler. Büyük sürüm, kayıt veya kurulum yolunu kıran değişiklik içindir.

## Sınırlar

Bayt düzeyinde artımlı gönderim, SFTP, SSH aktarımı, eşzamanlı birden fazla hesap, yedek şifreleme ve bayi paneli yoktur. Parça yedek, seçilen parçanın o andaki tam kopyasıdır. Günlükler, API belirteçleri ve bant verisi her paketin dışında kalır.

## English

cPBackup is a JetBackup alternative for cPanel and WHM. The administrator defines jobs and destinations in WHM. The customer creates a full or partial backup in cPanel, may delete a manual backup they uploaded, and can restore when the feature is enabled. Packages are built with cPanel’s `pkgacct` and `restorepkg`. The default file is a compressed `tar.gz` archive.

### Features

- Daily and weekly jobs, manual runs, account selection, and a retention count.
- Nine content boxes. With every box on, the job produces a full `cpmove` package. A closed box leaves that part out.
- FTP and FTPS, Amazon S3, S3-compatible storage, Google Drive, Dropbox, and OneDrive.
- Full restore from WHM and cPanel. A partial restore can select files, a database, or a mailbox. Preview does not overwrite the live site.
- Locks in history, retry for failed accounts, and remote file deletion.
- A customer can delete an uploaded manual backup. The file is removed from the destination as well.
- Manual backups are deleted after 48 hours. Scheduled backups follow the job’s retention count.
- One account at a time. Suspended accounts are skipped.

### Requirements

| Piece | Requirement |
| --- | --- |
| Panel | cPanel/WHM with a root shell |
| Python | `/usr/bin/python3` |
| rsync | `/usr/bin/rsync`. The installer copies files with it |
| Packaging | `/usr/local/cpanel/bin/pkgacct` and `restorepkg` |
| Destination | FTP, S3, or a cloud account |
| Node.js | Only when rebuilding the UI. Install uses the built `ui/dist` |

### Install

On the server, as root:

```bash
unzip cpbackup-kurulum.zip -d /root/cpbackup
cd /root/cpbackup
bash install.sh
```

The installer copies files to `/opt/cpbackup`, adds **cPBackup** to the WHM menu and **cPBackup Yedekler** to the cPanel menu, and starts `cpbackup.service`. Running it again on the same server replaces program files. `/opt/cpbackup/data` and `secret.key` stay. The service restarts, which stops an account package already in progress.

If the customer icon is missing, open WHM → Feature Manager and enable **cPBackup Yedekler** on the package.

Step-by-step guides are in Turkish: [install](docs/kurulum.md), [usage](docs/kullanim.md), and the [changelog](CHANGELOG.md).

### Limits

There is no byte-level incremental transfer, SFTP, SSH transport, concurrent accounts, backup encryption, or reseller panel. A partial backup is a full copy of the selected part at that moment. Logs, API tokens, and bandwidth data stay out of every package.

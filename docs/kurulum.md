# Kurulum kılavuzu

Bu kılavuz cPBackup 1.1.3 paketini yeni bir cPanel/WHM sunucusuna kurar ve kurulu bir kopyayı günceller. Kullanım için [kullanim.md](kullanim.md) dosyasına bakın.

## 1. Kurulum öncesi

Sunucuda root kabuğu, cPanel/WHM, `/usr/bin/python3`, `rsync`, `/usr/local/cpanel/bin/pkgacct` ve `/usr/local/cpanel/bin/restorepkg` bulunur. Betik bunlardan biri yoksa durur.

Yedeklerin gideceği yeri önceden hazırlayın: FTP hesabı, S3 kovası veya bir bulut uygulaması. Kurulum hedef oluşturmaz.

Paketi sunucuya root olarak alın. Arşivde parola ve veritabanı yoktur.

```bash
unzip cpbackup-kurulum.zip -d /root/cpbackup
cd /root/cpbackup
bash install.sh
```

Betik şunları yapar:

1. `engine/` ve `ui/` ağaçlarını `/opt/cpbackup` altına kopyalar.
2. WHM CGI, cPanel CGI, AdminBin, uygulama kayıtları, özellik dosyası ve simgeleri yerine koyar.
3. `/opt/cpbackup/data`, `/opt/cpbackup/logs` ve `/home/cpbackup-spool` dizinlerini `0700` ile açar.
4. `cpbackup.service` birimini etkinleştirir ve yeniden başlatır.
5. `service.py` ve `worker.py` dosyalarını `py_compile` ile kontrol eder.

`/opt/cpbackup/data` zaten varsa içi silinmez. `secret.key` varsa yenisi yazılmaz. İkinci kurulum bir yükseltmedir.

## 2. Yükseltme

Yeni zip’i boş bir dizine açın ve yine `bash install.sh` çalıştırın. Program dosyaları değişir, görevler ve hedefler durur. Servis yeniden başladığı için o anda `pkgacct` ile paketlenen hesap yarıda kalır. Yükseltmeyi kuyruk boşken yapın.

```bash
systemctl is-active cpbackup.service
```

Çıktı `active` olmalıdır. Son satırlar:

```bash
journalctl -u cpbackup.service -n 50 --no-pager
```

WHM’de sol menüde **cPBackup** görünür. Adres `https://SUNUCU:2087/cgi/cpbackup/index.cgi` biçimindedir.

## 3. Müşteri menüsü

cPanel kaydı `/var/cpanel/apps/cpbackup_cpanel.conf` dosyasıdır. Özellik adı `cpbackup`, görünen ad **cPBackup Yedekler**.

Özellik dosyası:

```text
/usr/local/cpanel/whostmgr/addonfeatures/cpbackup
```

WHM → Packages → Feature Manager içinde bu özelliği müşteriye açık paketlere ekleyin. Özelliği kapalı paketlerde simge çıkmaz.

## 4. Servis

Birim dosyası `/etc/systemd/system/cpbackup.service`.

| Ayar | Değer |
| --- | --- |
| Başlatma | `/usr/bin/python3 /opt/cpbackup/engine/worker.py --service` |
| Yeniden başlatma | `always`, 5 saniye ara |
| UMask | `0077` |

```bash
systemctl status cpbackup.service
systemctl restart cpbackup.service
```

İşçi tek kilit tutar: `/home/cpbackup-spool/worker.lock`. İkinci bir işçi aynı kuyruğu almaz.

Günlük dosyası `/opt/cpbackup/logs/cpbackup.log`.

## 5. İzinler

| Yol | Kip | Sahip |
| --- | --- | --- |
| `/opt/cpbackup` | `0700` | root |
| `/opt/cpbackup/data` | `0700` | root |
| `/home/cpbackup-spool` | `0700` | root |
| WHM `index.cgi` ve `api.cgi` | `0700` | root |
| cPanel `index.cgi` | `0755` | root |
| Müşteri arayüz varlıkları | `0644` | root |
| AdminBin `cpbackup` | `0700` | root |

Müşteri CGI, oturum kullanıcısı ile çalışır ve işi AdminBin üzerinden root’a devreder. Başka bir hesabın kaydına erişmez.

## 6. Kaldırma

Programı kaldırıp kayıtları bırakmak:

```bash
bash uninstall.sh
```

Silinenler: servis, `/opt/cpbackup/engine`, `/opt/cpbackup/ui`, `/opt/cpbackup/logs`, panel CGI, AdminBin, simgeler ve uygulama kayıtları.

Duranlar: `/opt/cpbackup/data` ve uzaktaki yedek dosyaları.

Kayıt veritabanı ve spool da silinecekse:

```bash
bash uninstall.sh --purge
```

Bu komut `/opt/cpbackup` ve `/home/cpbackup-spool` dizinlerini siler. FTP, S3 veya buluttaki arşivler durur. Onları WHM geçmişinden, kaldırmadan önce silin.

## 7. Sorun giderme

**Menü yok.** Feature Manager’da özelliği açın. WHM için `/var/cpanel/apps/cpbackup.conf` dosyasının durduğunu kontrol edin. Kurulumu tekrar çalıştırmak kayıtları silmez.

**`python3 bulunamadı`.** `/usr/bin/python3` kurulu ve çalışır olmalıdır. Betik başka bir Python yolu aramaz.

**Servis hemen çıkıyor.** `journalctl -u cpbackup.service -n 80 --no-pager` çıktısına bakın. Sık neden, `pkgacct` yolunun olmaması veya `/opt/cpbackup` izinlerinin root dışında bir kullanıcıya açılmış olmasıdır.

**Parça seçimi veya bulut hedefi kapalı.** Eski işçi süreci bu işi tam FTP yedeği sanmasın diye kapı vardır. `systemctl restart cpbackup.service` yeni işçiyi açar. Kuyrukta paketlenen hesap varsa yeniden başlatma onu keser.

**Google `invalid_client`.** Hedefteki istemci kimliği, sizin Google Cloud uygulamanızın kimliği olmalıdır. Yönlendirme adresi, uygulamanın kayıtlı adresi ile aynı olmalıdır. Biçim [kullanım kılavuzundaki](kullanim.md) bulut bölümündedir.

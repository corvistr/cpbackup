# Değişiklik günlüğü

Bu dosya [Keep a Changelog](https://keepachangelog.com/tr/1.1.0/) biçimindedir. Sürüm numaraları [Semantic Versioning](https://semver.org/lang/tr/) kurallarına uyar.

## 1.1.2 - 2026-11-12

### Fixed

- Sunucunun yerel kodlaması ASCII olduğunda panel `'ascii' codec can't decode byte` hatası veriyordu. Metin okunan ve yazılan her yer UTF-8’e sabitlendi.
- `whmapi1` çıktısı UTF-8 okunur. Türkçe karakter taşıyan paket, sahip veya alan adı artık hesap listesini ve özet ekranını kırmaz.
- Panele gelen istek gövdesi UTF-8 okunur. Uzunluk bayt olarak sayılır.
- `pkgacct` ve `restorepkg` çıktısı UTF-8 okunur. Günlük dosyası UTF-8 yazılır.
- Müşteri ekranının yanıtı UTF-8 gönderilir.
- Arşiv içindeki Türkçe dosya adları paket içeriğinde ve parça geri yüklemede bozulmaz.
- Servis birimi UTF-8 ile başlar.

## 1.1.1 - 2026-11-11

### Fixed

- S3’ten geri yükleme ve indirme, arşivi belleğe almadan parça parça yazar.
- S3 parça boyutu büyük arşivlerde 10.000 parça sınırına takılmayacak kadar büyür. Yarım kalan parçalı yükleme iptal edilir. Önekteki boşluk ve Türkçe karakter imzayı bozmaz.
- OneDrive parça boyutu 10 MiB oldu. Microsoft’un 320 KiB katı kuralına uyar.
- OneDrive ana klasörü her bağlantıda yerine yenisi konarak değil, yoksa oluşturulur.
- Drive, Dropbox ve OneDrive erişim jetonu süresi dolmadan yenilenir. 401 yanıtında jeton yenilenip istek bir kez tekrarlanır. Sağlayıcının verdiği yeni yenileme jetonu kaydedilir.
- 429, 5xx ve ağ kopmaları bulut hedeflerinde de yeniden denenir.
- Drive, Dropbox ve OneDrive listelemesi bütün sayfaları okur. Saklama kuralı eski dosyaları kaçırmaz.
- Uzakta zaten olmayan dosyayı silmek Drive, Dropbox ve OneDrive’da hata vermez.
- OAuth zaman aşımı mesajı “Bağlantı oturumu” der.

## 1.1.0 - 2026-11-11

### Added

- cPanel müşterisi, kendi elle aldığı ve yüklenmiş yedeği **Sil** ile kaldırabilir. Dosya FTP, S3 veya bağlı bulut hedefinden silinir.
- Kurulum paketi, GitHub düzeninde README, kurulum kılavuzu, kullanım kılavuzu ve bu günlüğü içerir.

### Changed

- `engine/config.py` içindeki sürüm `1.1.0` oldu.

## 1.0.0 - 2026-11-11

### Added

- WHM eklentisi: özet, hesaplar, hedefler, görevler, geçmiş, geri yükleme ve ayarlar.
- cPanel müşteri ekranı: tam yedek, parça yedek, yedek listesi, tam geri yükleme ve parça geri yükleme.
- Zamanlanmış yedek `pkgacct` ile sıkıştırılmış `cpmove` arşivi üretir. Hepsi açıkken bugünkü tam paket alınır.
- İçerik seçimi: panel, ana dizin, veritabanı, veritabanı kullanıcıları, e-posta, FTP, cron, alan adı ve SSL.
- E-posta içeriği, çöp ve spam hariç tutma, adlandırılmış veritabanı hariç tutma.
- Hedefler: FTP, FTPS, Amazon S3, S3 uyumlu depo, Google Drive, Dropbox ve OneDrive.
- Saklama adedi dosya grubuna göredir. Kilitli kopya rotasyondan çıkmaz.
- Elle alınan yedek 48 saat durur, süre dolunca hedeften silinir.
- Hatalı hesapları yeniden kuyruğa alma.
- Hesap sahibine hata ve başarı postası. İkisi de kapalı başlar.
- Aynı anda tek hesap paketlenir. Askıdaki hesap atlanır.

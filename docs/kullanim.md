# Kullanım kılavuzu

cPBackup 1.1.2. Yönetici işleri WHM’deki **cPBackup** ekranındadır. Müşteri işleri cPanel’deki **cPBackup Yedekler** ekranındadır.

## WHM ekranları

| Ekran | İş |
| --- | --- |
| Özet | Kuyruk, son tur, disk ve sıradaki görev |
| Hesaplar | Sunucudaki hesaplar. Askıdaki hesap yedeklenmez |
| Geri yükle | Tam geri yükleme, indirme ve parça seçimi |
| FTP hedefleri | FTP, S3 ve bulut hedefleri. Menü adı eski kalmıştır |
| Görevler | Zaman, saklama ve içerik |
| Geçmiş | Hesap sonucu, günlük, kilit, silme ve yeniden deneme |
| Ayarlar | Posta, yük, öncelik ve müşteri geri yükleme izni |

Aynı anda tek hesap paketlenir. Yük sınırı aşılırsa sıradaki hesap bekler. Eldeki paket yarıda kesilmez.

## Hedef ekleme

WHM → cPBackup → FTP hedefleri → Hedef ekle. Parolalar kayıtta mühürlenir. Form, kayıtlı parolayı geri göstermez. **Bağlantıyı sına** yazma iznini ve dizini kontrol eder.

### FTP ve FTPS

Sunucu, port, kullanıcı, parola, uzak dizin, pasif mod ve isteğe bağlı açık TLS. Pasif mod, dış FTP sunucularında açık kalmalıdır. FTPS anahtarı açık TLS ister. SFTP bu hedefte yoktur.

### Amazon S3

Bölge, kova, erişim anahtarı, gizli anahtar ve isteğe bağlı önek. İstek imzası SigV4 ile gider. Parça boyutu en az 8 MB’tır ve çok büyük arşivlerde 9.000 parçayı aşmayacak kadar büyür. Yarım kalan parçalı yükleme kovadan silinir.

### S3 uyumlu

Aynı alanlara uç nokta eklenir. Wasabi, DigitalOcean Spaces, Backblaze B2 ve özel S3 ucu bu türdedir. Adres yolu biçimindedir.

### Google Drive, Dropbox ve OneDrive

Bu üçü, sunucuya gömülü bir uygulama kimliği taşımaz. Hedefi kaydetmeden önce sağlayıcıda kendi uygulamanızı açın.

1. Sağlayıcının geliştirici ekranında uygulama oluşturun.
2. Yönlendirme adresine WHM adresinizi yazın. `SUNUCU` yerine WHM’nin gördüğü ana makine adını koyun:

   ```text
   https://SUNUCU:2087/cgi/cpbackup/api.cgi?action=destination.oauth
   ```

3. İstemci kimliği ve istemci sırrını hedefe kaydedin. Klasör adı yedeklerin duracağı dizindir.
4. **Gmail ile bağlan** veya **Bağlan** deyin. Onaydan sonra tarayıcı bu sunucuya döner. Kodu elle yapıştırmanız gerekmez.
5. **Bağlantıyı sına**.

Yedekler `cPBackup/hesap/` altında durur. Drive kaydı dosya kimliği ile tutulur. Dropbox ve OneDrive yol tutar.

OAuth dönüşü 15 dakika geçerli imzalı bir durum değeri kullanır. Süre dolarsa bağlanmayı yeniden başlatın.

Google Cloud’daki OAuth onay ekranı **Testing** durumunda kalırsa Google yenileme jetonunu 7 gün sonra iptal eder ve Drive hedefi durur. Uygulamayı **In production** durumuna alın.

Erişim jetonu süresi dolmadan yenilenir. Sağlayıcı yeni bir yenileme jetonu verirse hedefe mühürlenerek kaydedilir.

## Görev

WHM → Görevler → Görev ekle.

- Hedef, saat, dakika ve haftalık görevde gün.
- Saklama adedi. Bu adet, aynı dosya grubundan kaç kopyanın duracağını söyler.
- Tüm hesaplar veya seçilen hesaplar.
- İsteğe bağlı hesap başına boyut tavanı. Tavanın üstündeki hesap o görevde atlanır.

Zaman günlük, haftalık veya yalnız elle olabilir. **Çalıştır** görevi hemen kuyruğa alır.

### İçerik kutuları

| Kutu | Pakete giren |
| --- | --- |
| Panel yapılandırması | cPanel kullanıcı yapılandırması |
| Ana dizin dosyaları | `public_html` ve ev dizini |
| Veritabanları | MySQL dökümü |
| Veritabanı kullanıcıları | Veritabanı kullanıcıları |
| E-posta hesapları | Posta kutuları ve posta ayarı |
| FTP hesapları | FTP kullanıcıları |
| Cron işleri | Cron |
| Alan adları | DNS bölgeleri ve alan adları |
| SSL sertifikaları | Sertifikalar |

Hepsi işaretliyken, e-posta içeriği açıkken ve hariç tutulan veritabanı yokken paket bugünkü tam yedektir. Dosya adı `cpmove-HESAP-damga-run.tar.gz` biçimindedir ve saklama grubu `full` olur.

Bir kutu kapalıysa yalnız işaretli parçalar paketlenir. Yalnız veritabanı yedeği, tam paketlerin saklama sayısını düşürmez. Grup etiketi içeriğe göre `db`, `mail`, `files` veya kısa bir içerik kodudur.

E-posta açıksa ileti içeriği ayrı seçilir. İçerik açıkken çöp, spam ve taslak hariç tutulabilir. Veritabanı açıkken hariç tutulacak adlar virgülle yazılır. Bu üç durumda paket, seçilen üyeler çıkarılarak yeniden yazılır.

Günlükler, API belirteçleri ve bant verisi her zaman dışarıdadır.

## Saklama, kilit ve hata

Saklama, dosya grubu başına sayar. On tam ve on veritabanı kopyası istenmişse ikisi birbirinin yerini almaz.

Geçmişte **Kilitle**, o dosyayı saklama silmesinden çıkarır. Kilitli kopya adede dahil değildir. **Kilidi aç** onu yeniden rotasyona sokar.

**Hatalıları yeniden dene**, yalnız o turda hata yazan hesaplar için yeni kuyruk satırı açar. Başarılı hesaplar yeniden paketlenmez.

WHM geçmişinden yüklenmiş bir yedeğin uzak dosyası da silinebilir. Silme, hedefteki dosyayı kaldırır ve kaydı **Silindi** yapar.

Panel geçmişi ayarı, eski kayıt satırlarını listeden siler. Uzak dosyaya dokunmaz. `0` kayıtları tutar.

## Geri yükleme

WHM → Geri yükle. Hesabı arayın.

- **İndir**, arşivi spool’a çeker ve tarayıcıya verir.
- **Geri yükle**, `restorepkg` ile hesabın tamamını seçilen arşivle değiştirir. Hesap adının yazılması gerekir.
- **Parça**, arşivin içinden dosya, dizin, veritabanı veya posta kutusu seçtirir.

Önizleme, dosyaları `/home/HESAP/cpbackup-onizleme/` altına çıkar. Canlı site, veritabanı ve posta durur. Üzerine yazma hesap adını ister.

Veritabanı üzerine yazma, o `.sql` dosyasını mevcut sunucuya içeri alır. Posta kutusu üzerine yazma yalnız o Maildir’i değiştirir. Ev dizini dışındaki panel dosyaları listede görünebilir ve geri yüklenmez.

Eski bir yedekte iç liste yoktur. WHM parçayı ilk açtığında arşiv bir kez iner ve indekslenir. Büyük hesapta bu uzun sürer. cPanel listesi indeks yoksa WHM’nin bir kez açmasını ister. İndirme, müşteri isteğinin zaman sınırına sığmayabilir.

## Ayarlar

**Genel**

- Bildirim e-postası. Boşsa yöneticiye posta gitmez.
- Tur bitince tek özet mektup.
- Hesap sahibine hata postası ve başarı postası. İkisi de kapalı başlar. Adres, `/var/cpanel/users/HESAP` içindeki `CONTACTEMAIL`, o yoksa `EMAIL` alanıdır. Posta gitmezse yedek yine tamam sayılır.

**Performans**

- Yük sınırı. Bir dakikalık yük bu değerin üstündeyken sıradaki hesap bekler.
- Hesaplar arası bekleme, saniye. `0` beklemeyi kapatır.

**Kaynak**

- CPU önceliği `nice`, 0 en önde ve 19 en geride. Varsayılan 10’dur.
- Disk önceliği `ionice`, best-effort sınıfında 0 ile 7 arası. Varsayılan 7’dir.
- Bellek için ayrı tavan yoktur. Geçici paket, hesap boyutu kadar yer ister. Yer yetmezse o hesap hata yazar, sıra sürer.

**Geri yükleme**

- Müşterinin kendi yedeğini geri yüklemesi. Kapalıyken cPanel’deki geri yükleme düğmesi gizlenir. WHM geri yüklemesi durur.
- Hesap başına adet ve saat penceresi. `0` adet, sınır koymaz.

## cPanel müşterisi

Müşteri **cPBackup Yedekler** sayfasında iki ekran görür.

### Yedek al

**Tam yedek** varsayılandır. İçerik kutuları gizlidir ve hesabın o anki tam paketi kuyruğa girer.

**Parça parça** seçilince dokuz kutu, e-posta içeriği ve çöp hariç tutma görünür. Hiçbir kutu seçili değilse düğme kapalıdır. Seçilen parçalar paketlenir.

Elle alınan yedek 48 saat tutulur. Süre, kuyruğa alındığı andan hesaplanır ve bitiş saati ekranda yazılır. Süre dolunca işçi dosyayı hedeften siler. Zamanlanmış yedekler bu süreye bağlı değildir.

Aynı hesap için süren bir yedek varken yenisi alınmaz. Askıdaki hesap yedek alamaz. Boyut tavanının üstündeki hesap da alamaz.

### Yedeklerim

Liste hesabın kendi kayıtlarını gösterir.

| Düğme | Ne zaman | Sonuç |
| --- | --- | --- |
| Özet | Her satır | Kısa durum metni |
| Sil | Elle alınmış ve yüklenmiş yedek | Dosya hedeften silinir, yer boşalır, kayıt **Silindi** olur |
| Parça | Geri yükleme açık ve yedek yüklenmiş | Seçilen parçayı önizler veya üzerine yazar |
| Geri yükle | Geri yükleme açık ve yedek yüklenmiş | Hesabın tamamını bu arşivle değiştirir |

**Sil** zamanlanmış yedekte çıkmaz. Geri yüklemesi veya parça geri yüklemesi süren bir dosya silinmez. İşlem bitince yeniden deneyin. Silinen dosya geri gelmez.

**Geri yükle** hesap adının aynen yazılmasını ister. İş kuyruğa girer. Ekran kapansa da işçi sürdürür.

Parça penceresinde önizleme açıksa dosyalar `cpbackup-onizleme` klasörüne çıkar. Önizleme kapalıysa üzerine yazma için hesap adı istenir.

## Dosyaların ömrü

```text
pkgacct  →  /home/cpbackup-spool  →  hedefe yükleme  →  yerel kopya silinir
```

Yerel spool, yükleme doğrulanınca boşalır. Asıl kopya hedeftedir. Paneldeki satır, o uzak dosyanın kaydıdır.

Elle yedek 48 saat sonra hedeften silinir. Zamanlanmış yedek, kendi grubunda saklama adedini aşınca eski kopyadan başlayarak silinir. Kilitli ad silinmez.

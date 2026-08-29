# 7. Gün - Hata Yönetimi, Loglama ve Kaldığı Yerden Devam

## Amaç

Yargıtay veri çekme modülünü uzun süreli çalışmalara hazırlamak amacıyla sınırlı yeniden deneme, istekler arasında kontrollü bekleme, dosyaya loglama, tekrar kayıt engelleme ve kaldığı yerden devam etme özelliklerini geliştirmek.

Bu aşamada toplu 15.000 karar indirme işlemi başlatılmamıştır. Çalışmalar küçük sayfa boyutlarıyla ve kontrollü test senaryolarıyla sınırlandırılmıştır.

## Yeniden Deneme Mekanizması

Liste veya karar detayı isteğinde geçici servis hatası oluştuğunda aynı işlem sınırlı sayıda tekrar denenmektedir. Varsayılan deneme sayısı 3 olarak belirlenmiştir. Denemeler arasında doğrusal bekleme uygulanmaktadır:

```text
1. başarısız denemeden sonra: 2 saniye
2. başarısız denemeden sonra: 4 saniye
```

Deneme sayısı ve temel bekleme süresi komut satırı seçenekleriyle değiştirilebilmektedir. Yeniden deneme öncesinde istemcinin çerezleri ve hazırlanmış arama bilgisi temizlenerek yeni bir Yargıtay oturumu oluşturulmaktadır.

Yeniden deneme yalnızca bağlantı hatalarını değil, geçersiz liste yapısı, beklenmeyen kayıt sayısı ve boş karar HTML'i gibi geçici olabilecek veri doğrulama hatalarını da kapsamaktadır. Son deneme de başarısız olursa hata gizlenmeden üst katmana iletilmekte ve ilgili sayfa tamamlanmış olarak işaretlenmemektedir.

## Kontrollü Bekleme

Yargıtay sunucusuna arka arkaya ve gereksiz yük oluşturacak biçimde istek göndermemek için karar detay istekleri arasına kontrollü bekleme eklendi. Varsayılan istek aralığı 1 saniyedir ve `--request-delay` seçeneğiyle ayarlanabilmektedir.

Canlı testte süreyi makul tutmak için 0,5 saniyelik istek aralığı kullanılmıştır.

## Loglama

Scraper çalışmaları hem konsola hem de UTF-8 kodlamalı `logs/scraper.log` dosyasına kaydedilmektedir. Loglarda aşağıdaki bilgiler bulunmaktadır:

- Çalışmanın hangi sayfadan başladığı.
- Daha önce kaydedilmiş karar sayısı.
- Çekilmeye başlanan sayfa.
- Yeniden deneme sayısı ve hata açıklaması.
- Atlanan tekrar karar kimlikleri.
- Tamamlanan sayfa ve eklenen yeni kayıt sayısı.
- Toplam kayıt sayısı.

Log satırlarında tarih, saat ve seviye bilgileri kullanılmaktadır.

## Tekrar Kayıt Engelleme

Program başlatıldığında mevcut JSONL dosyasındaki karar kimlikleri okunarak bir kimlik kümesi oluşturulmaktadır. Liste servisinden gelen bir karar kimliği daha önce kaydedilmişse detay isteği gönderilmeden atlanmaktadır. Aynı sayfa içerisinde yinelenen kimliklere karşı da ayrıca kontrol yapılmaktadır.

JSONL dosyasında geçersiz JSON veya kimliği bulunmayan bir kayıt varsa işlem açık bir veri hatasıyla durdurulmaktadır. Ayrıca state dosyasındaki `total_saved` değeri ile JSONL dosyasındaki benzersiz karar sayısı uyuşmazsa veri kaybını gizlememek için scraper çalışmayı reddetmektedir.

## Kaldığı Yerden Devam Etme

İlerleme bilgisi `data/raw/scrape_state.json` dosyasında aşağıdaki yapıyla tutulmaktadır:

```json
{
  "last_completed_page": 3,
  "total_saved": 6
}
```

Program yeniden başlatıldığında `last_completed_page` değerinin bir sonraki sayfasından devam etmektedir. State dosyası geçici bir dosyaya yazılıp dosya değiştirme işlemiyle güncellendiği için yarım JSON oluşma riski azaltılmıştır.

Bir sayfanın state bilgisi, yalnızca o sayfadaki bütün yeni kararların detayları başarıyla alındıktan ve kayıtlar JSONL dosyasına eklendikten sonra güncellenmektedir. Bir karar bütün denemelere rağmen alınamazsa sayfa tamamlanmış sayılmaz. Program yeniden çalıştırıldığında JSONL içinde daha önce yazılmış kararlar tekrar eklenmeden aynı sayfa güvenli biçimde işlenebilir.

## Komut Satırı Seçenekleri

Scraper aşağıdaki seçeneklerle çalıştırılabilmektedir:

```powershell
python scripts/scrape_yargitay.py `
  --page-size 3 `
  --max-pages 1 `
  --attempts 3 `
  --retry-delay 2 `
  --request-delay 1
```

Varsayılan çalışma dosyaları:

```text
data/raw/decisions.jsonl
data/raw/scrape_state.json
logs/scraper.log
```

Bu çalışma dosyaları ileride büyüyebileceği ve her çalıştırmada değişeceği için `.gitignore` kapsamına alınmıştır. Küçük ve doğrulanmış günlük örnek dosyaları ise depoda korunmaktadır.

## Birim Testleri

7. gün kapsamında aşağıdaki yeni senaryolar test edildi:

- Geçici hatadan sonra işlemin başarıyla yeniden denenmesi.
- Bekleme sürelerinin doğrusal artması.
- Son denemeden sonra hatanın üst katmana iletilmesi.
- Hatalı JSONL kaydının reddedilmesi.
- Önceki state bilgisinden bir sonraki sayfaya geçilmesi.
- Daha önce kayıtlı karar kimliğinin detay isteği yapılmadan atlanması.
- Liste ve detay isteklerinin ayrı ayrı yeniden denenmesi.
- Başarısız sayfanın state bilgisini ilerletmemesi.
- State kayıt sayısı ile JSONL benzersiz kimlik sayısının uyuşmaması durumunda işlemin durması.

Önceki testlerle birlikte toplam 19 birim testinin tamamı başarıyla geçti.

## Canlı Devam Testi - 29.08.2026

Canlı Yargıtay servisi üzerinde `page_size=2` ve `max_pages=1` değerleriyle üç ayrı çalışma gerçekleştirildi:

```text
1. çalışma: 1. sayfa -> 2 yeni karar -> toplam 2
2. çalışma: 2. sayfa -> 2 yeni karar -> toplam 4
3. çalışma: 3. sayfa -> 2 yeni karar -> toplam 6
```

Her yeni çalışmanın son tamamlanan sayfanın bir sonrasından başladığı log dosyasında doğrulandı. Son durumda:

```text
JSONL kayıt sayısı: 6
Benzersiz karar kimliği: 6
last_completed_page: 3
total_saved: 6
Log satırı: 9
```

Altı kaydın zorunlu alanlarının dolu ve karar kimliklerinin benzersiz olduğu doğrulandı. Canlı test sırasında servis hatası oluşmadığı için gerçek yeniden deneme kaydı üretilmedi; yeniden deneme ve başarısız sayfada state ilerletmeme davranışları kontrollü birim testlerinde hata üretilerek doğrulandı.

## 7. Gün Sonucu

Yargıtay veri çekme modülüne hata yönetimi, sınırlı yeniden deneme, kontrollü istek aralığı, UTF-8 loglama, tekrar kayıt engelleme ve kaldığı yerden devam özellikleri eklendi. Bir sayfanın yalnızca tamamen işlendiğinde tamamlanmış sayılması sağlandı. Sistem 19 birim testi ve üç ardışık canlı çalışma ile doğrulandı. Toplu veri indirme işlemi henüz başlatılmadı.

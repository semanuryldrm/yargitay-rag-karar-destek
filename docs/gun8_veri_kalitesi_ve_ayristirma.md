# 8. Gün - Veri Kalitesi Testleri ve Ayrıştırma İyileştirmeleri

## Amaç

Yargıtay veri çekme uygulamasını farklı liste sayfaları ve karar türleri üzerinde sınamak; eksik alan, boş metin, bozuk içerik, bağlantı kesintisi ve karakter kodlama sorunlarını kontrollü senaryolarla incelemek; bulunan durumlara göre veri doğrulama ve ayrıştırma kodunu iyileştirmek.

7. günde scraper'ın uzun süreli çalışmasını sağlayan yeniden deneme, loglama, tekrar kayıt engelleme ve kaldığı yerden devam özellikleri geliştirilmişti. 8. günde aynı çalışmalar tekrarlanmadı; alınan verinin yapısal ve metinsel kalitesine odaklanıldı. Yaklaşık 15.000 kararlık toplu indirme henüz başlatılmadı.

## Liste Cevabı Doğrulamaları

Liste servisinden gelen her kaydın bir JSON nesnesi olduğu ve ham kayıt için gerekli `id`, `daire`, `esasNo`, `kararNo` ve `kararTarihi` alanlarını içerdiği doğrulanmaktadır. Alanı eksik veya boş olan bir kayıt doğrudan geçerli kabul edilmemektedir.

Önceki sürüm her sayfada tam olarak `page_size` kadar kayıt bekliyordu. Bu yaklaşım veri kümesinin son sayfasındaki doğal olarak kısa sonuçları hatalı sayabilirdi. Yeni doğrulamada `recordsFiltered` değeri ile sayfa numarası birlikte değerlendirilmekte; yalnızca gerçekten son sayfa olduğu doğrulanan kısa veya boş sayfalara izin verilmektedir. Sonuçların devam etmesi gerekirken eksik kayıt dönen bir sayfa veri hatası olarak değerlendirilmekte ve yeniden deneme mekanizmasına aktarılmaktadır.

## Metadata Standartlaştırma

Karar metadata alanlarında aşağıdaki işlemler uygulanmaktadır:

- Başta ve sonda bulunan gereksiz boşluklar kaldırılmaktadır.
- Art arda gelen boşluklar tek boşluğa indirilmektedir.
- Bölünemez boşluk karakteri normal boşluğa dönüştürülmektedir.
- Unicode metin NFC biçimine standartlaştırılmaktadır.
- NUL, Unicode replacement character (`�`) ve kontrol karakterleri reddedilmektedir.

`daire` alanından yüksek seviyeli bir `karar_turu` bilgisi türetilmektedir. Değerler `hukuk`, `ceza`, `kurul` ve sınıflandırılamayan birimler için `diger` olarak belirlenmiştir. Bu alan ileride chunk metadata ve vektör veritabanı filtrelerinde kullanılabilecektir.

## Karar Detayı Doğrulaması

Detay servisinden gelen `data` alanının boş olmayan bir metin olması tek başına yeterli kabul edilmemektedir. İçeriğin HTML etiketi taşıdığı ve `script` ile `style` bölümleri dışında görünür karar metni içerdiği doğrulanmaktadır. Düz metin, yalnızca görünmeyen kod içeren HTML, boş içerik, NUL ve `�` karakteri bulunan metinler bozuk içerik olarak reddedilmektedir.

Doğrulama başarılı olduğunda karar HTML'i temizlenmeden ve değiştirilmeden `karar_html` alanında saklanmaya devam etmektedir. HTML etiketlerinin kaldırılması ve asıl metin temizliği 10. günün processed veri aşamasına bırakılmıştır.

## Bağlantı ve Karakter Kodlama İyileştirmeleri

HTTP istemcisi; HTTP ve URL hatalarına ek olarak bağlantı sıfırlanması, genel bağlantı hatası ve işletim sistemi düzeyindeki ağ kesintilerini proje içindeki `YargitayClientError` türüne dönüştürmektedir. Böylece bu hatalar 7. günde oluşturulan sınırlı yeniden deneme akışı tarafından tutarlı biçimde ele alınabilmektedir.

JSON cevapları katı UTF-8 doğrulamasıyla okunmaktadır. Geçersiz UTF-8 baytları sessizce karaktere dönüştürülmemekte, açık bir hata üretilmektedir. Geçerli UTF-8 verinin başında isteğe bağlı BOM bulunması durumuna da destek eklenmiştir. JSONL çıktı dosyası okunurken geçersiz UTF-8 içerik bulunursa veri çekme işlemi durdurulmaktadır.

## Otomatik Testler

8. gün için eklenen veri kalitesi testleri aşağıdaki senaryoları kapsamaktadır:

- Hukuk, Ceza, Kurul ve bilinmeyen daire türlerinin sınıflandırılması.
- Metadata boşluklarının ve Unicode biçiminin standartlaştırılması.
- Liste içinde JSON nesnesi olmayan kaydın reddedilmesi.
- `recordsFiltered` ile doğrulanan kısa son sayfanın kabul edilmesi.
- Son sayfa olmadığı hâlde eksik dönen listenin reddedilmesi.
- Veri bittikten sonraki boş sayfada scraper'ın temiz biçimde durması.
- Metadata ve karar metnindeki `�` karakterinin reddedilmesi.
- HTML olmayan düz metnin reddedilmesi.
- Yalnızca `script` veya `style` içeren görünmez detayın reddedilmesi.
- Geçersiz UTF-8 JSONL ve HTTP cevaplarının reddedilmesi.
- UTF-8 BOM ve Türkçe karakterlerin doğru okunması.
- Bağlantı sıfırlanmasının istemci hatasına dönüştürülmesi.
- Geçici bozuk detayın yeniden istenip ikinci denemede kaydedilmesi.

Önceki testlerle birlikte toplam 35 otomatik testin tamamı başarıyla geçti.

## Kontrollü Canlı Test - 29.08.2026

`01.01.2025 - 01.12.2025` tarih aralığında, her sayfadan ikişer karar alınacak şekilde 1, 25, 100 ve 500. sayfalarda canlı doğrulama yapıldı.

| Sayfa | Karar sayısı | Karar türleri | Daireler |
| --- | ---: | --- | --- |
| 1 | 2 | 2 Ceza | 7. Ceza Dairesi |
| 25 | 2 | 1 Ceza, 1 Hukuk | 7. Ceza Dairesi, 7. Hukuk Dairesi |
| 100 | 2 | 2 Hukuk | 3. Hukuk Dairesi |
| 500 | 2 | 2 Ceza | 8. Ceza Dairesi |

Toplam sekiz kararın tamamının kimliği benzersizdi. Sonuçlarda beş Ceza ve üç Hukuk kararı bulundu. Karar HTML uzunlukları 1.504 ile 12.699 karakter arasında değişti. Hiçbir kayıtta boş detay veya Unicode replacement character görülmedi ve bütün kayıtlar yeni ayrıştırma doğrulamasından geçti.

Canlı test sırasında gerçek bağlantı kesintisi veya bozuk servis cevabı oluşmadı. Bu nedenle bağlantı sıfırlanması, geçersiz UTF-8, eksik alan ve geçici bozuk detay senaryoları kontrollü test nesneleriyle üretilerek doğrulandı.

## 8. Gün Sonucu

Veri çekme uygulaması farklı sayfalardaki Hukuk ve Ceza Dairesi kararlarıyla doğrulandı. Liste ve detay cevaplarının yalnızca biçimsel olarak değil, veri kalitesi açısından da denetlenmesi sağlandı. Metadata standartlaştırma, karar türü sınıflandırma, son sayfa kontrolü, görünür HTML metni kontrolü, katı UTF-8 doğrulaması ve daha geniş bağlantı hatası yakalama özellikleri eklendi. Sistem 35 otomatik test ve sekiz gerçek karar üzerinde yapılan kontrollü canlı test ile doğrulandı. Toplu veri çekme işlemi 9. güne bırakıldı.

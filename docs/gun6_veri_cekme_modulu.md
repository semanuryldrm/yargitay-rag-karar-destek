# 6. Gün - Karar Detaylarını Çeken Veri Toplama Modülü

## Amaç

Yargıtay liste servisinden alınan karar özetlerini, karar detay servisinden gelen ham HTML ile birleştiren yeniden kullanılabilir bir veri çekme modülü geliştirmek. Bu günün kapsamı tek ve kontrollü bir sayfayla sınırlandırılmıştır; toplu indirme, yeniden deneme, bekleme, loglama, tekrar kayıt kontrolü ve kaldığı yerden devam etme özellikleri henüz eklenmemiştir.

## Geliştirilen Yapı

`scripts/scrape_yargitay.py` dosyası oluşturuldu. Modül aşağıdaki görevleri birbirinden ayırmaktadır:

- Liste cevabının beklenen `data.data` yapısında olup olmadığını kontrol etmek.
- Her liste kaydında `id`, `daire`, `esasNo`, `kararNo` ve `kararTarihi` alanlarının dolu olduğunu doğrulamak.
- Her karar kimliği için detay servisini çağırmak.
- Detay cevabındaki ham HTML'in boş olmadığını kontrol etmek.
- Liste ve detay bilgilerini standart bir ham karar kaydında birleştirmek.
- Doğrulanmış kayıtları UTF-8 JSONL biçiminde yazmak.

Standart kayıt yapısı şu şekilde belirlendi:

```json
{
  "id": "1184895600",
  "daire": "7. Ceza Dairesi",
  "esas_no": "2024/1158",
  "karar_no": "2025/14770",
  "karar_tarihi": "01.12.2025",
  "karar_html": "<html>...</html>"
}
```

Ham HTML üzerinde temizleme veya metin dönüştürme uygulanmadı. Veri kaybını önlemek amacıyla servisten gelen içerik raw katmanında olduğu gibi korundu.

## Kodun Bölümleri

- `extract_list_items`: Liste cevabının yapısını doğrular ve karar özetlerini çıkarır.
- `build_decision_record`: Metadata ile detay HTML'ini standart kayıtta birleştirir.
- `fetch_decision_page`: Belirtilen sayfayı alır ve her kararın detayını sırayla çeker.
- `write_jsonl`: Doğrulanmış karar kayıtlarını UTF-8 JSONL dosyasına yazar.
- `DecisionDataError`: Eksik alan, boş HTML veya beklenmeyen cevap yapısını açık bir hataya dönüştürür.

5. günde hazırlanan `fetch_sample_decisions.py` dosyası da bu ortak fonksiyonları kullanacak biçimde düzenlendi. Böylece aynı veri eşleme ve doğrulama kodunun iki farklı dosyada tekrarlanması önlendi.

## Birim Testleri

`tests/test_scrape_yargitay.py` dosyasında aşağıdaki durumlar test edildi:

- Geçerli liste kayıtlarının çıkarılması.
- Geçersiz liste cevap yapısının reddedilmesi.
- Metadata alanlarının standart alan adlarına dönüştürülmesi.
- Ham HTML'in değiştirilmeden korunması.
- Eksik karar numarasının reddedilmesi.
- Boş detay HTML'inin reddedilmesi.
- Bir sayfadaki karar detaylarının liste sırasıyla alınması.
- Beklenenden farklı kayıt sayısının reddedilmesi.
- Türkçe karakter içeren JSONL çıktısının UTF-8 yazılması.

Önceki HTTP istemcisi testleriyle birlikte toplam 12 birim testinin tamamı başarıyla geçti.

## Canlı Servis Testi - 27.08.2026

İlk canlı çalışmada 5 kayıt istenmiş ancak Yargıtay servisi HTTP 200 içerisinde `ADALET_RUNTIME_EXCEPTION` döndürmüştür. Kodda otomatik yeniden deneme uygulanmamıştır; bu özellik 7. gün hata yönetimi kapsamında geliştirilecektir.

Daha sonra aynı modül 3 kayıtlık kontrollü bir istekle yeniden çalıştırılmış ve işlem başarıyla tamamlanmıştır. Kayıtlar `data/raw/day6_sample_decisions.jsonl` dosyasına yazılmıştır.

Canlı kontrolde:

- 3 kayıt üretildi.
- Bütün zorunlu alanların dolu olduğu doğrulandı.
- Karar kimliklerinin benzersiz olduğu doğrulandı.
- Ham HTML içeriklerinin korunduğu görüldü.
- Türkçe karakterlerin UTF-8 olarak bozulmadığı doğrulandı.

Alınan örnek kararlar:

```text
1184895600 | 7. Ceza Dairesi | 2024/1158  | 2025/14770 | 01.12.2025
1184889600 | 7. Ceza Dairesi | 2021/18586 | 2025/14887 | 01.12.2025
1184886900 | 7. Ceza Dairesi | 2021/15795 | 2025/14880 | 01.12.2025
```

## Çalıştırma

```powershell
python -m unittest discover -s tests -v
python scripts/scrape_yargitay.py --page-number 1 --page-size 3
```

Farklı bir çıktı dosyası seçmek için:

```powershell
python scripts/scrape_yargitay.py --page-number 1 --page-size 3 --output data/raw/ornek.jsonl
```

## 6. Gün Sonucu

Karar listesi ve detay servisini birleştiren, zorunlu metadata alanlarını ve ham HTML'i doğrulayan, sonucu standart UTF-8 JSONL kaydı olarak yazan tek sayfalık veri çekme modülü tamamlandı. Modül yerel birim testleri ve üç gerçek Yargıtay kararıyla doğrulandı. Bir sonraki aşamada hata yönetimi, sınırlı yeniden deneme, istekler arasında kontrollü bekleme, loglama, tekrar kayıt engelleme ve kaldığı yerden devam etme özellikleri geliştirilecektir.

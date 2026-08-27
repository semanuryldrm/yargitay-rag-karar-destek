# 5. Gün - Yargıtay HTTP İstekleri ve Örnek Veri Testi

## Amaç

Yargıtay Karar Arama servislerine Python ile bağlanmak, liste ve detay isteklerini doğrulamak, küçük bir karar örneğini JSONL olarak kaydetmek ve Türkçe karakter bütünlüğünü kontrol etmek.

## Geliştirilen Dosyalar

- `scripts/yargitay_client.py`: Liste ve detay uç noktaları için standart Python kütüphanesini kullanan HTTP istemcisi.
- `scripts/test_yargitay_connection.py`: Liste, detay ve Türkçe karakter kontrollerini yapan canlı bağlantı testi.
- `scripts/fetch_sample_decisions.py`: En fazla 10 kararlık kontrollü örnek veri üreten komut.
- `tests/test_yargitay_client.py`: Payload, sayfalama doğrulaması ve geçersiz JSON davranışı için birim testleri.

## Doğrulanan İstek Biçimi

Liste isteği:

```text
POST https://karararama.yargitay.gov.tr/aramadetaylist
Content-Type: application/json; charset=utf-8
```

Arama alanlarının doğrudan JSON kökünde değil, `data` alanı altında gönderilmesi gerektiği canlı testte doğrulandı:

```json
{
  "data": {
    "baslangicTarihi": "01.01.2025",
    "bitisTarihi": "01.12.2025",
    "pageNumber": 1,
    "pageSize": 3,
    "siralama": "3",
    "siralamaDirection": "desc"
  }
}
```

Servis çağrısından önce ana sayfa açılarak `JSESSIONID` ve ilgili oturum çerezleri alınmaktadır. Çerezsiz veya yanlış zarflanmış istekte HTTP 200 dönmesine rağmen servis `ADALET_RUNTIME_EXCEPTION` üretmiştir.

Ayrıca web arayüzünün gerçek akışına uygun olarak, liste isteğinden önce aynı oturumda `POST /detayliArama` çağrısıyla arama bağlamı hazırlanmaktadır. Bu hazırlık yapılmadan doğrudan liste uç noktasına gönderilen geçerli biçimdeki isteklerin de zaman zaman `ADALET_RUNTIME_EXCEPTION` ürettiği görüldü.

Detay isteği:

```text
GET https://karararama.yargitay.gov.tr/getDokuman?id=<karar_id>
```

## Canlı Test Sonucu - 27.08.2026

`01.01.2025 - 01.12.2025` aralığında, `pageNumber=1` ve `pageSize=3` ile test gerçekleştirildi.

- HTTP bağlantısı başarılı oldu.
- Liste servisinden 3 karar geldi.
- İkinci sayfa ayrıca istendi; ilk karar kimliği `1184903100` olarak dönerek sayfalama doğrulandı.
- `recordsFiltered` değeri test anında `282724` olarak döndü.
- İlk kayıt: `1184895600`, `7. Ceza Dairesi`, `2024/1158`, `2025/14770`, `01.12.2025`.
- İlk kararın detay HTML'i başarıyla alındı ve 1504 karakter uzunluğunda ölçüldü.
- HTML içerisinde Türkçe karakter bulunduğu ve UTF-8 çözümlemesinin bozulmadığı doğrulandı.
- Üç birim testinin tamamı geçti.
- Üç karar `data/raw/sample_decisions.jsonl` dosyasına UTF-8 JSONL olarak kaydedildi.

Sonuç sayısı canlı sistemde değişebildiği için `recordsFiltered` sabit bir test beklentisi olarak kullanılmayacaktır. Canlı bağlantı testi de dış servise bağlı olduğundan her çalıştırmada başarı garantisi veren birim test olarak değerlendirilmemelidir. Yeniden deneme ve kontrollü bekleme 7. gün hata yönetimi kapsamında eklenecektir.

## Çalıştırma

```powershell
python -m unittest discover -s tests -v
python scripts/test_yargitay_connection.py
python scripts/fetch_sample_decisions.py --count 3
```

## Ortam Notu

Depodaki `.venv`, daha önce kurulu olan fakat artık aynı konumda bulunmayan Python 3.12.10 yorumlayıcısına bağlı olduğu için 27.08.2026 tarihinde çalışmadı. Sanal ortam yerinde yükseltme yöntemiyle erişilebilir Python 3.12.13 çalışma zamanına bağlandı ve proje komutlarının `.venv` üzerinden yeniden çalıştığı doğrulandı.

## 5. Gün Sonucu

Listeleme, sayfalama, karar detayına erişim, üç kararlık örnek JSONL kaydı ve Türkçe karakter aktarımı küçük ölçekte doğrulandı. Bu aşama toplu scraper değildir; yeniden deneme, bekleme, loglama, tekrar kayıt engelleme ve kaldığı yerden devam özellikleri sonraki günlerin kapsamındadır.

# 16. Gün - Semantik Arama, FastAPI ve Bruno Doğrulaması

## Amaç

Kullanıcının doğal dille anlattığı hukuki olayı LM Studio'da embedding'e dönüştürmek, 15. günde tamamlanan 31.544 noktalı Qdrant indeksinde en yakın Yargıtay karar parçalarını bulmak, bu akışı doğrulamalı bir FastAPI uç noktasıyla sunmak ve gerçek yerel servisi Bruno üzerinden sınamak.

## Geliştirilen Semantik Arama Akışı

`app/semantic_search.py` içindeki `SemanticSearchService` aşağıdaki akışı uygular:

1. Kullanıcı olayını Unicode NFC biçimine getirir, gereksiz boşlukları temizler ve 10-4.000 karakter sınırını denetler.
2. `top_k` değerini 1-20 aralığında tam sayı olarak doğrular.
3. Sorguyu LM Studio'daki `text-embedding-embeddinggemma-300m` modeliyle 768 boyutlu vektöre dönüştürür.
4. Vektörü `yargitay_karar_parcalari` koleksiyonunda Cosine benzerliğiyle arar.
5. Sonuçların zorunlu metin alanlarını, parça sıra bilgilerini, isteğe bağlı hukuki metadata'yı ve veri kalitesi uyarılarını doğrular.
6. Karar parçalarını azalan benzerlik sırasıyla; karar kimliği, daire, esas/karar numarası, tarih, kaynak bağlantısı ve lisans bilgileriyle döndürür.

Yanıtta açıkça, sonuçların yalnızca anlamsal benzerliğe göre sıralandığı ve hukuki danışmanlık ya da kesin hukuki görüş olmadığı belirtilir. Kaynakta bulunmayan esas numarası, karar tarihi gibi değerler yine uydurulmadan `null` olarak korunur.

## FastAPI Bağlantısı

`app/main.py` iki uç nokta sağlar:

- `GET /health`: LM Studio model adı, Qdrant koleksiyonu ve indeksli parça sayısını döndürür.
- `POST /api/v1/semantic-search`: `olay` ve isteğe bağlı `top_k` alanlarını alarak kaynaklı semantik arama sonucu döndürür.

Uygulama yaşam döngüsü başlarken LM Studio'da embedding modelinin erişilebilirliğini, Qdrant koleksiyonunun 768/Cosine yapılandırmasını ve nokta sayısının tam `31.544` olmasını denetler. Geçersiz istekler FastAPI/Pydantic tarafından `422`; LM Studio veya Qdrant erişim sorunları ise açıklamalı ve kodlu `503` yanıtı olarak sunulur. Ayarlar `YARGITAY_RAG_*` ortam değişkenleriyle değiştirilebilir; varsayılanlar yerel LM Studio ve `data/vector_store/qdrant` dizinidir.

Servisi çalıştırma komutu:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

## Bruno Koleksiyonu

`bruno` klasöründe yeniden kullanılabilir bir Bruno koleksiyonu hazırlandı:

- `environments/Local.bru`: `http://127.0.0.1:8000` temel adresi.
- `01-health.bru`: servis durumu ve 31.544 kayıt sayısı testi.
- `02-semantic-search.bru`: örnek işe iade olayıyla beş sonuç isteyen semantik arama testi.

Arama isteğinin Bruno testleri HTTP durum kodunu, beş sonucun dönmesini, ilk sonucun kaynaklı karar metadata'sı taşımasını ve benzerlik skorlarının azalan sırada olmasını denetler.

## Gerçek Yerel Test Sonuçları - 07.09.2026

LM Studio, `text-embedding-embeddinggemma-300m` modeli ve yerel Qdrant veritabanı birlikte çalıştırıldı. Bruno 4.0.0 masaüstü uygulamasında `Local` ortamı seçilerek iki istek de gerçek FastAPI servisine gönderildi.

| İstek | HTTP | Bruno süresi | Doğrulanan sonuç |
| --- | ---: | ---: | --- |
| `GET /health` | 200 | 9 ms | `status=ok`, model doğru, `indexed_chunks=31544` |
| `POST /api/v1/semantic-search` | 200 | 151 ms | Beş kaynaklı karar parçası, API arama süresi 141,311 ms |

Örnek olay:

> İşveren belirsiz süreli iş sözleşmemi geçerli bir neden göstermeden feshetti. İşe iade talep edebilir miyim?

İlk sonuç `d1113966700:c0001` parçası oldu. Sonuç `7. Hukuk Dairesi`, `2013/2027` esas ve `2013/1322` karar numaralarını taşıdı; benzerlik skoru `0,714982` olarak döndü. Bu canlı sonuç, 13. ve 14. günlerdeki kontrollü işe iade örneğiyle de tutarlıdır.

## Otomatik Testler

16. gün için sekiz yeni test eklendi:

- sorgu ve `top_k` sınırları,
- embedding ve Qdrant çağrısının doğru parametrelerle yapılması,
- kaynaklı ve sıralı yanıt üretimi,
- kesin indeks sayısı denetimi,
- bozuk Qdrant payload'ının reddedilmesi,
- LM Studio hatasının güvenli biçimde sarılması,
- FastAPI sağlık ve arama sözleşmesi,
- `422` ve yapılandırılmış `503` hata davranışı.

Tam proje paketi `compileall` ile başarıyla derlendi. `python -m unittest discover -s tests -v` komutunda toplam **101 test** çalıştı ve tamamı geçti. `git diff --check` boşluk/hizalama hatası bulmadı. FastAPI TestClient çalıştırmasında Starlette'in gelecek istemci geçişine ilişkin bir deprecation uyarısı görülmüş, test sonucunu veya çalışma zamanındaki API davranışını etkilememiştir.

## 16. Gün Sonucu

16. günde kullanıcı olayını LM Studio ile embedding'e çeviren ve 31.544 gerçek Yargıtay karar parçası arasından en yakın sonuçları Qdrant üzerinden bulan semantik arama katmanı tamamlandı. Sonuçların zorunlu metadata'sı doğrulandı, kaynak ve lisans bilgileri korundu, hukuki danışmanlık olmadığına ilişkin uyarı yanıt sözleşmesine eklendi.

Arama FastAPI'ye bağlandı ve hem sağlık hem semantik arama uç noktaları Bruno masaüstü uygulamasından gerçek yerel servis üzerinde başarıyla çalıştırıldı. Böylece LM Studio, Qdrant, FastAPI ve Bruno'nun birlikte kullanıldığı uçtan uca arama zinciri doğrulandı; 17. gün için daha geniş arama kalitesi, filtre ve eşik karşılaştırmalarına hazır bir temel oluştu.

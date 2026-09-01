# 14. Gün - Qdrant Vektör Veritabanı ve Koleksiyon Doğrulaması

## Amaç

Projede kullanılacak vektör veritabanını seçip yerel ortamda kurmak; koleksiyon adını, embedding boyutunu, benzerlik yöntemini ve karar parçalarıyla birlikte saklanacak metadata alanlarını açık biçimde tanımlamak; gerçek Yargıtay parçalarıyla ekleme, okuma, silme ve benzerlik sorgusu işlemlerini doğrulamak.

Bu aşama yalnızca veritabanı altyapısını ve küçük kontrollü örnekleri kapsar. Temizlenmiş 31.544 karar parçasının tamamının toplu embedding üretimi ve veritabanına kaydı 15. gün çalışmasıdır.

## Vektör Veritabanı Seçimi

Vektör veritabanı olarak `qdrant-client==1.19.0` ile Qdrant seçildi. Dayanaklar:

1. Ayrı bir sunucu kurmadan yerel ve kalıcı modda çalışabilmesi.
2. Cosine uzaklık yöntemini ve 768 boyutlu yoğun vektörleri doğrudan desteklemesi.
3. Her vektörle birlikte yapılandırılmış payload/metadata saklayabilmesi.
4. İlerleyen aşamalarda metadata filtreleri, top-k arama ve sunucu moduna geçiş için uygun olması.
5. Verinin yerel makinede tutulabilmesi.

Yerel veritabanı `data/vector_store/qdrant` altında oluşturulur. Bu klasör türetilmiş ve yeniden üretilebilir veri içerdiği için Git dışında tutulur.

## Koleksiyon Yapılandırması

| Alan | Değer |
| --- | --- |
| Koleksiyon | `yargitay_karar_parcalari` |
| Vektör boyutu | 768 |
| Uzaklık yöntemi | Cosine |
| Embedding modeli | `text-embedding-embeddinggemma-300m` |
| Şema sürümü | 1.0 |
| Qdrant çalışma biçimi | Yerel ve kalıcı |
| Qdrant istemci sürümü | 1.19.0 |

Koleksiyon oluşturulurken bu bilgiler Qdrant koleksiyon metadata'sına yazılır. Var olan bir koleksiyonun vektör boyutu, uzaklık yöntemi, embedding modeli veya şema sürümü beklenen değerle uyuşmazsa uygulama işlemi durdurur. Böylece farklı model ya da vektör uzaylarının yanlışlıkla aynı koleksiyonda karışması engellenir.

## Payload ve Metadata Şeması

Her karar parçasında 22 alan saklanmaktadır:

| Grup | Alanlar |
| --- | --- |
| Parça bağlantısı | `chunk_id`, `karar_id`, `chunk_sirasi`, `toplam_chunk` |
| Hukuki metadata | `daire`, `karar_turu`, `esas_no`, `karar_no`, `karar_tarihi`, `baslik` |
| Metin bütünlüğü | `chunk_metni`, `chunk_metni_sha256` |
| Veri kalitesi | `veri_kalite_uyarilari`, `veri_kalite_durumu`, `metin_2000_karakter_sinirinda` |
| Kaynak bilgisi | `kaynak`, `kaynak_url`, `kaynak_lisans`, `kaynak_kayit_id` |
| Embedding bilgisi | `embedding_model`, `embedding_dimension`, `koleksiyon_sema_surumu` |

Yargıtay chunk kimlikleri Qdrant'ın nokta kimliği biçimine doğrudan uygun olmadığı için her `chunk_id`, sabit bir UUID ad alanıyla deterministik UUIDv5 değerine dönüştürülür. Asıl `chunk_id` payload içinde korunur. Aynı parça yeniden yüklendiğinde aynı nokta güncellenir ve gereksiz kopya oluşmaz.

Veritabanına yazmadan önce metin SHA-256 karması, karakter sayısı, sıra bilgisi, zorunlu metadata, veri kalitesi uyarıları, vektör boyutu, sayısal sonluluk ve sıfır olmayan vektör normu doğrulanır.

## Geliştirilen Modüller

### `scripts/qdrant_vector_store.py`

Bu modül Qdrant işlemlerini uygulamanın geri kalanından ayıran doğrulamalı bir katman sağlar:

- Koleksiyonu oluşturur veya var olan şemayı doğrular.
- Karar parçası payload'ını 22 alanlı şemaya dönüştürür.
- Deterministik nokta kimliği üretir.
- Batch upsert işlemi yapar.
- Chunk kimliğiyle kayıt okur.
- Chunk kimliğiyle kayıt siler ve silme sonucunu doğrular.
- Cosine benzerlik sorgusu çalıştırıp doğrulanmış sonuçlar döndürür.
- Koleksiyondaki kesin kayıt sayısını verir.

### `scripts/validate_qdrant_vector_store.py`

14. gün doğrulama aracı gerçek chunk dosyasını ve LM Studio embedding istemcisini kullanır. Üç sorgu ile üç karar parçasını tek altı metinlik batch isteğinde vektörleştirir; örnek parçaları Qdrant'a yazar ve bütün CRUD/arama adımlarını denetler.

Çalıştırma komutu:

```powershell
python scripts/validate_qdrant_vector_store.py
```

Ayrıntılı ve atomik yazılan yerel rapor:

```text
data/processed/yargitay_qdrant_day14_stats.json
```

Rapor ve yerel Qdrant dosyaları türetilmiş veri oldukları için Git'e eklenmez.

## Gerçek CRUD Sonuçları

Kaynak olarak 31.544 parçalık `yargitay_chunks_1200_200.jsonl` dosyası kullanıldı. Kaynak dosya SHA-256 değeri:

```text
fcd063fcc0f4fd532b4938d9e433682c95f53397528ed04c64315b93a5d7b04d
```

İşlem sonuçları:

| İşlem | Sonuç |
| --- | --- |
| Koleksiyon oluşturma | Başarılı |
| Üç gerçek chunk'ı ekleme/upsert | Başarılı, kayıt sayısı 3 |
| `d1113966700:c0001` kaydını kimlikle okuma | Başarılı, metin karması eşleşti |
| `d480864200:c0001` kaydını silme | Başarılı, kayıt sayısı 3'ten 2'ye düştü |
| Silinen kaydın bulunmadığını doğrulama | Başarılı |
| Silinen kaydı geri yükleme | Başarılı, kayıt sayısı yeniden 3 oldu |

Silme testi sonrasında örnek karar geri yüklendiği için koleksiyon doğrulama sonunda üç eksiksiz örnek içermektedir.

## Gerçek Benzerlik Sorgusu Sonuçları

| Sorgu | Birinci bulunan chunk | Skor | Sonuç |
| --- | --- | ---: | --- |
| Geçersiz fesih ve işe iade | `d1113966700:c0001` | 0,719056 | Doğru |
| Tapu iptali ve tescil | `d581878400:c0001` | 0,643115 | Doğru |
| Uyuşturucu ticareti | `d480864200:c0001` | 0,707660 | Doğru |

Beklenen karar parçası üç sorgunun tamamında ilk sırada bulundu. Qdrant'ın döndürdüğü sıralama, 13. günde doğrudan Python ile hesaplanan kosinüs sıralamasıyla aynıdır. Çok küçük son basamak farkları kayan noktalı sayı işleme biçiminden kaynaklanabilir.

Bu yüzde 100 sonuç yalnızca üç sorgu ve üç adaydan oluşan kontrollü doğrulamaya aittir; genel sistem doğruluğu değildir. Tam corpus araması, daha geniş test sorguları, top-k ölçümleri, eşik belirleme ve metadata filtreleri sonraki günlerin kapsamındadır.

## Otomatik Testler

`tests/test_qdrant_vector_store.py` dosyasına yedi test eklendi. Testler:

- 768/Cosine koleksiyon mantığını ve payload şemasını.
- Var olan uyumsuz koleksiyonun reddedilmesini.
- Upsert, kimlikle okuma, benzerlik sıralaması, silme ve geri yüklemeyi.
- Metin karması ile vektör boyutu, sonluluk ve norm doğrulamalarını.
- Deterministik ve benzersiz UUID üretimini.
- Tekrarlanan kimlik ve kayıt-vektör sayısı uyuşmazlığı reddini.
- Atomik 14. gün raporunu ve bütün işlem sonuçlarını kapsar.

Yeni yedi test ve önceki 79 testle birlikte tam proje paketindeki toplam 86 test başarıyla geçti. Python derleme kontrolü, bağımlılık denetimi ve `git diff --check` doğrulaması da tamamlandı.

## 14. Gün Sonucu

Qdrant yerel kalıcı modda kuruldu ve proje için 768 boyutlu Cosine koleksiyonu oluşturuldu. Karar bağlantısı, hukuki metadata, kaynak/lisans, veri kalitesi ve embedding bilgilerini kapsayan açık bir payload şeması tanımlandı.

Üç gerçek Yargıtay parçasıyla ekleme, okuma, silme, silinen kaydı geri yükleme ve benzerlik sorgusu başarıyla doğrulandı. Böylece 15. günde bütün karar parçalarının batch embedding üretimi ve metadata ile toplu kaydı için güvenli veritabanı katmanı hazırlandı.

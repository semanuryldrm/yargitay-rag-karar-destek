# 15. Gün - Toplu Embedding Üretimi ve Qdrant İndeksleme

## Amaç

Temizlenip parçalanmış Yargıtay corpusundaki 31.544 karar parçasının embedding vektörlerini LM Studio üzerinden toplu biçimde üretmek; her vektörü karar bağlantısı, hukuki metadata, kaynak, lisans ve veri kalitesi bilgileriyle birlikte Qdrant'a kaydetmek; uzun süren işlemin batch, ilerleme kaydı, kaldığı yerden devam ve başarısız kayıt denetimlerini güvenli biçimde gerçekleştirmek.

## Geliştirilen Toplu İndeksleme Akışı

`scripts/index_yargitay_chunks.py` modülü eklendi. Modül işlemden önce kaynak JSONL dosyasının tamamını tarayarak şu kontrolleri yapar:

- Dosyanın UTF-8 ve geçerli JSONL olması.
- Toplam kayıt sayısının tam olarak 31.544 olması.
- Bütün `chunk_id` değerlerinin benzersiz olması.
- Zorunlu payload alanlarının dolu ve doğru türde olması.
- Chunk sıra ve toplam parça bilgilerinin tutarlı olması.
- `chunk_metni` karakter sayısı ile SHA-256 karmasının kaynakla eşleşmesi.
- Kaynakta isteğe bağlı olan `esas_no`, `karar_no` ve `karar_tarihi` alanlarının yalnızca `null` veya boş olmayan metin içermesi.

Ön doğrulama tamamlanmadan LM Studio'ya istek gönderilmez ve Qdrant'a kayıt yazılmaz. Böylece corpusun sonlarına yakın bir veri hatasının yarım bir indeks oluşturması önlenir.

## Batch ve Devam Mekanizması

Varsayılan batch boyutu gerçek LM Studio denemelerinden sonra 128 olarak belirlendi. 32, 64 ve 128 parçalık canlı denemelerin tamamı 768 boyutlu geçerli vektör üretti; 128 parçalık seçenek daha az HTTP ve Qdrant çağrısıyla en uygun toplam işleme hızını sağladı.

Her batch için sırasıyla şu işlemler yürütülür:

1. Chunk metinleri tek bir `/v1/embeddings` isteğiyle LM Studio'ya gönderilir.
2. Dönen vektör sayısı, sırası, boyutu, sayısal sonluluğu ve sıfır olmayan normu doğrulanır.
3. Chunk payload'ları ve vektörler deterministik nokta kimlikleriyle Qdrant'a upsert edilir.
4. Qdrant işlemi tamamlandıktan sonra ilerleme durumu geçici dosya ve atomik değiştirme yöntemiyle kaydedilir.
5. Bir sonraki çalıştırmada aynı kaynak karması, model, vektör boyutu, koleksiyon ve batch yapılandırması doğrulanarak ilk tamamlanmamış satırdan devam edilir.

Durum dosyası:

```text
data/processed/yargitay_qdrant_day15_state.json
```

Durum dosyasında kaynak SHA-256 değeri, toplam kayıt, batch boyutu, model, vektör boyutu, koleksiyon adı, sıradaki satır, başarılı batch sayısı, başarısız deneme sayısı, geçen süre ve tamamlanma bilgisi tutulur. Aynı chunk kimliği her zaman aynı UUIDv5 nokta kimliğine dönüştüğü için bir kesinti ile durum kaydı arasındaki batch yeniden çalıştırılsa bile kopya nokta oluşmaz.

## Hata ve Başarısız Kayıt Denetimi

Bir embedding veya Qdrant batch'i başarısız olduğunda işlem varsayılan olarak en fazla üç kez denenir. Her başarısız denemede kaynak satır aralığı, chunk kimlikleri, deneme numarası, hata türü, hata metni ve UTC zamanı aşağıdaki JSONL günlüğüne yazılır:

```text
logs/day15_embedding_failures.jsonl
```

Son deneme de başarısız olursa ilerleme o batch'in sonrasına geçirilmez. İşlem açık bir hatayla durur ve tekrar çalıştırıldığında aynı batch yeniden işlenir. Böylece başarısız kayıtlar sessizce atlanmaz. Gerçek 31.544 parçalık çalıştırmada başarısız deneme oluşmadığı için hata günlüğü yaratılmadı.

## Eksik Hukuki Metadata'nın Korunması

Corpus ön doğrulamasında 19 chunk'ta `karar_tarihi`, 2 chunk'ta `esas_no` değerinin kaynakta bulunmadığı görüldü. Bu kayıtlar önceki veri temizleme aşamasındaki karara uygun biçimde silinmedi ve eksik bilgi uydurulmadı. `scripts/qdrant_vector_store.py` güncellenerek `esas_no`, `karar_no` ve `karar_tarihi` alanlarının `null` olmasına izin verildi; `eksik_karar_tarihi` veya `eksik_esas_no` kalite uyarıları payload içinde aynen korundu. Diğer zorunlu alanlar için sıkı doğrulama devam etmektedir.

## Gerçek Çalıştırma Sonuçları

Kaynak dosya:

```text
data/processed/yargitay_chunks_1200_200.jsonl
```

Kaynak SHA-256 değeri:

```text
fcd063fcc0f4fd532b4938d9e433682c95f53397528ed04c64315b93a5d7b04d
```

| Ölçüm | Sonuç |
| --- | ---: |
| Kaynak chunk sayısı | 31.544 |
| Benzersiz chunk kimliği | 31.544 |
| Qdrant başlangıç noktası | 3 |
| Qdrant son nokta sayısı | 31.544 |
| Embedding modeli | `text-embedding-embeddinggemma-300m` |
| Vektör boyutu | 768 |
| Batch boyutu | 128 |
| Başarılı batch | 247 |
| Başarısız deneme | 0 |
| Çözümlenmemiş başarısız batch | 0 |
| Toplam batch işlem süresi | 717,227 saniye |
| Ortalama hız | 43,98 chunk/saniye |
| Tamamlanma | %100 |

Son batch 56 parça içerdi. Koleksiyondaki kesin nokta sayısı kaynak kayıt sayısıyla eşleşti. Kaynağın ilk, orta ve son konumlarından seçilen aşağıdaki üç chunk Qdrant'tan tekrar okunarak payload metin karmaları doğrulandı:

| Konum | Chunk kimliği | Karma eşleşmesi |
| --- | --- | --- |
| İlk | `d80600600:c0001` | Başarılı |
| Orta | `d17210200:c0001` | Başarılı |
| Son | `d955439800:c0002` | Başarılı |

Atomik sonuç raporu yerel olarak şu dosyaya yazıldı:

```text
data/processed/yargitay_qdrant_day15_stats.json
```

Kaynak chunk, durum, istatistik ve Qdrant veritabanı dosyaları büyük veya yeniden üretilebilir veriler olduğu için Git dışında tutulmaktadır.

## Ölçek Notu

`qdrant-client==1.19.0`, yerel mod koleksiyonu 20.000 noktayı geçtiğinde performans uyarısı verdi. Bu uyarı veri hatası değildir; 31.544 noktanın tamamı yazılmış ve doğrulanmıştır. Mevcut yerel indeks geliştirme ve sonraki semantik arama çalışmaları için kullanılabilir. Daha yüksek veri hacmi, eşzamanlı istek veya üretim performansı gerektiğinde Qdrant'ın Docker ya da ayrı sunucu moduna taşınması önerilir.

## Otomatik Testler

`tests/test_index_yargitay_chunks.py` dosyasına altı test eklendi. Testler:

- Bütün kayıtların doğru batch'lerle indekslenmesini ve atomik raporu.
- Kısmi çalıştırmadan ilk tamamlanmamış satırla devam etmeyi ve kopya oluşmamasını.
- Başarısız batch'in günlüğe yazılmasını, atlanmamasını ve sonraki çalıştırmada toparlanmasını.
- Bozuk karma, tekrarlanan kimlik ve kayıt sayısı uyuşmazlıklarının yazma öncesinde reddedilmesini.
- Devam sırasında değişen batch yapılandırmasının reddedilmesini kapsar.
- Son batch yazıldıktan sonra nihai doğrulama öncesinde oluşabilecek bir kesintiden güvenli devamı kapsar.

Qdrant testlerine ayrıca kaynakta eksik hukuki metadata değerlerinin `null` olarak yazılıp tekrar okunmasını doğrulayan bir test eklendi. Yedi yeni test ve önceki 86 testle birlikte toplam 93 test başarıyla geçti.

## 15. Gün Sonucu

15. günde 31.544 temiz Yargıtay karar parçasının embedding vektörleri LM Studio üzerinde toplu olarak üretildi ve 22 alanlı payload bilgileriyle Qdrant'a kaydedildi. 128 parçalık batch yapısı, atomik ilerleme kaydı ve deterministik nokta kimlikleri sayesinde işlem kesintiye dayanıklı ve tekrarlanabilir hâle getirildi. Gerçek çalıştırma 247 başarılı batch, sıfır başarısız deneme ve yüzde 100 tamamlanmayla sonuçlandı; Qdrant'taki kesin kayıt sayısı kaynakla eşleşti.

Başarısız batch'lerin atlanmadan günlüğe alınması ve aynı yerden yeniden denenmesi sağlandı. Kaynakta bulunmayan esas numarası ve karar tarihi değerleri uydurulmadan `null` olarak, veri kalitesi uyarılarıyla birlikte korundu. Böylece 16. günde geliştirilecek kullanıcı sorgusu embedding'i, semantik benzerlik araması ve FastAPI bağlantısı için tam corpus vektör indeksi hazırlandı.

# 11. Gün - Yargıtay Karar Metinlerini Parçalama

## Amaç

Temizlenmiş Yargıtay kararlarının bölüm ve uzunluk yapısını incelemek, RAG sistemlerinde kullanılabilecek chunking yöntemlerini değerlendirmek ve uzun karar metinlerini bağlamı mümkün olduğunca koruyarak belirli parçalara ayıran yeniden üretilebilir bir metin işleme modülü geliştirmek.

Bu gün tek bir güvenli temel yapılandırma oluşturuldu. Farklı chunk boyutları ve örtüşme değerlerinin örnek kararlar üzerinde karşılaştırılması, çalışma çizelgesine uygun biçimde 12. güne bırakıldı.

## Karar Metni Uzunluk Profili

10. günde oluşturulan `data/processed/yargitay_clean_14870.jsonl` dosyasındaki 14.870 kararın tamamı incelendi.

| Karakter uzunluğu ölçümü | Değer |
| --- | ---: |
| En kısa karar metni | 287 |
| Yüzde 25 | 1.455 |
| Medyan | 1.999 |
| Yüzde 75 | 1.999 |
| Yüzde 90 | 1.999 |
| Yüzde 95 | 1.999 |
| Yüzde 99 | 1.999 |
| En uzun karar metni | 2.001 |
| Ortalama | 1.706,53 |

Temiz metinlerin 8.291'i kaynakta 2.000 karakter sınırında kalmış kayıt uyarısını taşımaktadır. En uzun metnin 2.001 karakter görünmesi, beş kaynak kaydında `İçtihat Metni"` kalıntısından sonra bitişik gelen içeriğe temizleme sırasında paragraf ayrımı eklenmesinden kaynaklanmaktadır; kaynak metin tamamlanmış değildir.

Kararlar yalnızca uzunluk açısından değil, paragraf yapıları açısından da farklıdır.

| Paragraf ölçümü | Değer |
| --- | ---: |
| En az paragraf | 2 |
| Yüzde 25 | 7 |
| Medyan | 8 |
| Yüzde 75 | 11 |
| Yüzde 90 | 13 |
| Yüzde 95 | 16 |
| Yüzde 99 | 19 |
| En fazla paragraf | 75 |
| Ortalama | 8,88 |

## Hukuki Bölüm Yapısı

Karar metinlerinin tek bir başlık şemasını izlemediği görüldü. Eski ve yeni karar biçimleri, hukuk ve ceza daireleri ile genel kurul kararlarında farklı başlıklar kullanmaktadır. Başlık tanıma işlemi, normal cümlelerde geçen “karar” veya “dava” sözcüklerini saymamak için satır başı ve başlık biçimi kurallarıyla yapıldı.

| Tanınan bölüm/işaret | Bu işareti içeren karar |
| --- | ---: |
| `İçtihat Metni` | 14.869 |
| `MAHKEMESİ:` üst bilgisi | 12.656 |
| “gereği düşünüldü/görüşülüp düşünüldü” kalıbı | 8.285 |
| `KARAR`, `K A R A R` veya `YARGITAY KARARI` başlığı | 4.842 |
| `HÜKÜM` başlığı | 3.870 |
| `DAVA` başlığı | 1.218 |
| `SONUÇ` başlığı | 787 |
| Temyiz bölümü | 679 |
| Hukuki/yargılama süreci bölümü | 560 |
| `TÜRK MİLLETİ ADINA` | 558 |
| Davacı istemi özeti | 556 |
| Gerekçe bölümü | 539 |
| Davalı cevabı özeti | 509 |
| Mahkeme kararı özeti/bölümü | 458 |
| `İNCELENEN KARARIN` | 369 |

Birçok kararda açık bölüm başlığı bulunmadığından yalnızca başlıklara dayalı bir parçalama yöntemi bütün corpus için yeterli değildir. Ayrıca kaynak metinlerin önemli bir bölümü 2.000 karakterde kesildiği için kararın sonuç veya hüküm bölümü her kayıtta mevcut olmayabilir.

## Değerlendirilen Chunking Yaklaşımları

Sabit karakter uzunluğuna göre parçalama basit ve yeniden üretilebilirdir ancak cümleleri ve hukuki gerekçeleri ortadan bölebilir. Sabit kelime veya token sayısına göre parçalama model bağlam sınırlarını daha doğrudan hedefleyebilir; buna karşılık belirli bir tokenizer'a bağımlıdır ve kullanılan embedding modeli değiştiğinde sonuçlar değişebilir.

Yalnızca paragraf veya hukuki bölüm başlıklarına göre parçalama daha anlamlı sınırlar üretir ancak Yargıtay kararlarının farklı şemaları ve çok uzun paragrafları nedeniyle üst uzunluk garantisi vermez. Cümle tabanlı yöntem anlam bütünlüğünü daha iyi korur fakat tek başına kullanıldığında çok kısa veya çok uzun parçalar oluşturabilir.

Bu nedenlerle hibrit bir yöntem seçildi: karakter uzunluğu kesin üst sınır olarak kullanıldı; bu sınır içinde paragraf ve cümle sonları tercih edildi. Çok uzun cümlelerde kelime sınırına, yalnızca hiç boşluk içermeyen yapay/bozuk bir içerikte zorunlu karakter sınırına düşüldü. Böylece modelden bağımsız ve tekrarlanabilir bir çıktı üretilirken hukuki metin yapısı mümkün olduğunca korundu.

## Geliştirilen Parçalama Modülü

`scripts/chunk_yargitay_data.py` aracı geliştirildi. Varsayılan yapılandırma:

- En fazla chunk uzunluğu: 1.200 karakter.
- Hedef örtüşme: 200 karakter.
- Çok parçalı bir kararda hedeflenen en küçük son parça: 250 karakter.

Örtüşme kesin bir sabit değildir. Modül kelimenin veya cümlenin ortasından başlamamak için en yakın yapısal sınırı seçer. Bu nedenle gerçek örtüşme bazı parçalarda 200 karakterden küçük veya büyük olabilir. Çok küçük son parçalar da önceki bağlamdan daha fazla içerik alınarak en az 250 karaktere tamamlanır.

İşlem sırası şöyledir:

1. Temiz corpus satırları UTF-8, JSON, karar kimliği, metin uzunluğu ve SHA-256 karması açısından doğrulanır.
2. Metin paragraf sınırlarına ayrılır.
3. Paragraflar Türkçe hukuk metinlerinde sık görülen kısaltmalar dikkate alınarak cümlelere ayrılır.
4. Tek başına çok uzun kalan cümleler önce kelime sınırlarından bölünür.
5. Atomik metin aralıkları 1.200 karakteri aşmayacak biçimde birleştirilir.
6. Sonraki parçanın başlangıcı yaklaşık 200 karakterlik bağlamı koruyacak en yakın cümle/paragraf sınırına taşınır.
7. Parça kimliği, karakter aralığı, sıra, toplam parça sayısı, karma ve kaynak karar metadata'sı eklenir.

Geçersiz UTF-8/JSON, tekrar karar kimliği, boş metin, yanlış metin uzunluğu, kaynak metin karması uyuşmazlığı veya beklenmeyen kayıt sayısı görülürse tamamlanmış çıktı yayımlanmadan işlem durur.

## Chunk Metadata Alanları

Her parçada temiz karar kaydındaki daire, esas/karar numarası, tarih, kaynak, lisans ve veri kalite alanları korunmaktadır. Ayrıca şu alanlar eklenmiştir:

- `id`: `karar_id:c0001` biçiminde benzersiz chunk kimliği.
- `karar_id`: parçanın ait olduğu temiz karar kimliği.
- `chunk_sirasi` ve `toplam_chunk`: karar içindeki sıralama bilgisi.
- `chunk_metni` ve `chunk_metni_sha256`: parça içeriği ve SHA-256 karması.
- `baslangic_karakteri` ve `bitis_karakteri`: temiz karar metnindeki kesin aralık.
- `karakter_sayisi`: parça uzunluğu.
- `onceki_chunk_ortusme_karakteri`: önceki parçayla gerçek örtüşme.
- `bitis_siniri`: paragraf, cümle, kelime veya zorunlu karakter sınırı.
- `bolum_isaretleri`: parçada tanınan hukuki bölüm işaretleri.
- `chunking_surum`, `chunk_boyutu_karakter` ve `hedef_ortusme_karakter`: yeniden üretilebilirlik bilgileri.

Kararın tam temiz metni her chunk içinde tekrar saklanmamıştır. Bunun yerine `karar_id`, kaynak metin karması ve kesin karakter aralığı üzerinden ilişki kurulmaktadır.

## Üretim Sonuçları

Komut:

```powershell
python scripts/chunk_yargitay_data.py
```

Yerel olarak şu dosyalar üretildi:

- `data/processed/yargitay_chunks_1200_200.jsonl`
- `data/processed/yargitay_chunks_1200_200_stats.json`

| Sonuç | Değer |
| --- | ---: |
| İşlenen temiz karar | 14.870 |
| Benzersiz karar kimliği | 14.870 |
| Üretilen chunk | 31.544 |
| Benzersiz chunk kimliği | 31.544 |
| Tek parçada kalan karar | 2.838 |
| Birden fazla parçaya ayrılan karar | 12.032 |
| Çıktı JSONL boyutu | 69.573.288 bayt |

Karar başına chunk dağılımı:

| Chunk sayısı | Karar sayısı |
| ---: | ---: |
| 1 | 2.838 |
| 2 | 7.671 |
| 3 | 4.080 |
| 4 | 281 |

Chunk uzunluğu dağılımı:

| Ölçüm | Karakter |
| --- | ---: |
| En kısa | 250 |
| Yüzde 25 | 816 |
| Medyan | 999 |
| Yüzde 75 | 1.116 |
| Yüzde 90 | 1.173 |
| Yüzde 95 | 1.189 |
| Yüzde 99 | 1.198 |
| En uzun | 1.200 |
| Ortalama | 935,33 |

İlk chunk'lar dışındaki gerçek örtüşme medyanı 185 karakter, ortalaması 247,58 karakterdir. Yapısal sınır koruması ve 250 karakterlik son parça kuralı nedeniyle en yüksek örtüşme 737 karakter olmuştur. Bu değişkenliğin arama kalitesine etkisi 12. gündeki yapılandırma karşılaştırmasında ölçülecektir.

Parçaların 23.244'ü paragraf, 6.128'i cümle ve 2.172'si kelime sonunda bitmiştir. Böylece 31.544 parçanın 29.372'si, yani yüzde 93,11'i paragraf veya cümle sınırında sonlanmıştır. Gerçek corpus üzerinde zorunlu karakter ortası kesme gerekmemiştir.

Çıktının SHA-256 değeri:

```text
fcd063fcc0f4fd532b4938d9e433682c95f53397528ed04c64315b93a5d7b04d
```

Türetilmiş chunk ve istatistik dosyaları büyük ve yeniden üretilebilir oldukları için mevcut `data/processed/yargitay_*.jsonl` ve `data/processed/yargitay_*_stats.json` kurallarıyla Git dışında tutulmaktadır.

## Bütünlük Doğrulaması

Üretimden sonra temiz corpus ve chunk çıktısı bağımsız olarak yeniden okunarak şu kontroller gerçekleştirildi:

- 14.870 kararın tamamının çıktıda en az bir parçayla temsil edildiği doğrulandı.
- 31.544 chunk kimliğinin tamamının benzersiz olduğu doğrulandı.
- Her kararda `chunk_sirasi` değerlerinin 1'den başlayıp kesintisiz ilerlediği ve `toplam_chunk` alanıyla uyuştuğu kontrol edildi.
- Her chunk metninin belirtilen başlangıç/bitiş aralığında kaynak kararın birebir alt metni olduğu doğrulandı.
- Karar metnindeki boşluk dışındaki bütün karakterlerin en az bir chunk tarafından kapsandığı doğrulandı.
- Chunk uzunluğu, SHA-256 karması ve gerçek örtüşme değerleri yeniden hesaplandı.
- Daire, esas/karar numarası, tarih, kaynak ve kalite uyarılarının karar kaydıyla aynı kaldığı kontrol edildi.
- Bölüm işaretleri yeniden hesaplandı.
- Çıktı dosyası SHA-256 değerinin istatistik dosyasıyla uyuştuğu doğrulandı.

Chunking için yedi yeni otomatik test eklendi. Testler kısa metnin tek parçada kalmasını, paragraf/cümle sınırlarının ve örtüşmenin kullanılmasını, uzun cümlede kelime ve zorunlu karakter yedek yollarını, hukuki bölüm işaretlerini, metadata/karakter aralığı/karma bütünlüğünü, geçersiz yapılandırmanın reddedilmesini ve bozuk girdide çıktı yayımlanmamasını kapsamaktadır. Önceki günlerin testleriyle birlikte toplam 65 otomatik test başarıyla geçti; Python derleme kontrolü ve `git diff --check` de tamamlandı.

## 11. Gün Sonucu

14.870 temiz Yargıtay kararının uzunluk ve paragraf yapısı ölçüldü; farklı karar şemalarında kullanılan hukuki bölüm işaretleri tanımlandı. Yalnızca sabit uzunluğa göre kör biçimde kesmek yerine paragraf, cümle ve gerektiğinde kelime sınırlarını kullanan hibrit bir chunking modülü geliştirildi.

Varsayılan 1.200 karakter ve 200 karakter hedef örtüşme ayarıyla 31.544 benzersiz parça üretildi. Her parçanın kaynak kararla ilişkisi, sırası, kesin karakter aralığı, metin karması ve kalite metadata'sı korundu; eksiksiz kapsam ve dosya bütünlüğü bağımsız kontrollerle doğrulandı. Bu çıktı 12. gündeki boyut/örtüşme karşılaştırması ve ardından embedding üretimi için temel veri kümesini oluşturmaktadır.

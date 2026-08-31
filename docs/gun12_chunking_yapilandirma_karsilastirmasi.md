# 12. Gün - Chunking Yapılandırmalarının Karşılaştırılması

## Amaç

11. günde geliştirilen hibrit chunking yöntemini farklı parça boyutu ve örtüşme değerleriyle karşılaştırmak; arama ayrıntısı, bağlam devamlılığı ve tekrar işleme yükü arasındaki dengeyi ölçmek; her parçanın kaynak Yargıtay kararıyla ilişkisinin bütün yapılandırmalarda korunduğunu doğrulamak.

Bu çalışma yalnızca karakter sayısına göre kör biçimde kesme deneyi değildir. Bütün seçeneklerde aynı paragraf, cümle ve kelime sınırı öncelikleri kullanılmış; yalnızca en büyük parça uzunluğu ile hedef örtüşme değiştirilmiştir. Böylece sonuçlardaki farkın yapılandırmadan kaynaklanması sağlanmıştır.

## Karşılaştırma Aracı

`scripts/compare_chunking_configs.py` aracı geliştirildi. Araç:

1. Temiz JSONL corpusunun UTF-8, kayıt sayısı, karar kimliği, metin uzunluğu ve SHA-256 bütünlüğünü doğrular.
2. Kararları metin uzunluğuna göre kısa, orta, uzun ve çok uzun gruplara ayırır.
3. Her uzunluk grubundan altı kararı, karar türlerini sırayla dağıtarak ve SHA-256 tabanlı sabit bir sıralamayla seçer.
4. Seçilen aynı kararları bütün chunk yapılandırmalarında işler.
5. Parça sayısı, uzunluk, gerçek örtüşme, yapısal bitiş sınırı ve tekrar kapsama maliyetini ölçer.
6. Her parçanın kaynak kimliği, metadata alanları, karakter aralığı, metin içeriği, karması, sıra bilgisi ve bölüm işaretlerini yeniden doğrular.

Varsayılan komut:

```powershell
python scripts/compare_chunking_configs.py
```

Özel yapılandırmalar da tekrarlanan `--config BOYUT:ÖRTÜŞME:EN_AZ` argümanıyla çalıştırılabilir:

```powershell
python scripts/compare_chunking_configs.py --config 1000:150:250 --config 1200:200:250
```

Yerel ayrıntılı deney çıktısı `data/processed/yargitay_chunk_config_comparison_stats.json` dosyasına yazılır. Bu dosya temiz corpustan yeniden üretilebildiği için mevcut `data/processed/yargitay_*_stats.json` kuralıyla Git dışında tutulmaktadır.

## Temsilî Örneklerin Seçimi

Karşılaştırma, `data/processed/yargitay_clean_14870.jsonl` içindeki 14.870 doğrulanmış karar arasından seçilen 24 karar üzerinde gerçekleştirildi. Kaynak corpus dosyasının SHA-256 değeri:

```text
9ee5f11d0f38ea82ac61e6916c09beedd8d741112fe797eeb764f2343d257999
```

Uzunluk katmanları:

| Uzunluk grubu | Karakter aralığı | Örnek karar |
| --- | ---: | ---: |
| Kısa | 0-800 | 6 |
| Orta | 801-1.200 | 6 |
| Uzun | 1.201-1.800 | 6 |
| Çok uzun | 1.801 ve üzeri | 6 |

Seçilen örneklerde 11 ceza, 8 hukuk ve 5 kurul kararı bulunmaktadır. Dört örnek, kaynak corpusun 2.000 karakter sınırı uyarısını taşımaktadır. Bu uyarı deney sırasında silinmemiş; parça metadata'sında korunmuştur.

Örnek seçiminde Python'un süreçler arasında değişebilen yerleşik `hash()` sonucu kullanılmamıştır. Karar kimliği ile kaynak metin karmasından SHA-256 anahtarı üretilerek aynı corpus ve aynı ayarlarla her çalıştırmada aynı 24 kararın seçilmesi sağlanmıştır.

## Karşılaştırılan Yapılandırmalar

Üç chunk boyutu ile üç hedef örtüşme değeri çaprazlanarak dokuz yapılandırma karşılaştırıldı:

| Chunk boyutu | Hedef örtüşmeler | En küçük son chunk hedefi |
| ---: | --- | ---: |
| 800 | 100, 200, 300 | 250 |
| 1.200 | 100, 200, 300 | 250 |
| 1.600 | 100, 200, 300 | 250 |

Hedef örtüşme kesin bir karakter sayısı değildir. Parçaların kelime veya cümle ortasında başlamaması ve çok küçük son parçaların önlenmesi önceliklidir. Bu nedenle raporda yapılandırma değeriyle birlikte gerçekleşen örtüşmenin dağılımı da ölçülmüştür.

## Ölçülen Değerler

- **Parça sayısı:** Aynı 24 kararın kaç chunk ürettiğini ve karar başına ortalamayı gösterir.
- **Medyan chunk uzunluğu:** Tipik parçanın karakter uzunluğunu gösterir.
- **Yapısal sınır oranı:** Paragraf veya cümle sonunda biten parçaların bütün parçalara oranıdır.
- **Tekrar kapsama oranı:** Örtüşme nedeniyle birden fazla chunk tarafından tekrar kapsanan kaynak karakterlerin, en az bir kez kapsanan kaynak karakterlere oranıdır.
- **Gerçek örtüşme dağılımı:** İlk chunk dışındaki parçaların önceki parçayla fiilen ortak karakter sayısıdır.
- **Bütünlük:** Kaynak metadata, kesin karakter aralığı, metin, karma, sıra, toplam chunk ve bölüm işaretlerinin yeniden hesaplanmasıdır.

Bu ölçümler henüz embedding tabanlı arama doğruluğunu göstermez. Semantik benzerlik davranışı 13. günde embedding modeliyle ayrıca test edilecektir. Buradaki amaç, embedding öncesinde teknik olarak dengeli ve güvenilir aday ayarı belirlemektir.

## Karşılaştırma Sonuçları

| Yapılandırma | Chunk | Karar başına ortalama | Tek chunk kalan karar | Medyan uzunluk | Paragraf/cümle sınırı | Tekrar kapsama |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 800/100 | 64 | 2,67 | 6 | 627 | %81,25 | %30,95 |
| 800/200 | 65 | 2,71 | 6 | 627 | %81,54 | %35,39 |
| 800/300 | 66 | 2,75 | 6 | 632 | %81,82 | %39,00 |
| 1.200/100 | 38 | 1,58 | 12 | 946 | %92,11 | %12,19 |
| **1.200/200** | **38** | **1,58** | **12** | **949** | **%92,11** | **%13,41** |
| 1.200/300 | 39 | 1,62 | 12 | 949 | %92,31 | %15,67 |
| 1.600/100 | 32 | 1,33 | 17 | 991 | %96,88 | %7,33 |
| 1.600/200 | 32 | 1,33 | 17 | 991 | %96,88 | %7,95 |
| 1.600/300 | 32 | 1,33 | 17 | 991 | %96,88 | %8,89 |

### 800 Karakterlik Yapılandırmalar

800 karakterlik ayarlar en yüksek arama ayrıntısını sağlayabilecek en fazla sayıda parçayı üretmiştir. Ancak 64-66 chunk oluşmuş, paragraf/cümle sınırı oranı yaklaşık yüzde 81'de kalmış ve kelime sonuna düşme sayısı artmıştır. Örtüşme yükseldikçe tekrar kapsama yükü yüzde 30,95'ten yüzde 39'a çıkmıştır. Bu seçenekler embedding ve vektör veritabanı maliyetini artırırken hukuki gerekçeyi daha küçük parçalara bölme riski taşımaktadır.

### 1.600 Karakterlik Yapılandırmalar

1.600 karakterlik ayarlar yalnızca 32 chunk üretmiş ve yüzde 96,88 ile en yüksek yapısal sınır oranına ulaşmıştır. Tekrar kapsama maliyeti de en düşüktür. Buna karşılık 24 örneğin 17'si tek chunk olarak kalmıştır. Kaynak metinlerin önemli bölümünün yaklaşık 2.000 karakterle sınırlı olduğu bu corpusta 1.600 karakterlik parçalar, karar içindeki olay-gerekçe-hüküm ayrımını semantik aramada yeterince ayrıntılı temsil etmeyebilir.

### 1.200 Karakterlik Yapılandırmalar

1.200 karakterlik ayarlar 38-39 chunk üretmiş; medyan uzunluğu 946-949 karakter ve yapısal sınır oranını yüzde 92'nin üzerinde tutmuştur. Böylece 800 karaktere göre belirgin biçimde daha az parçalanma ve tekrar yükü oluşurken, 1.600 karaktere göre daha fazla karar iki veya üç anlamlı arama birimine ayrılmıştır.

1.200/100 ve 1.200/200 yapılandırmaları aynı sayıda chunk üretmiştir. 100 karakter hedefinde gerçek örtüşmenin yüzde 25 değeri 54 karakterde kalırken, 200 karakter hedefinde 170 karaktere yükselmiştir. Buna karşılık tekrar kapsama maliyeti yalnızca yüzde 12,19'dan yüzde 13,41'e çıkmıştır. 300 karakter hedefi ise bir ek chunk ve yüzde 15,67 tekrar yükü oluşturmuş, yapısal sınır oranında yalnızca 0,20 puan artış sağlamıştır.

## Seçilen Yapılandırma

Sonraki embedding ve vektör veritabanı aşamaları için **1.200 karakter chunk boyutu, 200 karakter hedef örtüşme ve 250 karakter en küçük son chunk hedefi** korunmuştur.

Seçim gerekçeleri:

- 949 karakterlik medyan, hukuki olay ve gerekçe bağlamını koruyacak kadar geniştir.
- Kararların yarısı birden fazla arama parçasına ayrılarak 1.600 karaktere göre daha ayrıntılı erişim sağlar.
- Parçaların yüzde 92,11'i paragraf veya cümle sonunda tamamlanmıştır.
- Yüzde 13,41 tekrar kapsama yükü, 800 karakterlik seçeneklerin yükünden belirgin biçimde düşüktür.
- 100 karakter hedefe kıyasla düşük örtüşmeli parçaların bağlamı iyileşmiş; 300 karakter hedefe göre gereksiz tekrar sınırlanmıştır.

Bu karar, semantik doğruluk için son hüküm değildir. 13. günde aynı embedding modeliyle benzer ve ilgisiz metinlerin vektör yakınlıkları ölçülecek; 17. gündeki arama iyileştirmelerinde chunk boyutu yeniden değerlendirilebilecektir.

## Kaynak İlişkisi ve Bütünlük Doğrulaması

Dokuz yapılandırmada toplam 406 örnek chunk incelendi. Kaynak kararlardan kopyalanan bütün metadata alanları için toplam 7.308 alan eşitliği kontrolü gerçekleştirildi.

Her chunk için şu doğrulamalar geçti:

- `karar_id`, `chunk_sirasi` ve `toplam_chunk` değerleri.
- `daire`, `esas_no`, `karar_no` ve `karar_tarihi` metadata'sı.
- Kaynak, kaynak URL'si, lisans ve kaynak kayıt kimliği.
- Kaynak karar metninin SHA-256 değeri.
- `baslangic_karakteri` ve `bitis_karakteri` aralığının kaynak metindeki birebir karşılığı.
- Chunk metni uzunluğu ve SHA-256 değeri.
- Önceki chunk ile gerçekleşen örtüşme.
- Hukuki bölüm işaretlerinin kaynak metinle aynı kalması.
- Kaynak metindeki boşluk dışı bütün karakterlerin en az bir chunk tarafından kapsanması.

Tam kaynak karar metni deney raporundaki her chunk içinde tekrar saklanmamıştır. İlişki; karar kimliği, kaynak metin karması, kesin karakter aralığı ve kısa önizleme üzerinden kurulmuştur. Bütün dokuz yapılandırmada bütünlük sonucu başarılıdır.

## Otomatik Testler

`tests/test_compare_chunking_configs.py` dosyasına altı yeni test eklendi. Testler:

- Komut satırı yapılandırma biçimini.
- Uzunluk katmanlarından deterministik örnek seçimini.
- Farklı karar türlerinin sırayla seçilmesini.
- Yapılandırmalar arasındaki ölçümlerin üretilmesini.
- Kaynak metadata, kimlik, sıra, metin aralığı ve karma bağlantısını.
- Atomik rapor yazımını ve geçersiz/tekrar yapılandırmaların reddedilmesini kapsar.

11. gün chunking testleriyle birlikte yeni modüle ait 13 test başarıyla geçmiştir. Önceki günlerin testleri de dahil edilerek çalıştırılan tam test paketinde toplam 71 test başarıyla tamamlanmıştır. Python derleme kontrolü ve `git diff --check` doğrulaması da geçmiştir.

## 12. Gün Sonucu

Kısa, orta, uzun ve çok uzun Yargıtay kararlarından oluşan 24 temsilî örnek üzerinde dokuz chunk boyutu/örtüşme yapılandırması karşılaştırıldı. Parçalanma miktarı, yapısal sınır koruması, gerçek örtüşme ve tekrar işleme yükü sayısal olarak ölçüldü.

Kaynak karar bağlantısı bütün yapılandırmalarda eksiksiz korundu. 1.200/200 yapılandırması, hukuki bağlamı koruma ile semantik arama ayrıntısı arasında en dengeli teknik aday olarak seçildi ve 13. gündeki embedding deneyleri için sabitlendi.

# 17. Gün - Semantik Arama Kalitesinin Ölçülmesi ve İyileştirilmesi

## Amaç

31.544 parçalık gerçek Qdrant indeksinde semantik aramanın davranışını ölçmek; farklı `top_k`, benzerlik eşiği, metadata filtresi ve chunk boyutu seçeneklerini aynı sorgular üzerinde karşılaştırmak; sonuç çeşitliliğini ve yetersiz kaynak durumunun görünürlüğünü iyileştirmek.

## Uygulama Değişiklikleri

Semantik arama isteğine isteğe bağlı `min_score` alanı ile dört kesin eşleşmeli metadata filtresi eklendi: `karar_turu`, `daire`, `veri_kalite_durumu` ve `metin_2000_karakter_sinirinda`. Bilinmeyen filtre alanları, boş değerler, desteklenmeyen karar/kalite türleri ve `-1` ile `1` aralığı dışındaki eşikler reddedilir. Eşik sonrasında sonuç kalmazsa API bunu `yeterli_sonuc_bulundu: false` ve boş `sonuclar` listesiyle açıkça bildirir; düşük skorlu sonuçları zorla yeterli kaynak gibi göstermez.

Bir kararın birden çok chunk'ının sonuç listesini doldurmasını önlemek için istenen `top_k` değerinin beş katı kadar aday chunk aranır ve her `karar_id` için yalnızca en yüksek skorlu chunk tutulur. Böylece API sonucu chunk düzeyinde tekrar eden kayıtlar yerine benzersiz kararlar sunar. Aranan aday sayısı yanıttaki `aranan_aday_chunk_sayisi` alanında görünürdür.

## Tekrarlanabilir Değerlendirme

LM Studio ve yerel Qdrant kullanılabilirken deney şu komutla yeniden çalıştırılabilir:

```powershell
python scripts/evaluate_semantic_search_quality.py
```

Araç, işe iade, tapu iptali/tescil ve uyuşturucu ticareti için daha önce doğrulanmış üç çapa kararı; Yargıtay corpusunun kapsamı dışındaki vergi tarhiyatı, memur ataması ve imar planı uyuşmazlıklarına ilişkin üç alan dışı hukuki sorguyla birlikte değerlendirir. Arama sonuçları aynı karara ait chunk tekrarları çıkarılarak karar düzeyinde ölçülür. Çıktı `data/processed/yargitay_semantic_search_day17_stats.json` dosyasına atomik olarak yazılır ve türetilmiş veri olduğu için Git'e eklenmez.

## Gerçek İndeks Sonuçları

Tam 31.544 noktalı indeks doğrulandı. Eşiksiz çapa karar geri çağırma oranı `top_k=1`, `3` ve `5` için `1/3`; `top_k=10` ve `20` için `2/3` oldu. On sonuçta MRR `0,370370` ölçüldü. Bu metrik yalnızca önceden seçilmiş çapa kararın bulunmasını ölçer; üst sıralardaki başka bir kararın hukuken ilgisiz olduğunu tek başına göstermez.

| Ayar | İlgili çapa kararı | Alan dışı ret | Dengeli doğruluk |
|---|---:|---:|---:|
| `top_k=10`, `min_score=0,65` | 2/3 | 2/3 | %66,67 |

Deney ızgarasında en dengeli sonuç `top_k=10` ve `min_score=0,65` ile elde edildi. Alan dışı vergi ve imar sorguları eşik altında kaldı; memur atama sorgusu `0,658564` skoruyla eşiği az farkla geçti. Bu nedenle `0,65` zorunlu üretim varsayılanı yapılmadı; doğrulanmış bir istemci tarafından risk toleransına göre seçilebilen isteğe bağlı bir eşik olarak bırakıldı.

## Metadata Filtresi Karşılaştırması

Karar türü filtresi `top_k=5` çapa geri çağırmasını değiştirmedi (`1/3`). Doğru daire önceden bilindiğinde kesin `daire` filtresi üç çapa kararı da ilk sıraya taşıdı (`3/3`, MRR `1,0`). Daire filtresi güçlüdür ancak kullanıcının daireyi güvenle bildiği iş akışlarıyla sınırlı tutulmalıdır; yanlış daire seçimi ilgili kararı tamamen dışlayabilir.

## Chunk Boyutu Karşılaştırması

Tam indeksin ilgili sorgulardaki ilk on kararından oluşturulan 31 gerçek kararlık zor-negatif havuzunda 200 karakter örtüşme sabit tutularak üç boyut yeniden chunk'landı ve LM Studio ile tekrar vektörleştirildi.

| Chunk/örtüşme | Chunk sayısı | Çapa recall@5 | MRR |
|---|---:|---:|---:|
| 800/200 | 128 | 2/3 | 0,666667 |
| 1200/200 | 79 | 1/3 | 0,333333 |
| 1600/200 | 60 | 0/3 | 0,000000 |

Bu dar zor-negatif deney 800/200 ayarının daha ayrıntılı semantik eşleşme sağlayabildiğini gösterdi. Ancak yalnızca 31 karar ve üç çapa sorgu kullanıldığı için mevcut 31.544 noktalı 1200/200 indeks değiştirilmedi. 800/200, daha geniş etiketli bir değerlendirme ve yeniden indeksleme maliyeti ölçümü için aday yapılandırma olarak kaydedildi.

## Bruno Doğrulaması

`bruno/03-semantic-search-threshold-filter.bru` isteği `min_score=0,65` ile hukuk türü ve `7. Hukuk Dairesi` filtrelerini birlikte sınar. Testler HTTP durumunu, eşik/filtre yankısını, benzersiz karar kimliklerini ve her sonucun eşik ile metadata koşullarına uyduğunu doğrular. `metin_2000_karakter_sinirinda=false` filtresi ayrıca desteklenmekle birlikte bu örneğe eklenmedi; çünkü çapa kararın kaynak metni 2.000 karakterde kesilmiş olarak işaretlidir ve filtre onu bilinçli biçimde dışarıda bırakır.

Aynı istek güncel FastAPI servisine gerçek LM Studio ve Qdrant bağımlılıklarıyla gönderildi: API sürümü `1.1.0`, HTTP durumu `200`, sonuç sayısı `5` ve benzersiz karar sayısı `5` oldu. İlk sonuç `d1113966700:c0001`, skor `0,719056` ve daire `7. Hukuk Dairesi` olarak doğrulandı. Bruno 4.0.0 koleksiyonu yeni isteği yükledi; bu çalışma oturumundaki Windows otomasyon yardımcısı tıklama girdisinde erişim engeli verdiği için masaüstü `Send` eylemi otomatik tetiklenemedi. İsteğin kendisi ve testleri Bruno'da hazırdır; canlı uç nokta aynı gövdeyle ayrıca doğrulanmıştır.

## Sonuç

17. günde semantik arama yalnızca yakın chunk döndüren ilk sürümden; eşik, güvenli metadata filtreleri, benzersiz karar çeşitlendirmesi ve yetersiz sonuç bildirimi sunan ölçülebilir bir arama katmanına dönüştürüldü. Altı sorguluk deney yararlı bir geliştirme sinyali sağladı fakat üretim doğruluğu iddiası oluşturmaz; sonraki genişletmede daha çok uzman etiketli sorgu ve birden fazla kabul edilebilir karar etiketi kullanılmalıdır.

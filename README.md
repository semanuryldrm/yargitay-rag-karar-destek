# RAG Tabanlı Yargıtay Karar Araştırma ve Hukuki Karar Destek Sistemi

## Proje Hakkında

Bu proje, Yargıtay'ın kamuya açık karar metinleri üzerinde çalışan RAG tabanlı bir hukuki karar destek sistemi geliştirmeyi amaçlamaktadır.

Yaklaşık 15.000 Yargıtay kararının toplanması, temizlenmesi, anlamlı parçalara ayrılması, embedding vektörlerinin oluşturulması ve bir vektör veritabanında indekslenmesi planlanmaktadır.

Kullanıcı hukuki olayını doğal dille yazdığında sistem:

1. Kullanıcı sorgusunu embedding vektörüne dönüştürecektir.
2. Benzer Yargıtay karar parçalarını vektör veritabanından bulacaktır.
3. İlgili kararları metadata bilgileriyle birlikte getirecektir.
4. Getirilen kaynakları yerel Gemma modeline aktaracaktır.
5. Kaynaklara dayalı ve açıklayıcı bir cevap üretecektir.

## Projenin Kapsamı

Bu sistem otomatik hüküm veren veya kesin hukuki sonuç bildiren bir uygulama değildir.

Amaç, kullanıcının anlattığı olaya benzer Yargıtay kararlarını bulmak, ilgili kararları özetlemek ve kullanılan kaynakları kullanıcıya göstermektir.

Yeterli veya güvenilir kaynak bulunamadığında sistemin bu durumu açıkça belirtmesi hedeflenmektedir.

## Planlanan Teknolojiler

- Python 3.12
- FastAPI
- LM Studio
- Gemma 4 12B QAT
- LM Studio embedding modeli
- Qdrant vektör veritabanı (yerel kalıcı mod)
- Bruno API test aracı
- Git ve GitHub

## Donanım

Yerel model ve embedding işlemlerinde NVIDIA GeForce RTX 5060 Ti 16 GB ekran kartı kullanılacaktır.

## Proje Klasörleri

- `app/`: Uygulama ve FastAPI kaynak kodları
- `data/raw/`: Ham Yargıtay karar verileri
- `data/processed/`: Temizlenmiş ve işlenmiş veriler
- `scripts/`: Veri çekme ve yardımcı komut dosyaları
- `tests/`: Test kodları
- `logs/`: Uygulama ve hata kayıtları
- `docs/`: Teknik belgeler ve proje notları

## Mevcut Durum

- Projenin amacı ve kapsamı belirlendi.
- Temel kullanıcı senaryosu oluşturuldu.
- LM Studio kuruldu.
- Gemma 4 12B QAT modeli Türkçe soru-cevap ile test edildi.
- Embedding modelleri indirildi.
- Python 3.12 sanal ortamı oluşturuldu.
- Yerel Git deposu başlatıldı.
- Temel proje klasör yapısı oluşturuldu.
- Yargıtay liste ve detay uç noktaları Python ile canlı olarak doğrulandı.
- En fazla 10 kararlık örnek JSONL üretme komutu ve HTTP istemcisi hazırlandı.
- Liste ve detay cevaplarını doğrulayıp standart ham karar kaydına dönüştüren bir sayfalık veri çekme modülü geliştirildi.
- Veri çekme akışına yeniden deneme, kontrollü bekleme, loglama, tekrar kayıt engelleme ve kaldığı yerden devam özellikleri eklendi.
- Farklı sayfalardaki Hukuk ve Ceza Dairesi kararlarıyla veri kalitesi testleri yapıldı; metadata alanları standartlaştırıldı ve `karar_turu` alanı eklendi.
- Eksik alan, kısa/boş sayfa, HTML olmayan veya görünür metni bulunmayan detay, bozuk UTF-8 ve bağlantı kesintisi senaryolarına karşı doğrulamalar geliştirildi.
- Toplu çekim için hedef kayıt sayısı, kalıcı başarı/başarısızlık sayaçları, hata günlüğü, sorgu yapılandırmalı devam dosyası, uyarlanabilir hız sınırı beklemesi ve CAPTCHA'da güvenli duruş eklendi.
- Resmî servisteki hız sınırı ve CAPTCHA engeli aşılmadan durduruldu; kullanıcı onayıyla CC BY 4.0 lisanslı TurkLegalBench corpusundaki 15.000 benzersiz Yargıtay kaydı kaynak bilgileri korunarak yerel ham veri biçimine aktarıldı.
- Ham veri kümesi temizlenip standartlaştırıldı; aynı daire-esas-karar kimliğine sahip 130 mükerrer kayıt denetim iziyle ayrıldı ve 14.870 kayıtlık temiz corpus oluşturuldu.
- Eksik metadata, kaynakta 2.000 karakterle sınırlı metin ve farklı kararlarda tekrarlanan metinler silinmeden kalite uyarılarıyla görünür hâle getirildi.
- Karar uzunlukları, paragraf yapıları ve yaygın hukuki bölüm başlıkları analiz edildi; paragraf ve cümle sınırlarını önceleyen hibrit chunking modülü geliştirildi.
- 14.870 temiz karar, varsayılan 1.200 karakter ve 200 karakter hedef örtüşme ayarıyla 31.544 bütünlüğü doğrulanmış parçaya ayrıldı.
- Kısa, orta, uzun ve çok uzun metinlerden seçilen 24 temsilî kararda dokuz chunk boyutu/örtüşme yapılandırması karşılaştırıldı; kaynak metadata ve metin bağlantısı bütün yapılandırmalarda doğrulandı.
- 1.200 karakter ve 200 karakter hedef örtüşme ayarı, arama ayrıntısı, yapısal sınır koruması ve tekrar yükü arasındaki denge nedeniyle sonraki aşamalar için korundu.
- LM Studio için doğrulamalı bir embedding istemcisi ile kosinüs benzerliği ve sıralama yardımcıları geliştirildi.
- Üç hukuki kullanıcı sorgusu ve üç gerçek Yargıtay parçası `text-embedding-embeddinggemma-300m` modeliyle 768 boyutlu vektörlere dönüştürüldü; ilgili parça üç sorgunun tamamında ilk sırada bulundu.
- Qdrant 1.19.0 yerel kalıcı modda kuruldu; `yargitay_karar_parcalari` koleksiyonu 768 boyut ve Cosine uzaklık yöntemiyle oluşturuldu.
- Karar bağlantısı, hukuk metadata'sı, kaynak/lisans, veri kalitesi ve embedding bilgilerini kapsayan 22 alanlı payload şeması tanımlandı; gerçek karar parçalarıyla ekleme, okuma, silme, geri yükleme ve benzerlik sorguları doğrulandı.
- 31.544 temiz karar parçasının tamamı LM Studio ile 128 kayıttan oluşan batch'ler hâlinde vektörleştirilip metadata bilgileriyle Qdrant'a kaydedildi.
- Toplu indeksleme akışına atomik ilerleme durumu, kaldığı yerden devam, üç denemeli hata yönetimi, başarısız batch günlüğü ve son kayıt sayısı/payload karma doğrulaması eklendi; gerçek çalıştırma 247 batch ve sıfır hatayla tamamlandı.
- Kullanıcının doğal dille anlattığı hukuki olayı LM Studio ile embedding'e dönüştürüp 31.544 noktalı Qdrant koleksiyonunda en yakın karar parçalarını bulan doğrulamalı semantik arama servisi geliştirildi.
- Semantik arama FastAPI'ye bağlandı; sağlık ve arama uç noktaları Bruno koleksiyonuyla gerçek yerel servis üzerinde `200 OK` yanıtları alınarak doğrulandı.
- Semantik aramaya isteğe bağlı skor eşiği ve güvenli metadata filtreleri eklendi; aynı karara ait tekrar eden chunk'lar tek sonuca indirildi ve yetersiz sonuç durumu açık hâle getirildi.
- Altı hukuki sorguyla `top_k`, eşik ve filtre seçenekleri gerçek 31.544 noktalı indekste; üç chunk boyutu ise 31 kararlık zor-negatif havuzda karşılaştırıldı.
- Bulunan kararları `[K1]` biçiminde etiketleyip Gemma 4 12B QAT modeline aktaran kaynaklı RAG cevap zinciri geliştirildi; yetersiz kaynakta model çağrılmadan güvenli duruş sağlandı.
- Gemma çıktılarında geçerli kaynak etiketi, reasoning'in kapalı olması, kesin sonuç vermeme ve zorunlu hukuki uyarı kuralları uygulama katmanında doğrulandı.
- FastAPI servisleri `1.4.0` sürümünde tamamlandı; canlı embedding, Qdrant ve Gemma denetimi yapan sistem durumu uç noktası ile standart `422` istek doğrulama yanıtları eklendi.
- Boş, 4.000 karakterlik, aşırı uzun, hatalı ve normal sorgular gerçek yerel servis üzerinde sınandı; Bruno koleksiyonundaki dokuz isteğin tamamı geçti ve yeniden çalıştırılabilir uçtan uca test aracı eklendi.
- On kapsam içi ve beş alan dışı olaydan oluşan sabit test setiyle `top_k`/eşik ayarları değerlendirildi; RAG varsayılanı `top_k=10`, `min_score=0,65` olarak güncellendi.
- Dört chunk ayarı 102 gerçek kararlık zor-negatif havuzda karşılaştırıldı; 800/200 tam yeniden indeksleme için aday seçilirken sınırlı deney nedeniyle mevcut 1.200/200 indeksi korundu.
- RAG promptu `1.1` sürümüne çıkarıldı; veri kalitesi sınırlaması açıklaması ve geçersiz model çıktısında tek seferlik güvenli yeniden üretim eklendi.

## Toplu Veri Kaynağı

Projede doğrudan Yargıtay servisinden alınmış küçük doğrulama örnekleri ile haricî toplu corpus birbirinden ayrı tutulmaktadır. Toplu corpus [IremTRNL/TurkLegalBench](https://huggingface.co/datasets/IremTRNL/TurkLegalBench) kaynağından alınmıştır ve CC BY 4.0 lisansına tabidir. Her dönüştürülmüş kayıtta kaynak adı, bağlantısı, lisansı ve kaynak kayıt kimliği bulunmaktadır.

TurkLegalBench dosyası düz metin sunmaktadır; bu nedenle kayıtlar resmî servisten gelen `karar_html` alanına dönüştürülmemiş, `karar_metni` alanında saklanmıştır. 15.000 metnin 8.355'i kaynakta tam olarak 2.000 karakter uzunluğundadır ve bazıları cümle ortasında bitmektedir. Bu kayıtlar tam karar metni olarak varsayılmamalı; `metin_2000_karakter_sinirinda` alanı sonraki işleme aşamalarında dikkate alınmalıdır. Ayrıntılar `docs/gun9_toplu_veri_kumesi.md` dosyasındadır.

Kaynak corpusu indirip dosya karmasını doğrulamak ve 15.000 kaydı yeniden oluşturmak için:

```powershell
python scripts/import_turklegalbench.py --download
```

## Veri Temizleme

Ham corpus aşağıdaki komutla temizlenebilir ve veri bütünlüğü çıktıları yeniden üretilebilir:

```powershell
python scripts/clean_yargitay_data.py
```

İşlem UTF-8/JSON ve zorunlu alan doğrulaması yapar; HTML kalıntılarını, HTML karakter referanslarını, Unicode özel boşluklarını, gereksiz yatay boşlukları ve kaynak başındaki hatalı tırnağı temizler; metinleri Unicode NFC biçimine getirir. Mükerrerlik yalnızca `daire`, `esas_no` ve `karar_no` üçlüsü aynı olduğunda uygulanır. Aynı metne sahip farklı kararlar hukuken ayrı kayıt olabilecekleri için korunur ve kalite uyarısıyla işaretlenir.

Yerel olarak üretilen `data/processed/yargitay_clean_14870.jsonl` dosyasında 14.870 benzersiz karar kaydı bulunmaktadır. Temiz corpus, mükerrer kayıt denetimi ve istatistik dosyaları büyük/türetilmiş veri oldukları için Git'e eklenmez. Yöntem ve doğrulama sonuçları `docs/gun10_veri_temizleme_ve_butunluk.md` dosyasındadır.

## Karar Metinlerini Parçalama

Temiz corpus aşağıdaki komutla RAG sistemine uygun parçalara ayrılabilir:

```powershell
python scripts/chunk_yargitay_data.py
```

Varsayılan yöntem en fazla 1.200 karakterlik parçalar üretir ve parçalar arasında 200 karakter civarında bağlam örtüşmesi hedefler. Önce paragraf ve cümle sonları, bunlar yeterli olmadığında kelime sınırları kullanılır; yalnızca kesintisiz çok uzun bir metinde zorunlu karakter sınırına düşülür. Her parçanın kaynak kararı, sırası, karakter aralığı, metin karması, bölüm işaretleri ve tüm karar metadata'sı korunur.

Yerel `data/processed/yargitay_chunks_1200_200.jsonl` çıktısında 31.544 parça bulunmaktadır. Yöntemin geliştirilmesi ve corpus sonuçları `docs/gun11_karar_metinlerini_parcalama.md` dosyasındadır.

## Chunking Yapılandırması Karşılaştırması

Farklı chunk boyutu ve hedef örtüşme değerleri aşağıdaki komutla karşılaştırılabilir:

```powershell
python scripts/compare_chunking_configs.py
```

Araç, temiz corpus içinden kısa, orta, uzun ve çok uzun metin gruplarından deterministik örnekler seçer. Karar türü çeşitliliğini koruyarak 24 örnek üzerinde 800, 1.200 ve 1.600 karakterlik chunk boyutlarını; 100, 200 ve 300 karakterlik hedef örtüşmelerle çapraz karşılaştırır. Her yapılandırmada parça sayısı, uzunluk dağılımı, gerçek örtüşme, paragraf/cümle sınırı oranı ve tekrar kapsama yükü ölçülür.

Karşılaştırmada 1.200/200 ayarı; 949 karakterlik medyan parça uzunluğu, yüzde 92,11 paragraf/cümle sınırı oranı ve yüzde 13,41 tekrar kapsama yüküyle dengeli sonuç vermiştir. 800 karakterlik seçenekler fazla parçalanma ve daha yüksek tekrar yükü oluştururken, 1.600 karakterlik seçenekler örneklerin çoğunu tek parçada bırakarak semantik arama ayrıntısını azaltmıştır. Daire, esas numarası, karar numarası, tarih, kaynak metin karması ve kesin karakter aralıkları bütün yapılandırmalarda doğrulanmıştır. Ayrıntılar `docs/gun12_chunking_yapilandirma_karsilastirmasi.md` dosyasındadır.

## LM Studio Embedding Değerlendirmesi

LM Studio yerel sunucusu çalışırken gerçek Yargıtay parçalarıyla embedding değerlendirmesi şu komutla yürütülebilir:

```powershell
python scripts/evaluate_legal_embeddings.py
```

`scripts/lmstudio_embeddings.py`; `/v1/models` ve `/v1/embeddings` uç noktalarına UTF-8 batch istekleri gönderir. Model kimliği, cevap sayısı, sıra indeksleri, vektör boyutları, sayısal sonluluk ve sıfır olmayan vektör normları doğrulanmadan embedding sonucu kullanılmaz. Kullanıcı sorguları ile karar parçaları aynı `text-embedding-embeddinggemma-300m` modeliyle vektörleştirilir ve kosinüs benzerliğiyle sıralanır.

İşe iade, tapu iptali/tescil ve uyuşturucu ticareti konularındaki üç kullanıcı sorgusu; aynı konulardan seçilmiş üç gerçek Yargıtay chunk'ıyla karşılaştırılmıştır. Model 768 boyutlu vektörler üretmiş ve beklenen ilgili parça üç sorgunun tamamında ilk sırada yer almıştır. Ortalama ilgili-ilgisiz skor farkı 0,233831'dir. Bu küçük kontrollü deney bir genel doğruluk veya üretim eşiği ölçümü değildir; sonraki günlerde daha geniş test seti ve vektör veritabanı aramasıyla geliştirilecektir. Ayrıntılar `docs/gun13_lmstudio_embedding_degerlendirmesi.md` dosyasındadır.

## Qdrant Vektör Veritabanı

Bağımlılıkları proje sanal ortamına kurmak için:

```powershell
python -m pip install -r requirements.txt
```

LM Studio sunucusu ve embedding modeli çalışırken 14. gün koleksiyon ve işlem doğrulaması şu komutla yürütülebilir:

```powershell
python scripts/validate_qdrant_vector_store.py
```

Araç `data/vector_store/qdrant` altında yerel ve kalıcı Qdrant veritabanını açar. `yargitay_karar_parcalari` koleksiyonunun 768 boyutlu `text-embedding-embeddinggemma-300m` vektörleri ile Cosine uzaklık yöntemini kullandığını doğrular. Koleksiyon veya embedding modeli uyumsuzsa mevcut veriyi sessizce kullanmaz.

Üç gerçek Yargıtay parçası üzerinde upsert, kimlikle okuma, silme ve geri yükleme işlemleri başarıyla doğrulanmıştır. Aynı üç hukuki sorgunun her birinde beklenen karar parçası Qdrant benzerlik aramasında ilk sırada bulunmuştur. Ayrıntılar `docs/gun14_qdrant_vektor_veritabani.md` dosyasındadır. Tam 31.544 parçanın toplu embedding ve kayıt işlemi 15. günde tamamlanmıştır.

## Toplu Embedding ve Qdrant İndeksleme

LM Studio embedding modeli çalışırken temizlenmiş karar parçalarının tamamı şu komutla kaldığı yerden devam edebilen batch'ler hâlinde indekslenebilir:

```powershell
python scripts/index_yargitay_chunks.py
```

Araç işlem başlamadan önce 31.544 kaynak kaydın UTF-8/JSON biçimini, benzersiz chunk kimliklerini, zorunlu alanlarını, isteğe bağlı hukuki metadata değerlerini, metin uzunluklarını ve SHA-256 karmalarını doğrular. Varsayılan 128 parçalık her batch LM Studio'da vektörleştirilip Qdrant'a yazıldıktan sonra ilerleme durumu atomik olarak kaydedilir. Başarısız bir batch üç kez denenir, her deneme `logs/day15_embedding_failures.jsonl` dosyasına yazılır ve batch atlanmadan işlem durur; sonraki çalıştırma ilk tamamlanmamış satırdan devam eder.

Gerçek çalıştırmada `text-embedding-embeddinggemma-300m` modeliyle 768 boyutlu 31.544 vektör, 247 batch içinde `yargitay_karar_parcalari` koleksiyonuna kaydedildi. İşlem 717,227 saniye sürdü ve saniyede ortalama 43,98 parça işlendi. Başarısız deneme oluşmadı; koleksiyonun kesin kayıt sayısı kaynak sayısıyla eşleşti ve ilk, orta, son örneklerin payload metin karmaları doğrulandı. Kaynakta eksik olan `esas_no`, `karar_no` veya `karar_tarihi` değerleri uydurulmadan `null` olarak, ilgili kalite uyarılarıyla birlikte korundu.

Qdrant istemcisi yerel modda 20.000 üzerindeki koleksiyonlar için performans uyarısı verir. Mevcut 31.544 noktalı geliştirme indeksi doğrulanmış ve kullanılabilir durumdadır; daha yüksek ölçek veya üretim performansı gerektiğinde aynı koleksiyon şemasıyla Qdrant sunucu/Docker moduna geçilmesi değerlendirilmelidir. Ayrıntılar `docs/gun15_toplu_embedding_ve_qdrant_indeksleme.md` dosyasındadır.

## Semantik Arama API'si ve Bruno Testleri

LM Studio'da `text-embedding-embeddinggemma-300m` modeli açıkken FastAPI servisi proje kökünden şu komutla başlatılabilir:

```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Servis başlarken LM Studio modelini, Qdrant koleksiyon şemasını ve kesin `31.544` nokta sayısını doğrular. `GET /health` çalışma durumunu; `POST /api/v1/semantic-search` ise `olay`, isteğe bağlı `top_k`, `min_score` ve `filtreler` alanlarını alıp sorgu embedding'ini üretir. `karar_turu`, `daire`, `veri_kalite_durumu` ve `metin_2000_karakter_sinirinda` alanlarında kesin metadata filtresi uygulanabilir. Olay metni 10-4.000 karakter, `top_k` değeri 1-20 ve eşik -1 ile 1 aralığında doğrulanır; bilinmeyen filtreler reddedilir ve bağımlılık hataları yapılandırılmış `503` yanıtına çevrilir.

Arama, istenen sonuç sayısının beş katı kadar aday chunk getirip aynı `karar_id` değerine sahip tekrarları kaldırır; her karar için en yüksek skorlu chunk'ı döndürür. Eşik üstünde sonuç kalmazsa `yeterli_sonuc_bulundu` alanı `false` olur. Böylece düşük skorlu veya aynı karardan tekrar eden parçalar yeterli kaynak gibi sunulmaz.

`bruno` klasörü Bruno'da koleksiyon olarak açılıp `Local` ortamı seçildiğinde sağlık, temel semantik arama ve eşikli/filtreli arama istekleri çalıştırılabilir. İlk uçtan uca kurulumun ayrıntıları `docs/gun16_semantik_arama_fastapi_bruno.md` dosyasındadır.

## Semantik Arama Kalite Karşılaştırması

LM Studio ve yerel Qdrant çalışırken 17. gün deneyi şu komutla yeniden üretilebilir:

```powershell
python scripts/evaluate_semantic_search_quality.py
```

Üç çapa karar ve üç alan dışı hukuki sorguyla yapılan gerçek indeks deneyinde `top_k=10`, `min_score=0,65` ayarı çapa kararların `2/3`'ünü bulup alan dışı sorguların `2/3`'ünü reddetti. Doğru daire önceden bilindiğinde `daire` filtresi üç çapa kararı da ilk sıraya taşırken karar türü filtresi bu küçük sette ek kazanım sağlamadı. `0,65` eşiği küçük geliştirme setine özgü olduğundan zorunlu varsayılan yapılmadı.

31 kararlık zor-negatif aday havuzundaki chunk karşılaştırmasında 800/200 ayarı recall@5 değerini `2/3`, mevcut 1200/200 ayarı `1/3`, 1600/200 ayarı `0/3` üretti. Bu sınırlı deney yeniden indeksleme kararı için yeterli görülmedi; mevcut indeks korundu ve 800/200 daha geniş test için aday kaydedildi. Yöntem, tüm sonuçlar ve sınırlamalar `docs/gun17_semantik_arama_kalite_iyilestirmesi.md` dosyasındadır.

## Gemma RAG Cevap Zinciri

`POST /api/v1/rag-answer` uç noktası semantik arama ile bulunan benzersiz kararları Gemma 4 12B QAT modeline aktararak kaynaklı bir değerlendirme üretir. 20. gün değerlendirmesiyle seçilen varsayılan `top_k=10` ve `min_score=0,65` değerleri kullanılır; en az iki kaynak bulunamazsa Gemma çağrılmaz ve standart yetersiz bilgi cevabı döner. Chat modeli `YARGITAY_RAG_CHAT_MODEL` ortam değişkeniyle yapılandırılabilir.

Her karar `[K1]`, `[K2]` biçiminde etiketlenir ve cevapta kullanılan etiketler gerçek kaynak listesiyle doğrulanır. Bilinmeyen kaynak etiketi, kaynaksız cevap, kesin dava sonucu ifadesi veya zorunlu hukuki uyarının eksikliği güvenli biçimde reddedilir. LM Studio isteği `reasoning=off`, `temperature=0` ve `stream=false` seçenekleriyle gönderilir; model kimliği ile token istatistikleri doğrulanır.

Prompt `1.1` sürümünde kaynak veri kalitesi uyarılarını Gemma bağlamına taşır. Model uyarılı bir kaynağın eksik olabileceğini belirtmezse uygulama kaynak etiketiyle bir veri kalitesi notu ekler. Yapısal doğrulamayı geçmeyen model çıktısı en fazla bir kez yeniden üretilir; çağrı sayısı yanıttaki `model_cagri_sayisi` alanında gösterilir.

Bruno koleksiyonundaki `04-rag-answer.bru` kaynak bulunan normal akışı, `05-rag-insufficient-sources.bru` ise alan dışı sorguda Gemma çağrılmadan güvenli duruşu test eder. Gerçek uçtan uca işe iade testinde beş karar kullanılmış, cevap `[K1]`-`[K5]` etiketlerini içermiş ve reasoning tokenı sıfır kalmıştır. Uygulama ayrıntıları ve test sonuçları `docs/gun18_gemma_rag_cevap_zinciri.md` dosyasındadır.

## FastAPI Entegrasyon ve Uçtan Uca Testler

API `1.3.0` sürümünde `GET /api/v1/system-status`, `POST /api/v1/semantic-search` ve `POST /api/v1/rag-answer` servislerini sunar. Sistem durumu isteği LM Studio'daki embedding ve Gemma modellerini her çağrıda canlı olarak doğrular, Qdrant koleksiyonunun kayıt sayısını denetler ve üç bileşenin durumunu ayrı gösterir. Boş, kısa, 4.000 karakteri aşan, sınır dışı veya bilinmeyen alan içeren istekler, kullanıcı girdisini geri yansıtmayan standart `request_validation_failed` kodlu `422` yanıtıyla reddedilir.

Yerel API çalışırken 19. gün uçtan uca paketi şu komutla yeniden çalıştırılabilir:

```powershell
python scripts/run_day19_e2e.py
```

Araç sistem durumunu, üç hatalı istek sınıfını, 4.000 karakterlik geçerli sorguyu, normal semantik aramayı ve embedding-Qdrant-Gemma zincirini denetler. Gerçek koşuda bütün kontroller geçti; normal sorguda beş benzersiz karar bulundu, beşi Gemma cevabında kaynak olarak kullanıldı ve reasoning tokenı sıfır kaldı. Bruno masaüstü Runner'da koleksiyondaki dokuz isteğin dokuzu geçti. Ayrıntılar `docs/gun19_fastapi_entegrasyon_ve_uctan_uca_testler.md` dosyasındadır.

## Sistem Değerlendirmesi ve Doğruluk İyileştirmesi

LM Studio açık ve FastAPI kapalıyken 20. gün değerlendirmesi şu komutla yeniden çalıştırılabilir:

```powershell
python scripts/evaluate_day20_system.py
```

Araç 15 olaylık sabit test setini 31.544 noktalı Qdrant indeksinde çalıştırır; 28 `top_k`/eşik bileşimini, dört chunk yapılandırmasını ve seçili altı gerçek Gemma cevabını değerlendirir. Son koşuda önerilen `top_k=10`, `min_score=0,65` ayarı çapa recall `0,60`, MRR `0,444444`, alan dışı güvenli reddetme `1,00` ve dengeli doğruluk `0,80` üretti. Altı canlı RAG cevabının tamamı kaynak, veri kalitesi ve zorunlu uyarı denetimlerinden geçti; medyan semantik arama süresi `77,849 ms`, medyan RAG süresi `17.176,865 ms` oldu.

102 gerçek kararlık aday havuzunda 800/200 chunk ayarı Recall@10 `0,80` ve MRR@10 `0,622500` ile en iyi aday oldu. Sonuç tam indeks yeniden oluşturma maliyetini ve genel doğruluğu kanıtlamadığı için mevcut 1.200/200 koleksiyonu korunmuştur. Test seti, hata nedenleri, bütün metrikler ve sınırlamalar `docs/gun20_sistem_degerlendirmesi_ve_dogruluk_iyilestirmesi.md` dosyasındadır.

Nihai kontrolde altı gerçek Gemma olayının altısı, Bruno masaüstü Runner'daki 10 isteğin 10'u ve projenin 132 otomatik testinin tamamı geçti. Güncel API sürümü `1.4.0`, RAG prompt sürümü `1.1`'dir.

## Uyarı

Bu proje eğitim ve karar destek amacıyla geliştirilmektedir. Üretilen sonuçlar hukuki danışmanlık veya kesin hukuki görüş niteliğinde değildir.


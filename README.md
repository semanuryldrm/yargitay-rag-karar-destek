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
- Vektör veritabanı
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

## Uyarı

Bu proje eğitim ve karar destek amacıyla geliştirilmektedir. Üretilen sonuçlar hukuki danışmanlık veya kesin hukuki görüş niteliğinde değildir.


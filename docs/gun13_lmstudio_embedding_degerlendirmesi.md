# 13. Gün - LM Studio Embedding Modeli ve Benzerlik Değerlendirmesi

## Amaç

LM Studio üzerinde çalışan embedding modelini proje kodundan güvenli ve yeniden kullanılabilir biçimde çağırmak; gerçek Yargıtay karar parçaları ile kullanıcı sorgularını aynı vektör uzayına dönüştürmek; anlam bakımından ilgili ve ilgisiz metinleri kosinüs benzerliğiyle karşılaştırmak.

Bu çalışma 2. gündeki üç sentetik cümlelik ilk embedding denemesini genişletmektedir. 13. günde geliştirilen kod, 11. ve 12. günlerde seçilip bütünlüğü doğrulanan 1.200/200 chunk çıktısını doğrudan kullanmaktadır.

## Kullanılan Yerel Model ve API

- LM Studio adresi: `http://127.0.0.1:1234`
- Model: `text-embedding-embeddinggemma-300m`
- Model listeleme: `GET /v1/models`
- Embedding üretimi: `POST /v1/embeddings`
- Vektör boyutu: 768
- Benzerlik yöntemi: cosine similarity

Deney sırasında `/v1/models` cevabında şu modeller görüldü:

- `google/gemma-4-12b-qat`
- `text-embedding-embeddinggemma-300m`
- `text-embedding-embeddinggemma-300m-qat`
- `text-embedding-nomic-embed-text-v1.5`

Karar parçaları hangi embedding modeliyle vektörleştirildiyse kullanıcı sorgularının da aynı modelle işlenmesi zorunludur. Bu deneyde sorgular ve aday chunk'lar tek bir altı metinlik batch isteğinde aynı modelle vektörleştirilmiştir.

## Geliştirilen Embedding İstemcisi

`scripts/lmstudio_embeddings.py` geliştirildi. Haricî bir OpenAI Python paketine bağımlı olmadan standart Python HTTP araçlarıyla LM Studio'nun OpenAI uyumlu uç noktalarını kullanır.

İstemci şu kontrolleri yapmaktadır:

1. LM Studio temel adresinin geçerli HTTP/HTTPS adresi olması.
2. İstenen embedding modelinin `/v1/models` listesinde bulunması.
3. Girdi listesinin boş olmaması ve her girdinin boş olmayan metin olması.
4. Türkçe metinlerin UTF-8 JSON gövdesiyle gönderilmesi.
5. Dönen embedding sayısının girdi sayısıyla aynı olması.
6. Cevap indekslerinin benzersiz, eksiksiz ve geçerli aralıkta olması.
7. Bütün vektörlerin aynı boyutta olması.
8. Koordinatların sayısal ve sonlu olması; `NaN` veya sonsuz değer bulunmaması.
9. Vektör normunun sıfır olmaması.
10. Cevaptaki model kimliği verildiyse istenen modelle aynı olması.

HTTP hatası, bağlantı kesintisi, zaman aşımı, bozuk UTF-8, geçersiz JSON, uygulama hata cevabı veya bozuk embedding yapısı görülürse sonuç sessizce kullanılmaz; açıklayıcı bir hata üretilir.

Modülde ayrıca şu yeniden kullanılabilir yardımcılar bulunmaktadır:

- `cosine_similarity`: Eş boyutlu ve geçerli iki vektörün kosinüs benzerliğini hesaplar.
- `rank_by_similarity`: Sorgu vektörüne göre adayları yüksek skordan düşük skora sıralar.
- `vector_norm`: Vektör normunu doğrulayarak hesaplar.

Bu yapı 15. gündeki toplu embedding üretiminde ve 16. gündeki semantik arama modülünde yeniden kullanılabilecektir.

## Gerçek Karar Parçalarıyla Deney Tasarımı

`scripts/evaluate_legal_embeddings.py` geliştirildi. Araç önce `data/processed/yargitay_chunks_1200_200.jsonl` dosyasının 31.544 kayıt içerdiğini doğrular. Kullanılan chunk dosyasının SHA-256 değeri:

```text
fcd063fcc0f4fd532b4938d9e433682c95f53397528ed04c64315b93a5d7b04d
```

Üç farklı hukuk konusu seçildi:

| Konu | Kullanıcı olayının özeti | Beklenen gerçek Yargıtay chunk'ı |
| --- | --- | --- |
| Geçersiz fesih ve işe iade | İş sözleşmesinin geçerli neden gösterilmeden feshedilmesi | `d1113966700:c0001` |
| Tapu iptali ve tescil | Bedeli ödenen taşınmaz payının tapusunun verilmemesi | `d581878400:c0001` |
| Uyuşturucu ticareti | Tanık dinlenmeden ve eksik soruşturmayla mahkûmiyet | `d480864200:c0001` |

Aday karar parçaları rastgele veya sentetik değildir:

- `d1113966700:c0001`: 7. Hukuk Dairesi, E. 2013/2027, K. 2013/1322, 20.02.2013.
- `d581878400:c0001`: 14. Hukuk Dairesi, E. 2019/3321, K. 2020/3698, 16.06.2020.
- `d480864200:c0001`: 9. Ceza Dairesi, E. 2017/472, K. 2019/57, 24.01.2019.

Her sorgu üç adayın tamamıyla karşılaştırılmıştır. Sorgunun konusuyla eşleşen aday “ilgili”, diğer iki farklı hukuk konusu ise “ilgisiz” kontrollü aday olarak değerlendirilmiştir. Bu yöntem üç ayrı ikili test yerine aynı aday havuzunda gerçek bir sıralama üretmektedir.

Üç aday da kaynak corpusun 2.000 karakter sınırı uyarısını taşımaktadır. Bu sınırlama gizlenmemiş ve deney raporundaki `veri_kalite_uyarilari` alanında korunmuştur. Sonuçlar tam karar metinleriyle yapılmış bir değerlendirme gibi yorumlanmamalıdır.

## Değerlendirme Komutu

LM Studio sunucusu ve embedding modeli çalışırken:

```powershell
python scripts/evaluate_legal_embeddings.py
```

Ayrıntılı yerel çıktı:

```text
data/processed/yargitay_embedding_evaluation_stats.json
```

Bu dosya; sorgu metinlerini, chunk metadata'sını, vektör boyutunu, vektör karmalarını, normları, sıralamaları ve skorları içerir. Tam 768 boyutlu vektörler rapora yazılmaz. Çıktı yeniden üretilebilir ve `data/processed/yargitay_*_stats.json` kuralıyla Git dışında tutulur.

## Gerçek Deney Sonuçları

| Sorgu | İlgili chunk skoru | En yakın ilgisiz skor | Fark | Birinci sıra |
| --- | ---: | ---: | ---: | --- |
| Geçersiz fesih ve işe iade | 0,719056 | 0,455845 | 0,263211 | Doğru |
| Tapu iptali ve tescil | 0,643115 | 0,412575 | 0,230540 | Doğru |
| Uyuşturucu ticareti | 0,707660 | 0,499917 | 0,207743 | Doğru |

Özet sonuçlar:

- Doğru birinci sıra: 3/3.
- Kontrollü top-1 başarı oranı: yüzde 100.
- Bütün ilgili skorlar, aynı sorgudaki iki ilgisiz skordan yüksektir.
- Ortalama ilgili-en yakın ilgisiz farkı: 0,233831.
- En düşük fark: 0,207743.

### Geçersiz Fesih Sorgusu Sıralaması

1. İşe iade kararı: 0,719056.
2. Tapu iptali kararı: 0,455845.
3. Uyuşturucu ticareti kararı: 0,342457.

### Tapu İptali Sorgusu Sıralaması

1. Tapu iptali kararı: 0,643115.
2. İşe iade kararı: 0,412575.
3. Uyuşturucu ticareti kararı: 0,308023.

### Uyuşturucu Ticareti Sorgusu Sıralaması

1. Uyuşturucu ticareti kararı: 0,707660.
2. Tapu iptali kararı: 0,499917.
3. İşe iade kararı: 0,497565.

## Sonuçların Yorumu ve Sınırlamalar

Embedding modeli kontrollü üç örnekte Türkçe kullanıcı olayını doğru hukuk konusundaki Yargıtay parçasıyla eşleştirmiştir. İlgili skorların en yakın ilgisiz skorlardan en az 0,207743 yüksek olması, bu örneklerde anlam ayrımının yalnızca çok küçük skor farklarına dayanmadığını göstermektedir.

Bununla birlikte kosinüs benzerliği mutlak bir doğruluk yüzdesi değildir. İlgisiz adayların skorları sıfır olmak zorunda değildir; hukuk metinleri mahkeme, karar, dava ve temyiz gibi ortak kavramlar taşır. Bu nedenle tek bir sabit eşik bu üç örnekten türetilmemeli, sonuçlar adaylar arasındaki göreli sıralamayla birlikte değerlendirilmelidir.

Üç sorguluk deney genel sistem doğruluğunu kanıtlamaz. Aday havuzu küçüktür, bütün karar parçalarını kapsamaz ve üç adayın kaynak metni de 2.000 karakterle sınırlıdır. 14. günde vektör veritabanı kurulacak; 15. günde bütün chunk'lar vektörleştirilecek; 16. ve 17. günlerde daha geniş sorgu seti, top-k, eşik ve metadata filtreleriyle gerçek arama başarısı ölçülecektir.

## Otomatik Testler

`tests/test_lmstudio_embeddings.py` dosyasına sekiz yeni test eklendi. Testler:

- UTF-8 batch isteğinin doğru gövdeyle gönderilmesini.
- Karışık dönen cevap indekslerinin girdi sırasına getirilmesini.
- Model listesi ve model erişilebilirliği doğrulamasını.
- Eksik/fazla cevap, tekrar indeks, boyut uyuşmazlığı, `NaN` ve sıfır norm reddini.
- Geçersiz JSON ve boş girdi reddini.
- Kosinüs benzerliği ile sıralama davranışını.
- Gerçek chunk kimliklerinin, metin uzunluğunun ve SHA-256 karmasının kontrolünü.
- Atomik deney raporu yazımını ve kaynak dosya karmasını kapsar.

Önceki 71 testle birlikte tam proje test paketindeki toplam 79 test başarıyla tamamlanmıştır. Python derleme kontrolü ve `git diff --check` doğrulaması da geçmiştir.

## 13. Gün Sonucu

LM Studio için doğrulamalı ve yeniden kullanılabilir bir embedding istemcisi geliştirildi. Üç kullanıcı sorgusu ile üç gerçek Yargıtay karar parçası aynı `text-embedding-embeddinggemma-300m` modeliyle tek batch içinde 768 boyutlu vektörlere dönüştürüldü.

Kosinüs benzerliği sıralamasında beklenen ilgili karar üç sorgunun tamamında birinci geldi. Modelin küçük kontrollü örneklerde ilgili ve ilgisiz hukuk konularını ayırabildiği doğrulandı; sonuçların genel doğruluk veya üretim eşiği olarak yorumlanmaması gerektiği açıkça belgelendi.

# 2. Gün - LM Studio ve Gemma API Testleri

## Kullanılan Model

- Model: Gemma 4 12B QAT
- API model kimliği: `google/gemma-4-12b-qat`
- LM Studio sunucu adresi: `http://127.0.0.1:1234`

## Model Listesi Kontrolü

LM Studio sunucusuna `/v1/models` isteği gönderildi. Gemma 4 12B QAT modeli ile indirilen embedding modellerinin API üzerinden erişilebilir olduğu doğrulandı.

## İlk Türkçe Soru-Cevap Testleri

Modele “RAG nedir? Kısa bir şekilde açıklar mısın?” sorusu gönderildi.

İlk denemede maksimum çıktı sınırı 200 token olarak ayarlandı. Model tokenların büyük bölümünü reasoning işlemi için kullandığı için kullanıcıya gösterilecek cevap üretilemeden çıktı kesildi.

İkinci denemede token sınırı 600'e yükseltildi. Ancak model 580 tokenı reasoning için kullandığından asıl cevap yine tamamlanamadı.

## Başarılı Test

LM Studio REST API üzerindeki `/api/v1/chat` endpointi kullanıldı ve `reasoning` değeri `off` olarak ayarlandı. Model bu defa Türkçe ve tamamlanmış bir cevap üretti.

Test sonuçları:

- Girdi tokenı: 45
- Çıktı tokenı: 64
- Reasoning tokenı: 0
- Üretim hızı: yaklaşık 49.59 token/s
- İlk token süresi: yaklaşık 0.166 saniye

Sonuç olarak Gemma 4 12B QAT modelinin LM Studio yerel API'si üzerinden erişilebilir olduğu ve reasoning kapatıldığında kısa Türkçe sorulara başarılı şekilde cevap verdiği doğrulandı.

## Embedding ve Benzerlik Testi

LM Studio üzerinde `text-embedding-embeddinggemma-300m` modeli kullanılarak örnek bir Türkçe hukuk cümlesinin embedding vektörü oluşturuldu. Üretilen vektörün 768 boyutlu olduğu doğrulandı.

Kullanıcı sorgusu olarak şu metin kullanıldı:

“İşveren beni gerekçe göstermeden işten çıkardı ve kıdem tazminatımı ödemedi.”

Bu sorgu, anlam bakımından benzer bir hukuk cümlesi ve ilgisiz bir hava durumu cümlesiyle karşılaştırıldı. Cosine similarity yöntemiyle elde edilen sonuçlar:

- Benzer hukuk cümlesi: 0,7181
- İlgisiz hava durumu cümlesi: 0,1719

Benzer hukuk cümlesinin skorunun belirgin biçimde daha yüksek çıkması, embedding modelinin örnek Türkçe metinlerde anlamsal benzerliği ayırt edebildiğini gösterdi.

## Temel Kavramlar

- **Büyük Dil Modeli (LLM):** Metinleri anlayabilen ve verilen bağlama göre cevap üretebilen yapay zekâ modelidir. Bu projede Gemma 4 12B QAT modeli kullanılmaktadır.

- **RAG:** Modelin cevap üretmeden önce dış veri kaynağından ilgili bilgileri bulması ve cevabını bu bilgiler üzerinden oluşturması yöntemidir. Bu projede dış veri kaynağı Yargıtay kararları olacaktır.

- **Embedding:** Bir metnin anlamını sayısal bir vektörle temsil etme işlemidir. Anlam bakımından benzer metinlerin vektörlerinin birbirine daha yakın olması beklenir.

- **Vektör:** Embedding modeli tarafından oluşturulan sayısal değerler dizisidir. Yapılan testte her metin için 768 boyutlu vektör üretildi.

- **Vektör Veritabanı:** Metinlere ait embedding vektörlerini ve metadata bilgilerini saklayan, kullanıcı sorgusuna en yakın vektörleri bulabilen veritabanıdır.

- **Chunking:** Uzun karar metinlerinin daha küçük ve anlamlı parçalara ayrılması işlemidir. Böylece ilgili karar bölümlerinin bulunması ve modele bağlam olarak gönderilmesi kolaylaşır.

Karar metinleri ve kullanıcı sorguları aynı embedding modeliyle vektörleştirilmelidir. Farklı modeller kullanılırsa vektörler aynı anlam uzayında bulunmayacağı için sağlıklı bir benzerlik karşılaştırması yapılamaz.

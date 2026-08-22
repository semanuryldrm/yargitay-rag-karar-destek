# 4. Gün - Yargıtay Karar Arama Sitesi İncelemesi ve Scraper Tasarımı



## Amaç



Dördüncü gün çalışmasında Yargıtay Karar Arama sisteminin veri yapısı incelendi. Amaç, ileride geliştirilecek veri çekme modülünün hangi endpoint'leri kullanacağını, arama sonuçlarının nasıl sayfalandığını, karar detaylarının nasıl alındığını ve ham verinin hangi formatta saklanacağını belirlemekti.



Bu aşamada henüz scraper kodu geliştirilmedi ve toplu karar indirme işlemi yapılmadı. Çalışma, sitenin yapısının analiz edilmesi ve scraper mimarisinin tasarlanmasıyla sınırlandırıldı.



## Yargıtay Karar Arama Sitesinin İncelenmesi



Detaylı arama ekranında örnek olarak `01.01.2025 - 01.12.2025` tarih aralığı kullanıldı. Bu aramada sistemde `282.591` sonuç bulunduğu görüldü.



Liste ekranında her karar için aşağıdaki bilgilerin gösterildiği tespit edildi:



* Daire

* Esas numarası

* Karar numarası

* Karar tarihi



Bir karar seçildiğinde sağ tarafta kararın tam içtihat metninin görüntülendiği görüldü.



Ceza ve Hukuk Dairelerine ait farklı karar örnekleri incelendi. Ceza Dairesi kararlarında `MAHKEMESİ`, `SAYISI`, `SUÇ`, `HÜKÜM` ve `TEBLİĞNAME GÖRÜŞÜ` gibi ek alanlar bulunabilirken Hukuk Dairesi kararlarının aynı alan yapısına sahip olmadığı görüldü. Bu nedenle karar türüne özgü alanların zorunlu metadata olarak tutulmamasına karar verildi.



Ayrıca bazı kararların sonunda çok sayıda tekrar eden `Kişisel Verilerden Arındırılmıştır` ifadesi bulunduğu gözlemlendi. Bu ifadelerin ham veride korunması, sonraki veri temizleme aşamasında ise kaldırılması planlandı.



## Network Üzerinden İsteklerin İncelenmesi



Chrome Developer Tools içerisindeki `Network -> Fetch/XHR` bölümü kullanılarak Yargıtay Karar Arama sayfasının arka planda yaptığı HTTP istekleri incelendi.



Arama işlemi gerçekleştirildiğinde aşağıdaki istekler gözlemlendi:



* `detayliArama`

* `aramadetaylist`

* `getDokuman?id=...`



Karar listesini getiren isteğin `aramadetaylist`, tek bir kararın detay metnini getiren isteğin ise `getDokuman` olduğu doğrulandı.



## Karar Listesi Endpoint'i



Karar listesinin aşağıdaki endpoint üzerinden alındığı doğrulandı:



```text

POST https://karararama.yargitay.gov.tr/aramadetaylist

```



İstek başarılı şekilde `200 OK` durum kodu döndürdü.



İstek sırasında gönderilen gerçek payload alanları incelendi:



```text

arananKelime: ""

baslangicTarihi: "01.01.2025"

birimYrgCezaDaire: ""

birimYrgHukukDaire: ""

birimYrgKurulDaire: ""

bitisTarihi: "01.12.2025"

esasIlkSiraNo: ""

esasSonSiraNo: ""

esasYil: ""

kararIlkSiraNo: ""

kararSonSiraNo: ""

kararYil: ""

pageNumber: 1

pageSize: 10

siralama: "3"

siralamaDirection: "desc"

```



`pageNumber` alanının istenen sayfayı, `pageSize` alanının ise bir sayfada döndürülen karar sayısını belirlediği görüldü.



Test sırasında:



```text

pageNumber: 1

pageSize: 10

```



değerleri kullanıldığında cevap içerisinde 10 karar kaydı bulunduğu doğrulandı.



`siralamaDirection: "desc"` değeri azalan sıralamayı göstermektedir. `siralama: "3"` değeri mevcut arama ekranındaki sıralama seçimiyle birlikte gönderilmiştir ancak bu değerin hangi sıralama türünü temsil ettiği ayrıca test edilmedi.



## Liste Endpoint'inden Dönen Veri



Liste servisinin cevabında aşağıdaki yapı gözlemlendi:



```text

data

 ├── data

 ├── draw

 ├── recordsFiltered

 └── recordsTotal

```



Test sırasında:



```text

recordsFiltered: 282591

recordsTotal: 282591

```



değerleri döndü.



İlk karar kaydında aşağıdaki alanlar doğrulandı:



```text

id: "1184895600"

daire: "7. Ceza Dairesi"

esasNo: "2024/1158"

kararNo: "2025/14770"

kararTarihi: "01.12.2025"

arananKelime: ""

index: 1

siraNo: 1

```



Buna göre liste servisinden doğrudan kullanılacak temel alanlar:



```text

id

daire

esasNo

kararNo

kararTarihi

```



olarak belirlendi.



`index`, `siraNo` ve `arananKelime` alanlarının kararın kalıcı hukuki metadata'sının bir parçası olmadığı değerlendirildi.



## Karar Detay Endpoint'i



Liste servisinden alınan `id` değerinin karar detayına ulaşmak için kullanıldığı doğrulandı.



Örneğin:



```text

id: 1184895600

```



için tarayıcı tarafından aşağıdaki istek gönderildi:



```text

GET https://karararama.yargitay.gov.tr/getDokuman?id=1184895600

```



İstek `200 OK` durum kodu ile başarılı oldu.



Bu bağlantı sayesinde scraper'ın liste ekranındaki bir kararın `id` değerini aldıktan sonra aynı kararın detay metnine ulaşabileceği görüldü.



## Karar Detay Cevabının Yapısı



`getDokuman` endpoint'inin cevabının JSON formatında olduğu ancak JSON içerisindeki `data` alanında kararın HTML olarak tutulduğu görüldü.



Yapı genel olarak şu şekildedir:



```text

{

    "data": "<html> ... karar metni ... </html>",

    "metadata": {

        ...

    }

}

```



Karar metni içerisinde `<html>`, `<body>`, `<font>`, `<br>`, `<p>` ve `<b>` gibi HTML etiketleri bulunmaktadır.



Örnek kararda HTML içeriğinin içerisinde aşağıdaki bilgiler bulundu:



```text

7. Ceza Dairesi

2024/1158 E.

2025/14770 K.



MAHKEMESİ: Ceza Dairesi

SAYISI: 2021/397 E., 2023/3622 K.

SUÇ: Çekle ilgili karşılıksızdır işlemi yapılmasına sebebiyet verme

HÜKÜM: Mahkûmiyet

TEBLİĞNAME GÖRÜŞÜ: Ret

```



Ardından Yargıtay kararının gerekçe ve sonuç bölümleri gelmektedir.



Bu nedenle ham veri aşamasında HTML'in değiştirilmeden saklanması, temizlenmiş veri oluşturulurken HTML etiketlerinin ayrıştırılması planlandı.



## Ham Veri Formatı



Her karar için ham veri kaydının temel olarak aşağıdaki yapıda tutulması planlandı:



```json

{

  "id": "1184895600",

  "daire": "7. Ceza Dairesi",

  "esas_no": "2024/1158",

  "karar_no": "2025/14770",

  "karar_tarihi": "01.12.2025",

  "karar_html": "<html>...</html>"

}

```



Ham veri içerisinde Yargıtay'dan gelen karar HTML'i korunacaktır.



Temizleme aşamasında ise HTML içeriğinden okunabilir karar metni oluşturulacak ve gerekirse `mahkeme` gibi ek alanlar ayrıştırılacaktır.



## Raw ve Processed Veri Ayrımı



Veri kaybını önlemek amacıyla iki farklı veri katmanı kullanılmasına karar verildi.



```text

data/raw

```



Yargıtay'dan alınan orijinal verileri içerecektir.



```text

data/processed

```



HTML etiketleri, gereksiz boşluklar ve tekrar eden `Kişisel Verilerden Arındırılmıştır` ifadeleri gibi bölümlerin temizlendiği verileri içerecektir.



Bu yapı sayesinde temizleme işleminde hata oluşması durumunda orijinal veriye tekrar dönülebilecektir.



## Planlanan Scraper Mimarisi



Scraper için aşağıdaki dosya yapısı tasarlandı:



```text

scripts/

├── yargitay_client.py

└── scrape_yargitay.py



data/

└── raw/

    ├── decisions.jsonl

    └── scrape_state.json



logs/

└── scraper.log

```



Bu aşamada bu dosyalar henüz oluşturulmadı.



### yargitay_client.py



Yargıtay sunucusuyla yapılan HTTP iletişiminden sorumlu olacaktır.



Temel görevleri:



```text

POST /aramadetaylist

GET /getDokuman?id=<karar_id>

```



isteklerini gerçekleştirmek olacaktır.



### scrape_yargitay.py



Veri çekme sürecinin genel akışını yönetecektir.



Görevleri arasında:



* sayfalar arasında ilerlemek,

* karar ID'lerini almak,

* karar detaylarını istemek,

* kayıtları dosyaya yazmak,

* hata kontrolü yapmak,

* kaldığı yeri takip etmek



bulunacaktır.



## JSONL Formatının Tercih Edilmesi



Yaklaşık 15.000 kararın tek bir büyük JSON dizisi yerine JSONL formatında saklanması planlandı.



JSONL formatında her satır tek bir karar olacaktır:



```text

{"id":"...","daire":"...","esas_no":"..."}

{"id":"...","daire":"...","esas_no":"..."}

{"id":"...","daire":"...","esas_no":"..."}

```



Bu sayede her karar alındığında dosyanın sonuna eklenebilecek ve programın yarıda kalması durumunda daha önce kaydedilen veriler korunabilecektir.



## Kaldığı Yerden Devam Etme



Scraper'ın uzun süre çalışacağı göz önünde bulundurularak kaldığı yerden devam edebilmesi planlandı.



Bunun için:



```text

data/raw/scrape_state.json

```



dosyasının kullanılması tasarlandı.



Örneğin:



```json

{

  "last_completed_page": 347,

  "total_saved": 3470

}

```



şeklinde son tamamlanan sayfa ve kaydedilen karar sayısı tutulabilecektir.



Program yeniden başlatıldığında tamamlanmış sayfaların tekrar çekilmemesi hedeflenmektedir.



State bilgisinin, bir sayfadaki bütün kararlar başarıyla işlendiğinde güncellenmesi planlandı.



## Loglama ve Hata Yönetimi



Scraper çalışırken oluşan önemli işlemlerin ve hataların:



```text

logs/scraper.log

```



dosyasına yazılması planlandı.



Bir karar alınırken hata oluşmasının tüm veri çekme işlemini durdurmaması, isteğin sınırlı sayıda tekrar denenmesi ve hata bilgisinin loglanması planlandı.



Ayrıca Yargıtay sunucusuna gereksiz yük oluşturmamak için istekler arasında kontrollü bekleme uygulanması öngörüldü.



## Tasarlanan Veri Çekme Algoritması



Scraper'ın genel çalışma algoritması aşağıdaki şekilde tasarlandı:



1. Daha önce tamamlanmış bir çalışma olup olmadığını kontrol et.

2. İlk çalıştırmada birinci sayfadan, devam eden çalışmada son tamamlanan sayfanın bir sonrasından başla.

3. `POST /aramadetaylist` isteğiyle karar listesini al.

4. Dönen cevabın başarılı olup olmadığını kontrol et.

5. Sayfadaki kararların `id`, `daire`, `esasNo`, `kararNo` ve `kararTarihi` bilgilerini al.

6. Her karar için `GET /getDokuman?id=<id>` isteği gönder.

7. Dönen JSON içerisindeki `data` alanından ham HTML'i al.

8. Metadata ve ham HTML'i JSONL dosyasına kaydet.

9. Aynı `id` daha önce kaydedilmişse tekrar kaydetme.

10. Hata oluşursa logla ve kontrollü şekilde tekrar dene.

11. Sayfadaki bütün kararlar tamamlandıktan sonra state dosyasını güncelle.

12. Bir sonraki sayfaya geç.

13. Hedeflenen yaklaşık 15.000 karar toplandığında işlemi sonlandır.



## 4. Gün Sonucu



Yargıtay Karar Arama sitesinin listeleme, sayfalama ve karar detay yapısı tarayıcı geliştirici araçları kullanılarak incelendi. Karar listesinin `POST /aramadetaylist`, karar detayının ise `GET /getDokuman?id=...` isteğiyle alındığı doğrulandı. Gerçek request payload'ı ve response alanları incelendi, kararların liste endpoint'inden alınan `id` değerleri ile detay endpoint'ine erişildiği tespit edildi.



Ayrıca ham veri formatı, JSONL kullanımı, raw/processed veri ayrımı, kaldığı yerden devam etme, loglama ve hata yönetimi gibi scraper tasarım kararları oluşturuldu. Bu gün içerisinde scraper kodu yazılmadı ve toplu veri çekme işlemi gerçekleştirilmedi.







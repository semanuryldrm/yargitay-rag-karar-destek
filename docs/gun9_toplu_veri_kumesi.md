# 9. Gün - Kontrollü Toplu Veri Kümesi Oluşturma

## Amaç

Yaklaşık 15.000 Yargıtay kaydını ham veri alanına kontrollü biçimde almak; işlem ilerlemesini ve başarılı/başarısız kayıt sayılarını izlemek; yarım çalışmalarda veri bütünlüğünü korumak; erişim engellerini aşmaya çalışmadan güvenli bir alternatif veri kaynağıyla hedef corpus büyüklüğüne ulaşmak.

8. günde farklı sayfalardan alınan sekiz kararın veri kalitesi sınanmıştı. 9. günde aynı küçük örnek çalışması tekrarlanmadı; uzun süreli toplu çalışmanın durum yönetimi, başarısız kayıt takibi, servis hız sınırları ve 15.000 kayıtlık corpus oluşturma süreci ele alındı.

## Resmî Yargıtay Servisi İçin Toplu Çekim İyileştirmeleri

`scripts/scrape_yargitay.py` içindeki devam dosyası ikinci şema sürümüne yükseltildi. Devam bilgisi artık başlangıç ve bitiş tarihi, sayfa boyutu, tamamlanan son sayfa, toplam başarılı kayıt ve toplam başarısız kayıt değerlerini birlikte saklamaktadır. Önceki çalışmayla uyuşmayan tarih aralığı veya sayfa boyutuyla devam edilmeye çalışıldığında işlem reddedilmektedir.

Aşağıdaki toplu çalışma özellikleri eklendi:

- `--target-count` ile hedef başarılı kayıt sayısında durma.
- Her sayfada başarılı, başarısız ve hedefe göre yüzde ilerleme bilgisini loglama.
- `--continue-on-error` ile son denemede de alınamayan tekil kararları atlayarak sayfaya devam edebilme.
- Başarısız karar kimliği, sayfası, UTC zamanı, hata türü, hata açıklaması ve liste özetini ayrı JSONL dosyasında saklama.
- Çıktı, devam dosyası ve hata günlüğü sayaçlarının başlangıçta birbiriyle uyuştuğunu doğrulama.
- Hedef sayısına sayfa ortasında ulaşılırsa sayfayı tamamlanmış göstermeme; sonraki çalışmada aynı sayfayı yeniden getirip daha önce yazılan kimlikleri atlayarak güvenli devam etme.
- HTTP 429, “Too Many Requests” ve servis “Bulkhead” hatalarında en az 30, sonra 60 saniyelik uyarlanabilir bekleme.
- `DisplayCaptcha` cevabını ayrı bir `YargitayAccessBlockedError` olarak tanıma ve CAPTCHA gerektiren isteği tekrar denemeden çalışmayı durdurma.

CAPTCHA çözme, oturum yanıltma veya erişim engelini aşmaya yönelik bir yöntem uygulanmamıştır.

## Kontrollü Resmî Servis Pilotu

İlk pilotta `page_size=100`, `target_count=100` ve 0,25 saniyelik istek aralığı kullanıldı. Servis uygulama hataları, dolu “Bulkhead” ve HTTP 429 cevapları görüldü. Sayfa atomik işlendiği için pilot durdurulduğunda tamamlanmamış sayfaya ait çıktı veya ilerleme dosyası yazılmadı.

İkinci pilotta istek aralığı 1 saniyeye çıkarıldı ve hız sınırı hataları için 30 saniyelik bekleme uygulandı. Buna rağmen servis `DisplayCaptcha` cevabı verdi. Bu cevap ilk görüldüğü pilotta genel servis hatası olarak yeniden denenmişti; çalışma erişim engeli anlaşıldığında elle durduruldu ve ardından istemci CAPTCHA'yı özel bir erişim engeli olarak tanıyıp ilk cevapta duracak biçimde düzeltildi. Pilot sonunda resmî toplu çıktı, state veya başarısız kayıt dosyası oluşmadı; yalnızca tanılama logu kaldı.

Bu nedenle 15.000 kararı aynı oturumda resmî servisten çekmek hem kararlı değildi hem de servisin etkileşimli erişim kontrolüyle çelişiyordu. Güvenli davranış olarak resmî servis zorlanmadı.

## Onaylı Alternatif Kaynak

Kullanıcı onayıyla [IremTRNL/TurkLegalBench](https://huggingface.co/datasets/IremTRNL/TurkLegalBench) veri kümesinin `corpus.jsonl` dosyası kullanıldı. Veri kümesi kartı lisansı [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) olarak belirtmekte ve kaynak veriyi [erdem-erdem/Turkish-Law-Documents-700k-clustered](https://huggingface.co/datasets/erdem-erdem/Turkish-Law-Documents-700k-clustered) corpusuna dayandırmaktadır.

İndirilen kaynak dosyanın doğrulanan özellikleri:

| Özellik | Değer |
| --- | ---: |
| Dosya | `data/raw/yargitay_turklegalbench_source.jsonl` |
| Boyut | 31.359.433 bayt |
| SHA-256 | `6c267d0fd9eb7d3e01c6cb10778dc636c48a0b35e43a5c4af6e1fe8981cd603e` |
| JSONL kayıt sayısı | 15.000 |
| Geçersiz JSON | 0 |
| Benzersiz kaynak kimliği | 15.000 |
| Tekrar kimlik | 0 |
| Zorunlu üst alanı eksik kayıt | 0 |
| Unicode replacement character içeren kayıt | 0 |

SHA-256 değeri Hugging Face LFS nesne kimliğiyle birebir eşleşmektedir. Dataset kartı corpusu “Yargıtay/Danıştay” olarak tanımlasa da indirilen bu sürümdeki bütün `metadata.kurul` değerleri incelendi. 14.904 kayıt numaralı Hukuk veya Ceza Dairesine, 95 kayıt Hukuk veya Ceza Genel Kuruluna, bir kayıt da “Yargıtay (Hukuk Daireleri)” birimine aittir. Danıştay veya sınıflandırılamayan yüksek mahkeme kaydı bulunmamıştır; dolayısıyla doğrulanan 15.000 kaydın tamamı Yargıtay kapsamındadır.

## Kaynak Belirtimli Dönüşüm

`scripts/import_turklegalbench.py` aracı kaynak dosyanın SHA-256 değerini ve 15.000 kayıt hedefini doğrulamakta, JSONL satırlarını tek tek denetlemekte ve sonucu geçici dosya üzerinden atomik olarak oluşturmaktadır. Tekrar kimlik, geçersiz UTF-8/JSON, boş zorunlu alan, bilinmeyen mahkeme birimi veya desteklenmeyen kontrol karakteri görülürse dönüşüm tamamlanmadan durmaktadır.

Kaynak dosya Git'te tutulmadığı için işlem aşağıdaki tek komutla yeniden üretilebilir. `--download` aşaması dosyayı önce geçici bir konuma indirir ve yalnızca beklenen SHA-256 değeri doğrulanırsa kalıcı kaynak dosyanın yerine koyar. Ardından 15.000 kayıtlık dönüşüm çalışır.

```powershell
python scripts/import_turklegalbench.py --download
```

Kaynakta düz metin bulunduğu için içerik yanlış biçimde HTML gibi gösterilmemiştir. Resmî servis kayıtlarındaki `karar_html` yerine `karar_metni` alanı kullanılmıştır. Her kayda ayrıca şu alanlar eklenmiştir:

- `mahkeme`: `Yargıtay`
- `kaynak`: `IremTRNL/TurkLegalBench`
- `kaynak_url`: veri kümesi bağlantısı
- `kaynak_lisans`: `CC BY 4.0`
- `kaynak_kayit_id`: özgün corpus kimliği
- `metin_2000_karakter_sinirinda`: kaynak metnin tam 2.000 karakter olup olmadığı

Daire adlarındaki bölünemez boşluk ve `10.Hukuk` gibi nokta sonrası boşluk varyantları standartlaştırıldı. Bir kayıtta bulunan üç Windows C1 apostrof karakteri (`U+0092`) Unicode sağ apostrof (`U+2019`) olarak düzeltildi. Başka kontrol karakteri bulunmadı.

Kaynakta `-` olarak verilen sekiz karar tarihi ve bir esas numarası bilgi uydurulmaması için `null` değerine dönüştürüldü. Eksik karar numarası bulunmadı.

## Oluşturulan 15.000 Kayıtlık Çıktı

| Özellik | Değer |
| --- | ---: |
| Çıktı | `data/raw/yargitay_turklegalbench_15000.jsonl` |
| Boyut | 35.245.836 bayt |
| Toplam kayıt | 15.000 |
| Benzersiz kimlik | 15.000 |
| Hukuk | 8.479 |
| Ceza | 6.426 |
| Kurul | 95 |
| Normalize edilmiş farklı daire/kurul adı | 50 |
| Eksik esas numarası | 1 |
| Eksik karar numarası | 0 |
| Eksik karar tarihi | 8 |
| Geçersiz JSON/UTF-8/kontrol karakteri | 0 |

Kaynak ve dönüştürülmüş büyük JSONL dosyaları yerel olarak `data/raw/` altında bulunmaktadır ve Git'e eklenmemeleri için `.gitignore` kapsamındadır.

## Önemli Metin Bütünlüğü Sınırı

15.000 metnin 8.355'i tam olarak 2.000 karakterdir; örneklenen kayıtların bir kısmı kelime veya cümle ortasında bitmektedir. Bu durum kaynak corpusun bazı kararları 2.000 karakterde sınırlandırdığını güçlü biçimde göstermektedir. Bu nedenle çıktı “15.000 tam karar metni” olarak tanımlanmamaktadır; 15.000 benzersiz Yargıtay karar kaydı ve kaynakta sağlanan karar metni/kesiti olarak kullanılmalıdır.

Bu sınır her kayıttaki `metin_2000_karakter_sinirinda` alanıyla görünür hâle getirildi. 10. gündeki temizleme ve parçalama çalışmasında bu alanın kalite filtresi veya uyarı metadata'sı olarak korunması gerekir. Tam metin gerektiren nihai sistemde karar kimlikleri üzerinden izinli ve kontrollü bir zenginleştirme aşaması ayrıca planlanmalıdır.

## Otomatik Testler

9. gün sonunda önceki testlerle birlikte 52 otomatik test başarıyla geçti. Yeni testler aşağıdaki davranışları kapsamaktadır:

- Toplu çalışma state dosyasının sorgu yapılandırmasını doğrulaması.
- Hız sınırında 30 ve 60 saniyelik uyarlanabilir bekleme.
- CAPTCHA cevabının yeniden denenmeden durdurulması.
- Son başarısız kararın ayrı hata günlüğüne yazılıp sonraki kararla devam edilmesi.
- Hedefe sayfa ortasında ulaşıldıktan sonra aynı sayfadan tekrarsız devam edilmesi.
- Hedef zaten tamamlandıysa ağ isteği gönderilmemesi.
- Haricî kaydın düz metin alanı ve açık kaynak bilgileriyle dönüştürülmesi.
- Eksik metadata'nın `null` yapılması ve 2.000 karakter sınırının işaretlenmesi.
- Danıştay veya bilinmeyen birimin Yargıtay içe aktarımında reddedilmesi.
- Geçersiz JSON, tekrar kimlik, yanlış dosya karması ve yanlış kayıt sayısının reddedilmesi.
- C1 apostrof onarımı ve diğer kontrol karakterlerinin reddedilmesi.
- İndirilen dosyanın yalnızca doğru SHA-256 değeriyle kalıcı hâle getirilmesi.

## 9. Gün Sonucu

Resmî Yargıtay servisi için kontrollü toplu çekim altyapısı tamamlandı; ilerleme, başarı/başarısızlık sayaçları, güvenli devam, hata günlüğü, hız sınırı beklemesi ve CAPTCHA'da güvenli duruş geliştirildi. Canlı pilot servis sınırları nedeniyle veri üretmeden durduruldu ve erişim kontrolü aşılmadı.

Kullanıcı tarafından onaylanan CC BY 4.0 lisanslı alternatif corpus doğrulanarak 15.000 benzersiz Yargıtay kaydı kaynak ve lisans bilgileriyle yerel ham veriye dönüştürüldü. Veri kümesinin tam metin sınırlaması ayrıca ölçüldü ve görünür bir kalite alanı hâline getirildi; böylece kayıt sayısı hedefi karşılanırken veri kökeni ve metin bütünlüğü hakkında yanıltıcı bir iddiada bulunulmadı.

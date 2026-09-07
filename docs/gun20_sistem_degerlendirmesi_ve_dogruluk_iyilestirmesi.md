# 20. Gün - Sistem Değerlendirmesi ve Doğruluk İyileştirmesi

## Amaç

Farklı hukuk alanlarından örnek olaylarla semantik arama ve kaynaklı RAG zincirini birlikte ölçmek; yanlış veya ilgisiz sonuçların gözlenebilir nedenlerini ayırmak; `top_k`, benzerlik eşiği, chunk yapılandırması ve prompt davranışını gerçek LM Studio modelleri ile iyileştirmek; son performans ve regresyon kontrollerini tamamlamak.

## Sabit Test Seti ve Yöntem

`data/evaluation/day20_cases.json` dosyasına 15 olaylık, sürümlü bir değerlendirme seti eklendi. Set; iş, eşya, ceza, aile, fikrî mülkiyet, sigorta, sosyal güvenlik ve kadastro alanlarından 10 Yargıtay kapsamı sorgusu ile vergi, memur, imar, kamu ihalesi ve sınır dışı işlemlerine ilişkin 5 alan dışı kontrol sorgusundan oluşmaktadır. Her kapsam içi sorguda corpus içinde elle doğrulanmış bir çapa karar kimliği bulunur. Dosyanın SHA-256 değeri `a9a971cfda32995ffbcd3a05ae024dd575c733746d2b21b376fa2effedea6b5f` olup değerlendirme raporuna kaydedilir.

`scripts/evaluate_day20_system.py` aracı 15 sorguyu `text-embedding-embeddinggemma-300m` ile vektörleştirir, 31.544 noktalı Qdrant koleksiyonunda ilk 100 chunk'ı arar ve aynı karara ait chunk'ları tek karar sonucuna indirir. Araç 4 farklı `top_k` ile 7 eşik değerini çapraz karşılaştırır. Alan dışı güvenlik başarısı, RAG servisinin gerçek çalışma kuralıyla aynı şekilde, eşik üstünde iki benzersiz karar kalmaması olarak tanımlanmıştır. Sıfır sonuç oranı ayrıca raporlanır; böylece tek bir zayıf eşleşme yanlış biçimde güvenlik başarısızlığı sayılmaz.

Değerlendirme şu komutla yeniden çalıştırılabilir:

```powershell
python scripts/evaluate_day20_system.py
```

API açıkken aynı yerel Qdrant dizini kilitleneceği için bu araç çalıştırılmadan önce FastAPI süreci durdurulmalıdır. Ayrıntılı JSON raporu yerel ve türetilmiş çıktı olarak `data/processed/yargitay_day20_evaluation.json` konumuna yazılır ve Git'e eklenmez.

## Arama Ayarı Sonuçları

`min_score=0,65` sabitken önceki `top_k=5` ayarı 10 çapanın 5'ini buldu; çapa recall değeri `0,50`, MRR `0,433333`, alan dışı güvenli reddetme oranı `1,00` ve dengeli doğruluk `0,75` oldu. `top_k=10` aynı alan dışı güvenliğini korurken 6 çapa kararı buldu; recall `0,60`, MRR `0,444444` ve dengeli doğruluk `0,80` değerine yükseldi. `top_k=20` ek kazanç sağlamadığı için gereksiz bağlam büyümesini önlemek amacıyla RAG varsayılanı `top_k=10`, `min_score=0,65` olarak belirlendi.

Beş alan dışı sorgunun tamamı iki-kaynak kuralıyla güvenli biçimde reddedildi. Bunların üçünde hiç eşik üstü karar yoktu; memur atama ve kamu ihalesi sorgularında ise yalnızca birer eşik üstü karar bulunduğu için Gemma çağrısı yapılmayacak durum oluştu. Bu ayrım, katı sıfır-sonuç oranının `0,60`, gerçek RAG güvenli reddetme oranının ise `1,00` olmasını açıklamaktadır.

Çapa kararın bulunamadığı dört sorgunun üçünde karar ilk 100 chunk adayından oluşan karar havuzuna girmedi; boşanma/tebligat çapasında karar sırası 31'de kaldı. Üst sonuçların elle incelenmesi, özellikle uyuşturucu ve trafik sorgularında birçok sonucun yine aynı hukuki konuya ait olduğunu gösterdi. Bu nedenle `6/10` çapa recall değeri genel hukuki ilgililik doğruluğu değil, tek elle seçilmiş kararın geri çağrılmasına ilişkin ihtiyatlı bir alt sınırdır.

## Chunk Karşılaştırması

Tam indeks aramasındaki ilk 10 karar ve çapa kararlardan kurulan 102 gerçek kararlık zor-negatif havuzunda dört ayar karşılaştırıldı:

| Chunk / örtüşme | Chunk sayısı | Recall@5 | MRR@5 | Recall@10 | MRR@10 |
|---|---:|---:|---:|---:|---:|
| 800 / 100 | 397 | 0,60 | 0,60 | 0,80 | 0,621111 |
| 800 / 200 | 402 | 0,60 | 0,60 | 0,80 | 0,622500 |
| 1.200 / 200 | 252 | 0,50 | 0,433333 | 0,60 | 0,444444 |
| 1.600 / 200 | 192 | 0,50 | 0,241667 | 0,80 | 0,289286 |

Bu havuzda 800/200 en yüksek Recall@10 ile en yüksek MRR@10 bileşimini verdi ve sonraki tam yeniden indeksleme için aday seçildi. Bununla birlikte deney tam corpus yeniden indekslemesi değildir; 800/200 ayarı parça sayısını ve depolama yükünü artıracaktır. Bu nedenle mevcut 1.200/200 üretim indeksi 20. günde değiştirilmedi, 800/200 sonucu daha geniş etiketli set ve tam indeks maliyet ölçümü yapılana kadar aday olarak kaydedildi.

## Prompt ve Güvenlik İyileştirmeleri

RAG promptu `1.1` sürümüne çıkarıldı. Gemma bağlamında her kararın veri kalitesi uyarısı artık insan tarafından okunabilir biçimde gösterilir. Prompt; kesilmiş kaynağı tam karar gibi sunmamayı, bunun etkisini `Sınırlamalar` bölümünde belirtmeyi, farklı kaynak yaklaşımlarını yapay biçimde birleştirmemeyi ve kaynak gözlemini güncel hukuk veya doğrudan tavsiye gibi sunmamayı zorunlu kılar.

Model bazı ilk denemelerde veri kalitesi uyarısını atlayabildiği için yalnızca prompta güvenilmedi. Uyarılı kaynak varsa ve cevap bu sınırlamayı açıklamıyorsa, uygulama karar etiketleriyle doğrulanabilir bir `Veri kalitesi notu` ekler. Kaynak etiketi, kesin sonuç ve zorunlu kapanış doğrulamasından geçmeyen cevap bir kez yeniden üretilir; ikinci deneme de geçersizse servis yine güvenli biçimde hata verir. Yanıta `model_cagri_sayisi` alanı eklenerek yeniden üretim gözlenebilir hâle getirildi ve API sürümü `1.4.0` oldu.

## Gerçek LM Studio ve Performans Sonuçları

Altı farklı hukuk alanı olayı gerçek `google/gemma-4-12b-qat` modeliyle çalıştırıldı. Altı cevabın tamamı başarıyla üretildi; kaynak etiketi doğrulama, veri kalitesi açıklama ve sıfır reasoning oranları `1,00` oldu. Beş olay ilk denemede tamamlandı, işe iade olayı zorunlu kapanış eksikliği nedeniyle bir kez yeniden üretildi; toplam yedi model çağrısı yapıldı ve nihai başarısızlık oluşmadı. Tek çapa kararın nihai kaynak listesinde bulunma oranı `0,666667` oldu; bu oran da tek-çapa sınırlamasına tabidir.

Semantik aramanın medyan süresi `77,849 ms`, yüzde 95 süresi `80,832 ms` ölçüldü. RAG cevabının medyanı `17.176,865 ms`, yüzde 95 değeri tekrar yapılan olay dâhil `28.966,900 ms` oldu. Bütün değerlendirme 136,468 saniyede tamamlandı. Qdrant'ın 20.000 üzeri noktalarda yerel mod uyarısı devam etmektedir; mevcut geliştirme sistemi çalışsa da üretim performansı için sunucu veya Docker modu sonraki altyapı adımıdır.

## Bruno ve Regresyon Kontrolleri

Bruno koleksiyonuna `20. Gün Değerlendirilmiş RAG Varsayılanları` isteği eklendi. İstek `top_k` ve `min_score` göndermeden API'nin değerlendirilmiş varsayılanlarını, prompt `1.1` sürümünü, en az iki karar bulunmasını ve veri kalitesi sınırlamasının cevapta açıklanmasını sınar. Bruno `4.0.0` masaüstü Runner'da `Local` ortamıyla **10 isteğin 10'u geçti; 0 başarısız ve 0 atlanan** sonuç alındı.

19. gün HTTP uçtan uca aracı güncel API üzerinde yeniden çalıştırıldı ve sistem durumu, doğrulama hataları, sınır uzunluğu, semantik arama ile embedding-Qdrant-Gemma zincirinin tamamı geçti. Projenin bütün otomatik testlerinde **132 test geçti**; `app`, `scripts` ve `tests` dizinleri `compileall` ile, değişiklikler de `git diff --check` ile doğrulandı.

## Sınırlamalar

- Sorgular corpus kararlarından elle türetildiği için bağımsız son kullanıcı testi değildir.
- Her kapsam içi sorguda tek çapa karar vardır; üstteki başka bir kararın ilgisiz olduğu sonucu çıkarılamaz.
- Alan dışı set yalnızca beş idari yargı senaryosundan oluşur.
- Chunk karşılaştırması tam corpus üzerinde yeniden indeksleme değildir.
- Otomatik yapı ve güvenlik kontrolleri, hukuk uzmanının karar ilgililiği ve cevap doğruluğu incelemesinin yerini tutmaz.

## Sonuç

20. günde sabit ve yeniden çalıştırılabilir bir değerlendirme seti oluşturuldu; arama ayarları gerçek indeks üzerinde ölçülerek RAG varsayılanı `top_k=10` ve `min_score=0,65` olarak güncellendi. Chunk seçenekleri karşılaştırıldı, 800/200 gelecek tam indeks deneyi için aday seçildi, ancak sınırlı havuz nedeniyle mevcut indeks korunarak gereksiz yeniden indekslemeden kaçınıldı. Prompt, veri kalitesi açıklaması ve tek seferlik güvenli yeniden üretim ile güçlendirildi; LM Studio/Gemma canlı değerlendirmesinde altı olayın tamamı, Bruno'da 10 isteğin tamamı ve 132 otomatik test nihai doğrulamadan geçti.

# 10. Gün - Veri Temizleme ve Bütünlük Kontrolü

## Amaç

15.000 kayıtlık ham Yargıtay veri kümesindeki boş, eksik, hatalı ve tekrarlanan kayıtları belirlemek; metinlerdeki HTML kalıntılarını, özel karakterleri ve gereksiz boşlukları temizlemek; kayıtları standart bir biçime getirip veri bütünlüğünü ölçülebilir kontrollerle doğrulamak.

Bu günün çalışması, 9. günde oluşturulan ham corpus üzerinde yürütüldü. Kaynak veride bulunmayan esas numarası veya karar tarihi gibi bilgiler tahmin edilmedi. Temizleme işlemi metin biçimini iyileştirirken kaynak metnin hukuki içeriğini değiştirmeyecek ve kaynakta 2.000 karakterle sınırlanmış kararları yanlış biçimde tam metin gibi göstermeyecek şekilde tasarlandı.

## Ham Veri Profili

Temizleme öncesinde `data/raw/yargitay_turklegalbench_15000.jsonl` dosyasındaki bütün kayıtlar tarandı.

| Kontrol | Sonuç |
| --- | ---: |
| Toplam kayıt | 15.000 |
| Benzersiz kaynak kimliği | 15.000 |
| Boş karar metni | 0 |
| HTML etiketi içeren metin | 0 |
| HTML karakter referansı içeren metin | 0 |
| Unicode özel boşluk içeren kayıt | 361 |
| Unicode özel boşluk karakteri | 1.624 |
| Kaynak başında hatalı tırnak bulunan kayıt | 14.999 |
| Eksik esas numarası | 1 |
| Eksik karar numarası | 0 |
| Eksik karar tarihi | 8 |
| Kaynakta tam 2.000 karakter olan metin | 8.355 |

`daire`, `esas_no` ve `karar_no` birlikte karar kimliği kabul edildiğinde 108 mükerrer grup ve bu gruplarda korunacak tekil kayıtların dışında 130 fazla kayıt bulundu. Bu grupların 55'inde metinler aynı, 53'ünde ise aynı karar kimliği için farklı uzunlukta metin varyantları vardı.

Ham veride ayrıca metni birebir aynı olan 129 grup görüldü. Bunların bir bölümü farklı esas ve karar numaralarına sahip gerçek ayrı kararlardı. Örneğin aynı aktarım metni çok sayıda farklı Ceza Dairesi kararında kullanılabiliyordu. Bu nedenle yalnızca metin eşitliğine bakarak kayıt silmenin hukuki kararları yanlışlıkla kaybettireceği sonucuna varıldı.

## Temizleme ve Standartlaştırma Aracı

`scripts/clean_yargitay_data.py` aracı eklendi. Araç her JSONL satırını UTF-8 ve JSON bütünlüğü, zorunlu alanlar, desteklenen karar türü, Yargıtay mahkeme adı, benzersiz kaynak kimliği ve geçersiz kontrol karakterleri açısından doğrulamaktadır. Boş satır, geçersiz JSON, tekrar kaynak kimliği, boş karar metni veya beklenmeyen kayıt sayısı görülürse tamamlanmış çıktı yayımlanmadan işlem durur.

Karar metinlerine sırasıyla şu işlemler uygulanmaktadır:

- Satır sonlarını `LF` biçiminde standartlaştırma.
- Varsa HTML etiketlerini kaldırma, `script` ve `style` içeriğini dışlama ve blok/paragraf ayrımlarını koruma.
- HTML karakter referanslarını gerçek Unicode karakterlere dönüştürme.
- Bölünemez, şekil ve dar bölünemez boşlukları normal boşluğa dönüştürme.
- Sıfır genişlikli karakterleri kaldırma.
- Unicode NFC normalizasyonu uygulama.
- Satır başı/sonu ve tekrarlanan yatay boşlukları temizleme; üç veya daha fazla satır sonunu tek paragraf aralığına indirme.
- `İçtihat Metni"` kaynak kalıntısındaki hatalı tırnağı kaldırma; tırnaktan sonra metin bitişik geldiyse paragraf ayrımı ekleme.

Mevcut TurkLegalBench ham dosyasında HTML etiketi ve HTML karakter referansı bulunmadığı için bu iki işlem gerçek corpus üzerinde değişiklik üretmedi. Buna rağmen iki temizleme yolu da gelecekte resmî servisten gelebilecek HTML içerik için uygulanmış ve otomatik testlerle doğrulanmıştır.

## Mükerrer Kayıt Politikası

Mükerrerlik ölçütü yalnızca `(daire, esas_no, karar_no)` üçlüsüdür. Üç alanın da dolu olduğu aynı kimlik grubunda metni en uzun kayıt korunur. Uzunluk eşitse karar tarihi bulunan kayıt, bu da eşitse ham dosyada önce gelen kayıt seçilir. Düşürülen her kayıt, hangi kayıt lehine çıkarıldığı ve iki metnin uzunluklarıyla birlikte ayrı denetim dosyasına yazılır.

Metin içeriği aynı olsa bile karar kimliği farklı olan kayıtlar silinmedi. Temiz çıktıdaki bu kayıtlar `ayni_metin_farkli_kararlarda` uyarısıyla etiketlendi ve aynı metne sahip kayıt sayısı `ayni_metin_kayit_sayisi` alanında saklandı. Böylece corpus küçültülürken farklı hukuki kararların kaybolması engellendi.

## Kalite Alanları

Her temiz kayda aşağıdaki türetilmiş alanlar eklendi:

- `karar_metni_sha256`: temiz metnin SHA-256 karması.
- `karar_metni_karakter_sayisi`: temiz metnin karakter sayısı.
- `ayni_metin_kayit_sayisi`: aynı temiz metni taşıyan karar sayısı.
- `veri_kalite_uyarilari`: kayda ait kalite uyarılarının listesi.
- `veri_kalite_durumu`: `gecerli` veya `uyarili`.
- `temizleme_surum`: uygulanan temizleme kuralı sürümü.

Eksik metadata `null` olarak korundu ve sırasıyla `eksik_esas_no`, `eksik_karar_no` veya `eksik_karar_tarihi` uyarısına dönüştürüldü. Kaynakta tam 2.000 karakter olan metinler `kaynak_metin_2000_karakter_sinirinda` uyarısını aldı. Bu uyarılar birbirini dışlamadığından bir kayıt birden fazla kalite uyarısı taşıyabilir.

## Üretilen Çıktılar

Temizleme komutu:

```powershell
python scripts/clean_yargitay_data.py
```

Yerel olarak şu dosyalar üretildi:

- `data/processed/yargitay_clean_14870.jsonl`: temiz ve kalite etiketli corpus.
- `data/processed/yargitay_clean_duplicates.jsonl`: çıkarılan mükerrer kayıtların denetim izi.
- `data/processed/yargitay_clean_stats.json`: toplu temizlik ve kalite istatistikleri.

| Sonuç | Değer |
| --- | ---: |
| Girdi kaydı | 15.000 |
| Temiz çıktı kaydı | 14.870 |
| Benzersiz çıktı kimliği | 14.870 |
| Mükerrer karar kimliği grubu | 108 |
| Ayrılan mükerrer kayıt | 130 |
| Temizleme değişikliği yapılan ham kayıt | 14.999 |
| Özel boşluğu temizlenen kayıt | 361 |
| Değiştirilen özel boşluk karakteri | 1.624 |
| Boşluk düzeni standartlaştırılan kayıt | 163 |
| Hatalı kaynak tırnağı temizlenen kayıt | 14.999 |
| HTML etiketi temizlenen kayıt | 0 |
| HTML karakter referansı çözülen kayıt | 0 |
| Satır sonu biçimi değiştirilen kayıt | 0 |
| Unicode NFC biçimi değiştirilen kayıt | 0 |

Temiz çıktıdaki metin eşitliği ve kalite sonuçları:

| Kalite sonucu | Değer |
| --- | ---: |
| Aynı metne sahip farklı karar grubu | 74 |
| Bu gruplardaki kayıt | 577 |
| Eksik esas numarası | 1 |
| Eksik karar numarası | 0 |
| Eksik karar tarihi | 8 |
| Kaynakta 2.000 karakter sınırında kalan kayıt | 8.291 |
| En az bir kalite uyarısı taşıyan kayıt | 8.731 |

8.355 olan kaynak metin sınırı sayısının temiz çıktıda 8.291'e düşmesi, karar kimliği mükerrerleri arasından 64 adet 2.000 karakterlik fazla kaydın denetim iziyle ayrılmasından kaynaklanmaktadır; metinler tamamlanmış veya kesilmemiş değildir.

Temiz corpus dosyasının SHA-256 değeri:

```text
9ee5f11d0f38ea82ac61e6916c09beedd8d741112fe797eeb764f2343d257999
```

Büyük ve yeniden üretilebilir ham/işlenmiş JSONL dosyaları ile istatistik çıktısı `.gitignore` kapsamındadır. Kod, testler ve yöntem raporu Git'te tutulmaktadır.

## Bütünlük Doğrulaması

Üretimden sonra temiz çıktı bağımsız olarak yeniden okunup şu kontroller yapıldı:

- Kayıt sayısı, benzersiz kaynak kimliği ve benzersiz karar kimliği sayıları doğrulandı.
- Mükerrer denetim dosyasında tam 130 kayıt bulunduğu doğrulandı.
- Dosyadan yeniden hesaplanan SHA-256 değerinin istatistik dosyasıyla aynı olduğu görüldü.
- HTML etiketi, kaynak başındaki hatalı tırnak, Unicode özel boşluk ve geçersiz kontrol karakteri kalmadığı doğrulandı.
- Her kaydın metin karması ve karakter sayısı yeniden hesaplandı.
- Kalite uyarısı ile `veri_kalite_durumu` alanlarının birbiriyle uyumlu olduğu doğrulandı.

Temizleme için altı yeni birim testi eklendi. Bu testler HTML/karakter referansı/özel boşluk temizliğini, paragraf korumayı, aynı karar kimliğinde en uzun metnin seçilmesini, farklı kararlardaki aynı metnin korunmasını, eksik metadata'nın uyarıya dönüştürülmesini, geçersiz JSON ve boş metnin reddedilmesini, yanlış kayıt sayısında atomik duruşu ve tekrar kaynak kimliğinin reddedilmesini kapsamaktadır. Önceki günlerin testleriyle birlikte toplam 58 otomatik test başarıyla geçti; Python derleme kontrolü ve `git diff --check` de tamamlandı.

## 10. Gün Sonucu

15.000 kayıtlık ham Yargıtay corpusunun tamamı doğrulandı, metinleri standartlaştırıldı ve aynı karar kimliğine ait 130 fazla kayıt denetim izi korunarak ayrıldı. Sonuçta 14.870 benzersiz karar kaydı içeren, her metni karmalanmış ve kalite alanları eklenmiş temiz corpus oluşturuldu.

Eksik metadata veya 2.000 karakterlik kaynak sınırı gizlenmedi; bilgi uydurmak yerine açık kalite uyarıları üretildi. Aynı metni paylaşan farklı esas/karar numaraları da yanlışlıkla silinmedi. Böylece bir sonraki parçalama ve embedding aşaması için yeniden üretilebilir, ölçülmüş ve sınırlamaları belgelenmiş bir veri tabanı hazırlandı.

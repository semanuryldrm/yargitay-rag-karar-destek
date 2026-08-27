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

## Uyarı

Bu proje eğitim ve karar destek amacıyla geliştirilmektedir. Üretilen sonuçlar hukuki danışmanlık veya kesin hukuki görüş niteliğinde değildir.


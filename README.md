# Paper Trade Bot

Kağıt üzerinde (sanal parayla) çalışan kripto işlem botu. Eğitim PDF'lerindeki
mum formasyonlarını ve indikatörleri dört varlık üzerinde iki farklı zaman
diliminde uygular, sonuçları Streamlit panelinde gösterir.

Gerçek emir gönderilmez. Borsa API anahtarı gerekmez ve kullanılmaz.

## Kurulum

```
pip install -r requirements.txt
```

## Çalıştırma

İki ayrı terminal gerekir.

Bot (veri çeker, sinyal üretir, sanal işlem açar):

```
python runner.py
```

Panel:

```
streamlit run app.py
```

Geçmiş veri üzerinde test:

```
python backtest.py --days 30
```

## İnternete açma (Streamlit Community Cloud)

1. [share.streamlit.io](https://share.streamlit.io) adresine GitHub hesabınla gir.
2. "New app" de, bu depoyu ve `app.py` dosyasını seç.
3. Deploy'a bas. Birkaç dakika sonra paylaşabileceğin bir link verir.

Streamlit Cloud yalnızca `app.py`'yi çalıştırır, `runner.py`'yi ayrı süreç olarak
başlatamaz. Bu yüzden `bot_thread.py`, bulut ortamını tanıyınca botu uygulamanın
içinde arka plan iş parçacığı olarak başlatır. Ek ayar gerekmez.

Bulutta veritabanı kalıcı değildir. Uygulama uyuyup uyandığında sıfırlanır ve bot
son 3 günü yeniden işleyerek baştan başlar. Uzun süreli kesintisiz kayıt istiyorsan
botu kendi bilgisayarında ya da sürekli açık bir sunucuda çalıştırmalısın.

Botu yerel makinede uygulama içinde çalıştırmak istersen (ayrı terminal açmadan):

```
RUN_BOT_IN_APP=1 streamlit run app.py
```

Dikkat: bunu yaparken `python runner.py` ayrıca çalışmamalı. İki döngü aynı cüzdana
yazarsa her işlem iki kez açılır.

## Portföy

Toplam 10.000 USD, coin riskine göre bölünmüş. Her coin kendi payını 5m ve 15m
stratejileri arasında yarı yarıya paylaştırır.

| Coin | Borsa | Risk | Pay | USD | İşlem başına risk |
|---|---|---|---|---|---|
| XRP | Binance | düşük | %55 | 5.500 | %2,0 |
| DEBIT | KuCoin | orta | %27 | 2.700 | %1,5 |
| ROBIN | MEXC | yüksek | %18 | 1.800 | %1,0 |

Trabzonspor Fan Token çıkarıldı. İşlem gördüğü borsalarda günlük hacim yaklaşık
15.000 dolar. 250 dolarlık bir pozisyon bile günlük hacmin yüzde 1,7'si eder ve
gerçek piyasada fiyatı kendi kendine hareket ettirir. Orada yapılan simülasyon
gerçek uygulamada anlamını kaybediyordu.

Spot işlemde kaldıraç yok, pozisyon bakiyeyi geçemez. Pozisyon büyüklüğü ayrıca
giriş mumunun hacminin yüzde 2'siyle sınırlı, çünkü ince bir emir defterinde
bunun üzerindeki bir dolum inandırıcı değil. Her işlem gerçekte riske attığı
tutarı kaydeder ve panel bunu gösterir.

## Strateji

Giriş, kapanmış bir mumda şu dört koşul birden sağlanınca:

1. Dört boğa mum formasyonundan biri: hamile boğa, kros hamile boğa,
   doji yıldız boğa, çekiç. Hepsi kısa vadeli düşüş ön koşulu içerir.
2. Rejim filtresi: fiyat 200 periyotluk EMA'nın üstünde olmalı.
3. Teyit: RSI 45'in altında veya MACD son 3 mumda sinyal çizgisini yukarı kesti.
4. Hacim, son 20 mum ortalamasının en az yarısı.

İkinci madde eğitim materyalinden bir sapma. Materyal, düşüş trendinde dönüş
formasyonu almayı öneriyor. Kriptoda bu, düşen bıçağı yakalamaya çalışmak
anlamına geliyor. Rejim filtresi girişi koruyor ama uzun vadeli trendin yukarı
olmasını şart koşuyor, böylece formasyon bir dip tahmini değil yükseliş içindeki
geri çekilme oluyor. 180 günlük testte bu filtre sonucu yüzde -40,5'ten
yüzde -17,8'e çıkardı.

Çıkış, hangisi önce gelirse:

- Stop-loss: formasyon dibi ile giriş eksi 2,5 ATR değerlerinden geniş olanı,
  en az %1,5 mesafede.
- Take-profit: risk mesafesinin 2 katı.
- Ayı formasyonu (hamile ayı, yutan ayı, kara bulut).
- Süre limiti: 5m'de 48 mum, 15m'de 32 mum.

Sadece long. Short ve kaldıraç yok.

## Test sonuçları

Kısa test tek bir piyasa dönemini ölçer. O dönem yükselişse sonuç yanıltıcı
çıkar. Uzun test her iki yönü de içerir. İkisi ayrı ayrı saklanır ve panelde
ayrı sayfalarda görünür.

```
python backtest.py --days 30     kısa test
python backtest.py --long        180 günlük test
```

| Test | Sonuç | Komisyon öncesi brüt | Ödenen komisyon |
|---|---|---|---|
| 30 gün | +%0,50 | +270 $ | 220 $ |
| 180 gün | -%17,80 | -811 $ | 969 $ |

Otuz günlük artı sonuç dönem şansıdır. Yüz seksen günde sinyalin kendisi
komisyon hesaba katılmadan bile zarardadır. Her iki test de al-tut karşılaştırması
gösterir: aynı parayı coine yatırıp hiç dokunmamak ne getirirdi.

Sadece XRP'de 180 günlük geçmiş var. DEBIT 15 gün, ROBIN 4 gün önce listelendi,
onlar kendi yaşları kadar veri katıyor.

## Dosyalar

| Dosya | İş |
|---|---|
| `config.py` | portföy, parametreler, komisyon, kural anahtarları |
| `store.py` | SQLite katmanı |
| `fetcher.py` | ccxt ile mum verisi |
| `signals.py` | indikatörler ve mum formasyonları |
| `engine.py` | pozisyon boyutu, giriş/çıkış kuralları, sanal cüzdan |
| `runner.py` | canlı döngü |
| `backtest.py` | geçmiş veri üzerinde aynı kurallar |
| `app.py` | Streamlit paneli |

`runner.py` yazar, `app.py` okur. Aralarındaki tek bağ `data.db` dosyası.

## Ayarlanabilir kurallar

`config.py` içindeki iki anahtar çıkış davranışını değiştirir:

- `USE_BEAR_PATTERN_EXIT` (varsayılan açık): ayı formasyonu görünce çık.
- `USE_MACD_EXIT` (varsayılan kapalı): MACD aşağı kesişince çık. 30 günlük
  testte her varlıkta zarar artırdı, bu yüzden kapalı.

Değiştirdikten sonra `python backtest.py --days 30` ile karşılaştır.

## Bilinen sınırlar

- DEBIT ve ROBIN yeni listelenmiş. Borsalar bunlar için 30 günlük 5m geçmişi
  vermiyor; elde ne varsa o kullanılıyor.
- TRA hacmi çok düşük. Az sinyal üretir, bu beklenen durumdur.
- 5m'de işlem sayısı yüksek olduğu için komisyon ve slippage sonucu belirgin
  şekilde aşağı çeker. 30 günlük testte 5m, 15m'den belirgin biçimde kötü.

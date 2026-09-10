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
| XRP | Binance | düşük | %50 | 5.000 | %2,0 |
| DEBIT | KuCoin | orta | %25 | 2.500 | %1,5 |
| ROBIN | MEXC | yüksek | %15 | 1.500 | %1,0 |
| TRA | OKX | çok yüksek | %10 | 1.000 | %1,0 |

Spot işlemde kaldıraç yok, bu yüzden pozisyon bakiyenin %50'sini geçemez. Stop
mesafesi %1'den darsa bu tavan devreye girer ve işlem başına gerçek risk hedeflenen
yüzdenin altında kalır. Panel her pozisyonun gerçek risk tutarını gösterir.

## Strateji

Giriş, kapanmış bir mumda şu üç koşul birden sağlanınca:

1. Dört boğa mum formasyonundan biri: hamile boğa, kros hamile boğa,
   doji yıldız boğa, çekiç. Hepsi düşüş trendi ön koşulu içerir.
2. Teyit: RSI 45'in altında veya MACD son 3 mumda sinyal çizgisini yukarı kesti.
3. Hacim, son 20 mum ortalamasının en az yarısı.

Çıkış, hangisi önce gelirse:

- Stop-loss: formasyon dibi ile giriş eksi 1,5 ATR değerlerinden geniş olanı,
  en az %0,6 mesafede.
- Take-profit: risk mesafesinin 2 katı.
- Ayı formasyonu (hamile ayı, yutan ayı, kara bulut).
- Süre limiti: 5m'de 48 mum, 15m'de 32 mum.

Sadece long. Short ve kaldıraç yok.

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

# Paper Trading Bot — Tasarım Dokümanı

Tarih: 2026-09-10
Durum: Taslak, kullanıcı onayı bekliyor

## 1. Amaç

Dört kripto varlık üzerinde, eğitim PDF'lerindeki teknik analiz kurallarını (mum formasyonları, indikatörler, grafik formasyonları) otomatik uygulayan, gerçek para kullanmadan sanal cüzdanla al/sat yapan bir bot. Aynı strateji iki zaman diliminde (5m ve 15m) eş zamanlı çalışır; birkaç günlük canlı simülasyon ve 30 günlük backtest ile hangi zaman diliminin ve hangi kuralların daha kârlı olduğu ölçülür. Sonuçlar Streamlit paneli üzerinden izlenir.

Gerçek borsa hesabı, API anahtarı veya gerçek emir gönderimi kapsam dışıdır. Tüm işlemler simülasyondur.

## 2. Varlıklar ve Veri Kaynakları

| Sembol | Ad | Borsa | ccxt id | Çift | Not |
|---|---|---|---|---|---|
| ROBIN | Robin the Frog | MEXC | `mexc` | `ROBIN/USDT` | Meme coin, yüksek volatilite |
| DEBIT | Teller | KuCoin | `kucoin` | `DEBIT/USDT` | Meme coin, yüksek volatilite |
| XRP | XRP | Binance | `binance` | `XRP/USDT` | Yüksek likidite, referans varlık |
| TRA | Trabzonspor Fan Token | OKX | `okx` | `TRA/USDT` | Çok düşük likidite, boş mumlar olabilir |

Tüm borsaların herkese açık OHLCV (mum) uç noktaları doğrulandı; API anahtarı gerekmez. Erişim `ccxt` kütüphanesinin `fetch_ohlcv` metodu ile yapılır. Her borsa için ayrı `ccxt` nesnesi oluşturulur, `enableRateLimit=True` ile hız sınırına uyulur.

Veri toplama yaklaşımı: REST polling (Yaklaşım A). WebSocket kullanılmaz.

## 3. Genel Mimari

```
btc/
  config.py              varlık listesi, zaman dilimleri, strateji parametreleri, komisyon/slippage
  data/
    fetcher.py           ccxt ile OHLCV çekme (geçmiş doldurma + artımlı güncelleme)
    store.py             SQLite okuma/yazma (mumlar, işlemler, sinyaller, cüzdan geçmişi)
  signals/
    indicators.py        EMA, RSI, MACD, Bollinger, ATR
    candles.py           2 mumluk formasyonlar (PDF: Mum Çubukları)
    formations.py        pivot tabanlı grafik formasyonları (Faz 3)
  strategy/
    rules.py             sinyal üretimi: giriş/çıkış kararı, SL/TP hesaplama
  paper/
    portfolio.py         sanal cüzdan, pozisyon yönetimi, komisyon, slippage
  runner.py              canlı döngü: çek, hesapla, karar ver, sanal işlem yap, kaydet
  backtest.py            aynı strateji, geçmiş veri üzerinde
  app.py                 Streamlit panel
  data.db                SQLite veritabanı (git dışı)
  requirements.txt
```

Bağımlılıklar: `ccxt`, `pandas`, `numpy`, `streamlit`, `plotly`, `pytest`. İndikatörler elle yazılır (pandas ile), ek kütüphane gerekmez. Python 3.12.

Runner ve Streamlit iki ayrı süreç olarak çalışır. Aralarındaki tek arayüz SQLite dosyasıdır. Streamlit sadece okur, runner sadece yazar.

## 4. Veri Katmanı

### 4.1 Mum tablosu

`candles(exchange, symbol, timeframe, ts, open, high, low, close, volume)`
Birincil anahtar: `(exchange, symbol, timeframe, ts)`. `ts` milisaniye UTC.

### 4.2 Fetcher davranışı

- İlk çalıştırmada her varlık ve her zaman dilimi için son 30 günlük mum çekilir (backtest için). ccxt sayfalama ile `since` parametresi ilerletilerek doldurulur; borsa başına tek istekte en fazla 1000 mum varsayılır.
- Sonraki döngülerde son kaydedilen `ts` değerinden itibaren yeni mumlar çekilir. Kapanmamış son mum (`ts + timeframe > now`) sinyal hesabına dahil edilmez; sadece görüntüleme için tutulur.
- Ağ hatası veya borsa hatası tek varlığı atlar, döngüyü durdurmaz. Hata `logs` tablosuna yazılır.
- TRA gibi düşük hacimli varlıklarda hacmi sıfır mumlar korunur; strateji katmanı hacim filtresiyle bunları eler.

### 4.3 Diğer tablolar

- `trades(id, strategy_id, exchange, symbol, timeframe, side, entry_ts, entry_price, exit_ts, exit_price, qty, sl, tp, pnl, pnl_pct, fee, reason_entry, reason_exit, status)`
- `signals(ts, strategy_id, symbol, timeframe, rule, direction, price, acted, note)` — hangi kural tetiklendi, işlem açıldı mı, açılmadıysa neden.
- `equity(ts, strategy_id, balance, unrealized, total)` — her döngüde snapshot.
- `logs(ts, level, message)`

## 5. Sinyal Katmanı

### 5.1 İndikatörler (`indicators.py`)

PDF "Osilatörler ve İndikatörler" belgesinden:

| İndikatör | Parametre | Kullanım |
|---|---|---|
| EMA | 9, 21, 50 | 9/21 giriş zamanlaması, 21/50 trend filtresi |
| RSI | 14, eşik 30/70 | Aşırı alım/satım teyidi |
| MACD | 12, 26, sinyal 9 | MACD çizgisi sinyal çizgisini yukarı keserse al, aşağı keserse sat |
| Bollinger | 20, 2 std | Yatay piyasada bant teması (v1'de sadece grafikte gösterilir) |
| ATR | 14 | Stop-loss mesafesi (PDF'te yok, risk yönetimi için eklendi) |

Hepsi `DataFrame` alıp kolon ekleyen saf fonksiyonlar. Yan etki yok.

### 5.2 Mum formasyonları (`candles.py`)

PDF "Mum Çubukları ve Formasyonları" belgesindeki 7 formasyon, her biri boolean kolon döndürür. Trend ön koşulu: son 10 mumun kapanışlarının çoğunluğu EMA 21'in altındaysa "düşüş trendi", üstündeyse "yükseliş trendi" sayılır.

Boğa (AL) formasyonları, düşüş trendinde aranır:
- `bullish_harami`: önceki mum kırmızı ve gövdesi son 20 mumun ortalama gövdesinin 1.2 katından büyük; mevcut mum yeşil ve gövdesi öncekinin gövdesinin tamamen içinde.
- `bullish_harami_cross`: harami ile aynı, ancak mevcut mum doji (gövde, toplam aralığın %10'undan küçük).
- `bullish_doji_star`: önceki mum kırmızı; mevcut mum doji ve açılışı önceki kapanışın altında (gap down).
- `hammer`: gövde toplam aralığın üst %30'unda; alt fitil gövdenin en az 2 katı; üst fitil gövdeden kısa.

Ayı (SAT) formasyonları, yükseliş trendinde aranır:
- `bearish_harami`: önceki mum yeşil ve büyük gövdeli; mevcut mum kırmızı ve gövdesi öncekinin içinde.
- `bearish_engulfing`: önceki mum yeşil ve küçük gövdeli; mevcut mum kırmızı ve gövdesi öncekinin gövdesini tamamen kapsıyor.
- `dark_cloud_cover`: önceki mum yeşil; mevcut mum kırmızı, açılışı önceki yüksekten yukarıda, kapanışı önceki gövdenin orta noktasının altında ama önceki açılışın üstünde.

Her formasyon için PDF'teki "Teyit Seviyesi" ve "Stop-Loss" seviyeleri şöyle hesaplanır:
- Boğa: teyit = formasyonun (2 mum) en yükseği; stop = formasyonun en düşüğü.
- Ayı: teyit = formasyonun en düşüğü; stop = formasyonun en yükseği.

### 5.3 Grafik formasyonları (`formations.py`) — Faz 3

PDF "Formasyonlar" belgesindeki İkili Tepe/Dip, OBO/TOBO, Yükselen/Alçalan Üçgen. Pivot tespiti: son N mumda yerel maksimum/minimum (sağ ve sol 5 mum ile karşılaştırma). Hedef = formasyon yüksekliği (h) kırılma noktasına eklenir. Faz 1 ve 2'de bu modül boş bırakılır; ilk sürümde yalnızca mum formasyonları ve indikatörler kullanılır.

## 6. Strateji Katmanı (`rules.py`)

### 6.1 Strateji kimliği

Her (varlık, zaman dilimi) çifti bağımsız bir strateji örneğidir. `strategy_id = f"{symbol}_{timeframe}"`, örnek `XRP_5m`, `XRP_15m`. Toplam 8 örnek. Her örneğin kendi sanal cüzdanı vardır; böylece 5m ve 15m adil karşılaştırılır.

### 6.2 Karar kuralları (v1, sadece long / spot)

Giriş koşulları (hepsi aynı kapanmış mumda sağlanmalı):
1. Boğa mum formasyonlarından en az biri tetiklendi (formasyon zaten düşüş trendi ön koşulunu içerir).
2. Teyit: RSI < 45 veya MACD çizgisi son 3 mum içinde sinyal çizgisini yukarı kesti.
3. Hacim filtresi: mevcut mum hacmi son 20 mumun ortalama hacminin %50'sinden fazla. Sıfır hacimli mumlar (TRA) sinyal üretmez.
4. Aynı strateji için açık pozisyon yok.

Giriş fiyatı: bir sonraki mumun açılışı + slippage.

Çıkış koşulları (hangisi önce gelirse):
1. Stop-loss: formasyon dibi ile `entry - 1.5 × ATR` değerlerinden hangisi girişe daha yakınsa o kullanılır (risk sınırlı kalır). Mum düşüğü SL'yi görürse SL fiyatından çıkılır.
2. Take-profit: `entry + 2 × (entry - sl)` (risk/ödül 1:2). Mum yükseği TP'yi görürse TP fiyatından çıkılır.
3. Ayı formasyonu veya MACD aşağı kesişimi: mevcut kapanıştan çıkılır.
4. Zaman limiti: 5m için 48 mum (4 saat), 15m için 32 mum (8 saat) içinde TP/SL gelmezse kapanıştan çıkılır.

Aynı mumda hem SL hem TP görülürse SL varsayılır (kötümser yaklaşım).

### 6.3 Pozisyon büyüklüğü

İşlem başına risk = cüzdanın %2'si. `qty = (balance × 0.02) / (entry - sl)`. Pozisyon değeri cüzdanın %50'sini geçemez. Minimum işlem 5 USDT altındaysa işlem açılmaz.

### 6.4 Parametreler

Tüm eşikler `config.py` içinde; kullanıcı değiştirebilir. Streamlit'ten değiştirilmez (v1).

## 7. Sanal Cüzdan (`portfolio.py`)

- Her strateji için başlangıç bakiyesi 1000 USDT (config).
- Komisyon: alış ve satışta %0.1 (Binance spot referansı). Slippage: alış ve satışta fiyatın %0.05'i aleyhte; ROBIN, DEBIT, TRA için %0.2 (düşük likidite).
- Gerçekleşmiş P&L işlem kapanınca bakiyeye eklenir. Gerçekleşmemiş P&L her döngüde son kapanışa göre hesaplanır.
- Cüzdan durumu SQLite'ta tutulur; runner yeniden başlatılınca açık pozisyonlar ve bakiye kaldığı yerden devam eder.

## 8. Runner (`runner.py`)

Döngü:
1. Her 60 saniyede bir tüm (varlık, zaman dilimi) çiftleri için yeni mumları çek.
2. Yeni kapanmış mum gelen çiftler için indikatör ve formasyonları hesapla (son 300 mum yeterli).
3. Açık pozisyonlar için çıkış kurallarını kontrol et; gerekirse kapat.
4. Pozisyon yoksa giriş kurallarını kontrol et; sinyal varsa `signals` tablosuna yaz ve pozisyon aç.
5. `equity` snapshot yaz.
6. Hata olursa logla, devam et.

Komut: `python runner.py`. Durdurmak için Ctrl+C. Windows'ta arka planda çalışması için ayrı terminal penceresi yeterli.

## 9. Backtest (`backtest.py`)

- Aynı `rules.py` ve `portfolio.py` kodu, geçmiş mumlar üzerinde mum mum ilerletilir. Kod tekrarı yok; runner ile backtest aynı fonksiyonu farklı veri kaynağıyla çağırır.
- Girdi: son 30 gün. Çıktı: her strateji için işlem listesi, toplam getiri, kazanma oranı, ortalama R, maksimum düşüş (drawdown), işlem sayısı.
- Sonuçlar `trades` tablosuna `strategy_id` sonuna `_bt` eki ile yazılır; panelde ayrı sekmede gösterilir.
- Komut: `python backtest.py --days 30`.

## 10. Streamlit Paneli (`app.py`)

Komut: `streamlit run app.py`. Otomatik yenileme 60 saniye.

Sekmeler:
1. **Özet**: 8 strateji için tablo: bakiye, gerçekleşmiş P&L, gerçekleşmemiş P&L, işlem sayısı, kazanma oranı, maksimum düşüş. 5m ve 15m yan yana kıyas. Toplam equity eğrisi (Plotly çizgi grafiği, strateji başına çizgi).
2. **Grafik**: varlık ve zaman dilimi seçici. Plotly mum grafiği + EMA 9/21/50 + Bollinger; alt panelde RSI ve MACD. Al/sat noktaları işaretli, tespit edilen formasyon adı mum üstünde etiket.
3. **Açık pozisyonlar**: giriş fiyatı, SL, TP, mevcut fiyat, gerçekleşmemiş P&L, geçen süre.
4. **İşlem geçmişi**: filtrelenebilir tablo, giriş/çıkış nedeni dahil.
5. **Sinyal logu**: hangi kural ne zaman tetiklendi, işlem açıldı mı, açılmadıysa neden (hacim filtresi, açık pozisyon vb.).
6. **Backtest**: 30 günlük sonuçlar, aynı özet tablosu.

Panel yalnızca SQLite okur. Ağır hesap yapmaz; formasyon etiketleri runner tarafından `signals` tablosuna yazılmış olanlardır.

## 11. Hata Yönetimi

- Borsa erişilemezse o varlık döngüde atlanır, 3 ardışık hata sonrası panelde uyarı görünür.
- SQLite eş zamanlı erişim: runner yazar, Streamlit okur; `PRAGMA journal_mode=WAL` ile çakışma önlenir.
- Eksik mum (boşluk) varsa fetcher boşluğu doldurmayı dener; dolduramazsa indikatör hesabı mevcut veriyle devam eder.
- Runner çökerse yeniden başlatıldığında açık pozisyonları DB'den yükler.

## 12. Test

- `signals/candles.py` ve `indicators.py`: elle hazırlanmış küçük OHLCV tablolarıyla birim testler (formasyon doğru tespit ediliyor mu, RSI bilinen değeri veriyor mu).
- `portfolio.py`: komisyon, slippage, P&L hesabı birim testleri.
- `rules.py`: sentetik seri ile giriş/çıkış senaryoları (SL tetiklenme, TP tetiklenme, zaman limiti).
- Backtest, uçtan uca duman testi olarak kullanılır.
- Test aracı: `pytest`.

## 13. Fazlar

1. **Faz 1**: config, fetcher, store, indicators, candles, rules, portfolio, runner, app (özet + grafik + açık pozisyon + geçmiş + sinyal sekmeleri). Çalışan canlı simülasyon.
2. **Faz 2**: backtest modülü ve backtest sekmesi.
3. **Faz 3**: grafik formasyonları (İkili Tepe/Dip, OBO/TOBO, üçgen) ve bunların strateji kurallarına eklenmesi.

## 14. Kapsam Dışı

- Gerçek emir gönderimi, API anahtarı, cüzdan bağlantısı.
- Short pozisyon, kaldıraç, vadeli işlemler.
- Parametre optimizasyonu (grid search).
- Bildirim (Telegram, e-posta).
- Panelden strateji parametresi değiştirme.

## 15. Bilinen Sınırlamalar

- TRA/USDT hacmi çok düşük; 5m'de çoğu mum boş. Hacim filtresi işlemi engeller, bu varlıkta 15m bile az sinyal üretir. Bu beklenen bir sonuçtur ve panelde görünür.
- Birkaç günlük canlı test az işlem üretir; istatistiksel karar için backtest sonuçlarıyla birlikte değerlendirilmelidir.
- Slippage ve komisyon tahminidir; gerçek piyasada özellikle meme coinlerde daha kötü olabilir.

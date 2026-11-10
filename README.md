# Simülig veri dosyaları

Bu depo, Simülig iOS uygulamasının indirdiği güncel takım güçlerini ve Süper Lig sezon durumunu tutar.
Dosyalar her hafta otomatik olarak yeniden üretilir.

## Dosyalar
- `teams.json`: ligler, kulüpler, milli takımlar ve efsane takımlar. Her takımın hücum ve savunma gücü (45-97) ile liglerin gol çarpanı (`goalFactor`).
- `season-tr-superlig.json`: Süper Lig 2026-27'nin gerçek durumu. Oynanan maçlar, puan tablosu, kalan fikstür, `updatedAt` (üretim zamanı, UTC).
- `manifest.json`: `version` (her güncellemede artar, YYYYMMDDHH), `generatedAt`, `season`, `superLigWeek` ve dosyaların SHA-256 özetleri. İstemci önce bunu okuyup sürüm değiştiyse diğer dosyaları indirebilir ve özetlerle doğrulayabilir.
- `scripts/`: dosyaları üreten Python 3 betikleri (yalnızca standart kütüphane).

## Kaynaklar
- Kulüp maç sonuçları, xG ve bahis oranları: [football-data.co.uk](https://www.football-data.co.uk) (2025-26 ve 2026-27; İngiltere, İspanya, İtalya, Almanya, Fransa, Hollanda, Portekiz, Türkiye).
- TFF 1. Lig sonuçları: Türkçe Vikipedi, "2025-26 1. Lig" ve "2026-27 1. Lig" sayfaları ile puan durumu şablonları.
- Milli maçlar: [martj42/international_results](https://github.com/martj42/international_results) (son 5 yıl).

## Güncelleme
GitHub Actions her pazartesi 06:00 UTC'de (ve elle tetiklendiğinde) çalışır:

```
python scripts/update_all.py --out .
```

Betik tüm kaynakları indirir, modelleri kurar ve sonucu doğrular (takım sayıları, tekrar eden id, 45-97 aralığı,
fikstürün eksiksiz olması, hafta bilgisi). Herhangi bir adım ya da doğrulama başarısız olursa hiçbir dosya değişmez.
Veri değiştiyse dosyalar `github-actions[bot]` tarafından commit edilir.

## Lisans
Bu dosyalar Simülig uygulaması için üretilmiş türetilmiş verilerdir. Ham veriler kaynaklarının kendi
koşullarına tabidir (football-data.co.uk, Vikipedi CC BY-SA, international_results). Betikler Simülig'e aittir.

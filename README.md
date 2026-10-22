# GİB Özelge MCP Sunucusu

Gelir İdaresi Başkanlığı'nın (gib.gov.tr) özelgelerini arayan ve tam metnini okuyan bir MCP sunucusu.

## Araçlar

| Araç | Ne yapar |
|---|---|
| `ozelge_ara` | Başlıkta ve tam metinde arama. Filtreler: tam ifade, kanun no (ör. `193`, `3065,5520`), tarih aralığı, sıralama, sayfalama. |
| `ozelge_oku` | Bir özelgenin tam metnini (düz metin), sayısını, tarihini, kanununu ve ilgili maddelerini getirir. |
| `kanun_listesi` | `kanun_no` filtresinde kullanılabilecek kanun numaralarını listeler. |

## Kurulum

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

Deneme (gerçek API'ye birkaç istek atar):

```powershell
.\.venv\Scripts\python.exe tests\smoke_test.py
```

## Claude'a ekleme

**Claude Code:**

```powershell
claude mcp add ozelge -- C:\PROJE\ozelge\.venv\Scripts\gib-ozelge-mcp.exe
```

**Claude Desktop** (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "ozelge": {
      "command": "C:\\PROJE\\ozelge\\.venv\\Scripts\\gib-ozelge-mcp.exe"
    }
  }
}
```

## Nasıl çalışıyor

gib.gov.tr bir Next.js sitesi; özelge verileri herkese açık JSON uçlarından geliyor (Chrome ağ trafiği ve sitenin JS paketleri incelenerek bulundu):

- `POST https://gib.gov.tr/api/gibportal/mevzuat/ozelge/list?page=0&size=10&sortFieldName=ozelgeTarih&sortType=DESC`
  Gövde: `{"status":2,"deleted":false,"title":"<terim>","kanunNo":"<terim>","description":"<terim>","kanunIds":[433],"ozelgeStartDate":"2024-01-01T00:00:00","ozelgeEndDate":"2024-12-31T23:59:59"}`
  Terim tırnak içindeyse (`"kira geliri"`) tam ifade aranır; değilse tüm kelimeleri içerenler döner.
- `GET https://gib.gov.tr/api/gibportal/mevzuat/ozelge/findById?id=<id>` – tek özelge (metin HTML olarak `description` alanında).
- `POST https://gib.gov.tr/api/gibportal/mevzuat/kanun/filterList?page=0&size=1000&sortFieldName=priority&sortType=ASC` – kanun numarası → iç `kanunId` eşlemesi.

Site kısa sürede çok istek gelirse **HTTP 429** döndürüyor. Sunucu istekleri sıraya koyup arada en az 1 saniye bekliyor ve 429'da artan sürelerle yeniden deniyor.

Bu resmi bir API değildir; site değişirse uçlar da değişebilir.


Windows paket sürümlerinde ayar klasörü değişebilir. Doğru dosyayı Claude ayarlarındaki geliştirici bölümünden açın. Örnek yolları kendi kurulumunuzun mutlak yolu ile değiştirin.

## Veri ve güvenlik

Sunucu stdio üzerinden yerel çalışır; ağ üzerinde dinleme portu açmaz. Üç araç GİB verilerini okur, dosya veya komut çalıştırma aracı sunmaz. Arama metni GİB sunucusuna HTTPS üzerinden gönderilir; aramalara kişisel veya gizli bilgiler yazmayın. Dış kaynaktan gelen özelge metinleri veri olarak ele alınmalı, talimat olarak uygulanmamalıdır.

.venv, kişisel Claude ayarları, erişim anahtarları ve günlükler depoya eklenmez. Bu proje GİB'in resmi ürünü değildir.

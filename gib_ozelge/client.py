"""GİB (gib.gov.tr) özelge API istemcisi.

Site bir Next.js uygulaması; veriler şu herkese açık JSON uçlarından geliyor:
  POST /api/gibportal/mevzuat/ozelge/list?page=&size=&sortFieldName=&sortType=   (arama/listeleme)
  GET  /api/gibportal/mevzuat/ozelge/findById?id=                                (tek özelge)
  POST /api/gibportal/mevzuat/kanun/filterList?page=&size=&sortFieldName=&sortType= (kanun listesi)

Sunucu kısa sürede çok istek gelince HTTP 429 döndürüyor; bu yüzden istekler
arasında bekleme ve 429'da geri çekilip yeniden deneme var.
"""

from __future__ import annotations

import asyncio
import re
import time
from html import unescape
from html.parser import HTMLParser
from typing import Any

import httpx

BASE_URL = "https://gib.gov.tr/api/gibportal/"
SITE_URL = "https://gib.gov.tr/mevzuat/kanun/{kanun_id}/ozelge/{id}"
USER_AGENT = "Mozilla/5.0 (compatible; gib-ozelge-mcp/0.1)"


class GibError(RuntimeError):
    pass


class GibClient:
    def __init__(self, min_interval: float = 1.0, max_retries: int = 4, timeout: float = 30.0):
        self._http = httpx.AsyncClient(
            base_url=BASE_URL,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._lock = asyncio.Lock()
        self._last_request = 0.0
        self._kanun_cache: list[dict[str, Any]] | None = None

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _request(self, method: str, path: str, *, params=None, json=None) -> Any:
        delay = 2.0
        for attempt in range(self._max_retries + 1):
            async with self._lock:  # istekleri sıraya koy ve aralarına boşluk bırak
                wait = self._min_interval - (time.monotonic() - self._last_request)
                if wait > 0:
                    await asyncio.sleep(wait)
                try:
                    resp = await self._http.request(method, path, params=params, json=json)
                finally:
                    self._last_request = time.monotonic()

            if resp.status_code in (429, 502, 503, 504) and attempt < self._max_retries:
                retry_after = resp.headers.get("Retry-After", "")
                await asyncio.sleep(float(retry_after) if retry_after.isdigit() else delay)
                delay *= 2
                continue
            if resp.status_code == 429:
                raise GibError("GİB sunucusu çok fazla istek nedeniyle geçici olarak engelledi (429). Biraz bekleyip tekrar deneyin.")
            if resp.status_code >= 400:
                raise GibError(f"GİB API hatası: HTTP {resp.status_code} ({path})")

            data = resp.json()
            if isinstance(data, dict) and data.get("status") not in (None, 200):
                raise GibError(f"GİB API hatası: {data.get('status')} {data.get('messages')}")
            return data.get("resultContainer") if isinstance(data, dict) else data
        raise GibError("GİB API'ye ulaşılamadı.")

    # ---- kanunlar -------------------------------------------------------

    async def kanunlar(self) -> list[dict[str, Any]]:
        if self._kanun_cache is None:
            rc = await self._request(
                "POST", "mevzuat/kanun/filterList",
                params={"page": 0, "size": 1000, "sortFieldName": "priority", "sortType": "ASC"},
                json={},
            )
            items = rc.get("content", []) if isinstance(rc, dict) else (rc or [])
            self._kanun_cache = [
                {"id": k.get("id"), "kanun_no": str(k.get("kanunNo") or "").strip(), "baslik": (k.get("title") or "").strip()}
                for k in items
            ]
        return self._kanun_cache

    async def kanun_idleri(self, kanun_nolari: list[str]) -> list[int]:
        wanted = {n.strip() for n in kanun_nolari if n.strip()}
        kanunlar = await self.kanunlar()
        ids = [k["id"] for k in kanunlar if k["kanun_no"] in wanted]
        missing = wanted - {k["kanun_no"] for k in kanunlar}
        if missing:
            raise GibError(f"Bilinmeyen kanun numarası: {', '.join(sorted(missing))}. kanun_listesi aracıyla kontrol edin.")
        return ids

    # ---- özelgeler -------------------------------------------------------

    async def ara(
        self,
        sorgu: str = "",
        *,
        tam_ifade: bool = False,
        kanun_idleri: list[int] | None = None,
        baslangic: str | None = None,
        bitis: str | None = None,
        sayfa: int = 0,
        boyut: int = 10,
        en_yeni_once: bool = True,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"status": 2, "deleted": False}
        terim = sorgu_hazirla(sorgu, tam_ifade)
        if terim:
            # Sitenin kendisi de aynı metni üç alana birden gönderiyor (başlık, kanun no, metin).
            body.update(title=terim, kanunNo=terim, description=terim)
        if kanun_idleri:
            body["kanunIds"] = kanun_idleri
        if baslangic:
            body["ozelgeStartDate"] = f"{baslangic}T00:00:00"
        if bitis:
            body["ozelgeEndDate"] = f"{bitis}T23:59:59"
        rc = await self._request(
            "POST", "mevzuat/ozelge/list",
            params={"page": sayfa, "size": boyut, "sortFieldName": "ozelgeTarih",
                    "sortType": "DESC" if en_yeni_once else "ASC"},
            json=body,
        )
        return {
            "toplam": rc.get("totalElements", 0),
            "toplam_sayfa": rc.get("totalPages", 0),
            "sonuclar": [ozet(it) for it in rc.get("content", [])],
        }

    async def getir(self, ozelge_id: int) -> dict[str, Any]:
        rc = await self._request("GET", "mevzuat/ozelge/findById", params={"id": ozelge_id})
        if not rc:
            raise GibError(f"{ozelge_id} numaralı özelge bulunamadı.")
        d = ozet(rc)
        d["metin"] = html_to_text(rc.get("description") or "")
        d["ilgili_maddeler"] = [
            m.get("title") or m.get("maddeNo") for m in (rc.get("maddeList") or []) if m.get("title") or m.get("maddeNo")
        ]
        d["ekler"] = rc.get("fileNames") or []
        return d


def sorgu_hazirla(sorgu: str, tam_ifade: bool) -> str:
    """Sitedeki davranışın aynısı: tırnak içindeki metin tam ifade olarak aranır,
    aksi halde tüm kelimeleri içeren kayıtlar döner."""
    s = (sorgu or "").strip()
    if not s:
        return ""
    if (s[0] == s[-1] and s[0] in "\"'") and len(s) > 1:
        return s
    if tam_ifade:
        return '"' + s.strip("\"'") + '"'
    return s


def ozet(it: dict[str, Any]) -> dict[str, Any]:
    tarih = (it.get("ozelgeTarih") or "")[:10]
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", tarih):
        y, m, g = tarih.split("-")
        tarih = f"{g}.{m}.{y}"
    return {
        "id": it.get("id"),
        "baslik": (it.get("title") or "").strip(),
        "ozelge_no": it.get("ozelgeNo"),
        "tarih": tarih,
        "kanun_no": it.get("kanunNo"),
        "kanun": it.get("kanunTitle"),
        "url": it.get("siteLink") or SITE_URL.format(kanun_id=it.get("kanunId"), id=it.get("id")),
    }


# ---- HTML -> düz metin ------------------------------------------------------

_BLOCK = {"p", "div", "br", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "tbody", "ul", "ol", "blockquote"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0
        self._cell = 0  # tablo hücresi içindeyken paragraflar satır kırmaz

    def _block(self, tag) -> None:
        if self._cell and tag not in ("tr", "table", "tbody"):
            self.parts.append(" ")
        else:
            self.parts.append("\n")

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("td", "th"):
            self._cell += 1
            self.parts.append(" ")
        elif tag in _BLOCK:
            self._block(tag)
        elif tag == "li":
            self.parts.append("\n- ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th"):
            self._cell = max(0, self._cell - 1)
            self.parts.append(" ")
        elif tag in _BLOCK:
            self._block(tag)

    def handle_data(self, data):
        if not self._skip:
            # HTML'de kaynak koddaki satır sonları yalnızca boşluktur
            self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> str:
    p = _TextExtractor()
    p.feed(html)
    p.close()
    text = unescape("".join(p.parts)).replace("\xa0", " ")
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.split("\n")]
    out: list[str] = []
    for ln in lines:
        if ln or (out and out[-1]):
            out.append(ln)
    return "\n".join(out).strip()

"""GİB özelge MCP sunucusu (stdio)."""

from __future__ import annotations

import logging
import re
from typing import Annotated, Literal

from pydantic import Field

from mcp.server.mcpserver import MCPServer

from .client import GibClient, GibError

mcp = MCPServer(
    name="ozelge",
    instructions=(
        "Gelir İdaresi Başkanlığı (gib.gov.tr) özelgelerini arar ve okur. "
        "Önce ozelge_ara ile ilgili özelgeleri bulun, sonra ozelge_oku ile tam metni okuyun. "
        "Arama başlıkta ve tam metinde yapılır; birden çok kelime verilirse hepsini içerenler döner."
    ),
)

_client: GibClient | None = None


def client() -> GibClient:
    global _client
    if _client is None:
        _client = GibClient()
    return _client


_TARIH = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _tarih(v: str | None, ad: str) -> str | None:
    if not v:
        return None
    v = v.strip()
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", v)
    if m:
        v = f"{m[3]}-{m[2]}-{m[1]}"
    if not _TARIH.match(v):
        raise GibError(f"{ad} YYYY-AA-GG veya GG.AA.YYYY biçiminde olmalı: {v!r}")
    return v


@mcp.tool()
async def ozelge_ara(
    sorgu: Annotated[str, Field(description="Aranacak kelime(ler). Boş bırakılırsa filtrelere uyan en son özelgeler listelenir.")] = "",
    tam_ifade: Annotated[bool, Field(description="True ise sorgu tam ifade olarak aranır (sitedeki 'Tam ifadeyi ara').")] = False,
    kanun_no: Annotated[str | None, Field(description="Kanun numarasıyla filtre, ör. '193' (GVK), '3065' (KDV), '5520' (KVK). Virgülle birden fazla verilebilir.")] = None,
    baslangic_tarihi: Annotated[str | None, Field(description="Özelge tarihi alt sınırı (YYYY-AA-GG veya GG.AA.YYYY).")] = None,
    bitis_tarihi: Annotated[str | None, Field(description="Özelge tarihi üst sınırı (YYYY-AA-GG veya GG.AA.YYYY).")] = None,
    siralama: Annotated[Literal["yeni", "eski"], Field(description="Tarihe göre sıralama.")] = "yeni",
    sayfa: Annotated[int, Field(ge=1, description="Sayfa numarası (1'den başlar).")] = 1,
    sayfa_boyutu: Annotated[int, Field(ge=1, le=50, description="Sayfa başına sonuç (en fazla 50).")] = 10,
) -> str:
    """GİB özelgelerinde arama yapar; başlık, özelge no, tarih, kanun ve id döndürür."""
    try:
        c = client()
        ids = await c.kanun_idleri(kanun_no.split(",")) if kanun_no else None
        r = await c.ara(
            sorgu,
            tam_ifade=tam_ifade,
            kanun_idleri=ids,
            baslangic=_tarih(baslangic_tarihi, "baslangic_tarihi"),
            bitis=_tarih(bitis_tarihi, "bitis_tarihi"),
            sayfa=sayfa - 1,
            boyut=sayfa_boyutu,
            en_yeni_once=siralama == "yeni",
        )
    except GibError as e:
        return f"Hata: {e}"

    if not r["sonuclar"]:
        return "Sonuç bulunamadı." if r["toplam"] == 0 else f"Bu sayfada sonuç yok (toplam {r['toplam']} sonuç, {r['toplam_sayfa']} sayfa)."

    satirlar = [f"Toplam {r['toplam']} özelge bulundu (sayfa {sayfa}/{r['toplam_sayfa']}).", ""]
    for i, s in enumerate(r["sonuclar"], start=(sayfa - 1) * sayfa_boyutu + 1):
        satirlar.append(
            f"{i}. [{s['id']}] {s['baslik']}\n"
            f"   Tarih: {s['tarih']} | Sayı: {s['ozelge_no']} | Kanun: {s['kanun_no']} {s['kanun'] or ''}\n"
            f"   {s['url']}"
        )
    satirlar.append("\nTam metin için ozelge_oku aracına köşeli parantezdeki id'yi verin.")
    return "\n".join(satirlar)


@mcp.tool()
async def ozelge_oku(
    ozelge_id: Annotated[int, Field(description="ozelge_ara sonucundaki id (köşeli parantez içindeki sayı) veya özelge sayfası URL'sinin sonundaki sayı.")],
) -> str:
    """Bir özelgenin tam metnini ve bilgilerini getirir."""
    try:
        d = await client().getir(ozelge_id)
    except GibError as e:
        return f"Hata: {e}"
    bas = [
        f"# {d['baslik']}",
        f"Özelge No: {d['ozelge_no']}",
        f"Tarih: {d['tarih']}",
        f"Kanun: {d['kanun_no']} {d['kanun'] or ''}".rstrip(),
    ]
    if d["ilgili_maddeler"]:
        bas.append("İlgili maddeler: " + ", ".join(map(str, d["ilgili_maddeler"])))
    if d["ekler"]:
        bas.append("Ekler: " + ", ".join(map(str, d["ekler"])))
    bas.append(f"Kaynak: {d['url']}")
    return "\n".join(bas) + "\n\n" + d["metin"]


@mcp.tool()
async def kanun_listesi(
    filtre: Annotated[str | None, Field(description="Kanun adında veya numarasında geçen metin, ör. 'katma değer' ya da '213'.")] = None,
) -> str:
    """ozelge_ara'daki kanun_no filtresi için kullanılabilecek kanun numaralarını listeler."""
    try:
        kanunlar = await client().kanunlar()
    except GibError as e:
        return f"Hata: {e}"
    if filtre:
        f = filtre.casefold()
        kanunlar = [k for k in kanunlar if f in k["kanun_no"].casefold() or f in k["baslik"].casefold()]
    if not kanunlar:
        return "Eşleşen kanun bulunamadı."
    return "\n".join(f"{k['kanun_no']}: {k['baslik']}" for k in kanunlar)


def main() -> None:
    logging.getLogger("httpx").setLevel(logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()

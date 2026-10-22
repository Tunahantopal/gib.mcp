"""Sunucuyu stdio üzerinden başlatıp araçları gerçek GİB API'sine karşı dener.

Çalıştırma:  .venv\\Scripts\\python.exe tests\\smoke_test.py
"""

import asyncio
import re
import sys

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


def text(result) -> str:
    return "\n".join(c.text for c in result.content if getattr(c, "type", "") == "text")


async def main() -> None:
    params = StdioServerParameters(command=sys.executable, args=["-m", "gib_ozelge.server"])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            print("Araçlar:", [t.name for t in tools.tools])

            r = text(await session.call_tool("ozelge_ara", {"sorgu": "kira geliri", "tam_ifade": True, "kanun_no": "193", "sayfa_boyutu": 3}))
            print("\n--- ozelge_ara ---\n" + r)
            ids = re.findall(r"\[(\d+)\]", r)
            assert ids, "arama sonuç döndürmedi"

            r = text(await session.call_tool("ozelge_oku", {"ozelge_id": int(ids[0])}))
            print("\n--- ozelge_oku ---\n" + r[:1500] + ("\n..." if len(r) > 1500 else ""))
            assert "Özelge No" in r

            r = text(await session.call_tool("kanun_listesi", {"filtre": "katma"}))
            print("\n--- kanun_listesi ---\n" + r)

            r = text(await session.call_tool("ozelge_ara", {"sorgu": "kripto", "baslangic_tarihi": "01.01.2024", "bitis_tarihi": "2025-12-31", "sayfa_boyutu": 2}))
            print("\n--- tarih filtresi ---\n" + r)


if __name__ == "__main__":
    asyncio.run(main())

#실행용
# ./okx_ws_main.py
import asyncio
from HYPERRSI.src.data_collector.websocket import OKXMultiTimeframeWebSocket

async def main():
    ws_client = OKXMultiTimeframeWebSocket()
    await ws_client.run()

if __name__ == "__main__":
    asyncio.run(main())
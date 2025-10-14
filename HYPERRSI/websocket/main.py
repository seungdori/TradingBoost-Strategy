import asyncio
import json

from fastapi import FastAPI, Path, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordBearer
from position_monitor import OKXWebsocketClient

from HYPERRSI.src.api.dependencies import get_user_api_keys
from shared.database.redis import get_redis
from shared.logging import get_logger

logger = get_logger(__name__)

app = FastAPI(
    title="OKX Position Monitor",
    description="OKX 포지션 모니터링을 위한 WebSocket API",
    version="1.0.0"
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

html = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>OKX 포지션 및 주문 모니터링</title>
    <style>
        body { font-family: sans-serif; margin: 20px; }
        #status { margin-bottom: 10px; font-weight: bold; }
        .section { margin-bottom: 20px; }
        .section h2 { margin-bottom: 5px; }
        .data { background-color: #f4f4f4; padding: 10px; border: 1px solid #ccc; }
        .error { color: red; font-weight: bold; }
    </style>
</head>
<body>
    <h1>OKX 실시간 데이터 모니터링 (BTC-USDT-SWAP)</h1>
    <div>
        <label for="telegram_id">텔레그램 ID:</label>
        <input type="text" id="telegram_id" placeholder="텔레그램 ID를 입력하세요">
        <button onclick="connect()">연결</button>
    </div>
    <div id="status">웹소켓 연결 상태: 대기 중...</div>
    
    <div class="section">
        <h2>Ticker</h2>
        <pre id="ticker" class="data"></pre>
    </div>
    
    <div class="section">
        <h2>Position (Long)</h2>
        <pre id="position_long" class="data"></pre>
    </div>

    <div class="section">
        <h2>Position (Short)</h2>
        <pre id="position_short" class="data"></pre>
    </div>
    
    <div class="section">
        <h2>Open Orders</h2>
        <pre id="open_orders" class="data"></pre>
    </div>
    
    <script>
        let ws = null;
        
        function connect() {
            const telegram_id = document.getElementById('telegram_id').value;
            if (!telegram_id) {
                alert('텔레그램 ID를 입력해주세요.');
                return;
            }
            
            if (ws) {
                ws.close();
            }
            
            connectWebSocket(telegram_id);
        }

        function connectWebSocket(telegram_id) {
            const statusElem = document.getElementById("status");
            const tickerElem = document.getElementById("ticker");
            const positionLongElem = document.getElementById("position_long");
            const positionShortElem = document.getElementById("position_short");
            const openOrdersElem = document.getElementById("open_orders");

            ws = new WebSocket(`ws://localhost:8001/ws/${telegram_id}`);
            
            ws.onopen = function() {
                statusElem.textContent = "웹소켓 연결 상태: 연결됨";
                statusElem.className = "";
            };

            ws.onmessage = function(event) {
                try {
                    const data = JSON.parse(event.data);
                    if (data.error) {
                        statusElem.textContent = `오류: ${data.error}`;
                        statusElem.className = "error";
                        return;
                    }
                    
                    tickerElem.textContent = JSON.stringify(data.ticker, null, 2);
                    positionLongElem.textContent = JSON.stringify(data.position_long, null, 2);
                    positionShortElem.textContent = JSON.stringify(data.position_short, null, 2);
                    openOrdersElem.textContent = JSON.stringify(data.open_orders, null, 2);
                } catch (err) {
                    console.error("메시지 파싱 오류:", err);
                }
            };

            ws.onclose = function() {
                statusElem.textContent = "웹소켓 연결 상태: 연결 종료";
                ws = null;
            };

            ws.onerror = function(error) {
                console.error("WebSocket 오류:", error);
                statusElem.textContent = "웹소켓 연결 오류 발생";
                statusElem.className = "error";
            };
        }
    </script>
</body>
</html>
"""

@app.get("/")
async def get_root():
    return HTMLResponse(html)

@app.get("/api/ticker/{symbol}", tags=["market"])
async def get_ticker(symbol: str = Path(..., description="거래 심볼")):
    """
    현재 시세 정보를 조회합니다.
    """
    redis = await get_redis()
    ticker_key = f"ws:okx:tickers:{symbol}"
    ticker_data = await redis.get(ticker_key)
    return json.loads(ticker_data) if ticker_data else {}

@app.get("/api/position/{user_id}", tags=["position"])
async def get_position(
    user_id: str = Path(..., description="사용자 ID"),
    symbol: str = Query(..., description="거래 심볼"),
    side: str = Query("long", description="long 또는 short")
):
    """
    현재 포지션 정보를 조회합니다.
    """
    redis = await get_redis()
    position_key = f"ws:user:{user_id}:{symbol}:{side}"
    position_data = await redis.get(position_key)
    return json.loads(position_data) if position_data else {}

@app.get("/api/orders/{user_id}", tags=["orders"])
async def get_orders(
    user_id: str = Path(..., description="사용자 ID"),
    symbol: str = Query(..., description="거래 심볼")
):
    """
    현재 주문 정보를 조회합니다.
    """
    redis = await get_redis()
    open_orders_key = f"ws:user:{user_id}:{symbol}:open_orders"
    orders_data = await redis.get(open_orders_key)
    return json.loads(orders_data) if orders_data else {}

@app.websocket("/ws/{telegram_id}")
async def websocket_endpoint(websocket: WebSocket, telegram_id: str):
    """
    - OKXWebsocketClient를 통해 실시간 데이터(Positions/Orders 등)를 Redis에 업데이트
    - 5초 간격으로 Redis에서 꺼내서 웹소켓 클라이언트에 push
    """
    await websocket.accept()
    okx_client = None
    public_task = None
    private_task = None
    
    try:
        # 1) 사용자 API 키 가져오기
        api_keys = await get_user_api_keys(telegram_id)
        if not api_keys:
            await websocket.send_text(json.dumps({
                "error": "API 키를 찾을 수 없습니다. 먼저 /register 명령어로 API 키를 등록해주세요."
            }))
            return

        # API 키가 모두 존재하는지 확인
        required_keys = ['api_key', 'api_secret', 'password']
        missing_keys = [key for key in required_keys if not api_keys.get(key)]
        if missing_keys:
            await websocket.send_text(json.dumps({
                "error": f"필수 API 정보가 누락되었습니다: {', '.join(missing_keys)}"
            }))
            return

        # 2) OKX 웹소켓 클라이언트
        okx_client = OKXWebsocketClient(
            api_key=api_keys['api_key'],
            api_secret=api_keys['api_secret'],
            passphrase=api_keys['password'],
            options={'defaultType': 'swap'}
        )

        # 연결 성공 여부 확인
        if not await okx_client.connect():
            await websocket.send_text(json.dumps({
                "error": "OKX 웹소켓 연결에 실패했습니다."
            }))
            return

        # 백그라운드로 실시간 메시지 처리(티커/포지션/오더)
        public_task = asyncio.create_task(okx_client.handle_public_messages())
        private_task = asyncio.create_task(okx_client.handle_private_messages(telegram_id))

        while True:
            # Redis에서 최신 데이터 조회
            redis = await get_redis()
            ticker_key = f"ws:okx:tickers:BTC-USDT-SWAP"
            
            # posSide가 "long" 혹은 "net"으로 들어올 수 있으니 우선 long key / net key 모두 봐도 됨
            # 여기서는 long, short만 보여주는 예시
            position_long_key = f"ws:user:{telegram_id}:BTC-USDT-SWAP:long"
            position_net_key  = f"ws:user:{telegram_id}:BTC-USDT-SWAP:net"  # 추가 체크할 수도 있음
            position_short_key = f"ws:user:{telegram_id}:BTC-USDT-SWAP:short"
            open_orders_key = f"ws:user:{telegram_id}:BTC-USDT-SWAP:open_orders"
            
            ticker_data = await redis.get(ticker_key)
            position_long_data = await redis.get(position_long_key)
            position_net_data = await redis.get(position_net_key)   # 필요하면 추가
            position_short_data = await redis.get(position_short_key)
            open_orders_data = await redis.get(open_orders_key)
            
            # 예: posSide가 net일 경우 position_long 자리가 비어 있을 수 있으니
            # net 데이터가 있으면 long 자리로도 보여줄 수 있음 (원하는 방식대로 조정)
            if position_long_data is None and position_net_data is not None:
                position_long_data = position_net_data

            aggregated = {
                "ticker": json.loads(ticker_data) if ticker_data else {},
                "position_long": json.loads(position_long_data) if position_long_data else {},
                "position_short": json.loads(position_short_data) if position_short_data else {},
                "open_orders": json.loads(open_orders_data) if open_orders_data else {},
            }

            await websocket.send_text(json.dumps(aggregated))
            await asyncio.sleep(5)

    except WebSocketDisconnect:
        logger.info(f"[WS] Client disconnected (telegram_id={telegram_id})")
    except Exception as e:
        logger.error(f"[WS] Exception: {str(e)}")
        try:
            await websocket.send_text(json.dumps({"error": str(e)}))
        except RuntimeError:
            pass
    finally:
        # WebSocket 루프 정지
        if okx_client:
            okx_client.stop()
        if public_task:
            public_task.cancel()
        if private_task:
            private_task.cancel()
        try:
            await websocket.close()
        except RuntimeError:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
import asyncio
import websockets
import logging

# 로깅 설정
logging.basicConfig(level=logging.DEBUG)

async def test_websocket():
    uri = "ws://localhost:8000/logs/ws/1"
    try:
        async with websockets.connect(uri) as websocket:
            print("Connected to WebSocket")
            
            # 메시지 전송
            await websocket.send("Hello Server!")
            print("Sent message: Hello Server!")
            
            # 응답 수신
            response = await websocket.recv()
            print(f"Received response: {response}")
    except Exception as e:
        print(f"Error occurred: {e}")
        raise e

if __name__ == "__main__":
    asyncio.run(test_websocket())
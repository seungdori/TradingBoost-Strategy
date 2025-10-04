import asyncio
import websockets
import json
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_websocket():
    uri = "ws://localhost:8000/logs/ws/587662504768345929"
    
    try:
        logger.info(f"Connecting to {uri}...")
        async with websockets.connect(uri) as websocket:
            logger.info("Connected successfully!")
            
            # 메시지 전송
            test_message = "테스트 메시지"
            logger.info(f"Sending message: {test_message}")
            await websocket.send(test_message)
            
            # 메시지 수신
            while True:
                try:
                    response = await websocket.recv()
                    logger.info(f"Received message: {response}")
                except websockets.exceptions.ConnectionClosed:
                    logger.info("Connection closed")
                    break
                
    except ConnectionRefusedError:
        logger.error("Connection refused. Make sure the server is running.")
    except Exception as e:
        logger.error(f"An error occurred: {str(e)}")

async def main():
    try:
        await test_websocket()
    except KeyboardInterrupt:
        logger.info("Test stopped by user")
    except Exception as e:
        logger.error(f"Test failed: {str(e)}")

if __name__ == "__main__":
    # Python 3.12에서는 새로운 이벤트 루프 생성 방식 사용
    asyncio.run(main())
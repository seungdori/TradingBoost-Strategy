#!/usr/bin/env python3
"""
텔레그램 메시지 직접 전송 테스트 (큐 우회)
"""
import asyncio
import os
import sys

# Add project root to Python path
project_root = "/Users/seunghyun/TradingBoost-Strategy"
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from HYPERRSI.telegram_message import send_telegram_message_direct

async def main():
    user_id = "1709556958"  # OWNER_ID (Telegram ID)
    
    test_message = """
🧪 직접 전송 테스트
━━━━━━━━━━━━━━━
이 메시지가 도착하면 텔레그램 봇 설정이 정상입니다.
"""
    
    print(f"📤 텔레그램 메시지 직접 전송 중... (telegram_id: {user_id})")
    
    try:
        result = await send_telegram_message_direct(
            message=test_message,
            okx_uid=user_id,
            debug=False
        )
        
        if result:
            print("✅ 메시지 직접 전송 성공!")
            print("📱 텔레그램 앱을 확인해보세요.")
        else:
            print("❌ 메시지 직접 전송 실패!")
            
    except Exception as e:
        print(f"🚨 에러 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())

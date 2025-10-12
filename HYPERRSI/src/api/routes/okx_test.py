import os
from typing import Any, Dict

import dotenv
from okx.api.account import Account
from okx.api.trade import Trade

from HYPERRSI.src.config import OKX_API_KEY, OKX_PASSPHRASE, OKX_SECRET_KEY

dotenv.load_dotenv()

OKX_API_KEY = OKX_API_KEY
OKX_API_SECRET_KEY = OKX_SECRET_KEY
OKX_PASSPHRASE = OKX_PASSPHRASE

class OKXOrderStatus:
    def __init__(self):
        """
        OKX API 클라이언트 초기화
        """
        self.tradeAPI = Trade(
            key=OKX_API_KEY,
            secret=OKX_API_SECRET_KEY,
            passphrase=OKX_PASSPHRASE,
            flag='0'  # 실제 거래용. 테스트넷은 '1'
        )

    def get_stop_order_status(self, orderId: str, instId: str) -> Dict[str, Any]:
        """
        특정 stop loss 주문의 상태를 조회
        
        Args:
            orderId (str): 조회할 주문의 ID
            instId (str): 거래쌍 (예: 'BTC-USDT')
            
        Returns:
            Dict[str, Any]: 주문 상태 정보
        """
        try:
            result = self.tradeAPI.get_order(
                instId=instId,
                ordId="2217872850785148928",
                clOrdId="e847386590ce4dBC13071110f9f040ad"
            )
            
            if result and isinstance(result, dict) and result.get('data'):
                return result['data'][0]
            return None
            
        except Exception as e:
            print(f"Error getting order status: {str(e)}")
            return None

# 사용 예시
def main():
    # OKX 클라이언트 초기화
    # OKX 클라이언트 초기화
    okx_client = OKXOrderStatus()
    
    # 주문 상태 조회
    order_status = okx_client.get_stop_order_status(
        orderId="2217872850785148928",
        instId="SOL-USDT-SWAP"  # 거래쌍 예시
    )
    
    if order_status:
        print(f"주문 상태: {order_status['state']}")
        print(f"주문 정보: {order_status}")
    else:
        print("주문을 찾을 수 없습니다.")

if __name__ == "__main__":
    main()
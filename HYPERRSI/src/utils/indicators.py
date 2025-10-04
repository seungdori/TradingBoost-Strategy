import numpy as np
from core.logger import get_logger


logger = get_logger(__name__)

def calc_rsi(prices: np.ndarray, period: int = 14) -> np.ndarray:
    """
    RSI(Relative Strength Index) 계산
    
    Args:
        prices (np.ndarray): 가격 데이터 배열
        period (int): RSI 계산 기간
    
    Returns:
        np.ndarray: RSI 값 배열
    """
    try:
        # 가격 변화량 계산
        deltas = np.diff(prices)
        deltas = np.append([0], deltas)  # 첫 번째 요소를 0으로 채움
        
        # 상승/하락 구분
        gains = np.where(deltas > 0, deltas, 0)
        losses = np.where(deltas < 0, -deltas, 0)
        
        # 초기 평균 계산
        avg_gain = np.zeros_like(prices)
        avg_loss = np.zeros_like(prices)
        
        # 첫 번째 평균
        avg_gain[period] = np.mean(gains[:period])
        avg_loss[period] = np.mean(losses[:period])
        
        # 나머지 평균 계산
        for i in range(period + 1, len(prices)):
            avg_gain[i] = (avg_gain[i-1] * (period-1) + gains[i]) / period
            avg_loss[i] = (avg_loss[i-1] * (period-1) + losses[i]) / period
        
        # RSI 계산
        rs = avg_gain / np.where(avg_loss == 0, 1e-10, avg_loss)  # 0으로 나누기 방지
        rsi = 100 - (100 / (1 + rs))
        
        return rsi
        
    except Exception as e:
        logger.error(f"RSI 계산 중 오류 발생: {str(e)}")
        return np.array([]) 
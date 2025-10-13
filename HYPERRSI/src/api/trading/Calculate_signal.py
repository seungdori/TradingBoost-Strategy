import json
from functools import lru_cache
from typing import Dict, Optional, Tuple, Union

import numpy as np
import pandas as pd

from HYPERRSI.src.trading.models import get_timeframe
from shared.database.redis_helper import get_redis_client
from shared.logging import get_logger

logger = get_logger(__name__)

class TrendStateCalculatorException(Exception):
    """TrendStateCalculator 관련 예외"""
    pass

class TrendStateCalculator:
    # 클래스 레벨 상수
    DEFAULT_CYCLE_TYPE = "JMA"
    DEFAULT_LEN_FAST = 5
    DEFAULT_LEN_MEDIUM = 10
    DEFAULT_LEN_SLOW = 20
    DEFAULT_PHASE_JMA = 50
    DEFAULT_POWER = 2
    DEFAULT_BB_LENGTH = 15
    DEFAULT_BB_MULT = 1.5
    DEFAULT_BBW_MA_LENGTH = 100
    
    def __init__(self, 
                 cycle_type: str = DEFAULT_CYCLE_TYPE,
                 len_fast: int = DEFAULT_LEN_FAST,
                 len_medium: int = DEFAULT_LEN_MEDIUM,
                 len_slow: int = DEFAULT_LEN_SLOW,
                 phase_jma: float = DEFAULT_PHASE_JMA,
                 power: float = DEFAULT_POWER,
                 bb_length: int = DEFAULT_BB_LENGTH,
                 bb_mult: float = DEFAULT_BB_MULT,
                 bbw_ma_length: int = DEFAULT_BBW_MA_LENGTH):
        """
        Initialize TrendStateCalculator with default parameters
        """
        self.cycle_type = cycle_type
        self.len_fast = len_fast
        self.len_medium = len_medium
        self.len_slow = len_slow
        self.phase_jma = phase_jma
        self.power = power
        self.bb_length = bb_length
        self.bb_mult = bb_mult
        self.bbw_ma_length = bbw_ma_length
        self._cached_results = {}  # 캐시 저장소

    @lru_cache(maxsize=128)
    def calc_jma(self, data_tuple: tuple, length: int, phase: float, power: float) -> pd.Series:
        """
        캐시를 사용하여 JMA 계산
        """
        data = pd.Series(data_tuple)
        phase_ratio = 0.5 if phase < -100 else 2.5 if phase > 100 else phase / 100 + 1.5
        beta = 0.45 * (length - 1) / (0.45 * (length - 1) + 2)
        alpha = beta ** power

        e0 = pd.Series(index=data.index, dtype=float)
        e1 = pd.Series(index=data.index, dtype=float)
        e2 = pd.Series(index=data.index, dtype=float)
        jma = pd.Series(index=data.index, dtype=float)

        for i in range(len(data)):
            if i == 0:
                e0.iloc[i] = data.iloc[i]
                e1.iloc[i] = 0
                e2.iloc[i] = 0
                jma.iloc[i] = data.iloc[i]
            else:
                e0.iloc[i] = (1 - alpha) * data.iloc[i] + alpha * e0.iloc[i-1]
                e1.iloc[i] = (data.iloc[i] - e0.iloc[i]) * (1 - beta) + beta * e1.iloc[i-1]
                e2.iloc[i] = (e0.iloc[i] + phase_ratio * e1.iloc[i] - jma.iloc[i-1]) * (1 - alpha)**2 + alpha**2 * e2.iloc[i-1]
                jma.iloc[i] = e2.iloc[i] + jma.iloc[i-1]

        return jma

    def calc_t3(self, data: pd.Series, length: int) -> pd.Series:
        """Calculate T3 Moving Average"""
        e1 = data.ewm(span=length, adjust=False).mean()
        e2 = e1.ewm(span=length, adjust=False).mean()
        e3 = e2.ewm(span=length, adjust=False).mean()
        e4 = e3.ewm(span=length, adjust=False).mean()
        e5 = e4.ewm(span=length, adjust=False).mean()
        e6 = e5.ewm(span=length, adjust=False).mean()
        
        a = 0.7
        c1 = -a**3
        c2 = 3 * a**2 + 3 * a**3
        c3 = -6 * a**2 - 3 * a - 3 * a**3
        c4 = 1 + 3 * a + a**3 + 3 * a**2
        
        return c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3

    def calculate_moving_averages(self, data: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        세 가지 이동평균을 계산합니다.
        """
        if data.empty:
            raise TrendStateCalculatorException("입력 데이터가 비어있습니다.")
        
        if self.cycle_type not in ["JMA", "T3"]:
            raise TrendStateCalculatorException(f"지원하지 않는 cycle_type입니다: {self.cycle_type}")
        
        if self.cycle_type == "JMA":
            ma_fast = self.calc_jma(tuple(data), self.len_fast, self.phase_jma, self.power)
            ma_medium = self.calc_jma(tuple(data), self.len_medium, self.phase_jma, self.power)
            ma_slow = self.calc_jma(tuple(data), self.len_slow, self.phase_jma, self.power)
        elif self.cycle_type == "T3":
            ma_fast = self.calc_t3(data, self.len_fast)
            ma_medium = self.calc_t3(data, self.len_medium)
            ma_slow = self.calc_t3(data, self.len_slow)
        else:
            ma_fast = data.ewm(span=self.len_fast, adjust=False).mean()
            ma_medium = data.ewm(span=self.len_medium, adjust=False).mean()
            ma_slow = data.ewm(span=self.len_slow, adjust=False).mean()
            
        return ma_fast, ma_medium, ma_slow

    def get_trend_state(self, data: pd.Series) -> pd.Series:
        """
        Calculate trend state based on moving averages
        
        Returns:
            Series with trend states: 1 for bullish, -1 for bearish, 0 for neutral
        """
        ma_fast, ma_medium, ma_slow = self.calculate_moving_averages(data)
        
        bull_condition = ((ma_fast > ma_medium) & (ma_medium > ma_slow)) | \
                         ((ma_medium > ma_fast) & (ma_fast > ma_slow))
        
        bear_condition = (ma_slow > ma_medium) & (ma_medium > ma_fast)
        
        trend_state = pd.Series(0, index=data.index)
        trend_state[bull_condition] = 1
        trend_state[bear_condition] = -1
        
        return trend_state
    
    def calculate_bollinger_bands(self, data: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Bollinger Bands 계산
        (기본값 self.bb_length=15, self.bb_mult=1.5)
        """
        middle = data.rolling(window=self.bb_length).mean()
        std = data.rolling(window=self.bb_length).std()
        
        upper = middle + (std * self.bb_mult)
        lower = middle - (std * self.bb_mult)
        
        
        return upper, middle, lower

    def calculate_bbw(self, data: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series, pd.Series, pd.Series, pd.Series]:
        """
        BBW 관련 지표 계산
        Returns:
            (BBW, BBW 이동평균, BBR, upper, middle, lower)
        """
        upper, middle, lower = self.calculate_bollinger_bands(data)
        
        # BBW 계산 ((Upper - Lower) / Middle) * 10
        bbw = ((upper - lower) * 10) / middle
        
        # BBW의 이동평균
        bbw_ma = bbw.rolling(window=self.bbw_ma_length).mean()
        
        # BBR (Bollinger Band Ratio) 계산
        bbr = (data - lower) / (upper - lower)
        
        return bbw, bbw_ma, bbr, upper, middle, lower

    def find_bbw_pivots(self, bbw: pd.Series, left_bars: int = 20, right_bars: int = 10) -> Tuple[pd.Series, pd.Series]:
        """
        BBW의 피봇 고점과 저점 찾기
        """
        pivot_highs = pd.Series(index=bbw.index, dtype=float)
        pivot_lows = pd.Series(index=bbw.index, dtype=float)
        
        for i in range(left_bars, len(bbw) - right_bars):
            current = bbw.iloc[i]
            left_window = bbw.iloc[i - left_bars:i]
            right_window = bbw.iloc[i + 1:i + right_bars + 1]
            
            # 피봇 고점
            if current > left_window.max() and current > right_window.max():
                pivot_highs.iloc[i] = current
                
            # 피봇 저점
            if current < left_window.min() and current < right_window.min():
                pivot_lows.iloc[i] = current
        
        return pivot_highs, pivot_lows

    def calculate_bbw_state(self, data: pd.Series) -> pd.Series:
        """
        BBW 상태 계산 (2: 강한 확장, -2: 강한 수축, 0: 중립)
        """
        bbw, bbw_ma, bbr, upper, middle, lower  = self.calculate_bbw(data)
        pivot_highs, pivot_lows = self.find_bbw_pivots(bbw)
        
        bbw_state = pd.Series(0, index=data.index)
        
        for i in range(len(data)):
            if i < 3:  # 초기 구간은 계산 X
                continue
                
            current_bbw = bbw.iloc[i]
            current_bbr = bbr.iloc[i]
            
            # 최근 피봇 고점/저점 (여기서는 50봉 내 피봇을 검색 예시)
            recent_high = pivot_highs.iloc[max(0, i-50):i+1].max()
            recent_low = pivot_lows.iloc[max(0, i-50):i+1].min()
            
            buzz, squeeze = self._calculate_volatility_thresholds(recent_high, recent_low)
            
            # 상태 결정
            if current_bbw > buzz:
                if current_bbr > 0.5:
                    bbw_state.iloc[i] = 2  # 상방 확장
                else:
                    bbw_state.iloc[i] = -2  # 하방 확장
            elif current_bbw < squeeze:
                bbw_state.iloc[i] = -1  # 수축
                
            # 추가 상태 조정
            if bbw_state.iloc[i] == 2 and current_bbr < 0.2:
                bbw_state.iloc[i] = -2
            elif bbw_state.iloc[i] == -2 and current_bbr > 0.8:
                bbw_state.iloc[i] = 2
        
        return bbw_state

    def calculate_extreme_state(self, data: pd.Series, use_longer_trend: bool = False) -> pd.Series:
        """
        극단 상태(Extreme State) 계산 (2: 강한 상승, -2: 강한 하락, 0: 중립)
        """
        trend_state = self.get_trend_state(data)
        bbw_state = self.calculate_bbw_state(data)
        
        extreme_state = pd.Series(0, index=data.index)
        
        for i in range(len(data)):
            bull_condition = trend_state.iloc[i] > 0 and (use_longer_trend or bbw_state.iloc[i] == 2)
            bear_condition = trend_state.iloc[i] < 0 and (use_longer_trend or bbw_state.iloc[i] == -2)
            prev_state = extreme_state.iloc[i-1] if i > 0 else 0
            
            if bull_condition:
                extreme_state.iloc[i] = 2
            elif bear_condition:
                extreme_state.iloc[i] = -2
            elif prev_state == 2 and trend_state.iloc[i] <= 0:
                extreme_state.iloc[i] = 0
            elif prev_state == -2 and trend_state.iloc[i] >= 0:
                extreme_state.iloc[i] = 0
            else:
                extreme_state.iloc[i] = prev_state
                
        return extreme_state

    def clear_cache(self):
        """캐시된 결과 정리"""
        self._cached_results.clear()

    def calculate_rsi(self, data: pd.Series, length: int = 14) -> pd.Series:
        """
        RSI 계산
        """
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
        
    def get_rsi_state(self, rsi: pd.Series) -> pd.Series:
        """
        RSI 상태 판단
        (-2: 강한 과매도, -1: 과매도, 0: 중립, 1: 과매수, 2: 강한 과매수)
        """
        states = pd.Series(index=rsi.index, data=0)  # 기본값 중립
        states = np.where(rsi < 20, -2, states)  # 강한 과매도
        states = np.where((rsi >= 20) & (rsi < 30), -1, states)  # 과매도
        states = np.where((rsi > 70) & (rsi <= 80), 1, states)    # 과매수
        states = np.where(rsi > 80, 2, states)                    # 강한 과매수
        return pd.Series(states, index=rsi.index)
    
    def _calculate_volatility_thresholds(self, 
                                         recent_high: float, 
                                         recent_low: float) -> Tuple[float, float]:
        """변동성 임계값 계산 보조 메서드"""
        if pd.isna(recent_high) or pd.isna(recent_low):
            # 피봇값이 없을 때는 임시로 (1, 1) 같은 값 반환
            return (1, 1)
        buzz = recent_high * 0.7
        squeeze = recent_low / 0.7
        return buzz, squeeze

    # --------------------------------------------------------------------------
    #   Redis로부터 가져오는 부분(수정된 핵심)
    # --------------------------------------------------------------------------
    
    async def get_candles_with_indicators_from_redis(self, symbol: str, timeframe: str, fetch_count: int = 3000) -> pd.DataFrame:
        """
        Redis에서 candles_with_indicators:{symbol}:{tf} 리스트를 읽어
        DataFrame으로 변환해 반환
        """
        

        redis = await get_redis_client()
        tf_str = get_timeframe(timeframe)
        key = f"candles_with_indicators:{symbol}:{tf_str}"
        
        try:
            logger.debug(f"[{symbol}] Redis에서 캔들 데이터 가져오기 시작, key={key}")
            # 예: 맨 끝(최신)부터 fetch_count개 가져오고 싶으면 lrange(key, -fetch_count, -1)
            # 여기서는 전체 가져온 뒤, 필요하면 뒤집는 식으로 처리
            candles = await redis.lrange(key, 0, -1)
            
            if not candles:
                logger.error(f"Redis key='{key}'에서 캔들을 찾을 수 없습니다.")
                return pd.DataFrame()
            
            # JSON 디코딩
            records = [json.loads(candle) for candle in candles]
            df = pd.DataFrame(records)
            
            # timestamp가 초단위라 가정 (예: 1737605460)
            # 실제 ms단위라면 unit='ms'로 수정
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='s')
            
            # 정렬 (오름차순: 가장 오래된 게 위, 최신이 아래)
            df.sort_values('timestamp', inplace=True)
            df.set_index('timestamp', inplace=True)
            
            # 필요한 컬럼들만 float로 변환 (존재하는 컬럼에 한해)
            float_cols = [
                'open','high','low','close','volume',
                'sma5','sma20','sma50','sma60','sma100','sma200',
                'jma5','jma10','jma20','rsi',
                # 혹시 Redis에 Bollinger Bands가 저장되어 있을 경우
                'bb_upper','bb_middle','bb_lower'
            ]
            for col in float_cols:
                if col in df.columns:
                    df[col] = df[col].astype(float)
            
            return df
        
        except Exception as e:
            logger.error(f"Redis에서 캔들 데이터 가져오기 실패(key={key}): {str(e)}")
            return pd.DataFrame()
    
    async def analyze_market_state_from_redis(self, symbol: str, timeframe: str, trend_timeframe: str = None) -> Dict:
        """
        간단한 예시:
        - 최근 21개 캔들을 불러와서 모멘텀 계산
        - 없는 경우(예: bb_upper)라면 Bollinger Bands 자동 계산
        - sma20, sma60(또는 sma50 등)을 비교하여 상태 구분
        """
        try:
            tf_str = get_timeframe(timeframe)
            trend_tf_str = get_timeframe(trend_timeframe)
            # DataFrame 전체 가져와서 뒤에서 21개만 사용(혹은 필요한 만큼)
            df = await self.get_candles_with_indicators_from_redis(symbol, tf_str)
            
            # trend_timeframe이 None이거나 timeframe과 동일한 경우
            if trend_tf_str is None or trend_tf_str == tf_str:
                trend_df = df
            else:
                trend_df = await self.get_candles_with_indicators_from_redis(symbol, trend_tf_str)
                
            if df.empty or len(trend_df) < 21:
                logger.error(f"충분한 캔들 데이터를 찾을 수 없습니다: {symbol} / {tf_str}")
                return self._get_empty_state()
            
            # ----- (1) Bollinger Bands가 없다면 여기서 계산 -----
            # 예: 'bb_upper' 혹은 'bb_lower' 컬럼이 없다면 직접 calculate_bollinger_bands 사용
            if 'bb_upper' not in trend_df.columns or 'bb_lower' not in trend_df.columns:
                upper, middle, lower = self.calculate_bollinger_bands(df['close'])
            
                df['bb_upper'] = upper
                df['bb_middle'] = middle
                df['bb_lower'] = lower
            # --------------------------------------------------
            
            # 뒤에서 21개
            recent_df = trend_df.iloc[-21:]
            
            close_prices = recent_df['close'].values
            current_price = close_prices[-1]
            price_20_periods_ago = close_prices[0]
            momentum = (current_price - price_20_periods_ago) / price_20_periods_ago
            trend_state = recent_df['trend_state'].iloc[-1]
            # latest candle (가장 마지막)
            latest_candle = recent_df.iloc[-1]
            
            # 필요한 지표들 (예시에 맞게 가져옴. 실제로는 sma60 대신 sma50 등 쓰세요)
            ma20 = latest_candle.get('sma20', 0.0)
            # 예시상 sma60 이 없는 경우가 많으니, sma50, sma100 등으로 교체 가능
            ma60 = latest_candle.get('sma60', 0.0)  # 혹은 sma60을 실제로 넣어서 쓰세요
            
            # Bollinger Bands 컬럼에서 가져오기
            upper_band = latest_candle.get('bb_upper', 0.0)
            lower_band = latest_candle.get('bb_lower', 0.0)
            
            # 상태 판단 (예시 로직)
            extreme_state = 0  # 기본 중립
            if current_price > upper_band and momentum > 0:
                extreme_state = 2  # 강한 상승
            elif current_price > ma20 and ma20 > ma60 and momentum > 0:
                extreme_state = 1  # 약한 상승
            elif lower_band <= current_price <= upper_band:
                extreme_state = 0  # 중립
            elif current_price < ma20 and ma20 < ma60 and momentum < 0:
                extreme_state = -1  # 약한 하락
            elif current_price < lower_band and momentum < 0:
                extreme_state = -2  # 강한 하락
            
            return {
                'ma20': ma20,
                'ma60': ma60,
                'momentum': momentum,
                'upper_band': upper_band,
                'lower_band': lower_band,
                'extreme_state': extreme_state,
                'trend_state': trend_state
            }
            
        except Exception as e:
            logger.error(f"시장 상태 분석 중 오류 발생: {str(e)}")
            return self._get_empty_state()

    def _get_empty_state(self) -> Dict:
        """
        데이터가 없을 때 반환할 기본 상태 딕셔너리
        """
        return {
            'ma20': None,
            'ma60': None,
            'momentum': None,
            'upper_band': None,
            'lower_band': None,
            'extreme_state': 0,
            'trend_state': 0
        }

# --------------------------------------------------------------------------
import asyncio


async def main():
    calculator = TrendStateCalculator()
    result = await calculator.analyze_market_state_from_redis("BTC-USDT-SWAP", "1h")
    print(result)

if __name__ == "__main__":
    asyncio.run(main())
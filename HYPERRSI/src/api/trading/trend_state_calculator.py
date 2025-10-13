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
        
        Args:
            cycle_type: Type of moving average ("JMA", "T3", etc.)
            len_fast: Length for fast MA
            len_medium: Length for medium MA
            len_slow: Length for slow MA
            phase_jma: Phase parameter for JMA calculation
            power: Power parameter for JMA calculation
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
        캐시를 사용하여 JMA 계산 성능 향상
        Note: pd.Series는 해시 불가능하므로 tuple로 변환하여 캐싱
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
        
        Args:
            data: 가격 시리즈
            
        Returns:
            Tuple[pd.Series, pd.Series, pd.Series]: (빠른 이동평균, 중간 이동평균, 느린 이동평균)
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
        
        Args:
            data: Price series
            
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
    
    def calculate_bollinger_bands(self, data: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
        """
        Bollinger Bands 계산
        
        Args:
            data: 가격 시리즈
            
        Returns:
            tuple containing (upper band, middle band, lower band)
        """
        middle = data.rolling(window=self.bb_length).mean()
        std = data.rolling(window=self.bb_length).std()
        
        upper = middle + (std * self.bb_mult)
        lower = middle - (std * self.bb_mult)
        
        return upper, middle, lower

    def calculate_bbw(self, data: pd.Series) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        BBW 관련 지표들을 계산합니다.
        
        Args:
            data: 가격 시리즈
            
        Returns:
            Tuple[pd.Series, pd.Series, pd.Series]: (BBW, BBW 이동평균, BBR)
        """
        upper, middle, lower = self.calculate_bollinger_bands(data)
        
        # BBW 계산 ((Upper - Lower) / Middle) * 10
        bbw = ((upper - lower) * 10) / middle
        
        # BBW의 이동평균
        bbw_ma = bbw.rolling(window=self.bbw_ma_length).mean()
        
        # BBR (Bollinger Band Ratio) 계산
        bbr = (data - lower) / (upper - lower)
        
        return bbw, bbw_ma, bbr, upper, middle, lower

    def find_bbw_pivots(self, bbw: pd.Series, left_bars: int = 20, right_bars: int = 10) -> tuple[pd.Series, pd.Series]:
        """
        BBW의 피봇 고점과 저점 찾기
        
        Args:
            bbw: BBW 시리즈
            left_bars: 좌측 비교 기간
            right_bars: 우측 비교 기간
            
        Returns:
            tuple containing (pivot highs, pivot lows)
        """
        pivot_highs = pd.Series(index=bbw.index, dtype=float)
        pivot_lows = pd.Series(index=bbw.index, dtype=float)
        
        for i in range(left_bars, len(bbw) - right_bars):
            # 현재 값
            current = bbw.iloc[i]
            
            # 좌우 윈도우
            left_window = bbw.iloc[i - left_bars:i]
            right_window = bbw.iloc[i + 1:i + right_bars + 1]
            
            # 피봇 고점 확인
            if current > left_window.max() and current > right_window.max():
                pivot_highs.iloc[i] = current
                
            # 피봇 저점 확인
            if current < left_window.min() and current < right_window.min():
                pivot_lows.iloc[i] = current
        
        return pivot_highs, pivot_lows

    def calculate_bbw_state(self, data: pd.Series) -> pd.Series:
        """
        BBW 상태 계산
        
        Args:
            data: 가격 시리즈
            
        Returns:
            BBW 상태 시리즈 (2: 강한 확장, -2: 강한 수축, 0: 중립)
        """
        bbw, bbw_ma, bbr, upper, middle, lower  = self.calculate_bbw(data)
        pivot_highs, pivot_lows = self.find_bbw_pivots(bbw)
        
        # BBW 상태를 저장할 시리즈
        bbw_state = pd.Series(0, index=data.index)
        
        # 이동 윈도우로 상태 계산
        for i in range(len(data)):
            if i < 3:  # 초기값 처리
                continue
                
            current_bbw = bbw.iloc[i]
            current_bbr = bbr.iloc[i]
            
            # 최근 피봇 고점/저점 찾기
            recent_high = pivot_highs.iloc[max(0, i-50):i+1].max()
            recent_low = pivot_lows.iloc[max(0, i-50):i+1].min()
            
            # Volatility Threshold 계산
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
        극단 상태(Extreme State) 계산
        
        Args:
            data: 가격 시리즈
            use_longer_trend: 장기 추세 사용 여부
            
        Returns:
            극단 상태 시리즈 (2: 강한 상승, -2: 강한 하락, 0: 중립)
        """
        # 추세 상태 계산
        trend_state = self.get_trend_state(data)
        
        # BBW 상태 계산
        bbw_state = self.calculate_bbw_state(data)
        
        # 극단 상태를 저장할 시리즈
        extreme_state = pd.Series(0, index=data.index)
        
        for i in range(len(data)):
            # 불리시(상승) 극단 상태 조건
            bull_condition = trend_state.iloc[i] > 0 and (
                use_longer_trend or bbw_state.iloc[i] == 2
            )
            
            # 베어리시(하락) 극단 상태 조건
            bear_condition = trend_state.iloc[i] < 0 and (
                use_longer_trend or bbw_state.iloc[i] == -2
            )
            
            # 이전 상태
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

    async def analyze_market_state_from_redis(self, symbol: str, timeframe: str) -> Dict:
        """시장 상태 분석
        
        Args:
            prices (pd.Series): 종가 시계열 데이터
            
        Returns:
            Dict: 분석 결과를 담은 딕셔너리
        """
        try:
            redis = await get_redis_client()
            tf_str = get_timeframe(timeframe)
            redis_key = f"candles_with_indicators:{symbol}:{tf_str}"
            # 최근 21개 캔들 데이터 가져오기 (20기간 모멘텀 계산용)
            candles = await redis.lrange(redis_key, -21, -1)
            if not candles or len(candles) < 21:
                logger.error(f"충분한 캔들 데이터를 찾을 수 없습니다: {redis_key}")
                return self._get_empty_state()
            # 캔들 데이터 파싱
            try:
                candles_data = [json.loads(candle) for candle in candles]
                close_prices = [float(candle.get('close', 0)) for candle in candles_data]
                
                # 20기간 모멘텀 계산 (현재가격 - 20봉전 가격) / 20봉전 가격
                current_price = close_prices[-1]
                price_20_periods_ago = close_prices[0]
                momentum = (current_price - price_20_periods_ago) / price_20_periods_ago
                
                # 최신 캔들의 다른 지표들 가져오기
                latest_candle = candles_data[-1]
                ma20 = float(latest_candle.get('sma20', 0))
                ma60 = float(latest_candle.get('sma60', 0))
                upper_band = float(latest_candle.get('bb_upper', ma20 + (float(latest_candle.get('bb_std', 0)) * 2)))
                lower_band = float(latest_candle.get('bb_lower', ma20 - (float(latest_candle.get('bb_std', 0)) * 2)))
                
                # 상태 판단
                extreme_state = 0  # 기본값 (중립)
                
                if current_price > upper_band and momentum > 0:
                    extreme_state = 2  # 강한 상승
                elif current_price > ma20 and ma20 > ma60 and momentum > 0:
                    extreme_state = 1  # 약한 상승
                elif current_price >= lower_band and current_price <= upper_band:
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
                    'extreme_state': extreme_state
                }
                
            except (json.JSONDecodeError, ValueError) as e:
                logger.error(f"캔들 데이터 파싱 중 오류 발생: {str(e)}")
                return self._get_empty_state()
                
        except Exception as e:
            logger.error(f"시장 상태 분석 중 오류 발생: {str(e)}")
            return self._get_empty_state()

    def calculate_rsi(self, data: pd.Series, length: int = 14) -> pd.Series:
        """RSI 계산"""
        delta = data.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=length).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=length).mean()
        
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
        
    def get_rsi_state(self, rsi: pd.Series) -> pd.Series:
        """
        RSI 상태 판단
        Returns:
            -2: 강한 과매도
            -1: 과매도
            0: 중립
            1: 과매수
            2: 강한 과매수
        """
        states = pd.Series(index=rsi.index, data=0)  # 기본값 중립
        
        # 과매도/과매수 기준
        states = np.where(rsi < 30, -1, states)  # 과매도
        states = np.where(rsi < 20, -2, states)  # 강한 과매도
        states = np.where(rsi > 70, 1, states)   # 과매수
        states = np.where(rsi > 80, 2, states)   # 강한 과매수
        
        return pd.Series(states, index=rsi.index)
    
    def get_market_signals(self, data: pd.Series) -> pd.DataFrame:
        """
        시장 신호 생성
        
        Args:
            data: 가격 시리즈
            
        Returns:
            DataFrame with trading signals
        """
        analysis = self.analyze_market_state(data)
        
        signals = pd.DataFrame(index=data.index)
        
        # 매수 신호
        signals['buy_signal'] = (
            (analysis['extreme_state'] == 2) & 
            (analysis['extreme_state'].shift(1) != 2)
        )
        
        # 매도 신호
        signals['sell_signal'] = (
            (analysis['extreme_state'] == -2) & 
            (analysis['extreme_state'].shift(1) != -2)
        )
        
        # 청산 신호
        signals['exit_signal'] = (
            (analysis['extreme_state'] == 0) & 
            (analysis['extreme_state'].shift(1) != 0)
        )
        
        return signals

    def clear_cache(self):
        """캐시된 결과 정리"""
        self._cached_results.clear()

    def _validate_input_data(self, data: pd.Series) -> None:
        """입력 데이터 유효성 검사"""
        if data.empty:
            raise TrendStateCalculatorException("입력 데이터가 비어있습니다.")
        if not isinstance(data, pd.Series):
            raise TrendStateCalculatorException("입력은 pandas Series여야 합니다.")

    def _calculate_volatility_thresholds(self, 
                                           recent_high: float, 
                                           recent_low: float) -> Tuple[float, float]:
        """변동성 임계값 계산"""
        buzz = recent_high * 0.7
        squeeze = recent_low * (1/0.7)
        return buzz, squeeze

    async def get_candles_from_redis(symbol: str, timeframe: int) -> pd.DataFrame:
        """Redis에서 캔들 데이터를 가져와 DataFrame으로 변환"""
        try:
            # Redis 키 형식: candles:SOL-USDT-SWAP:240
            tf_str = get_timeframe(timeframe)
            key = f"candles:{symbol}:{tf_str}"
            candles = await redis.lrange(key, 0, -1)  # 모든 캔들 가져오기
            
            # 캔들 데이터를 DataFrame으로 변환
            df = pd.DataFrame([eval(candle) for candle in candles])
            
            # 컬럼 설정 (Redis에 저장된 형식에 따라 수정 필요)
            df = df.rename(columns={
                'ts': 'timestamp',
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume'
            })
            
            # timestamp를 datetime으로 변환
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
            df.set_index('timestamp', inplace=True)
            
            # 숫자형 데이터로 변환
            for col in ['open', 'high', 'low', 'close', 'volume']:
                df[col] = df[col].astype(float)
                
            return df.iloc[::-1]  # 최신 데이터가 마지막에 오도록 정렬
            
        except Exception as e:
            logger.error(f"Redis에서 캔들 데이터 가져오기 실패: {str(e)}")
            return None

    async def analyze_symbol(self, symbol: str, timeframe: int):
        price_data = await self.get_candles_from_redis(symbol, timeframe)
        return self.analyze_market_state(price_data)
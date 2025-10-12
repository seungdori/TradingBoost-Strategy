import asyncio
import logging
import multiprocessing
import os
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
from celery import Celery
from celery.signals import task_failure, task_success
from trend import analyze_trend, getMA

from GRID.main import periodic_analysis
from shared.utils import path_helper

# 로깅 설정
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Celery 설정   
from shared.config import settings

REDIS_PASSWORD = settings.REDIS_PASSWORD

if REDIS_PASSWORD:  
    redis_url = f'redis://:{REDIS_PASSWORD}@localhost:6379/0'
else:
    redis_url = f'redis://localhost:6379/0'

app = Celery('trading_tasks', broker=redis_url)
app.conf.update(
    broker_url=redis_url,
    result_backend=redis_url,
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    timezone='Asia/Seoul',  
    enable_utc=False  # UTC 사용 비활성화
)

app.autodiscover_tasks(['trading_strategy'])

class TradingStrategy:
    def __init__(self, params):
        self.params = params
        self.initialize_variables()
        self.setup_logging()

    def setup_logging(self):
        self.logger = logging.getLogger(f"{self.__class__.__name__}")
        self.logger.setLevel(logging.INFO)
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')

        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)

    def initialize_variables(self):
        self.position_state = 0
        self.state = 0
        self.tp_state = 0
        self.long_avg_price = 0
        self.short_avg_price = 0
        self.long_sl = 0
        self.short_sl = 0
        self.long_tp1 = self.long_tp2 = self.long_tp3 = 0
        self.short_tp1 = self.short_tp2 = self.short_tp3 = 0
        self.last_long_entry_price = 0
        self.last_short_entry_price = 0
        self.pyramiding_long_price = 0
        self.pyramiding_short_price = 0
        self.waiting_for_long_entry = False
        self.waiting_for_short_entry = False
        self.total_position = 0
        self.rsi_bear = False
        self.rsi_bull = False
        self.extreme_state = 0
        self.bbw = 0
        self.bbr = 0
        self.buzz = 0
        self.squeeze = 0
        self.longTrailStopPrice = 0
        self.shortTrailStopPrice = 0
        self.safty_long_entry = np.nan
        self.safty_short_entry = np.nan

    async def process_symbol(self, symbol, timeframe):
        try:
            df = self.load_data(symbol, timeframe)
            df = self.calculate_indicators(df)

            current_bar = df.iloc[-1]
            previous_bar = df.iloc[-2]

            trend_result = await analyze_trend(df, symbol, timeframe, self.params['ma_type'], self.params['use_longer_trend'])
            if trend_result is None:
                self.logger.warning(f"{symbol} 트렌드 분석 결과가 없습니다. 처리를 건너뜁니다.")
                return
            
            self.update_extreme_state(trend_result)
            
            self.execute_entry(symbol, current_bar)
            self.check_tp_sl(current_bar)
            self.update_pyramiding(current_bar)
            self.check_safety_entry(current_bar)
            self.update_break_even(current_bar)

            self.print_final_results(symbol)

        except Exception as e:
            self.logger.error(f"{symbol} 처리 중 오류 발생: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            
    def load_data(self, symbol, timeframe):
        file_path = os.path.join(path_helper.grid_dir, self.params['exchange_name'], f"{symbol}_{timeframe}.csv")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"파일이 존재하지 않습니다: {file_path}")
        
        # 필요한 행 수 계산
        max_length = 120 if self.params['use_longer_trend'] else 20
        needed_rows = max(max_length, 100, 15) + 1

        # 파일의 끝에서부터 필요한 행 수만큼 읽기
        df = pd.read_csv(file_path, nrows=needed_rows, skipfooter=0, engine='c')
        
        # timestamp를 datetime으로 변환
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        return df
    
    def calculate_indicators(self, df):
        # RSI 계산
        rsi_df = df.tail(15).copy()
        delta = rsi_df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)
        avg_gain = gain.ewm(com=13, min_periods=14).mean()
        avg_loss = loss.ewm(com=13, min_periods=14).mean()
        rs = avg_gain / avg_loss
        df['rsi'] = 100 - (100 / (1 + rs))
        
        # ATR 계산
        df['tr1'] = abs(df['high'] - df['low'])
        df['tr2'] = abs(df['high'] - df['close'].shift())
        df['tr3'] = abs(df['low'] - df['close'].shift())
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        df['atr'] = df['tr'].rolling(window=14).mean()

        return df

    def update_state(self, current_bar, previous_bar):
        if self.params['entry_option'] == '돌파':
            if not self.params['reverse']:
                self.rsi_bear = current_bar['rsi'] > self.params['rsi_overbought'] and previous_bar['rsi'] <= self.params['rsi_overbought']
                self.rsi_bull = current_bar['rsi'] < self.params['rsi_oversold'] and previous_bar['rsi'] >= self.params['rsi_oversold']
            else:
                self.rsi_bear = current_bar['rsi'] < self.params['rsi_oversold'] and previous_bar['rsi'] >= self.params['rsi_oversold']
                self.rsi_bull = current_bar['rsi'] > self.params['rsi_overbought'] and previous_bar['rsi'] <= self.params['rsi_overbought']
        elif self.params['entry_option'] == '변곡':
            if not self.params['reverse']:
                self.rsi_bear = ((previous_bar['rsi'] > self.params['rsi_overbought']) or (current_bar['rsi'] > self.params['rsi_overbought'])) and current_bar['rsi'] < previous_bar['rsi']
                self.rsi_bull = ((previous_bar['rsi'] < self.params['rsi_oversold']) or (current_bar['rsi'] < self.params['rsi_oversold'])) and current_bar['rsi'] > previous_bar['rsi']
            else:
                self.rsi_bear = ((previous_bar['rsi'] < self.params['rsi_oversold']) or (current_bar['rsi'] < self.params['rsi_oversold'])) and current_bar['rsi'] > previous_bar['rsi']
                self.rsi_bull = ((previous_bar['rsi'] > self.params['rsi_overbought']) or (current_bar['rsi'] > self.params['rsi_overbought'])) and current_bar['rsi'] < previous_bar['rsi']
        
        if self.rsi_bull or self.rsi_bear:
            logging.info(f"Current RSI: {current_bar['rsi']:.2f}, Previous RSI: {previous_bar['rsi']:.2f}")
            logging.info(f"RSI Overbought: {self.params['rsi_overbought']}, RSI Oversold: {self.params['rsi_oversold']}")
            logging.info(f"Entry Option: {self.params['entry_option']}, Reverse: {self.params['reverse']}")
            logging.info(f"RSI Bull: {self.rsi_bull}, RSI Bear: {self.rsi_bear}")
            
        if self.params['direction'] == '':  # 양방향 거래
            return self.rsi_bull or self.rsi_bear
        elif self.params['direction'] == '매수':
            return self.rsi_bull
        elif self.params['direction'] == '매도':
            return self.rsi_bear
        return False
        
    # def check_entry_conditions(self, current_bar, previous_bar):
    #     bbw_condition = self.bbw > self.buzz or self.bbw < self.squeeze
    #     return ((self.rsi_bear and self.params['direction'] != '매수') or 
    #             (self.rsi_bull and self.params['direction'] != '매도')) and bbw_condition

    def execute_entry(self, symbol, current_bar):
        current_time = pd.to_datetime(current_bar['timestamp'])
        if not self.is_in_trading_time(current_time):
            return

        logging.info(f"self.state = {self.state}")
        if self.state == 0:
            logging.info(f"self.state 0 진입가격 print준비")
            logging.info(f"rsi_bull = {self.rsi_bull} and rsi_bear = {self.rsi_bear} and 방향 = {self.params['direction']}")
            if (self.rsi_bull and (self.params['direction'] == '' or self.params['direction'] != '매도')):
                logging.info(f"{symbol} - 롱 진입: 가격 {current_bar['close']:.2f}, RSI {current_bar['rsi']:.2f}")
                self.enter_long(symbol, current_bar)
            elif (self.rsi_bear and (self.params['direction'] == '' or self.params['direction'] != '매수')):
                logging.info(f"{symbol} - 숏 진입: 가격 {current_bar['close']:.2f}, RSI {current_bar['rsi']:.2f}")
                self.enter_short(symbol, current_bar)

    def check_extreme_exit(self, current_bar):
        if self.state == 1 and self.params['use_extreme_exit_long'] and self.extreme_state == -2:
            self.close_position("강한 하락 추세로 인한 롱 포지션 종료")
        elif self.state == -1 and self.params['use_extreme_exit_short'] and self.extreme_state == 2:
            self.close_position("강한 상승 추세로 인한 숏 포지션 종료")

    def is_in_trading_time(self, current_time):
        if not self.params['use_time_filter']:
            return True
        
        start_time = datetime.strptime(self.params['trading_start_time'], '%H:%M').time()
        end_time = datetime.strptime(self.params['trading_end_time'], '%H:%M').time()
        
        current_time = current_time.time()
        if start_time <= end_time:
            return start_time <= current_time <= end_time
        else:  # 자정을 걸치는 경우
            return current_time >= start_time or current_time <= end_time

    def enter_long(self, symbol, current_bar):
        logging.info("enter_long 코드실행")
        self.state = 1
        self.position_state = 1
        self.long_avg_price = current_bar['close']
        self.last_long_entry_price = current_bar['close']
        self.set_long_tp_sl(current_bar)
        self.total_position = self.calculate_position_size(self.params['real_qty'], current_bar)

    def enter_short(self, symbol, current_bar):
        logging.info("enter_short 코드실행")
        self.state = -1
        self.position_state = -1
        self.short_avg_price = current_bar['close']
        self.last_short_entry_price = current_bar['close']
        self.set_short_tp_sl(current_bar)
        self.total_position = -self.calculate_position_size(self.params['real_qty'], current_bar)

    def set_long_tp_sl(self, current_bar):
        self.long_tp1 = self.calculate_tp('long', self.params['ProfitPerc1'], current_bar)
        self.long_tp2 = self.calculate_tp('long', self.params['ProfitPerc2'], current_bar)
        self.long_tp3 = self.calculate_tp('long', self.params['ProfitPerc3'], current_bar)
        
        if self.params['use_sl']:
            self.long_sl = self.calculate_sl('long', current_bar)

    def set_short_tp_sl(self, current_bar):
        self.short_tp1 = self.calculate_tp('short', self.params['ProfitPerc1'], current_bar)
        self.short_tp2 = self.calculate_tp('short', self.params['ProfitPerc2'], current_bar)
        self.short_tp3 = self.calculate_tp('short', self.params['ProfitPerc3'], current_bar)
        
        if self.params['use_sl']:
            self.short_sl = self.calculate_sl('short', current_bar)

    def calculate_tp(self, position_type, tp_level, current_bar):
        avg_price = self.long_avg_price if position_type == 'long' else self.short_avg_price
        if self.params['tp_option'] == 'ATR 기준':
            return avg_price + current_bar['atr'] * tp_level * (1 if position_type == 'long' else -1)
        elif self.params['tp_option'] == '퍼센트 기준':
            return avg_price * (1 + tp_level / 100 if position_type == 'long' else 1 - tp_level / 100)
        else:  # 금액 기준
            return avg_price + tp_level * (1 if position_type == 'long' else -1)

    def calculate_sl(self, position_type, current_bar):
        avg_price = self.long_avg_price if position_type == 'long' else self.short_avg_price
        if self.params['sl_option'] == 'ATR 기준':
            return avg_price + (current_bar['atr'] * self.params['sl_value'] * (-1 if position_type == 'long' else 1))
        elif self.params['sl_option'] == '퍼센트 기준':
            return avg_price * (1 - self.params['sl_value'] / 100 if position_type == 'long' else 1 + self.params['sl_value'] / 100)
        else:  # 금액 기준
            return avg_price + (self.params['sl_value'] * (-1 if position_type == 'long' else 1))
        
    def check_tp_sl(self, current_bar):
        if self.state == 1:  # Long position
            self.check_tp_sl_long(current_bar)
        elif self.state == -1:  # Short position
            self.check_tp_sl_short(current_bar)

    def check_tp_sl_long(self, current_bar):
        for i, tp_level in enumerate([self.long_tp1, self.long_tp2, self.long_tp3], 1):
            if current_bar['high'] >= tp_level and self.tp_state < i:
                self.logger.info(f"롱 TP{i} 도달: 가격 {tp_level:.2f}")
                self.tp_state = i
                if i == 3 and not self.params['get_tp_reset_state']:
                    self.close_position("롱 전체 청산")

        if self.params['use_sl'] and current_bar['low'] <= self.long_sl:
            self.close_position("롱 손절")

    def check_tp_sl_short(self, current_bar):
        for i, tp_level in enumerate([self.short_tp1, self.short_tp2, self.short_tp3], 1):
            if current_bar['low'] <= tp_level and self.tp_state > -i:
                self.logger.info(f"숏 TP{i} 도달: 가격 {tp_level:.2f}")
                self.tp_state = -i
                if i == 3 and not self.params['get_tp_reset_state']:
                    self.close_position("숏 전체 청산")

        if self.params['use_sl'] and current_bar['high'] >= self.short_sl:
            self.close_position("숏 손절")

    def close_position(self, reason):
        self.logger.info(f"포지션 종료: {reason}")
        self.state = 0
        self.position_state = 0
        self.tp_state = 0
        self.total_position = 0

    def update_pyramiding(self, current_bar):
        if self.params['pyramiding_allow_same_dir'] or self.params['pyramiding_allow_same_dir_rsi']:
            if self.state == 1 and self.can_add_to_long(current_bar):
                self.add_to_position('long', current_bar)
            elif self.state == -1 and self.can_add_to_short(current_bar):
                self.add_to_position('short', current_bar)

    def can_add_to_long(self, current_bar):
        return (abs(self.position_state) < self.params['pyramiding_limit'] and
                self.state == 1 and
                (not self.params['pyramiding_cond'] or current_bar['low'] < self.pyramiding_long_price) and
                (not self.params['rsi_cond'] or current_bar['rsi'] < self.params['rsi_oversold']))

    def can_add_to_short(self, current_bar):
        return (abs(self.position_state) < self.params['pyramiding_limit'] and
                self.state == -1 and
                (not self.params['pyramiding_cond'] or current_bar['high'] > self.pyramiding_short_price) and
                (not self.params['rsi_cond'] or current_bar['rsi'] > self.params['rsi_overbought']))

    def add_to_position(self, position_type, current_bar):
        qty = self.calculate_position_size(self.params['real_qty'] * (self.params['qty_multiplier'] ** abs(self.position_state)), current_bar)
        
        if position_type == 'long':
            self.position_state += 1
            self.long_avg_price = (self.long_avg_price * (self.position_state - 1) + current_bar['close']) / self.position_state
            self.total_position += qty
        else:
            self.position_state -= 1
            self.short_avg_price = (self.short_avg_price * (abs(self.position_state) - 1) + current_bar['close']) / abs(self.position_state)
            self.total_position -= qty
        
        #self.logger.info(f"{position_type.capitalize()} 추가 진입: 가격 {current_bar['close']:.2f}, 수량 {qty:.4f}, RSI {current_bar['rsi']:.2f}")
        self.calculate_pyramiding_prices(current_bar)

    def calculate_position_size(self, qty_value, current_bar):
        if self.params['default_qty_option'] == '금액 기준':
            return qty_value / current_bar['close']
        else:  # 계약 수
            return qty_value

    def calculate_pyramiding_prices(self, current_bar):
        if self.params['pyramiding_entry_type'] == '퍼센트 기준':
            self.pyramiding_long_price = self.long_avg_price * (1 - self.params['pyramiding_value'] / 100)
            self.pyramiding_short_price = self.short_avg_price * (1 + self.params['pyramiding_value'] / 100)
        elif self.params['pyramiding_entry_type'] == 'ATR 기준':
            self.pyramiding_long_price = self.long_avg_price - self.params['pyramiding_value'] * current_bar['atr']
            self.pyramiding_short_price = self.short_avg_price + self.params['pyramiding_value'] * current_bar['atr']
        else:  # 금액 기준
            self.pyramiding_long_price = self.long_avg_price - self.params['pyramiding_value']
            self.pyramiding_short_price = self.short_avg_price + self.params['pyramiding_value']

    def update_extreme_state(self, trend_result):
        self.extreme_state = trend_result['extreme_state']
        self.bbw = trend_result['bbw']
        self.bbr = trend_result['bbr']
        self.buzz = trend_result['buzz']
        self.squeeze = trend_result['squeeze']

        # logging.info(f"extreme_state updated to: {self.extreme_state}")
        # logging.info(f"bbw updated to: {self.bbw}")
        # logging.info(f"bbr updated to: {self.bbr}")
        # logging.info(f"buzz updated to: {self.buzz}")
        # logging.info(f"squeeze updated to: {self.squeeze}")

    def check_safety_entry(self, current_bar):
        if self.params['use_safty'] and self.state == 0:
            if self.waiting_for_long_entry:
                safety_long_entry = self.calculate_safety_entry('long', current_bar)
                if current_bar['low'] <= safety_long_entry:
                    self.execute_safety_entry('long', safety_long_entry, current_bar)
            elif self.waiting_for_short_entry:
                safety_short_entry = self.calculate_safety_entry('short', current_bar)
                if current_bar['high'] >= safety_short_entry:
                    self.execute_safety_entry('short', safety_short_entry, current_bar)

    def calculate_safety_entry(self, entry_type, current_bar):
        if self.params['safty_entry_type'] == '퍼센트 기준':
            return current_bar['open'] * (1 - self.params['safty_value'] / 100) if entry_type == 'long' else current_bar['open'] * (1 + self.params['safty_value'] / 100)
        elif self.params['safty_entry_type'] == 'ATR 기준':
            return current_bar['open'] - self.params['safty_value'] * current_bar['atr'] if entry_type == 'long' else current_bar['open'] + self.params['safty_value'] * current_bar['atr']
        else:  # 금액 기준
            return current_bar['open'] - self.params['safty_value'] if entry_type == 'long' else current_bar['open'] + self.params['safty_value']

    def execute_safety_entry(self, entry_type, entry_price, current_bar):
        qty = self.calculate_position_size(self.params['safty_qty'], current_bar)
        if entry_type == 'long':
            self.long_avg_price = (self.long_avg_price * self.position_state + entry_price * qty) / (self.position_state + qty)
            self.position_state += qty
            self.state = 1
        else:
            self.short_avg_price = (self.short_avg_price * abs(self.position_state) + entry_price * qty) / (abs(self.position_state) + qty)
            self.position_state -= qty
            self.state = -1
        self.logger.info(f"세이프티 {entry_type} 진입: 가격 {entry_price:.2f}, 수량 {qty:.4f}")
        self.waiting_for_long_entry = False
        self.waiting_for_short_entry = False

    def update_break_even(self, current_bar):
        if self.state == 1:  # Long position
            if self.tp_state >= 1 and self.params['use_BreakEven']:
                self.long_sl = self.long_avg_price
            elif self.tp_state >= 2 and self.params['use_BreakEven_TP2']:
                self.long_sl = self.calculate_tp('long', self.params['ProfitPerc1'], current_bar)
            elif self.tp_state >= 3 and self.params['use_BreakEven_TP3']:
                self.long_sl = self.calculate_tp('long', self.params['ProfitPerc2'], current_bar)
        elif self.state == -1:  # Short position
            if self.tp_state <= -1 and self.params['use_BreakEven']:
                self.short_sl = self.short_avg_price
            elif self.tp_state <= -2 and self.params['use_BreakEven_TP2']:
                self.short_sl = self.calculate_tp('short', self.params['ProfitPerc1'], current_bar)
            elif self.tp_state <= -3 and self.params['use_BreakEven_TP3']:
                self.short_sl = self.calculate_tp('short', self.params['ProfitPerc2'], current_bar)

    def format_price(self, price):
        """
        가격을 적절한 소수점 자릿수로 포맷팅합니다.
        """
        price = Decimal(str(price))
        if price < Decimal('0.0001'):
            return f"{price:.8f}"
        elif price < Decimal('0.01'):
            return f"{price:.6f}"
        elif price < Decimal('1'):
            return f"{price:.4f}"
        elif price < Decimal('10'):
            return f"{price:.3f}"
        elif price < Decimal('100'):
            return f"{price:.2f}"
        elif price < Decimal('1000'):
            return f"{price:.1f}"
        else:
            return f"{price:.0f}"

    def print_final_results(self, symbol):
        logger.info(f"\n{symbol} 최종 결과:")
        logger.info(f"최종 포지션 상태: {self.position_state}")
        logger.info(f"최종 포지션 크기: {self.format_price(self.total_position)}")
        if self.state == 1:
            logger.info(f"롱 평균 진입가: {self.format_price(self.long_avg_price)}")
            logger.info(f"롱 TP1: {self.format_price(self.long_tp1)}, TP2: {self.format_price(self.long_tp2)}, TP3: {self.format_price(self.long_tp3)}")
            if self.params['use_sl']:
                logger.info(f"롱 SL: {self.format_price(self.long_sl)}")
        elif self.state == -1:
            logger.info(f"숏 평균 진입가: {self.format_price(self.short_avg_price)}")
            logger.info(f"숏 TP1: {self.format_price(self.short_tp1)}, TP2: {self.format_price(self.short_tp2)}, TP3: {self.format_price(self.short_tp3)}")
            if self.params['use_sl']:
                logger.info(f"숏 SL: {self.format_price(self.short_sl)}")

@app.task(name='trading_tasks.process_symbol_task')
def process_symbol_task(symbol, timeframe, params):
    strategy = TradingStrategy(params)
    loop = asyncio.get_event_loop()
    loop.run_until_complete(strategy.process_symbol(symbol, timeframe))
    return f"{symbol} 처리 완료"

@task_success.connect
def task_success_handler(sender=None, **kwargs):
    logger.info(f"태스크 성공: {kwargs.get('result')}")

@task_failure.connect
def task_failure_handler(sender=None, **kwargs):
    logger.error(f"태스크 실패: {kwargs.get('exception')}")

# async def analyze_and_scan(params):
#     base_path = Path(path_helper.grid_dir) / params['exchange_name']  
#     # 새로운 즉시 실행 코드
#     try:
#         csv_files = list(base_path.glob(f'*_{params["timeframe"]}.csv'))
#         matching_symbols = []

#         for csv_file in csv_files:
#             symbol = csv_file.stem.split(f'_{params["timeframe"]}')[0]
            
#             strategy = TradingStrategy(params)
#             df = strategy.load_data(symbol, params['timeframe'])
#             df = strategy.calculate_indicators(df)

#             current_bar = df.iloc[-1]
#             previous_bar = df.iloc[-2]

#             if strategy.update_state(current_bar, previous_bar):
#                 matching_symbols.append(symbol)
#                 await strategy.process_symbol(symbol, params['timeframe'])

#         logger.info(f"조건을 만족하는 종목: {matching_symbols}")

#     except Exception as e:
#         logger.error(f"오류 발생: {e}")
#         logger.exception("상세 오류:")

async def analyze_and_scan(params):
    base_path = Path(path_helper.grid_dir) / params['exchange_name']
    
    timeframe_minutes = {
        '1m': 1, '5m': 5, '15m': 15, '30m': 30, '1h': 60, '4h': 240, '1d': 1440
    }
    interval = timeframe_minutes.get(params['timeframe'], 1)

    while True:
        try:
            current_time = datetime.now()
            next_update = current_time.replace(
                minute=(current_time.minute // interval) * interval,
                second=0,
                microsecond=0
            ) + timedelta(minutes=interval)

            wait_seconds = (next_update - current_time).total_seconds()
            logger.info(f"다음 업데이트까지 {wait_seconds:.2f}초 대기 중 (다음 업데이트: {next_update})")
            await asyncio.sleep(wait_seconds)
    
            csv_files = list(base_path.glob(f'*_{params["timeframe"]}.csv'))
            tasks = []

            for csv_file in csv_files:
                symbol = csv_file.stem.split(f'_{params["timeframe"]}')[0]
                
                strategy = TradingStrategy(params)
                df = strategy.load_data(symbol, params['timeframe'])
                df = strategy.calculate_indicators(df)

                current_bar = df.iloc[-1]
                previous_bar = df.iloc[-2]

                if strategy.update_state(current_bar, previous_bar):
                    task = asyncio.create_task(strategy.process_symbol(symbol, params['timeframe']))
                    tasks.append(task)

            # 모든 태스크가 완료될 때까지 기다림
            await asyncio.gather(*tasks)
            logger.info(f"처리된 종목 수: {len(tasks)}")

        except Exception as e:
            logger.error(f"오류 발생: {e}")
            logger.exception("상세 오류:")

def start_celery_worker():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    cmd = [sys.executable, '-m', 'celery', '-A', 'trading_strategy', 'worker', '--loglevel=WARNING']
    
    # Celery 로그를 별도 파일로 리다이렉션
    celery_log_file = open('celery_worker.log', 'w')
    process = subprocess.Popen(cmd, stdout=celery_log_file, stderr=celery_log_file, cwd=current_dir)
    
    # 워커 시작 확인을 위한 대기
    time.sleep(5)
    
    if process.poll() is None:
        logger.info("Celery 워커가 성공적으로 시작되었습니다.")
        return process, celery_log_file
    else:
        logger.error("Celery 워커 시작 실패.")
        celery_log_file.close()
        return None, None

def stop_celery_worker(process, log_file):
    if process:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
        logger.info("Celery 워커가 종료되었습니다.")
    if log_file:
        log_file.close()

if __name__ == "__main__":
    params = {
        'exchange_name': 'okx',  # 거래소 이름 (예: 'okx', 'binance' 등)
        'timeframe': "1m",  # 차트의 시간 프레임 (예: '1m', '5m', '15m', '1h', '4h', '1d')
        'entry_option': "변곡",  # 진입 옵션: '돌파' 또는 '변곡'
        'tp_option': "ATR 기준",  # 이익실현(Take Profit) 옵션: 'ATR 기준', '퍼센트 기준', '금액 기준'
        'ProfitPerc1': 2.0,  # 첫 번째 이익실현 목표 (tp_option에 따라 ATR 배수, 퍼센트, 또는 금액)
        'ProfitPerc2': 3.0,  # 두 번째 이익실현 목표
        'ProfitPerc3': 4.0,  # 세 번째 이익실현 목표
        'reverse': False,  # RSI 신호 반전 여부
        'rsi_overbought': 70,  # RSI 과매수 기준값
        'rsi_oversold': 30,  # RSI 과매도 기준값
        'use_sl': True,  # 손절(Stop Loss) 사용 여부
        'sl_option': '퍼센트 기준',  # 손절 옵션: 'ATR 기준', '퍼센트 기준', '금액 기준'
        'sl_value': 2.0,  # 손절 값 (sl_option에 따라 ATR 배수, 퍼센트, 또는 금액)
        'pyramiding_allow_same_dir': True,  # 같은 방향으로의 피라미딩 허용 여부
        'pyramiding_limit': 4,  # 최대 피라미딩 횟수
        'pyramiding_entry_type': '퍼센트 기준',  # 피라미딩 진입 기준: '금액 기준', '퍼센트 기준', 'ATR 기준'
        'pyramiding_value': 1.0,  # 피라미딩 진입 값 (pyramiding_entry_type에 따라 해석)
        'rsi_cond': True,  # RSI 조건 사용 여부 (피라미딩시)
        'direction': '',  # 거래 방향 제한 ('매수', '매도', '' (양방향))
        'get_tp_reset_state': False,  # TP 도달 후 재진입 허용 여부
        'default_qty_option': '계약 수',  # 기본 수량 옵션: '계약 수' 또는 '금액 기준'
        'real_qty': 1.0,  # 실제 거래 수량 또는 금액
        'qty_multiplier': 1.0,  # 피라미딩 시 수량 증가 배수
        'pyramiding_cond': True,  # 피라미딩 조건 사용 여부
        'use_time_filter': False,  # 시간 필터 사용 여부
        'trading_start_time': '00:00',  # 거래 시작 시간
        'trading_end_time': '23:59',  # 거래 종료 시간
        'use_safty': False,  # 안전 진입 사용 여부
        'safty_entry_type': '퍼센트 기준',  # 안전 진입 기준: '금액 기준', '퍼센트 기준', 'ATR 기준'
        'safty_value': 3.0,  # 안전 진입 값 (safty_entry_type에 따라 해석)
        'safty_qty': 1.0,  # 안전 진입 시 거래 수량
        'use_BreakEven': True,  # 손익분기점(Break-even) 사용 여부
        'use_BreakEven_TP2': True,  # TP2 도달 후 Break-even 사용 여부
        'use_BreakEven_TP3': True,  # TP3 도달 후 Break-even 사용 여부
        'ma_type': 'VIDYA',  # 이동평균 유형 (예: 'EMA', 'SMA')
        'use_longer_trend': False,  # 장기 트렌드 사용 여부
        'use_extreme_state_long': True,  # 강한 상승 추세에서만 롱 진입 허용
        'use_extreme_state_short': True,  # 강한 하락 추세에서만 숏 진입 허용
        'use_extreme_exit_long': False,  # 강한 하락 추세 시 롱 포지션 종료
        'use_extreme_exit_short': False,  # 강한 상승 추세 시 숏 포지션 종료
    }
    logger.info(f"실제 Grid 데이터 경로: {path_helper.grid_dir.resolve()}")
    logger.info(f"거래소 데이터 경로: {path_helper.grid_dir / str(params['exchange_name'])}")
    
    # Celery 워커 시작
    celery_process, celery_log_file = start_celery_worker()

    if celery_process:
        try:
            # 메인 로직 실행
            asyncio.run(analyze_and_scan(params))
        except KeyboardInterrupt:
            logger.info("프로그램 종료 중...")
        finally:
            # Celery 워커 종료
            stop_celery_worker(celery_process, celery_log_file)
    else:
        logger.error("Celery 워커를 시작할 수 없어 프로그램을 종료합니다.")
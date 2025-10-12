import logging
import os
from pathlib import Path

import numpy as np
import pandas as pd

from shared.indicators import calc_rsi
from shared.utils import path_helper

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class RSITester:
    def __init__(self, params):
        self.params = params

    def load_data(self, symbol, timeframe):
        current_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(current_dir, 'GRID', 'okx', f"{symbol}_{timeframe}.csv")
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"파일이 존재하지 않습니다: {file_path}")
        
        # 필요한 행 수 계산 (RSI 계산에 필요한 최소 데이터 + 현재 봉)
        needed_rows = 14 + 1
        
        # 파일의 전체 행 수 계산
        total_rows = sum(1 for _ in open(file_path)) - 1  # 헤더 제외
        
        # 필요한 열만 지정
        columns_to_read = ['timestamp', 'open', 'high', 'low', 'close']
        
        # 파일의 마지막 needed_rows 개의 행만 읽기
        if total_rows > needed_rows:
            df = pd.read_csv(file_path, usecols=columns_to_read, nrows=needed_rows, skiprows=range(1, total_rows - needed_rows + 1))
        else:
            df = pd.read_csv(file_path, usecols=columns_to_read)
        
        # timestamp를 datetime으로 변환
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        
        return df

    def calculate_indicators(self, df):
        # RSI 계산 - shared.indicators 사용
        rsi_values = calc_rsi(df['close'].values, period=14)
        df['rsi'] = rsi_values
        return df

    def update_state(self, current_bar, previous_bar):
        if self.params['entry_option'] == '돌파':
            if not self.params['reverse']:
                rsi_bear = current_bar['rsi'] > self.params['rsi_overbought'] and previous_bar['rsi'] <= self.params['rsi_overbought']
                rsi_bull = current_bar['rsi'] < self.params['rsi_oversold'] and previous_bar['rsi'] >= self.params['rsi_oversold']
            else:
                rsi_bear = current_bar['rsi'] < self.params['rsi_oversold'] and previous_bar['rsi'] >= self.params['rsi_oversold']
                rsi_bull = current_bar['rsi'] > self.params['rsi_overbought'] and previous_bar['rsi'] <= self.params['rsi_overbought']
        elif self.params['entry_option'] == '변곡':
            if not self.params['reverse']:
                rsi_bear = ((previous_bar['rsi'] > self.params['rsi_overbought']) or (current_bar['rsi'] > self.params['rsi_overbought'])) and current_bar['rsi'] < previous_bar['rsi']
                rsi_bull = ((previous_bar['rsi'] < self.params['rsi_oversold']) or (current_bar['rsi'] < self.params['rsi_oversold'])) and current_bar['rsi'] > previous_bar['rsi']
            else:
                rsi_bear = ((previous_bar['rsi'] < self.params['rsi_oversold']) or (current_bar['rsi'] < self.params['rsi_oversold'])) and current_bar['rsi'] > previous_bar['rsi']
                rsi_bull = ((previous_bar['rsi'] > self.params['rsi_overbought']) or (current_bar['rsi'] > self.params['rsi_overbought'])) and current_bar['rsi'] < previous_bar['rsi']

        if self.params['direction'] == '':  # 양방향 거래
            return rsi_bull or rsi_bear
        elif self.params['direction'] == '매수':
            return rsi_bull
        elif self.params['direction'] == '매도':
            return rsi_bear
        return False

    def find_matching_symbols(self):
        matching_symbols = []
        csv_files = list(Path(os.path.join(path_helper.grid_dir, 'okx')).glob(f'*_{self.params["timeframe"]}.csv'))
        
        for csv_file in csv_files:
            symbol = csv_file.stem.split(f'_{self.params["timeframe"]}')[0]
            try:
                df = self.load_data(symbol, self.params['timeframe'])
                df = self.calculate_indicators(df)

                if len(df) < 2:
                    logger.warning(f"{symbol}의 데이터가 충분하지 않습니다.")
                    continue

                current_bar = df.iloc[-1]
                previous_bar = df.iloc[-2]

                if self.update_state(current_bar, previous_bar):
                    matching_symbols.append(symbol)

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")

        return matching_symbols

if __name__ == "__main__":
    params = {
        'timeframe': '1m',
        'entry_option': '변곡',
        'reverse': False,
        'rsi_overbought': 70,
        'rsi_oversold': 30,
        'direction': ''
    }

    tester = RSITester(params)
    matching_symbols = tester.find_matching_symbols()
    logger.info(f"조건을 만족하는 심볼: {matching_symbols}")
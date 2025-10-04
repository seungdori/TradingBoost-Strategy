import os
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from shared.indicators import calc_rsi

async def analyze_and_scan(timeframe, entry_option, tp_option, profit_perc1, profit_perc2, profit_perc3, reverse=False):
    print(f"현재 작업 디렉토리: {os.getcwd()}")
    base_path = os.path.dirname(os.path.abspath(__file__))
    if not os.path.exists(base_path):
        os.mkdir(base_path)
    timeframe_path = os.path.join(base_path, 'okx_ohlcv', timeframe)
    print(f"검색 중인 경로: {os.path.abspath(timeframe_path)}")

    def get_futures():
        if not os.path.exists(timeframe_path):
            print(f"경로가 존재하지 않습니다: {timeframe_path}")
            return []

        files = os.listdir(timeframe_path)
        #print(f"디렉토리 내 모든 파일: {files}")
        
        futures = [f.split('_')[0] for f in files if f.endswith(f'_{timeframe}.csv')]
        print(f"발견된 선물 개수: {len(futures)}")
        print(f"발견된 선물: {futures}")
        return futures

    async def process_symbol(symbol):
        file_path = os.path.join(timeframe_path, f"{symbol}_{timeframe}.csv")
        #print(f"처리 중인 파일: {file_path}")
        try:
            if not os.path.exists(file_path):
                print(f"파일이 존재하지 않습니다: {file_path}")
                return None

            # CSV 파일 읽기 (헤더가 있음을 명시)
            df = pd.read_csv(file_path, parse_dates=['timestamp'])

            # RSI 계산 - shared.indicators 사용
            rsi_values = calc_rsi(df['close'].values, period=14)
            df['rsi'] = rsi_values
            
            # ATR 계산
            df['tr1'] = abs(df['high'] - df['low'])
            df['tr2'] = abs(df['high'] - df['close'].shift())
            df['tr3'] = abs(df['low'] - df['close'].shift())
            df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
            df['atr'] = df['tr'].rolling(window=233).mean()

            # 상태 계산 (간단한 예시, 실제 로직에 맞게 조정 필요)
            df['state'] = np.where(df['close'] > df['close'].shift(), 1, -1)

            latest = df.iloc[-1]
            previous = df.iloc[-2]
            
            #print(f"{symbol}의 현재 RSI: {latest['rsi']:.2f}")
            
            rsi_overbought = 70
            rsi_oversold = 30
            
            if entry_option == '돌파':
                if not reverse:
                    rsi_bear = latest['rsi'] > rsi_overbought and previous['rsi'] <= rsi_overbought
                    rsi_bull = latest['rsi'] < rsi_oversold and previous['rsi'] >= rsi_oversold
                else:
                    rsi_bear = latest['rsi'] < rsi_oversold and previous['rsi'] >= rsi_oversold
                    rsi_bull = latest['rsi'] > rsi_overbought and previous['rsi'] <= rsi_overbought
            elif entry_option == '변곡':
                if not reverse:
                    rsi_bear = ((previous['rsi'] > rsi_overbought) or (latest['rsi'] > rsi_overbought)) and latest['rsi'] < previous['rsi']
                    rsi_bull = ((previous['rsi'] < rsi_oversold) or (latest['rsi'] < rsi_oversold)) and latest['rsi'] > previous['rsi']
                else:
                    rsi_bear = ((previous['rsi'] < rsi_oversold) or (latest['rsi'] < rsi_oversold)) and latest['rsi'] > previous['rsi']
                    rsi_bull = ((previous['rsi'] > rsi_overbought) or (latest['rsi'] > rsi_overbought)) and latest['rsi'] < previous['rsi']
            
            if rsi_bear or rsi_bull:
                # TradingView 코드 기반 추가 계산
                pyramiding_value = 3  # 트레이딩뷰 코드의 기본값
                srcATR = latest['close']  # srcATR을 현재 종가로 가정

                bearse = srcATR + latest['atr'] * (pyramiding_value * 1)
                bullse = srcATR - latest['atr'] * (pyramiding_value * 1)
                bearse3 = srcATR + latest['atr'] * (pyramiding_value * 3)
                bullse3 = srcATR - latest['atr'] * (pyramiding_value * 3)

                # SL과 TP 계산 (트레이딩뷰 코드 기반)
                long_avg_price = latest['close']  # 예시, 실제로는 포지션의 평균 진입가격을 사용해야 함
                short_avg_price = latest['close']  # 예시, 실제로는 포지션의 평균 진입가격을 사용해야 함
                
                atr_value_long = latest['atr']
                atr_value_short = latest['atr']

                # Long TP 계산
                if tp_option == 'ATR 기준':
                    long_tp1 = long_avg_price + atr_value_long * profit_perc1
                    long_tp2 = long_avg_price + atr_value_long * profit_perc2
                    long_tp3 = long_avg_price + atr_value_long * profit_perc3
                elif tp_option == '퍼센트 기준':
                    long_tp1 = long_avg_price * (1 + profit_perc1 * 0.01)
                    long_tp2 = long_avg_price * (1 + profit_perc2 * 0.01)
                    long_tp3 = long_avg_price * (1 + profit_perc3 * 0.01)
                elif tp_option == '금액 기준':
                    long_tp1 = long_avg_price + profit_perc1
                    long_tp2 = long_avg_price + profit_perc2
                    long_tp3 = long_avg_price + profit_perc3

                # Short TP 계산
                if tp_option == 'ATR 기준':
                    short_tp1 = short_avg_price - atr_value_short * profit_perc1
                    short_tp2 = short_avg_price - atr_value_short * profit_perc2
                    short_tp3 = short_avg_price - atr_value_short * profit_perc3
                elif tp_option == '퍼센트 기준':
                    short_tp1 = short_avg_price * (1 - profit_perc1 * 0.01)
                    short_tp2 = short_avg_price * (1 - profit_perc2 * 0.01)
                    short_tp3 = short_avg_price * (1 - profit_perc3 * 0.01)
                elif tp_option == '금액 기준':
                    short_tp1 = short_avg_price - profit_perc1
                    short_tp2 = short_avg_price - profit_perc2
                    short_tp3 = short_avg_price - profit_perc3

                return {
                    'symbol': symbol,
                    'rsi': latest['rsi'],
                    'close': latest['close'],
                    'signal': 'SELL' if rsi_bear else 'BUY',
                    'atr': latest['atr'],
                    'bearse': bearse,
                    'bullse': bullse,
                    'bearse3': bearse3,
                    'bullse3': bullse3,
                    'long_tp1': long_tp1,
                    'long_tp2': long_tp2,
                    'long_tp3': long_tp3,
                    'short_tp1': short_tp1,
                    'short_tp2': short_tp2,
                    'short_tp3': short_tp3
                }
        except Exception as e:
            print(f"{symbol} 처리 중 오류 발생: {e}")
            # 파일 내용 샘플 출력
            with open(file_path, 'r') as f:
                print(f"{symbol} 파일 내용 샘플:")
                print(f.read(500))  # 처음 500바이트만 출력
        
        return None

    while True:
        try:
            current_time = datetime.now()
            next_update = current_time.replace(second=0, microsecond=0) + timedelta(minutes=1)
            wait_seconds = (next_update - current_time).total_seconds()
            print(f"다음 업데이트까지 {wait_seconds:.2f}초 대기 중 (다음 업데이트: {next_update})")
            await asyncio.sleep(wait_seconds)
            
            print(f"\n{timeframe} 타임프레임 스캔 중:")
            futures = get_futures()
            if not futures:
                print("선물을 찾을 수 없습니다. 경로를 확인해주세요.")
                continue

            tasks = [process_symbol(symbol) for symbol in futures]
            results = await asyncio.gather(*tasks)
            results = [result for result in results if result is not None]
            
            if results:
                print("\n조건에 맞는 심볼:")
                for result in results:
                    print(f"{result['symbol']} - RSI: {result['rsi']:.2f}, 종가: {result['close']}, 신호: {result['signal']}")
                    print(f"  ATR: {result['atr']:.4f}")
                    print(f"  BEARSE: {result['bearse']:.4f}, BULLSE: {result['bullse']:.4f}")
                    print(f"  BEARSE3: {result['bearse3']:.4f}, BULLSE3: {result['bullse3']:.4f}")
                    print(f"  Long TP1: {result['long_tp1']:.4f}, TP2: {result['long_tp2']:.4f}, TP3: {result['long_tp3']:.4f}")
                    print(f"  Short TP1: {result['short_tp1']:.4f}, TP2: {result['short_tp2']:.4f}, TP3: {result['short_tp3']:.4f}")
            else:
                print("조건에 맞는 심볼이 없습니다.")
        
        except Exception as e:
            print(f"오류 발생: {e}")
            await asyncio.sleep(60)  # 1분 대기 후 재시도

# 사용 예시
if __name__ == "__main__":
    timeframe = "1m"
    entry_option = "돌파"  # 또는 "변곡"
    tp_option = "ATR 기준"  # 또는 "퍼센트 기준" 또는 "금액 기준"
    profit_perc1 = 2.0  # TP1의 값, 기본값 2.0
    profit_perc2 = 3.0  # TP2의 값, 기본값 3.0
    profit_perc3 = 4.0  # TP3의 값, 기본값 4.0
    reverse = False  # 역방향 신호를 원하면 True로 설정
    
    asyncio.run(analyze_and_scan(timeframe, entry_option, tp_option, profit_perc1, profit_perc2, profit_perc3, reverse))
    


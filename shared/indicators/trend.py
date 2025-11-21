import asyncio
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from shared.utils import path_helper


def get_csv_path(symbol, timeframe):
    return os.path.join(path_helper.grid_dir, 'okx', f"{symbol}_{timeframe}.csv")

def getMA(df, ma_type, length, src='close'):
    if len(df) < length:
        return pd.Series(np.nan, index=df.index)
    
    if ma_type == 'SMA':
        return df[src].rolling(window=length).mean()
    elif ma_type == 'EMA':
        return df[src].ewm(span=length, adjust=False).mean()
    elif ma_type == 'VIDYA':
        cmo_period = 9  # CMO period for VIDYA calculation
        delta = df[src].diff()
        up = delta.clip(lower=0).rolling(window=cmo_period).sum()
        down = -delta.clip(upper=0).rolling(window=cmo_period).sum()
        cmo = (up - down) / (up + down).replace(0, np.nan) * 100
        cmo.fillna(0, inplace=True)
        alpha = (abs(cmo) / 100) * (2 / (length + 1))
        vidya = pd.Series(0, index=df.index, dtype=float)
        vidya.iloc[0] = df[src].iloc[0]
        for i in range(1, len(df)):
            a = alpha.iloc[i-1]
            if not np.isnan(a):
                vidya.iloc[i] = vidya.iloc[i-1] + a * (df[src].iloc[i] - vidya.iloc[i-1])
            else:
                vidya.iloc[i] = df[src].iloc[i]
        return vidya
    elif ma_type == 'T3':
        def t3(series, length):
            e1 = series.ewm(span=length, adjust=False).mean()
            e2 = e1.ewm(span=length, adjust=False).mean()
            e3 = e2.ewm(span=length, adjust=False).mean()
            e4 = e3.ewm(span=length, adjust=False).mean()
            e5 = e4.ewm(span=length, adjust=False).mean()
            e6 = e5.ewm(span=length, adjust=False).mean()
            c1 = -0.343
            c2 = 0.743 * 3
            c3 = -0.478 * 3
            c4 = 1.078
            return c1 * e6 + c2 * e5 + c3 * e4 + c4 * e3
        return t3(df[src], length)
    elif ma_type == 'JMA':
        def calc_jma(src, length, phase, power):
            phase_ratio = 0.5 if phase < -100 else 2.5 if phase > 100 else phase / 100 + 1.5
            beta = 0.45 * (length - 1) / (0.45 * (length - 1) + 2)
            alpha = beta ** power
            e0 = e1 = e2 = jma = np.zeros(len(src))
            for i in range(1, len(src)):
                e0[i] = (1 - alpha) * src.iloc[i] + alpha * e0[i-1]
                e1[i] = (src.iloc[i] - e0[i]) * (1 - beta) + beta * e1[i-1]
                e2[i] = (e0[i] + phase_ratio * e1[i] - jma[i-1]) * (1 - alpha)**2 + alpha**2 * e2[i-1]
                jma[i] = e2[i] + jma[i-1]
            return pd.Series(jma, index=src.index)
        return calc_jma(df[src], length, 50, 2)
    else:
        raise ValueError(f"지원되지 않는 MA 타입: {ma_type}")
    
def read_last_n_rows(file_path, n):
    with open(file_path, 'r') as f:
        lines = f.readlines()
        header = lines[0].strip().split(',')
        data = [line.strip().split(',') for line in lines[-n:]]
    df = pd.DataFrame(data, columns=header)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df.set_index('timestamp', inplace=True)
    for col in df.columns:
        if col != 'timestamp':
            df[col] = df[col].astype(float)
    return df

def calculate_pivot_points(series, left, right):
    pivots = pd.Series(np.nan, index=series.index)
    pivot_array = []
    for i in range(left, len(series) - right):
        if all(series.iloc[i] > series.iloc[i-left:i]) and all(series.iloc[i] > series.iloc[i+1:i+right+1]):
            pivots.iloc[i] = series.iloc[i]
            pivot_array.append(series.iloc[i])
            #print(f"Pivot point found at index {i}: {series.iloc[i]}")
    #print(f"Total pivot points found: {len(pivot_array)}")
    return pivots, pivot_array

def is_rising(series, length):
    if len(series) < length:
        return False
    return all(series.iloc[j] > series.iloc[j - 1] for j in range(1, length))

def is_falling(series, length):
    if len(series) < length:
        return False
    return all(series.iloc[j] < series.iloc[j - 1] for j in range(1, length))

async def analyze_trend(df, symbol, timeframe, ma_type="JMA", use_longer_trend=False):
    try:
        # 데이터가 충분한지 확인
        needed_rows = 120 if use_longer_trend else 20
        if len(df) < needed_rows:
            print(f"데이터가 충분하지 않습니다. 현재 데이터 수: {len(df)}")
            return None

        # CYCLE 타입 및 길이 설정
        CYCLE_TYPE = ma_type
        lenF, lenM, lenS = (20, 40, 120) if use_longer_trend else (5, 10, 20)

        # MA CYCLE 계산
        MA1_ = getMA(df, CYCLE_TYPE, lenF)
        MA2_ = getMA(df, CYCLE_TYPE, lenM)
        MA3_ = getMA(df, CYCLE_TYPE, lenS)

        CYCLE_MA1_MTF = MA1_
        CYCLE_MA2_MTF = MA2_
        CYCLE_MA3_MTF = MA3_

        # 2nd CYCLE 계산
        CYCLE_TYPE_2nd, CYCLE_RES_2nd = 'VIDYA', '4h'
        lenF_2nd, lenM_2nd, lenS_2nd = 3, 9, 21
        needed_rows_2nd = lenS_2nd + 1

        # 4시간 데이터로 리샘플링
        df_2nd = df.set_index('timestamp').resample('4h').last().ffill()
        
        # 리샘플링된 데이터에 대해 MA 계산
        CYCLE_MA1_2nd = getMA(df_2nd, CYCLE_TYPE_2nd, lenF_2nd)
        CYCLE_MA2_2nd = getMA(df_2nd, CYCLE_TYPE_2nd, lenM_2nd)
        CYCLE_MA3_2nd = getMA(df_2nd, CYCLE_TYPE_2nd, lenS_2nd)

        # 원본 데이터의 타임스탬프에 맞춰 리샘플링된 데이터 재정렬
        CYCLE_MA1_MTF_2nd = CYCLE_MA1_2nd.reindex(df['timestamp'], method='ffill')
        CYCLE_MA2_MTF_2nd = CYCLE_MA2_2nd.reindex(df['timestamp'], method='ffill')
        CYCLE_MA3_MTF_2nd = CYCLE_MA3_2nd.reindex(df['timestamp'], method='ffill')

        # CYCLE 조건 계산 (불리언 마스크)
        CYCLE_Bull = ((CYCLE_MA1_MTF > CYCLE_MA2_MTF) & (CYCLE_MA2_MTF > CYCLE_MA3_MTF)) | ((CYCLE_MA2_MTF > CYCLE_MA1_MTF) & (CYCLE_MA1_MTF > CYCLE_MA3_MTF))
        CYCLE_Bear = (CYCLE_MA3_MTF > CYCLE_MA2_MTF) & (CYCLE_MA2_MTF > CYCLE_MA1_MTF)

        CYCLE_Bull_2nd = ((CYCLE_MA1_MTF_2nd > CYCLE_MA3_MTF_2nd) & (CYCLE_MA3_MTF_2nd > CYCLE_MA2_MTF_2nd)) | \
                         ((CYCLE_MA1_MTF_2nd > CYCLE_MA2_MTF_2nd) & (CYCLE_MA2_MTF_2nd > CYCLE_MA3_MTF_2nd)) | \
                         ((CYCLE_MA2_MTF_2nd > CYCLE_MA1_MTF_2nd) & (CYCLE_MA1_MTF_2nd > CYCLE_MA3_MTF_2nd))
        CYCLE_Bear_2nd = ((CYCLE_MA3_MTF_2nd > CYCLE_MA2_MTF_2nd) & (CYCLE_MA2_MTF_2nd > CYCLE_MA1_MTF_2nd)) | \
                         ((CYCLE_MA2_MTF_2nd > CYCLE_MA3_MTF_2nd) & (CYCLE_MA3_MTF_2nd > CYCLE_MA1_MTF_2nd)) | \
                         ((CYCLE_MA3_MTF_2nd > CYCLE_MA1_MTF_2nd) & (CYCLE_MA1_MTF_2nd > CYCLE_MA2_MTF_2nd))

        if use_longer_trend:
            CYCLE_Bull = CYCLE_Bull & CYCLE_Bull_2nd
            CYCLE_Bear = CYCLE_Bear & CYCLE_Bear_2nd

        # BBW 계산
        length, mult, len_ma = 15, 1.5, 100
        basis = df['close'].rolling(window=length).mean()
        dev = mult * df['close'].rolling(window=length).std()
        upper = basis + dev
        lower = basis - dev
        bbw = (upper - lower) * 10 / basis
        bbr = (df['close'] - lower) / (upper - lower)
        ma = bbw.rolling(window=len_ma).mean()

        # print(f"BBW range: {bbw.min()} to {bbw.max()}")
        # print(f"BBR range: {bbr.min()} to {bbr.max()}")

        # 피벗 포인트 계산
        pivot_left, pivot_right = 20, 20
        #print("Calculating high pivots...")
        ph, ph_array = calculate_pivot_points(bbw, pivot_left, pivot_right)
        #print("Calculating low pivots...")
        pl, pl_array = calculate_pivot_points(-bbw, pivot_left, pivot_right)
        pl = -pl  # 부호 반전
        pl_array = [-x for x in pl_array]  # 부호 반전

        # print(f"Number of high pivots: {len(ph_array)}")
        # print(f"Number of low pivots: {len(pl_array)}")

        # 피벗 평균 계산
        ph_avg = np.mean(ph_array) if ph_array else max(bbw.max(), 5)
        pl_avg = np.mean(pl_array) if pl_array else min(bbw.min(), 5)

        # print(f"ph_avg: {ph_avg}")
        # print(f"pl_avg: {pl_avg}")

        # Buzz와 Squeeze 계산
        mult_plph = 0.7
        buzz = ph_avg * mult_plph
        squeeze = pl_avg * (1/mult_plph)

        # print(f"Calculated Buzz: {buzz}")
        # print(f"Calculated Squeeze: {squeeze}")

        # BB_State 계산
        BB_State = pd.Series(np.zeros(len(df)), index=df.index)
        for i in range(1, len(df)):
            if np.isnan(buzz) or np.isnan(squeeze):
                BB_State.iloc[i] = BB_State.iloc[i-1]
            elif bbw.iloc[i] > buzz and bbw.iloc[i-1] <= buzz and bbr.iloc[i] > 0.5:
                BB_State.iloc[i] = 2
            elif bbw.iloc[i] > buzz and bbw.iloc[i-1] <= buzz and bbr.iloc[i] < 0.5:
                BB_State.iloc[i] = -2
            elif bbw.iloc[i] < squeeze:
                BB_State.iloc[i] = -1
            else:
                BB_State.iloc[i] = BB_State.iloc[i-1]

            if BB_State.iloc[i] == 2 and bbr.iloc[i] < 0.2:
                BB_State.iloc[i] = -2
            if BB_State.iloc[i] == -2 and bbr.iloc[i] > 0.8:
                BB_State.iloc[i] = 2

            if ((BB_State.iloc[i] == 2 or BB_State.iloc[i] == -2) and is_falling(bbw.iloc[i-2:i+1], 3)) or (bbw.iloc[i] > pl_avg and BB_State.iloc[i] == -1 and is_rising(bbw.iloc[i-1:i+1], 1)):
                BB_State.iloc[i] = 0

        #print(f"BB_State values: {BB_State.value_counts()}")

        # Trend State 계산 (PineScript Line 364-374)
        trend_state = pd.Series(np.zeros(len(df)), index=df.index)
        for i in range(1, len(df)):
            # 이전 상태 (PineScript의 var 동작 모방)
            prev_state = trend_state.iloc[i-1]

            # Bull 조건 (Line 364-365)
            if CYCLE_Bull.iloc[i] and (BB_State.iloc[i] == 2):
                trend_state.iloc[i] = 2
            # Bull 종료 조건 (Line 367-368)
            elif prev_state == 2 and not CYCLE_Bull.iloc[i]:
                trend_state.iloc[i] = 0
            # Bear 조건 (Line 370-371)
            elif CYCLE_Bear.iloc[i] and (BB_State.iloc[i] == -2):
                trend_state.iloc[i] = -2
            # Bear 종료 조건 (Line 373-374)
            elif prev_state == -2 and not CYCLE_Bear.iloc[i]:
                trend_state.iloc[i] = 0
            else:
                # 상태 유지 (PineScript의 var 동작)
                trend_state.iloc[i] = prev_state

        trend = "중립"
        if trend_state.iloc[-1] == 2:
            trend = "강한 상승"
        elif trend_state.iloc[-1] == -2:
            trend = "강한 하락"
        elif CYCLE_Bull.iloc[-1]:
            trend = "상승"
        elif CYCLE_Bear.iloc[-1]:
            trend = "하락"

        # print(f"Final BB_State: {BB_State.iloc[-1]}")
        # print(f"Final trend_state: {trend_state.iloc[-1]}")
        # print(f"Final trend: {trend}")

        return {
            'symbol': symbol,
            'trend': trend_state.iloc[-1],
            'trend_state': trend_state.iloc[-1],
            'BB_State': BB_State.iloc[-1],
            'CYCLE_Bull': CYCLE_Bull.iloc[-1],
            'CYCLE_Bear': CYCLE_Bear.iloc[-1],
            'bbw': bbw.iloc[-1],
            'bbr': bbr.iloc[-1],
            'buzz': buzz,
            'squeeze': squeeze
        }

    except Exception as e:
        print(f"{symbol} 트랜드 분석 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
    
    return None

async def analyze_all_trends(symbol, timeframe, ma_type="JMA", use_longer_trend=False):
    try:
        result = await analyze_trend(symbol, timeframe, ma_type, use_longer_trend)
        # if result:
        #     print(f"\n트랜드 분석 결과:")
        #     print(f"{result['symbol']} - 트랜드: {result['trend']}")
        #     print(f"Trend State: {result['trend_state']}")
        #     print(f"BB State: {result['BB_State']}")
        #     print(f"CYCLE Bull: {result['CYCLE_Bull']}")
        #     print(f"CYCLE Bear: {result['CYCLE_Bear']}")
        #     print(f"BBW: {result['bbw']:.4f}")
        #     print(f"BBR: {result['bbr']:.4f}")
        #     print(f"Buzz: {result['buzz']:.4f}")
        #     print(f"Squeeze: {result['squeeze']:.4f}")
        # else:
        #     print(f"{symbol} 분석 결과가 없습니다.")
        return result
    except Exception as e:
        print(f"{symbol} 분석 중 예기치 않은 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None


# 사용 예시
if __name__ == "__main__":
    symbol = "ZRO-USDT-SWAP"  # 분석하고자 하는 심볼
    timeframe = "1m"  # 분석하고자 하는 타임프레임
    ma_type = "VIDYA"
    use_longer_trend = True
    asyncio.run(analyze_all_trends(symbol, timeframe, ma_type, use_longer_trend))
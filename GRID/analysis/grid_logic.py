"""
Grid trading logic and calculations
"""
import pandas as pd
import numpy as np
import logging
import traceback
from typing import Tuple


def initialize_orders(df: pd.DataFrame, n_levels: int = 20) -> pd.DataFrame:
    """
    주문 초기화 - 그리드 레벨별 주문 컬럼 생성

    Args:
        df: OHLCV 데이터프레임
        n_levels: 그리드 레벨 수 (기본값: 20)

    Returns:
        주문 컬럼이 추가된 데이터프레임
    """
    # 주문 초기화
    data = {f'order_{n}': False for n in range(1, n_levels + 1)}
    data.update({f'order_{n}_quantity': 0.0 for n in range(1, n_levels + 1)})
    data.update({f'order_{n}_entry_price': 0.0 for n in range(1, n_levels + 1)})
    data.update({f'order_{n}_profit': 0.0 for n in range(1, n_levels + 1)})
    data['total_matched_orders'] = 0.0
    data['total_position'] = 0.0
    data['avg_entry_price'] = 0.0
    data['unrealized_profit'] = 0.0
    data['total_profit'] = 0.0  # 총 수익 열 초기화

    orders_df = pd.DataFrame(data, index=df.index)
    df = pd.concat([df, orders_df], axis=1).copy()  # 조각화 감소를 위해 copy 사용
    return df


def calculate_grid_levels(df: pd.DataFrame, band_mult: float = 0.5,
                         n_levels: int = 20, min_diff: float = 0.004) -> pd.DataFrame:
    """
    그리드 레벨 계산

    Args:
        df: OHLCV 데이터프레임
        band_mult: 밴드 배수 (기본값: 0.5)
        n_levels: 그리드 레벨 수 (기본값: 20)
        min_diff: 최소 차이 (기본값: 0.004)

    Returns:
        그리드 레벨 컬럼이 추가된 데이터프레임
    """
    # 그리드 레벨 계산
    grid_levels = {}
    main_plot = df['main_plot']
    atr = np.maximum(df['atr'], main_plot * min_diff)

    for n in range(0, n_levels + 1):
        atr_mult = atr * (11 - n) * 1.5
        multiplier = 1 - band_mult * 0.012 * (11 - n)
        grid_level_perc = (main_plot * multiplier).ewm(span=5, adjust=False).mean()
        grid_level_atr = (main_plot - atr_mult).ewm(span=5, adjust=False).mean()
        grid_level = (grid_level_perc + grid_level_atr) / 2

        diff = (main_plot - grid_level) / main_plot
        max_gap = min(0.05 * abs(11 - n), 0.5)

        # 이전 그리드 레벨과의 차이 확인
        if n > 1:
            prev_level = grid_levels[f'grid_level_{n-1}']
            diff = (grid_level - prev_level) / prev_level

            # 차이가 최대 간격(max_gap)을 초과하는 경우 조정
            mask = abs(diff) > max_gap
            grid_level[mask] = np.where(diff[mask] > 0,
                                        main_plot[mask] * (1 - max_gap),
                                        main_plot[mask] * (1 + max_gap))

            # 차이가 최소 차이(min_diff) 미만인 경우 조정
            mask = abs(diff) < min_diff
            grid_level[mask] = np.where(diff[mask] > 0, prev_level[mask] * (1 + min_diff), prev_level[mask] * (1 - min_diff))

        grid_levels[f'grid_level_{n}'] = round(grid_level, 8)

    grid_levels_df = pd.DataFrame(grid_levels)
    grid_level_adjusted = grid_levels_df.ewm(span=5, adjust=False).mean()
    # 데이터프레임 병합을 한 번에 수행
    new_df = pd.concat([df, grid_level_adjusted], axis=1)

    return new_df


def enter_position(df: pd.DataFrame, i: int, n: int, direction: str, initial_capital: float) -> None:
    """
    포지션 진입 및 청산 로직

    Args:
        df: 거래 데이터프레임
        i: 현재 인덱스
        n: 그리드 레벨
        direction: 거래 방향 ("long" 또는 "short")
        initial_capital: 초기 자본금
    """
    if direction == "long":
        entry_condition = df['low'].iloc[i] < df[f'grid_level_{n}'].iloc[i] and df['low'].iloc[i-1] > df[f'grid_level_{n}'].iloc[i-1]
        exit_condition = df['high'].iloc[i] > df[f'grid_level_{n+2}'].iloc[i]
        quantity_sign = 1
    else:
        entry_condition = df['high'].iloc[i] > df[f'grid_level_{n}'].iloc[i] and df['high'].iloc[i-1] < df[f'grid_level_{n}'].iloc[i-1]
        exit_condition = df['low'].iloc[i] < df[f'grid_level_{n-2}'].iloc[i]
        quantity_sign = -1

    if entry_condition:
        df.at[df.index[i], f'order_{n}'] = True
        df.at[df.index[i], f'order_{n}_entry_price'] = df[f'grid_level_{n}'].iloc[i]
        if df.at[df.index[i], f'order_{n}_entry_price'] != 0:
            df.at[df.index[i], f'order_{n}_quantity'] = quantity_sign * float((initial_capital / 20) / df.at[df.index[i], f'order_{n}_entry_price'])
    elif exit_condition:
        df.at[df.index[i], f'order_{n}'] = False
        profit = df.at[df.index[i-1], f'order_{n}_quantity'] * (df[f'grid_level_{n+2}'].iloc[i] - df.at[df.index[i-1], f'order_{n}_entry_price'])
        df.at[df.index[i], f'order_{n}_profit'] += profit
        df.at[df.index[i], f'order_{n}_quantity'] = 0
        df.at[df.index[i], f'order_{n}_entry_price'] = 0


def execute_trading_logic(df: pd.DataFrame, initial_capital: float, direction: str) -> pd.DataFrame:
    """
    거래 로직 실행

    Args:
        df: OHLCV 데이터프레임
        initial_capital: 초기 자본금
        direction: 거래 방향 ("long", "short", "long-short")

    Returns:
        거래 결과가 포함된 데이터프레임
    """
    df = df.reset_index(drop=True)
    temp_df = df.copy()  # 임시 데이터프레임 생성
    unrealized_profit = 0.0  # 미실현 수익 변수 초기화
    total_position = 0.0  # 총 포지션 변수 초기화
    total_matched_orders = 0  # 총 매칭된 주문 변수 초기화
    total_quantity = 0.0  # 총 수량 변수 초기화
    total_profit = 0.0  # 누적 수익 변수 초기화
    avg_entry_price = 0.0  # 평균 진입 가격 변수 초기화
    total_weighted_price = 0.0  # 가중 평균 가격 변수 초기화

    for i in range(1, len(df)):
        exceeds_top_grid = df['high'].iloc[i] > df['grid_level_20'].iloc[i]
        exceeds_bottom_grid = df['low'].iloc[i] < df['grid_level_1'].iloc[i]
        adx_state = df['adx_state_4h'].iloc[i]
        last_adx_state = df['adx_state_4h'].iloc[i-1]

        #================================================================================================
        # 롱 포지션 거래 로직
        #================================================================================================
        if direction == 'long':
            for n in range(1, 21):
                current_zone = df[f'grid_level_{n}'].iloc[i]
                last_current_zone = df[f'grid_level_{n}'].iloc[i-1]

                if n <= 18:
                    if adx_state < 2:
                        exit_zone = df[f'grid_level_{n+2}'].iloc[i] if f'grid_level_{n+2}' in df.columns else current_zone*1.005
                    if adx_state >= 2 and n < 18:
                        exit_zone = df[f'grid_level_{n+3}'].iloc[i] if f'grid_level_{n+3}' in df.columns else current_zone*1.005
                    elif adx_state >= 2 and n >= 18:
                        exit_zone = df[f'grid_level_{n}'].iloc[i]*1.01 if f'grid_level_{n}' in df.columns else current_zone*1.005
                elif n >= 19:
                    if adx_state < 2:
                        exit_zone = df[f'grid_level_{n}'].iloc[i]*1.005 if f'grid_level_{n}' in df.columns else current_zone*1.005
                    elif adx_state >= 2:
                        exit_zone = df[f'grid_level_{n}'].iloc[i]*1.01 if f'grid_level_{n}' in df.columns else current_zone*1.005

                if exceeds_top_grid:
                    if temp_df.at[df.index[i-1], f'order_{n}']:
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['high'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0

                try:
                    value = temp_df.at[df.index[i-1], f'order_{n}']
                    if isinstance(value, pd.Series):
                        print(f"Value at index {df.index[i-1]} and column 'order_{n}': {value}")
                        print(f"Type of the value: {type(value)}")

                    if not temp_df.at[df.index[i-1], f'order_{n}'] and adx_state >= -1:
                        if df['low'].iloc[i] < current_zone and df['low'].iloc[i-1] > last_current_zone:
                            temp_df.at[df.index[i], f'order_{n}'] = True
                            temp_df.at[df.index[i], f'order_{n}_entry_price'] = current_zone
                            if temp_df.at[df.index[i], f'order_{n}_entry_price'] != 0:
                                temp_df.at[df.index[i], f'order_{n}_quantity'] = float((initial_capital / 20) / temp_df.at[df.index[i], f'order_{n}_entry_price'])
                    elif temp_df.at[df.index[i-1], f'order_{n}'] and adx_state < -1:
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['close'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1
                    elif temp_df.at[df.index[i-1], f'order_{n}'] and df['high'].iloc[i] > exit_zone:
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['high'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1
                    else:
                        temp_df.at[df.index[i], f'order_{n}'] = temp_df.at[df.index[i-1], f'order_{n}']
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = temp_df.at[df.index[i-1], f'order_{n}_quantity']
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = temp_df.at[df.index[i-1], f'order_{n}_entry_price']

                    if temp_df.at[df.index[i], f'order_{n}']:
                        quantity = temp_df.at[df.index[i], f'order_{n}_quantity']
                        entry_price = temp_df.at[df.index[i], f'order_{n}_entry_price']
                        total_quantity += quantity
                        total_weighted_price += quantity * entry_price
                        total_position += quantity * df['close'].iloc[i]
                except Exception as e:
                    print(e)
                    print('Error in long position logic')
                    traceback.print_exc()

                if total_quantity > 0:
                    avg_entry_price = total_weighted_price / total_quantity
                else:
                    avg_entry_price = 0
                unrealized_profit = total_position - (total_quantity * avg_entry_price)
                temp_df.at[df.index[i], 'avg_entry_price'] = avg_entry_price
                temp_df.at[df.index[i], 'unrealized_profit'] = unrealized_profit
                temp_df.at[df.index[i], 'total_position'] = total_position
                total_profit += temp_df.at[df.index[i], f'order_{n}_profit']
                temp_df.at[df.index[i], 'total_profit'] = (float(total_profit)/10)

        #================================================================================================
        # 숏 포지션 거래 로직
        #================================================================================================
        elif direction == 'short':
            for n in range(1, 21):
                current_zone = df[f'grid_level_{n}'].iloc[i]
                last_current_zone = df[f'grid_level_{n}'].iloc[i-1]

                if n >= 3:
                    if adx_state > -2:
                        exit_zone = df[f'grid_level_{n-2}'].iloc[i] if f'grid_level_{n-2}' in df.columns else current_zone * 0.993
                    if adx_state <= -2 and n > 3:
                        exit_zone = df[f'grid_level_{n-3}'].iloc[i] if f'grid_level_{n-3}' in df.columns else current_zone * 0.993
                    else:
                        exit_zone = df[f'grid_level_{n}'].iloc[i]*0.993 if f'grid_level_{n}' in df.columns else current_zone * 0.993
                elif n <= 2:
                    exit_zone = df[f'grid_level_{n}'].iloc[i]*0.993 if f'grid_level_{n-1}' in df.columns else current_zone * 0.993

                if exceeds_bottom_grid:
                    if temp_df.at[df.index[i-1], f'order_{n}']:
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['low'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1
                elif not temp_df.at[df.index[i-1], f'order_{n}'] and adx_state <= 1:
                    if df['high'].iloc[i] > current_zone and df['high'].iloc[i-1] < last_current_zone:
                        temp_df.at[df.index[i], f'order_{n}'] = True
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = current_zone
                        if temp_df.at[df.index[i], f'order_{n}_entry_price'] != 0:
                            temp_df.at[df.index[i], f'order_{n}_quantity'] = -1 * float((initial_capital / 20) / temp_df.at[df.index[i], f'order_{n}_entry_price'])
                elif temp_df.at[df.index[i-1], f'order_{n}'] and adx_state > 1:
                    temp_df.at[df.index[i], f'order_{n}'] = False
                    temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['close'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                    temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                    temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                    temp_df.at[df.index[i], 'total_matched_orders'] += 1
                elif temp_df.at[df.index[i-1], f'order_{n}'] and df['low'].iloc[i] < exit_zone:
                    temp_df.at[df.index[i], f'order_{n}'] = False
                    temp_df.at[df.index[i], f'order_{n}_profit'] = float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * df['low'].iloc[i]) - float(temp_df.at[df.index[i-1], f'order_{n}_quantity'] * temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                    temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                    temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                    temp_df.at[df.index[i], 'total_matched_orders'] += 1
                else:
                    temp_df.at[df.index[i], f'order_{n}'] = temp_df.at[df.index[i-1], f'order_{n}']
                    temp_df.at[df.index[i], f'order_{n}_quantity'] = temp_df.at[df.index[i-1], f'order_{n}_quantity']
                    temp_df.at[df.index[i], f'order_{n}_entry_price'] = temp_df.at[df.index[i-1], f'order_{n}_entry_price']

                if temp_df.at[df.index[i], f'order_{n}']:
                    quantity = temp_df.at[df.index[i], f'order_{n}_quantity']
                    entry_price = temp_df.at[df.index[i], f'order_{n}_entry_price']
                    total_quantity += quantity
                    total_weighted_price += quantity * entry_price
                    total_position += quantity * df['close'].iloc[i]

                unrealized_profit = total_position - (total_quantity * avg_entry_price)
                temp_df.at[df.index[i], 'avg_entry_price'] = avg_entry_price
                temp_df.at[df.index[i], 'unrealized_profit'] = unrealized_profit

                if total_quantity < 0:
                    avg_entry_price = total_weighted_price / total_quantity
                else:
                    avg_entry_price = 0

                total_profit += temp_df.at[df.index[i], f'order_{n}_profit']
                total_position = temp_df.at[df.index[i], f'order_{n}_quantity'] * df['close'].iloc[i]
                temp_df.at[df.index[i], 'total_profit'] = (float(total_profit)/10)
                temp_df.at[df.index[i], 'total_position'] = total_position

        #================================================================================================
        # 양방향 포지션 거래 로직
        # TODO : 양방향 포지션 거래 로직이 제대로 작동하는지 확인 필요. 반드시.
        #================================================================================================
        else:  # direction == 'long-short'
            for n in range(1, 21):
                current_zone = df[f'grid_level_{n}'].iloc[i]
                last_current_zone = df[f'grid_level_{n}'].iloc[i-1]

                if n == 20:
                    if adx_state == 2:
                        short_exit_zone = df['grid_level_18'].iloc[i] if 'grid_level_18' in df.columns else current_zone * 0.993
                        long_exit_zone = df['grid_level_20'].iloc[i] * 1.007 if 'grid_level_20' in df.columns else current_zone * 1.007
                    elif adx_state == -2:
                        short_exit_zone = df['grid_level_17'].iloc[i] if 'grid_level_17' in df.columns else current_zone * 0.993
                        long_exit_zone = df['grid_level_20'].iloc[i] * 1.007 if 'grid_level_20' in df.columns else current_zone * 1.007
                    else:
                        short_exit_zone = df['grid_level_17'].iloc[i] if 'grid_level_17' in df.columns else current_zone * 0.993
                        long_exit_zone = df['grid_level_20'].iloc[i] * 1.007 if 'grid_level_20' in df.columns else current_zone * 1.007
                elif n == 2:
                    if adx_state == 2:
                        long_exit_zone = df['grid_level_4'].iloc[i] if 'grid_level_4' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i] if 'grid_level_1' in df.columns else current_zone * 0.993
                    elif adx_state == -2:
                        long_exit_zone = df['grid_level_3'].iloc[i] if 'grid_level_3' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i]*0.995 if 'grid_level_1' in df.columns else current_zone * 0.993
                    else:
                        long_exit_zone = df['grid_level_3'].iloc[i] if 'grid_level_3' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i] if 'grid_level_1' in df.columns else current_zone * 0.993
                elif n == 1:
                    if adx_state == 2:
                        long_exit_zone = df['grid_level_4'].iloc[i] if 'grid_level_3' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i] * 0.993 if 'grid_level_1' in df.columns else current_zone*0.993
                    elif adx_state == -2:
                        long_exit_zone = df['grid_level_3'].iloc[i] if 'grid_level_3' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i] * 0.993 if 'grid_level_1' in df.columns else current_zone * 0.993
                    else:
                        long_exit_zone = df['grid_level_3'].iloc[i] if 'grid_level_3' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_1'].iloc[i] if 'grid_level_1' in df.columns else current_zone * 0.993
                elif n == 19:
                    if adx_state == 2:
                        long_exit_zone = df['grid_level_20'].iloc[i] if 'grid_level_20' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_17'].iloc[i] if 'grid_level_17' in df.columns else current_zone * 0.993
                    elif adx_state == -2:
                        long_exit_zone = df['grid_level_20'].iloc[i] if 'grid_level_20' in df.columns else current_zone * 1.014
                        short_exit_zone = df['grid_level_16'].iloc[i] if 'grid_level_16' in df.columns else current_zone * 0.986
                    else:
                        long_exit_zone = df['grid_level_20'].iloc[i] if 'grid_level_20' in df.columns else current_zone * 1.007
                        short_exit_zone = df['grid_level_17'].iloc[i] if 'grid_level_17' in df.columns else current_zone * 0.993
                else:
                    if adx_state >= 2:
                        long_exit_zone = df[f'grid_level_{n+3}'].iloc[i] if f'grid_level_{n+3}' in df.columns else current_zone * 1.007
                        short_exit_zone = df[f'grid_level_{n-2}'].iloc[i] if f'grid_level_{n-2}' in df.columns else current_zone * 0.993
                    elif adx_state <= -2:
                        long_exit_zone = df[f'grid_level_{n+2}'].iloc[i] if f'grid_level_{n+2}' in df.columns else current_zone * 1.007
                        short_exit_zone = df[f'grid_level_{n-3}'].iloc[i] if f'grid_level_{n-3}' in df.columns else current_zone * 0.993
                    else:
                        long_exit_zone = df[f'grid_level_{n+2}'].iloc[i] if f'grid_level_{n+2}' in df.columns else current_zone * 1.007
                        short_exit_zone = df[f'grid_level_{n-2}'].iloc[i] if f'grid_level_{n-2}' in df.columns else current_zone * 0.993

                # 롱 포지션 진입
                if df['low'].iloc[i] < current_zone and adx_state >= -1 and df['low'].iloc[i-1] > last_current_zone:
                    if not (temp_df.at[df.index[i-1], f'order_{n}']):  # 포지션이 없었을 때
                        temp_df.at[df.index[i], f'order_{n}'] = True
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = current_zone
                        if temp_df.at[df.index[i], f'order_{n}_entry_price'] != 0:
                            temp_df.at[df.index[i], f'order_{n}_quantity'] = float((initial_capital / 20) / temp_df.at[df.index[i], f'order_{n}_entry_price'])
                    if (temp_df.at[df.index[i-1], f'order_{n}'] and temp_df.at[df.index[i-1], f'order_{n}_quantity'] < 0):
                        profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (temp_df.at[df.index[i-1], f'order_{n}_entry_price'] - df['low'].iloc[i])
                        temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1

                # 롱 포지션 청산 또는 익절
                if temp_df.at[df.index[i-1], f'order_{n}_quantity'] > 0:  # 롱 포지션이 있을 때
                    if long_exit_zone is not None and temp_df.at[df.index[i-1], f'order_{n}'] and df['high'].iloc[i] > long_exit_zone:  # 익절 조건
                        profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (df['high'].iloc[i] - temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1
                    if adx_state == -2 and last_adx_state >= -1 and temp_df.at[df.index[i-1], f'order_{n}']:  # 롱 포지션 종료 조건
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (df['close'].iloc[i] - temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                        temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1

                if (not (temp_df.at[df.index[i-1], f'order_{n}'] and adx_state <= 1) or (temp_df.at[df.index[i-1], f'order_{n}'] and temp_df.at[df.index[i-1], f'order_{n}_quantity'] > 0)):
                    if df['high'].iloc[i] > current_zone and df['high'].iloc[i-1] < last_current_zone:
                        if (not temp_df.at[df.index[i-1], f'order_{n}']):  # 롱포지션이 없을 때
                            temp_df.at[df.index[i], f'order_{n}'] = True
                            temp_df.at[df.index[i], f'order_{n}_entry_price'] = current_zone
                            if temp_df.at[df.index[i], f'order_{n}_entry_price'] != 0:
                                temp_df.at[df.index[i], f'order_{n}_quantity'] = -1 * float((initial_capital / 20) / temp_df.at[df.index[i], f'order_{n}_entry_price'])
                        if (temp_df.at[df.index[i-1], f'order_{n}'] and temp_df.at[df.index[i-1], f'order_{n}_quantity'] > 0):  # 롱포지션이 있을 때
                            temp_df.at[df.index[i], f'order_{n}'] = False  # 롱포지션 청산
                            profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (df['high'].iloc[i] - temp_df.at[df.index[i-1], f'order_{n}_entry_price'])
                            temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                            temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                            temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                            temp_df.at[df.index[i], 'total_matched_orders'] += 1

                # 숏 포지션 청산
                elif temp_df.at[df.index[i-1], f'order_{n}']:  # 숏 포지션이 있을 때
                    if adx_state == 2 and last_adx_state <= 1 and temp_df.at[df.index[i-1], f'order_{n}_quantity'] < 0:  # ADX가 2일 때 숏 포지션 종료 조건
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (temp_df.at[df.index[i-1], f'order_{n}_entry_price'] - df['close'].iloc[i])
                        temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                    elif exceeds_bottom_grid:
                        temp_df.at[df.index[i], f'order_{n}'] = False
                        profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (temp_df.at[df.index[i-1], f'order_{n}_entry_price'] - df['low'].iloc[i])
                        temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                        temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                        temp_df.at[df.index[i], 'total_matched_orders'] += 1
                        temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                    elif short_exit_zone is not None:  # 숏 포지션이 있고, 청산 지점이 설정된 경우
                        if df['low'].iloc[i] < short_exit_zone:  # 청산 조건
                            temp_df.at[df.index[i], f'order_{n}'] = False
                            profit = temp_df.at[df.index[i-1], f'order_{n}_quantity'] * (temp_df.at[df.index[i-1], f'order_{n}_entry_price'] - df['low'].iloc[i])
                            temp_df.at[df.index[i], f'order_{n}_profit'] += profit
                            temp_df.at[df.index[i], f'order_{n}_entry_price'] = 0
                            temp_df.at[df.index[i], f'order_{n}_quantity'] = 0
                            temp_df.at[df.index[i], 'total_matched_orders'] += 1

                # 포지션 유지
                else:
                    temp_df.at[df.index[i], f'order_{n}'] = temp_df.at[df.index[i-1], f'order_{n}']
                    temp_df.at[df.index[i], f'order_{n}_quantity'] = temp_df.at[df.index[i-1], f'order_{n}_quantity']
                    temp_df.at[df.index[i], f'order_{n}_entry_price'] = temp_df.at[df.index[i-1], f'order_{n}_entry_price']

                # entry_정보
                if temp_df.at[df.index[i], f'order_{n}']:
                    quantity = temp_df.at[df.index[i], f'order_{n}_quantity']
                    entry_price = temp_df.at[df.index[i], f'order_{n}_entry_price']
                    total_quantity += quantity
                    total_weighted_price += quantity * entry_price
                    total_position += quantity * df['close'].iloc[i]

                # 총 수익 계산
                if abs(total_quantity) > 0:
                    avg_entry_price = total_weighted_price / total_quantity
                else:
                    avg_entry_price = 0
                total_profit += temp_df.at[df.index[i], f'order_{n}_profit']
                total_position = temp_df.at[df.index[i], f'order_{n}_quantity'] * df['close'].iloc[i]
                temp_df.at[df.index[i], 'total_profit'] = (float(total_profit)/10)
                temp_df.at[df.index[i], 'total_position'] = total_position

    print(f"{direction} total_profit : {total_profit}")
    df = temp_df
    return df

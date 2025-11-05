"""
OHLCV calculation and analysis
"""
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from GRID.analysis.grid_logic import calculate_grid_levels, execute_trading_logic
from GRID.data import save_grid_results_to_redis

# Import from GRID modules
from GRID.indicators import (
    IndicatorState,
    atr_incremental,
    calculate_adx_incremental,
    compute_mama_fama_incremental,
    get_indicator_state,
    map_4h_adx_to_15m,
    save_indicator_state,
    update_adx_state,
)
from shared.indicators import calculate_adx


def is_data_valid(df: pd.DataFrame) -> bool:
    """
    데이터 유효성 검증

    Args:
        df: 검증할 데이터프레임

    Returns:
        데이터가 유효하면 True, 아니면 False
    """
    if df.empty:
        return False
    if 'timestamp' not in df.columns:
        return False
    if df['timestamp'].isna().any():
        return False
    if not df['timestamp'].is_monotonic_increasing:
        return False
    # 추가적인 유효성 검사 (예: 가격 데이터가 모두 양수인지 등)
    return True


async def refetch_data(exchange_instance: Any, exchange_name: str, symbol: str, user_id: int) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
    """
    데이터 재fetching - 전체 데이터를 강제로 다시 가져옴

    Args:
        exchange_instance: 거래소 인스턴스
        exchange_name: 거래소 이름
        symbol: 심볼
        user_id: 사용자 ID

    Returns:
        OHLCV 데이터 튜플 (15분, 4시간)
    """
    from GRID.data import fetching_data
    return await fetching_data(
        exchange_instance=exchange_instance,
        exchange_name=exchange_name,
        symbol=symbol,
        user_id=user_id,
        force_refetch=True
    )


async def calculate_ohlcv(exchange_name: str, symbol: str, ohlcv_data: pd.DataFrame,
                         ohlcv_data_4h: pd.DataFrame) -> Tuple[Optional[pd.DataFrame], Optional[Dict]]:
    """
    OHLCV 데이터를 증분형으로 계산합니다.

    Args:
        exchange_name: 거래소 이름
        symbol: 심볼
        ohlcv_data: 15분 OHLCV 데이터
        ohlcv_data_4h: 4시간 OHLCV 데이터

    Returns:
        (계산된 데이터프레임, 방향별 결과 딕셔너리)
    """
    try:
        if ohlcv_data is None:
            logging.warning(f"15분 OHLCV 데이터가 없습니다: {exchange_name}:{symbol}")
            return None, None

        if ohlcv_data_4h is None:
            logging.warning(f"4시간 OHLCV 데이터가 없습니다: {exchange_name}:{symbol}")
            # 4시간 데이터가 없어도 15분 데이터는 처리 가능하도록 설정
            ohlcv_data_4h = pd.DataFrame()

        # 원본 데이터를 사용하여 메모리 효율화
        df = ohlcv_data

        # 타임스탬프 처리 - 모든 타임스탬프를 UTC 기준으로 타임존 정보 없이 통일
        if 'timestamp' in df.columns and df['timestamp'].dt.tz is not None:
            df['timestamp'] = df['timestamp'].dt.tz_localize(None)

        # 방향에 따라 다른 계산 상태 관리
        directions = ['long', 'short', 'long-short']

        # 거래소가 스팟인 경우 long 방향만 계산
        is_spot_exchange = exchange_name in ['bitget_spot', 'okx_spot', 'binance_spot', 'upbit', 'bybit_spot']
        if is_spot_exchange:
            directions = ['long']

        results_by_direction = {}

        # 각 방향에 대해 계산
        for direction in directions:
            try:
                # 이전 계산 상태 가져오기
                state = await get_indicator_state(exchange_name, symbol, direction)

                # 타임스탬프 기준으로 새 데이터 확인
                latest_timestamp = df['timestamp'].iloc[-1]

                # 상태에 마지막 업데이트 시간이 있고, 그 시간이 현재 데이터의 마지막 시간과 동일하면 재계산 불필요
                if (state.last_update_time is not None and
                    pd.to_datetime(state.last_update_time) >= latest_timestamp):
                    logging.info(f"이미 최신 데이터까지 계산되어 있음: {exchange_name}:{symbol}:{direction}")
                    continue

                # 필요한 경우에만 4시간 데이터 처리
                have_4h_data = not ohlcv_data_4h.empty
                if have_4h_data:
                    df_4h = ohlcv_data_4h

                    if 'timestamp' in df_4h.columns and df_4h['timestamp'].dt.tz is not None:
                        df_4h['timestamp'] = df_4h['timestamp'].dt.tz_localize(None)

                    # ADX 상태 계산 (4시간 데이터 기반)
                    if state.adx is None or len(state.adx) == 0:
                        # 전체 데이터를 사용하여 초기 계산
                        df_4h = calculate_adx(df_4h, 28, 28)
                        df_4h = update_adx_state(df_4h)
                        df = map_4h_adx_to_15m(df_4h, df)
                    else:
                        # 증분 계산: 필요한 데이터만 계산
                        adx, plus_di, minus_di = calculate_adx_incremental(df_4h, state, 28, 28)

                        # 데이터프레임에 결과 할당
                        df_4h['adx'] = adx
                        df_4h['plus_di'] = plus_di
                        df_4h['minus_di'] = minus_di

                        # ADX 상태 업데이트
                        df_4h = update_adx_state(df_4h)
                        df = map_4h_adx_to_15m(df_4h, df)

                # 데이터 크기 최적화 - 필요한 과거 데이터만 유지
                required_lookback = 200  # 지표 계산에 필요한 충분한 과거 데이터

                if len(df) > required_lookback:
                    working_df = df.iloc[-required_lookback:].copy()
                else:
                    working_df = df.copy()

                # 증분형 지표 계산
                with ThreadPoolExecutor(max_workers=3) as executor:
                    # 병렬 계산을 위한 작업 생성
                    futures = []

                    # ADX 계산 (필요한 경우)
                    if not have_4h_data:
                        futures.append(executor.submit(
                            calculate_adx_incremental, working_df, state, 28, 28))

                    # MAMA/FAMA 계산
                    futures.append(executor.submit(
                        compute_mama_fama_incremental, working_df['close'].values, state))  # type: ignore[arg-type]

                    # ATR 계산
                    futures.append(executor.submit(
                        atr_incremental, working_df, state, 14))  # type: ignore[arg-type]

                    # 결과 수집
                    results = [future.result() for future in futures]

                    # 결과 할당
                    result_index = 0

                    if not have_4h_data:
                        adx, plus_di, minus_di = results[result_index]
                        working_df['adx'] = adx
                        working_df['plus_di'] = plus_di
                        working_df['minus_di'] = minus_di
                        result_index += 1

                    mama, fama = results[result_index]  # type: ignore[misc]
                    working_df['mama'] = mama
                    working_df['fama'] = fama
                    working_df['main_plot'] = fama
                    result_index += 1

                    working_df['atr'] = results[result_index]

                # 나머지 지표 계산
                if not have_4h_data:
                    working_df = update_adx_state(working_df)

                # 격자 레벨 계산
                working_df = calculate_grid_levels(working_df)

                # 거래 로직 실행
                result_df = execute_trading_logic(working_df.copy(), 100, direction)
                results_by_direction[direction] = result_df

                # 결과 저장
                await save_grid_results_to_redis(result_df, exchange_name, symbol, f"{direction}")

                # 지표 상태 업데이트
                state.adx_last_idx = len(working_df) - 1
                state.adx = working_df['adx'].values if 'adx' in working_df.columns else None
                state.plus_di = working_df['plus_di'].values if 'plus_di' in working_df.columns else None
                state.minus_di = working_df['minus_di'].values if 'minus_di' in working_df.columns else None

                state.mama_last_idx = len(working_df) - 1
                state.mama_values = working_df['mama'].values if 'mama' in working_df.columns else None
                state.fama_values = working_df['fama'].values if 'fama' in working_df.columns else None

                state.atr_last_idx = len(working_df) - 1
                state.atr_values = working_df['atr'].values if 'atr' in working_df.columns else None
                state.prev_atr = working_df['atr'].iloc[-1] if 'atr' in working_df.columns else None

                state.last_update_time = latest_timestamp.isoformat()

                # 상태 저장
                await save_indicator_state(state, exchange_name, symbol, direction)

            except Exception as e:
                logging.error(f"거래 로직 실행 중 오류 발생: {exchange_name}:{symbol}:{direction}: {e}")
                logging.debug(traceback.format_exc())

        return df, results_by_direction

    except Exception as e:
        error_message = str(e)
        if "None of" in error_message:
            logging.error(f"{symbol} 분석 중 오류 발생: {e}. 분석을 종료합니다.")
        else:
            logging.error(f"{symbol} 분석 중 오류 발생: {e}")
            logging.debug(traceback.format_exc())
        return None, None


async def summarize_trading_results(exchange_name: str, direction: str) -> list:
    """
    거래 결과를 요약합니다. Redis에서 데이터를 가져와 처리합니다.

    Args:
        exchange_name: 거래소 이름
        direction: 거래 방향

    Returns:
        거래 결과 요약 리스트
    """
    try:
        from GRID.data import get_cache, set_cache
        from shared.database.redis import get_redis
        from shared.database.redis_patterns import scan_keys_pattern

        # Use shared async connection pool
        redis_client = await get_redis()

        # Redis에서 해당 거래소와 방향의 모든 심볼 키 가져오기
        pattern = f"{exchange_name}:*:{direction}"
        # Use SCAN instead of KEYS to avoid blocking Redis
        all_keys = await scan_keys_pattern(pattern, redis=redis_client)

        results = []

        for key in all_keys:
            try:
                # 키에서 심볼 추출
                parts = key.decode('utf-8').split(':')
                if len(parts) < 2:
                    continue
                symbol = parts[1]

                # Redis에서 데이터 가져오기
                df = await get_cache(exchange_name, symbol, direction)

                if df is None or df.empty or 'total_profit' not in df.columns:
                    continue

                # 마지막 총 수익 계산
                last_total_profit = df['total_profit'].iloc[-1]

                # 이상치 처리
                if last_total_profit >= 2000:
                    last_total_profit /= 100
                elif last_total_profit <= -2000:
                    last_total_profit /= 100
                elif last_total_profit >= 900:
                    last_total_profit /= 10
                elif last_total_profit <= -100:
                    last_total_profit /= 100

                # 추가 정보 수집
                total_trades = df['order_count'].iloc[-1] if 'order_count' in df.columns else 0
                win_rate = df['win_rate'].iloc[-1] if 'win_rate' in df.columns else 0
                drawdown = df['max_drawdown'].iloc[-1] if 'max_drawdown' in df.columns else 0

                # 결과 추가
                results.append({
                    'symbol': symbol,
                    'total_profit': last_total_profit,
                    'total_trades': total_trades,
                    'win_rate': win_rate,
                    'drawdown': drawdown
                })

            except Exception as e:
                key_str = key.decode() if isinstance(key, bytes) else key
                logging.error(f"심볼 처리 중 오류 발생: {key_str} - {str(e)}")
                continue

        # 결과를 DataFrame으로 변환
        if not results:
            logging.warning(f"{exchange_name}의 {direction} 방향 거래 결과가 없습니다.")
            return []

        summary_df = pd.DataFrame(results)

        # 수익 기준으로 정렬
        summary_df = summary_df.sort_values('total_profit', ascending=False)

        # Redis에 요약 결과 저장
        await set_cache(exchange_name, "summary", summary_df, direction)

        logging.info(f"{exchange_name}의 {direction} 방향 거래 전략 요약이 완료되었습니다.")

        # 결과 반환
        return summary_df.to_dict('records')  # type: ignore[no-any-return]

    except Exception as e:
        logging.error(f"거래 결과 요약 중 오류 발생: {str(e)}")
        traceback.print_exc()
        return []

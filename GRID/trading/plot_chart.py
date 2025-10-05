import asyncio
from shared.utils import path_helper
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
import pickle
import redis
import logging
from shared.config import settings

# Redis 연결 설정
redis_client = redis.Redis(host=settings.REDIS_HOST, port=settings.REDIS_PORT, db=settings.REDIS_DB,
                          password=settings.REDIS_PASSWORD if settings.REDIS_PASSWORD else None, decode_responses=False)

async def read_csv_and_plot(exchange_name: str, coin_name: str, direction : str):
    if exchange_name == 'bitget':
        coin_name = coin_name.replace("/", "")
    try:
        # Redis에서 데이터 가져오기
        redis_key = f"{exchange_name}:{coin_name}:{direction}"
        serialized_data = redis_client.get(redis_key)
        
        if serialized_data is None:
            logging.error(f"Redis에서 데이터를 찾을 수 없습니다: {redis_key}")
            raise FileNotFoundError(f"Redis에서 데이터를 찾을 수 없습니다: {redis_key}")
            
        # 직렬화된 데이터 복원
        trading_data = pickle.loads(serialized_data)
        print(trading_data.tail(1))
        await plot_trading_signals(trading_data, coin_name)

    except Exception as e:
        print(f"데이터를 읽는 중 오류 발생: {e}")
        raise e


async def plot_trading_signals(df, coin_name):
    # 롱 진입 신호를 찾기
    df.columns = [col.lower() for col in df.columns]
    long_entry_signals = (df[[f'order_{n}' for n in range(1, 21)]] == True) & (df[[f'order_{n}' for n in range(1, 21)]].shift(1) == False)

    # 롱 종료 신호를 찾기
    long_exit_signals = (df[[f'order_{n}' for n in range(1, 21)]] == False) & (df[[f'order_{n}' for n in range(1, 21)]].shift(1) == True)

    # 캔들스틱 차트 생성
    fig = go.Figure(data=[go.Candlestick(x=df['timestamp'],
                                         open=df['open'],
                                         high=df['high'],
                                         low=df['low'],
                                         close=df['close'], name='OHLC')])
     #배경 추가 로직
    start = df['timestamp'].iloc[0]
    for i, row in df.iterrows():
        if i > 0:  # 첫 번째 행을 제외한 모든 행에 대해 실행
            if row['adx_state_4h'] == 2 and df.iloc[i - 1]['adx_state_4h'] != 2:
                # adx_state_4h가 2로 시작하는 지점 찾기
                start = row['timestamp']
            elif row['adx_state_4h'] != 2 and df.iloc[i - 1]['adx_state_4h'] == 2:
                # adx_state_4h가 2에서 다른 값으로 바뀌는 지점 찾기
                end = row['timestamp']
                fig.add_vrect(x0=start, x1=end, fillcolor="green", opacity=0.2, line_width=0)

            
            if row['adx_state_4h'] == -2 and df.iloc[i - 1]['adx_state_4h'] != -2:
                start = row['timestamp']
            elif row['adx_state_4h'] != -2 and df.iloc[i - 1]['adx_state_4h'] == -2:
                end = row['timestamp']
                fig.add_vrect(x0=start, x1=end, fillcolor="red", opacity=0.2, line_width=0)



    for n in range(1, 21):
        entry_x = df['timestamp'][long_entry_signals[f'order_{n}']]
        exit_x = df['timestamp'][long_exit_signals[f'order_{n}']]
        # 진입 시의 y값을 'low'로 설정
        entry_y = df['low'][long_entry_signals[f'order_{n}']]
        if n <= 18:
            exit_y = df['high'][long_exit_signals[f'order_{n}']]
        else:
            exit_y = None  # n이 19 또는 20인 경우, exit_y에 None 할당
        
        # 롱 진입 신호 추가
        fig.add_trace(go.Scatter(x=entry_x, y=entry_y,
                                 mode='markers', name=f'Long Entry {n}',
                                 marker=dict(color='green', size=8, symbol='triangle-up')))
        
        # 롱 종료 신호 추가 (종료 신호가 유효한 경우에만 추가)
        if exit_y is not None:
            fig.add_trace(go.Scatter(x=exit_x, y=exit_y,
                                     mode='markers', name=f'Long Exit {n}',
                                     marker=dict(color='red', size=8, symbol='triangle-down')))

    # grid_levels 추가
    for n in range(1, 21):
        fig.add_trace(go.Scatter(x=df['timestamp'], y=df[f'grid_level_{n}'], name=f'Grid Level {n}',
                                 line=dict(width=1, dash='dot')))
    fig.add_trace(go.Scatter(x=df['timestamp'], y=df['main_plot'], name='MAIN PLOT', line=dict(color='black')))

    # 차트 레이아웃 설정
    fig.update_layout(title=f'GRID Chart : {coin_name}', xaxis_title='Date', yaxis_title='Price', xaxis_rangeslider_visible=False, showlegend=False)

    # 차트 표시
    #await asyncio.to_thread(pio.write_image, fig, 'chart.png', width=1900, height=1080, scale=2)
    await asyncio.to_thread(pio.write_image, fig, f'{coin_name}_chart.png', width=1900, height=1080, scale=2)
    #fig.show()
    
"""
Visualization Utility Module

Handles chart plotting and visualization for grid trading.
Extracted from grid_original.py for better maintainability.
"""

import asyncio

import plotly.graph_objects as go
import plotly.io as pio


async def plot_trading_signals(df, coin_name):
    """
    Plot trading signals with grid levels and ADX states.

    Args:
        df: DataFrame with OHLC data, grid levels, and trading signals
        coin_name: Name of the coin for chart title

    Creates:
        PNG chart file saved as '{coin_name}_chart.png'
    """
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
    # 배경 추가 로직
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
    await asyncio.to_thread(pio.write_image, fig, f'{coin_name}_chart.png', width=1900, height=1080, scale=2)

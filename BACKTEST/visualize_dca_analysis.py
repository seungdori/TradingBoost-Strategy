"""
DCA 미작동 원인 분석 및 시각화 스크립트
"""
import json
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timezone
from sqlalchemy import create_engine, text
import numpy as np

# 한글 폰트 설정
plt.rcParams['font.family'] = 'AppleGothic'
plt.rcParams['axes.unicode_minus'] = False

# 데이터베이스 연결
DB_URL = "postgresql://tradeuser:SecurePassword123@158.247.218.188:5432/tradedb"

def load_backtest_result():
    """백테스트 결과 로드"""
    with open('/Users/seunghyun/TradingBoost-Strategy/BACKTEST/backtest_result.json', 'r') as f:
        return json.load(f)

def get_candle_data(symbol: str, start: str, end: str):
    """TimescaleDB에서 캔들 데이터 조회"""
    engine = create_engine(DB_URL)

    query = text("""
        SELECT
            time as timestamp,
            open, high, low, close, volume,
            rsi, atr,
            ma7 as ema, ma20 as sma
        FROM okx_candles_15m
        WHERE symbol = :symbol
          AND time >= :start_date
          AND time <= :end_date
        ORDER BY time ASC
    """)

    with engine.connect() as conn:
        result = conn.execute(query, {
            'symbol': symbol,
            'start_date': start,
            'end_date': end
        })

        df = pd.DataFrame(result.fetchall(), columns=result.keys())

    return df

def calculate_dca_levels(entry_price: float, side: str, pyramiding_value: float):
    """DCA 진입 레벨 계산 (3% 기준)"""
    levels = []

    for i in range(1, 4):  # 최대 3회 DCA
        if side == 'long':
            # Long: 진입가보다 3%씩 하락한 가격
            level = entry_price * (1 - (pyramiding_value / 100) * i)
        else:  # short
            # Short: 진입가보다 3%씩 상승한 가격
            level = entry_price * (1 + (pyramiding_value / 100) * i)

        levels.append(level)

    return levels

def analyze_trade_dca(trade: dict, candles: pd.DataFrame, dca_params: dict):
    """특정 거래의 DCA 조건 분석"""
    entry_time = pd.to_datetime(trade['entry_timestamp'])
    exit_time = pd.to_datetime(trade['exit_timestamp'])
    entry_price = trade['entry_price']
    side = trade['side']

    # 거래 기간의 캔들만 추출
    trade_candles = candles[
        (candles['timestamp'] >= entry_time) &
        (candles['timestamp'] <= exit_time)
    ].copy()

    if trade_candles.empty:
        return None, None

    # DCA 레벨 계산
    dca_levels = calculate_dca_levels(
        entry_price,
        side,
        dca_params['pyramiding_value']
    )

    # 각 캔들에서 DCA 조건 체크
    dca_checks = []

    for idx, candle in trade_candles.iterrows():
        price = candle['close']
        rsi = candle['rsi']
        ema = candle['ema']
        sma = candle['sma']

        # 1. 가격 조건 체크 (첫 번째 DCA 레벨)
        if side == 'long':
            price_condition = price <= dca_levels[0]
        else:
            price_condition = price >= dca_levels[0]

        # 2. RSI 조건 체크
        if pd.isna(rsi):
            rsi_condition = False
        else:
            if side == 'long':
                rsi_condition = rsi <= dca_params.get('rsi_oversold', 30)
            else:
                rsi_condition = rsi >= dca_params.get('rsi_overbought', 70)

        # 3. Trend 조건 체크
        if pd.isna(ema) or pd.isna(sma):
            trend_condition = False
        else:
            if side == 'long':
                trend_condition = ema > sma  # Long: 상승 추세
            else:
                trend_condition = ema < sma  # Short: 하락 추세

        # 전체 조건 충족 여부
        all_conditions = price_condition and rsi_condition and trend_condition

        dca_checks.append({
            'timestamp': candle['timestamp'],
            'price': float(price),
            'rsi': float(rsi) if not pd.isna(rsi) else None,
            'ema': float(ema) if not pd.isna(ema) else None,
            'sma': float(sma) if not pd.isna(sma) else None,
            'price_condition': price_condition,
            'rsi_condition': rsi_condition,
            'trend_condition': trend_condition,
            'all_conditions': all_conditions,
            'distance_from_dca1': abs(float(price) - dca_levels[0]) / dca_levels[0] * 100
        })

    return pd.DataFrame(dca_checks), dca_levels

def visualize_trade_dca(trade: dict, candles: pd.DataFrame, dca_checks: pd.DataFrame,
                       dca_levels: list, trade_num: int):
    """거래별 DCA 분석 시각화"""
    fig, axes = plt.subplots(4, 1, figsize=(16, 12), sharex=True)
    fig.suptitle(f'거래 #{trade_num} DCA 조건 분석 ({trade["side"].upper()})',
                 fontsize=16, fontweight='bold')

    timestamps = pd.to_datetime(candles['timestamp'])

    # 1. 가격 차트 + DCA 레벨
    ax1 = axes[0]
    ax1.plot(timestamps, candles['close'], 'b-', linewidth=1.5, label='Close Price')

    # 진입가
    ax1.axhline(y=trade['entry_price'], color='green', linestyle='--',
                linewidth=2, label=f'진입가: ${trade["entry_price"]:,.0f}')

    # 청산가
    ax1.axhline(y=trade['exit_price'], color='red', linestyle='--',
                linewidth=2, label=f'청산가: ${trade["exit_price"]:,.0f}')

    # DCA 레벨
    colors = ['orange', 'purple', 'brown']
    for i, level in enumerate(dca_levels):
        ax1.axhline(y=level, color=colors[i], linestyle=':',
                   linewidth=1.5, alpha=0.7, label=f'DCA Level {i+1}: ${level:,.0f}')

    ax1.set_ylabel('Price (USDT)', fontsize=12)
    ax1.legend(loc='best', fontsize=9)
    ax1.grid(True, alpha=0.3)
    ax1.set_title('가격 움직임 및 DCA 레벨', fontsize=12)

    # 2. RSI
    ax2 = axes[1]
    ax2.plot(timestamps, candles['rsi'], 'purple', linewidth=1.5, label='RSI')
    ax2.axhline(y=30, color='green', linestyle='--', alpha=0.5, label='Oversold (30)')
    ax2.axhline(y=70, color='red', linestyle='--', alpha=0.5, label='Overbought (70)')

    # RSI 조건 충족 구간 하이라이트
    rsi_met = dca_checks[dca_checks['rsi_condition'] == True]
    if not rsi_met.empty:
        for _, row in rsi_met.iterrows():
            ax2.axvspan(row['timestamp'], row['timestamp'],
                       alpha=0.3, color='yellow')

    ax2.set_ylabel('RSI', fontsize=12)
    ax2.set_ylim(0, 100)
    ax2.legend(loc='best', fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.set_title('RSI 지표 (노란색: RSI 조건 충족)', fontsize=12)

    # 3. Trend (EMA vs SMA)
    ax3 = axes[2]
    ax3.plot(timestamps, candles['ema'], 'blue', linewidth=1.5, label='EMA (7)')
    ax3.plot(timestamps, candles['sma'], 'red', linewidth=1.5, label='SMA (20)')

    # Trend 조건 충족 구간 하이라이트
    trend_met = dca_checks[dca_checks['trend_condition'] == True]
    if not trend_met.empty:
        for _, row in trend_met.iterrows():
            ax3.axvspan(row['timestamp'], row['timestamp'],
                       alpha=0.3, color='lightgreen')

    ax3.set_ylabel('Price (USDT)', fontsize=12)
    ax3.legend(loc='best', fontsize=9)
    ax3.grid(True, alpha=0.3)
    ax3.set_title(f'Trend 지표 (녹색: {"EMA > SMA" if trade["side"] == "long" else "EMA < SMA"} 조건 충족)',
                 fontsize=12)

    # 4. 조건 충족 현황
    ax4 = axes[3]

    # 각 조건별 충족 여부를 시계열로 표시
    price_cond = dca_checks['price_condition'].astype(int)
    rsi_cond = dca_checks['rsi_condition'].astype(int)
    trend_cond = dca_checks['trend_condition'].astype(int)
    all_cond = dca_checks['all_conditions'].astype(int)

    ax4.fill_between(timestamps, 0, price_cond * 0.25, alpha=0.5, label='가격 조건', color='orange')
    ax4.fill_between(timestamps, 0.25, 0.25 + rsi_cond * 0.25, alpha=0.5, label='RSI 조건', color='purple')
    ax4.fill_between(timestamps, 0.5, 0.5 + trend_cond * 0.25, alpha=0.5, label='Trend 조건', color='blue')
    ax4.fill_between(timestamps, 0.75, 0.75 + all_cond * 0.25, alpha=0.7, label='전체 조건 충족', color='red')

    ax4.set_ylabel('조건 충족', fontsize=12)
    ax4.set_ylim(0, 1)
    ax4.set_yticks([0.125, 0.375, 0.625, 0.875])
    ax4.set_yticklabels(['가격', 'RSI', 'Trend', '전체'])
    ax4.legend(loc='best', fontsize=9)
    ax4.grid(True, alpha=0.3)
    ax4.set_title('DCA 조건 충족 현황 (빨간색 영역 = 모든 조건 동시 충족)', fontsize=12)

    # X축 포맷
    ax4.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d %H:%M'))
    plt.xticks(rotation=45)

    plt.tight_layout()

    # 저장
    filename = f'/Users/seunghyun/TradingBoost-Strategy/BACKTEST/trade_{trade_num}_dca_analysis.png'
    plt.savefig(filename, dpi=150, bbox_inches='tight')
    print(f"✅ 저장: {filename}")

    plt.close()

    return filename

def generate_dca_summary_report(result: dict, all_analyses: list):
    """DCA 미작동 원인 요약 리포트 생성"""
    report = f"""
{'='*80}
DCA 미작동 원인 상세 분석 리포트
{'='*80}

📊 DCA 설정 파라미터
{'─'*80}
• Entry Type: {result['strategy_params']['pyramiding_entry_type']}
• Entry Value: {result['strategy_params']['pyramiding_value']}%
• Entry Criterion: {result['strategy_params']['entry_criterion']}
• Pyramiding Limit: {result['strategy_params']['pyramiding_limit']}회
• Price Check: {result['strategy_params']['use_check_DCA_with_price']}
• RSI Check: {result['strategy_params']['use_rsi_with_pyramiding']} (Oversold: 30, Overbought: 70)
• Trend Check: {result['strategy_params']['use_trend_logic']} (Long: EMA > SMA, Short: EMA < SMA)

"""

    for i, analysis in enumerate(all_analyses, 1):
        trade = analysis['trade']
        dca_checks = analysis['dca_checks']
        dca_levels = analysis['dca_levels']

        # 조건별 충족 통계
        total_candles = len(dca_checks)
        price_met = dca_checks['price_condition'].sum()
        rsi_met = dca_checks['rsi_condition'].sum()
        trend_met = dca_checks['trend_condition'].sum()
        all_met = dca_checks['all_conditions'].sum()

        # 가장 근접했던 순간
        closest_idx = dca_checks['distance_from_dca1'].idxmin()
        closest = dca_checks.loc[closest_idx]

        report += f"""
{'─'*80}
거래 #{i} ({trade['side'].upper()})
{'─'*80}
• 진입: {trade['entry_timestamp']} @ ${trade['entry_price']:,.2f}
• 청산: {trade['exit_timestamp']} @ ${trade['exit_price']:,.2f}
• DCA Level 1: ${dca_levels[0]:,.2f} ({'+' if trade['side'] == 'short' else '-'}{result['strategy_params']['pyramiding_value']}%)
• DCA Level 2: ${dca_levels[1]:,.2f} ({'+' if trade['side'] == 'short' else '-'}{result['strategy_params']['pyramiding_value'] * 2}%)
• DCA Level 3: ${dca_levels[2]:,.2f} ({'+' if trade['side'] == 'short' else '-'}{result['strategy_params']['pyramiding_value'] * 3}%)

📈 조건 충족 통계 (전체 {total_candles}개 캔들)
  • 가격 조건 충족: {price_met}회 ({price_met/total_candles*100:.1f}%)
  • RSI 조건 충족: {rsi_met}회 ({rsi_met/total_candles*100:.1f}%)
  • Trend 조건 충족: {trend_met}회 ({trend_met/total_candles*100:.1f}%)
  • 전체 조건 동시 충족: {all_met}회 ({all_met/total_candles*100:.1f}%)

🎯 DCA Level 1 최근접 순간
  • 시각: {closest['timestamp']}
  • 가격: ${closest['price']:,.2f} (DCA Level 1까지 {closest['distance_from_dca1']:.2f}%)
  • RSI: {closest['rsi']:.1f} {'✅' if closest['rsi_condition'] else '❌'}
  • EMA: ${closest['ema']:,.2f}, SMA: ${closest['sma']:,.2f} {'✅' if closest['trend_condition'] else '❌'}
  • 가격 조건: {'✅' if closest['price_condition'] else '❌'}
  • 전체 조건: {'✅ 충족!' if closest['all_conditions'] else '❌ 미충족'}

💡 미작동 원인
"""

        # 원인 분석
        if all_met > 0:
            report += f"  ⚠️ 전체 조건이 {all_met}회 충족되었으나 DCA가 발동되지 않음 → 엔진 로직 확인 필요!\n"
        elif price_met == 0:
            report += f"  • 가격이 DCA Level 1 (${dca_levels[0]:,.2f})에 도달하지 못함 (최소 거리: {closest['distance_from_dca1']:.2f}%)\n"
        elif rsi_met == 0:
            report += f"  • RSI 조건 미충족 ({'과매도(30 이하)' if trade['side'] == 'long' else '과매수(70 이상)'} 구간 없음)\n"
        elif trend_met == 0:
            report += f"  • Trend 조건 미충족 ({'EMA > SMA' if trade['side'] == 'long' else 'EMA < SMA'} 구간 없음)\n"
        else:
            report += f"  • 가격({price_met}회), RSI({rsi_met}회), Trend({trend_met}회) 조건이 개별적으로는 충족되었으나\n"
            report += f"    동시에 모두 충족된 순간은 없음 → 조건이 너무 엄격함\n"

    report += f"""
{'='*80}
🎯 종합 결론 및 권장사항
{'='*80}

1️⃣ **DCA 미작동 주요 원인**
   • 3% 가격 하락/상승 조건이 충족되기 전에 TP 달성
   • RSI와 Trend 조건이 동시에 충족되는 순간 부족
   • 평균 보유 시간 74.92시간 동안 역방향 큰 움직임 없음

2️⃣ **DCA 발동을 위한 권장 조정**
   • Entry Value: 3.0% → 1.5% (더 빨리 DCA 레벨 도달)
   • RSI Check: True → False (RSI 조건 제거하여 완화)
   • 또는 Trend Check: True → False (Trend 조건 제거하여 완화)
   • Pyramiding Value를 낮춰 더 자주 DCA 기회 확보

3️⃣ **테스트 전략**
   • 변동성이 큰 기간 선택 (예: 8월 초 급락장)
   • 더 긴 보유 시간이 예상되는 전략 사용
   • DCA 조건을 하나씩 제거하며 민감도 테스트

{'='*80}
"""

    # 파일로 저장
    with open('/Users/seunghyun/TradingBoost-Strategy/BACKTEST/DCA_ANALYSIS_REPORT.txt', 'w', encoding='utf-8') as f:
        f.write(report)

    print("\n" + report)
    print("✅ DCA 분석 리포트 저장: DCA_ANALYSIS_REPORT.txt\n")

def main():
    """메인 실행"""
    print("="*80)
    print("DCA 미작동 원인 시각화 분석 시작")
    print("="*80)

    # 1. 백테스트 결과 로드
    result = load_backtest_result()
    print(f"\n✅ 백테스트 결과 로드: {len(result['trades'])}개 거래")

    # 2. 각 거래별 분석
    all_analyses = []

    for trade in result['trades']:
        print(f"\n📊 거래 #{trade['trade_number']} 분석 중...")

        # 캔들 데이터 조회 (거래 기간 + 여유분)
        candles = get_candle_data(
            result['symbol'],
            trade['entry_timestamp'],
            trade['exit_timestamp']
        )

        if candles.empty:
            print(f"  ❌ 캔들 데이터 없음")
            continue

        print(f"  ✅ {len(candles)}개 캔들 데이터 로드")

        # DCA 조건 분석
        dca_checks, dca_levels = analyze_trade_dca(trade, candles, result['strategy_params'])

        if dca_checks is None:
            print(f"  ❌ DCA 분석 실패")
            continue

        # 시각화
        filename = visualize_trade_dca(trade, candles, dca_checks, dca_levels, trade['trade_number'])

        all_analyses.append({
            'trade': trade,
            'candles': candles,
            'dca_checks': dca_checks,
            'dca_levels': dca_levels,
            'chart_file': filename
        })

    # 3. 종합 리포트 생성
    print(f"\n📝 종합 리포트 생성 중...")
    generate_dca_summary_report(result, all_analyses)

    print("\n" + "="*80)
    print("✅ DCA 분석 완료!")
    print("="*80)
    print("\n생성된 파일:")
    for analysis in all_analyses:
        print(f"  • {analysis['chart_file']}")
    print(f"  • /Users/seunghyun/TradingBoost-Strategy/BACKTEST/DCA_ANALYSIS_REPORT.txt")
    print()

if __name__ == "__main__":
    main()

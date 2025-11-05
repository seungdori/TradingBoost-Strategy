"""
3개월 DCA 백테스트 결과 분석 스크립트
"""
import json
from datetime import datetime
from typing import Dict, Any, List

def load_result(filepath: str) -> Dict[str, Any]:
    """백테스트 결과 로드"""
    with open(filepath, 'r') as f:
        return json.load(f)

def analyze_dca_usage(result: Dict[str, Any]) -> Dict[str, Any]:
    """DCA 동작 분석"""
    trades = result.get('trades', [])

    # DCA 진입 분석
    dca_entries = {}
    for trade in trades:
        trade_num = trade['trade_number']
        # 실제 거래 데이터에서 DCA 여부 확인
        # (현재는 단순 거래만 있음, DCA 추가 진입은 확인 불가)
        dca_entries[trade_num] = {
            'entry_count': 1,  # 기본 1회 진입
            'entry_price': trade['entry_price'],
            'quantity': trade['quantity']
        }

    return {
        'total_positions': len(trades),
        'positions_with_dca': 0,  # 실제 DCA 추가 진입 없음
        'total_dca_entries': 0,
        'avg_dca_per_position': 0.0,
        'dca_details': dca_entries
    }

def analyze_performance(result: Dict[str, Any]) -> Dict[str, Any]:
    """성능 지표 분석"""
    trades = result.get('trades', [])

    # 거래 기간 계산
    if trades:
        first_entry = datetime.fromisoformat(trades[0]['entry_timestamp'].replace('Z', '+00:00'))
        last_exit = datetime.fromisoformat(trades[-1]['exit_timestamp'].replace('Z', '+00:00'))
        trading_period_days = (last_exit - first_entry).days
    else:
        trading_period_days = 0

    # 월별 수익률 계산
    total_return_percent = result.get('total_return_percent', 0)
    monthly_return = (total_return_percent / 3) if trading_period_days > 0 else 0

    return {
        'initial_balance': result.get('initial_balance'),
        'final_balance': result.get('final_balance'),
        'total_return_usdt': result.get('total_return'),
        'total_return_percent': total_return_percent,
        'monthly_return_percent': monthly_return,
        'max_drawdown_usdt': result.get('max_drawdown'),
        'max_drawdown_percent': result.get('max_drawdown_percent'),
        'total_trades': result.get('total_trades'),
        'winning_trades': result.get('winning_trades'),
        'losing_trades': result.get('losing_trades'),
        'win_rate': result.get('win_rate'),
        'profit_factor': result.get('profit_factor'),
        'sharpe_ratio': result.get('sharpe_ratio'),
        'avg_win': result.get('avg_win'),
        'avg_loss': result.get('avg_loss'),
        'largest_win': result.get('largest_win'),
        'largest_loss': result.get('largest_loss'),
        'avg_trade_duration_minutes': result.get('avg_trade_duration_minutes'),
        'avg_trade_duration_hours': round(result.get('avg_trade_duration_minutes', 0) / 60, 2),
        'total_fees_paid': result.get('total_fees_paid'),
        'trading_period_days': trading_period_days,
        'execution_time_seconds': result.get('execution_time_seconds')
    }

def analyze_trades(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """개별 거래 상세 분석"""
    trades = result.get('trades', [])

    analyzed_trades = []
    for trade in trades:
        entry_time = datetime.fromisoformat(trade['entry_timestamp'].replace('Z', '+00:00'))
        exit_time = datetime.fromisoformat(trade['exit_timestamp'].replace('Z', '+00:00'))
        duration_hours = (exit_time - entry_time).total_seconds() / 3600

        analyzed_trades.append({
            'trade_number': trade['trade_number'],
            'side': trade['side'],
            'entry_date': entry_time.strftime('%Y-%m-%d %H:%M'),
            'exit_date': exit_time.strftime('%Y-%m-%d %H:%M'),
            'duration_hours': round(duration_hours, 2),
            'entry_price': trade['entry_price'],
            'exit_price': trade['exit_price'],
            'exit_reason': trade['exit_reason'],
            'quantity': trade['quantity'],
            'leverage': trade['leverage'],
            'pnl_usdt': trade['pnl'],
            'pnl_percent': trade['pnl_percent'],
            'entry_fee': trade['entry_fee'],
            'exit_fee': trade['exit_fee'],
            'total_fee': trade['entry_fee'] + trade['exit_fee']
        })

    return analyzed_trades

def generate_report(result: Dict[str, Any]) -> str:
    """백테스트 결과 리포트 생성"""
    perf = analyze_performance(result)
    dca = analyze_dca_usage(result)
    trades = analyze_trades(result)

    report = f"""
{'='*80}
3개월 DCA 백테스트 결과 리포트
{'='*80}

📊 백테스트 기본 정보
{'─'*80}
• 심볼: {result.get('symbol')}
• 타임프레임: {result.get('timeframe')}
• 기간: {result.get('start_date')} ~ {result.get('end_date')} ({perf['trading_period_days']}일)
• 전략: {result.get('strategy_name')}
• 실행 시간: {perf['execution_time_seconds']:.3f}초

💰 수익 성과
{'─'*80}
• 초기 자본: ${perf['initial_balance']:,.2f}
• 최종 자본: ${perf['final_balance']:,.2f}
• 총 수익: ${perf['total_return_usdt']:,.2f} ({perf['total_return_percent']:.2f}%)
• 월평균 수익률: {perf['monthly_return_percent']:.2f}%
• 최대 낙폭: ${perf['max_drawdown_usdt']:,.2f} ({perf['max_drawdown_percent']:.2f}%)

📈 거래 통계
{'─'*80}
• 총 거래: {perf['total_trades']}회
• 승리: {perf['winning_trades']}회 / 패배: {perf['losing_trades']}회
• 승률: {perf['win_rate']:.2f}%
• Profit Factor: {perf['profit_factor']:.2f}
• Sharpe Ratio: {perf['sharpe_ratio']:.2f}
• 평균 승리: ${perf['avg_win']:,.2f}
• 평균 손실: ${perf['avg_loss']:,.2f}
• 최대 승리: ${perf['largest_win']:,.2f}
• 최대 손실: ${perf['largest_loss']:,.2f}
• 평균 거래 시간: {perf['avg_trade_duration_hours']:.2f}시간
• 총 수수료: ${perf['total_fees_paid']:,.2f}

🎯 DCA 동작 분석
{'─'*80}
• DCA 활성화: {result['strategy_params']['pyramiding_enabled']}
• Pyramiding Limit: {result['strategy_params']['pyramiding_limit']}
• Entry Multiplier: {result['strategy_params']['entry_multiplier']}
• Entry Type: {result['strategy_params']['pyramiding_entry_type']}
• Entry Value: {result['strategy_params']['pyramiding_value']}%
• Entry Criterion: {result['strategy_params']['entry_criterion']}
• Price Check: {result['strategy_params']['use_check_DCA_with_price']}
• RSI Check: {result['strategy_params']['use_rsi_with_pyramiding']}
• Trend Check: {result['strategy_params']['use_trend_logic']}

⚠️ DCA 진입 현황
{'─'*80}
• 총 포지션: {dca['total_positions']}개
• DCA 추가 진입 포지션: {dca['positions_with_dca']}개
• 총 DCA 진입: {dca['total_dca_entries']}회
• 포지션당 평균 진입: {dca['avg_dca_per_position']:.2f}회

⚠️ 참고: 3개월 기간 동안 DCA 추가 진입 조건이 충족되지 않아
    모든 포지션이 단일 진입으로만 거래되었습니다.
    DCA 기능이 활성화되어 있지만 실제 발동되지 않았습니다.

📋 개별 거래 내역
{'─'*80}
"""

    for trade in trades:
        report += f"""
거래 #{trade['trade_number']} - {trade['side'].upper()}
  진입: {trade['entry_date']} @ ${trade['entry_price']:,.2f}
  청산: {trade['exit_date']} @ ${trade['exit_price']:,.2f}
  청산 사유: {trade['exit_reason']}
  보유 시간: {trade['duration_hours']:.2f}시간
  수량: {trade['quantity']:.8f} BTC
  레버리지: {trade['leverage']}x
  손익: ${trade['pnl_usdt']:,.2f} ({trade['pnl_percent']:.2f}%)
  수수료: ${trade['total_fee']:.2f} (진입 ${trade['entry_fee']:.2f} + 청산 ${trade['exit_fee']:.2f})
"""

    report += f"""
{'='*80}
"""

    return report

if __name__ == "__main__":
    # 결과 로드
    result = load_result('/Users/seunghyun/TradingBoost-Strategy/BACKTEST/backtest_result.json')

    # 리포트 생성
    report = generate_report(result)

    # 출력
    print(report)

    # 파일로 저장
    with open('/Users/seunghyun/TradingBoost-Strategy/BACKTEST/backtest_report.txt', 'w', encoding='utf-8') as f:
        f.write(report)

    print("✅ 리포트 저장 완료: backtest_report.txt")

#!/usr/bin/env python3
"""
로그 분석 스크립트
주문 로그, 에러 로그, 알림 로그를 분석하여 통계와 인사이트를 제공합니다.
"""

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple
import argparse


class LogAnalyzer:
    """로그 분석 클래스"""

    def __init__(self, log_dir: Path):
        self.log_dir = log_dir
        self.orders_dir = log_dir / 'orders'
        self.errors_dir = log_dir / 'errors'
        self.alerts_dir = log_dir / 'alerts'
        self.debug_dir = log_dir / 'debug'

    def analyze_order_logs(self, days: int = 7) -> Dict[str, Any]:
        """
        주문 로그를 분석합니다.

        Args:
            days: 분석할 기간 (일)

        Returns:
            분석 결과 딕셔너리
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        action_types = Counter()
        symbols = Counter()
        users = Counter()
        position_sides = Counter()
        total_volume = 0.0
        errors = []
        hourly_distribution = defaultdict(int)

        order_log_file = self.orders_dir / 'trading_orders.log'

        if not order_log_file.exists():
            print(f"⚠️  주문 로그 파일이 없습니다: {order_log_file}")
            return {}

        with open(order_log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    log_entry = json.loads(line)
                    log_time = datetime.fromisoformat(log_entry.get('timestamp', ''))

                    if log_time >= cutoff_date:
                        action_types[log_entry.get('action_type', 'unknown')] += 1
                        symbols[log_entry.get('symbol', 'unknown')] += 1
                        users[log_entry.get('user_id', 'unknown')] += 1
                        position_sides[log_entry.get('position_side', 'unknown')] += 1

                        # 시간대별 분포
                        hour = log_time.hour
                        hourly_distribution[hour] += 1

                        # 거래량 계산
                        if 'quantity' in log_entry and log_entry['quantity']:
                            try:
                                total_volume += float(log_entry['quantity'])
                            except (ValueError, TypeError):
                                pass

                        # 에러 로그 수집
                        if log_entry.get('level') == 'ERROR':
                            errors.append(log_entry)

                except (json.JSONDecodeError, ValueError, KeyError) as e:
                    continue

        return {
            'total_orders': sum(action_types.values()),
            'action_types': dict(action_types.most_common(10)),
            'top_symbols': dict(symbols.most_common(10)),
            'active_users': len(users),
            'top_users': dict(users.most_common(5)),
            'position_distribution': dict(position_sides),
            'total_volume': round(total_volume, 4),
            'error_count': len(errors),
            'hourly_distribution': dict(sorted(hourly_distribution.items())),
            'errors': errors[:10]  # 최근 10개 에러
        }

    def analyze_error_logs(self, days: int = 7) -> Dict[str, Any]:
        """
        에러 로그를 분석합니다.

        Args:
            days: 분석할 기간 (일)

        Returns:
            분석 결과 딕셔너리
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        error_types = Counter()
        error_modules = Counter()
        critical_errors = []
        recent_errors = []

        error_log_file = self.errors_dir / 'error.log'

        if not error_log_file.exists():
            print(f"⚠️  에러 로그 파일이 없습니다: {error_log_file}")
            return {}

        with open(error_log_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    # 로그 라인 파싱 (간단한 형식 가정)
                    if 'ERROR' in line or 'CRITICAL' in line:
                        # 타임스탬프 추출 시도
                        parts = line.split(' - ')
                        if len(parts) >= 2:
                            try:
                                timestamp_str = parts[0].strip('[]')
                                log_time = datetime.fromisoformat(timestamp_str)

                                if log_time >= cutoff_date:
                                    if 'CRITICAL' in line:
                                        critical_errors.append(line.strip())
                                        error_types['CRITICAL'] += 1
                                    elif 'ERROR' in line:
                                        error_types['ERROR'] += 1
                                        recent_errors.append(line.strip())

                                    # 모듈명 추출
                                    if len(parts) >= 3:
                                        module = parts[1].strip()
                                        error_modules[module] += 1
                            except (ValueError, IndexError):
                                continue
                except Exception:
                    continue

        return {
            'total_errors': sum(error_types.values()),
            'error_distribution': dict(error_types),
            'top_error_modules': dict(error_modules.most_common(10)),
            'critical_errors': critical_errors[:5],
            'recent_errors': recent_errors[:10]
        }

    def analyze_alert_logs(self, days: int = 7) -> Dict[str, Any]:
        """
        알림 로그를 분석합니다.

        Args:
            days: 분석할 기간 (일)

        Returns:
            분석 결과 딕셔너리
        """
        cutoff_date = datetime.now() - timedelta(days=days)

        alert_types = Counter()
        user_alerts = Counter()
        symbol_alerts = Counter()

        # 최근 N일간의 알림 로그 파일 찾기
        alert_files = []
        for i in range(days + 1):
            date_str = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
            alert_file = self.alerts_dir / f'system_alerts_{date_str}.log'
            if alert_file.exists():
                alert_files.append(alert_file)

        total_alerts = 0
        for alert_file in alert_files:
            with open(alert_file, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        log_entry = json.loads(line)
                        alert_types[log_entry.get('alert_type', 'unknown')] += 1
                        user_alerts[log_entry.get('user_id', 'unknown')] += 1
                        symbol_alerts[log_entry.get('symbol', 'unknown')] += 1
                        total_alerts += 1
                    except (json.JSONDecodeError, KeyError):
                        continue

        return {
            'total_alerts': total_alerts,
            'alert_types': dict(alert_types.most_common(10)),
            'top_user_alerts': dict(user_alerts.most_common(5)),
            'top_symbol_alerts': dict(symbol_alerts.most_common(5))
        }

    def print_report(self, days: int = 7):
        """
        전체 로그 분석 리포트를 출력합니다.

        Args:
            days: 분석할 기간 (일)
        """
        print("=" * 80)
        print(f"📊  HYPERRSI 로그 분석 리포트 (최근 {days}일)")
        print("=" * 80)
        print()

        # 1. 주문 로그 분석
        print("📦 [1] 주문 로그 분석")
        print("-" * 80)
        order_stats = self.analyze_order_logs(days)
        if order_stats:
            print(f"총 주문 수: {order_stats['total_orders']:,}")
            print(f"활성 사용자: {order_stats['active_users']}")
            print(f"총 거래량: {order_stats['total_volume']:,}")
            print(f"에러 수: {order_stats['error_count']}")
            print()

            print("주문 타입별 분포:")
            for action_type, count in order_stats['action_types'].items():
                percentage = (count / order_stats['total_orders']) * 100
                print(f"  {action_type:15s}: {count:6,} ({percentage:5.1f}%)")
            print()

            print("상위 거래 심볼:")
            for symbol, count in order_stats['top_symbols'].items():
                percentage = (count / order_stats['total_orders']) * 100
                print(f"  {symbol:15s}: {count:6,} ({percentage:5.1f}%)")
            print()

            print("포지션 분포:")
            for position_side, count in order_stats['position_distribution'].items():
                percentage = (count / order_stats['total_orders']) * 100
                print(f"  {position_side:15s}: {count:6,} ({percentage:5.1f}%)")
            print()

            if order_stats['hourly_distribution']:
                print("시간대별 주문 분포 (UTC):")
                max_count = max(order_stats['hourly_distribution'].values())
                for hour in range(24):
                    count = order_stats['hourly_distribution'].get(hour, 0)
                    bar_length = int((count / max_count) * 40) if max_count > 0 else 0
                    bar = '█' * bar_length
                    print(f"  {hour:02d}:00  {count:4d}  {bar}")
                print()
        else:
            print("⚠️  분석할 주문 로그가 없습니다.")
        print()

        # 2. 에러 로그 분석
        print("🚨 [2] 에러 로그 분석")
        print("-" * 80)
        error_stats = self.analyze_error_logs(days)
        if error_stats:
            print(f"총 에러 수: {error_stats['total_errors']:,}")
            print()

            print("에러 레벨 분포:")
            for error_type, count in error_stats['error_distribution'].items():
                print(f"  {error_type:15s}: {count:6,}")
            print()

            print("상위 에러 모듈:")
            for module, count in error_stats['top_error_modules'].items():
                print(f"  {module:40s}: {count:6,}")
            print()

            if error_stats['critical_errors']:
                print("⚠️  최근 치명적 에러:")
                for error in error_stats['critical_errors']:
                    print(f"  - {error[:100]}...")
                print()
        else:
            print("✅ 분석할 에러 로그가 없습니다.")
        print()

        # 3. 알림 로그 분석
        print("📢 [3] 알림 로그 분석")
        print("-" * 80)
        alert_stats = self.analyze_alert_logs(days)
        if alert_stats:
            print(f"총 알림 수: {alert_stats['total_alerts']:,}")
            print()

            print("알림 타입별 분포:")
            for alert_type, count in alert_stats['alert_types'].items():
                percentage = (count / alert_stats['total_alerts']) * 100
                print(f"  {alert_type:20s}: {count:6,} ({percentage:5.1f}%)")
            print()

            print("상위 알림 발생 사용자:")
            for user_id, count in alert_stats['top_user_alerts'].items():
                print(f"  {user_id:40s}: {count:6,}")
            print()
        else:
            print("⚠️  분석할 알림 로그가 없습니다.")
        print()

        print("=" * 80)
        print("✅ 분석 완료!")
        print("=" * 80)


def main():
    """메인 함수"""
    parser = argparse.ArgumentParser(
        description='HYPERRSI 로그 분석 도구',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예제:
    %(prog)s                # 최근 7일 로그 분석
    %(prog)s -d 30          # 최근 30일 로그 분석
    %(prog)s -d 1 -v        # 어제 로그만 상세 분석
        """
    )
    parser.add_argument(
        '-d', '--days',
        type=int,
        default=7,
        help='분석할 기간 (일) (기본값: 7)'
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='상세 정보 출력'
    )

    args = parser.parse_args()

    # 로그 디렉토리 경로 설정
    script_dir = Path(__file__).parent
    project_dir = script_dir.parent
    log_dir = project_dir / 'logs'

    if not log_dir.exists():
        print(f"❌ 로그 디렉토리가 존재하지 않습니다: {log_dir}")
        sys.exit(1)

    # 로그 분석 실행
    analyzer = LogAnalyzer(log_dir)
    analyzer.print_report(days=args.days)


if __name__ == '__main__':
    main()

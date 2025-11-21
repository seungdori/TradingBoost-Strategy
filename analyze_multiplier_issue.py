#!/usr/bin/env python3
"""
Analyze multiplier execution issue
"""

# 실제 거래 내역 분석
print("=" * 80)
print("🔍 거래 패턴 분석")
print("=" * 80)

# 사이클별로 그룹화
cycles = {
    "사이클 1 (진입 #1-7)": [
        (1, 0.31, None),
        (2, 0.31, 1.00),
        (3, 0.65, 2.10),
        (4, 1.34, 2.06),
        (5, 2.02, 1.51),
        (6, 0.31, 0.15),
        (7, 0.65, 2.10),
    ],
    "사이클 2 (진입 #8-14) - multiplier=2.0": [
        (8, 0.38, None),
        (9, 0.76, 2.00),
        (10, 1.52, 2.00),
        (11, 3.04, 2.00),
        (12, 6.08, 2.00),
        (13, 12.16, 2.00),
        (14, 24.32, 2.00),
    ],
    "사이클 3 (진입 #15-19)": [
        (15, 0.33, None),
        (16, 0.33, 1.00),
        (17, 0.69, 2.09),
        (18, 1.41, 2.04),
        (19, 2.86, 2.03),
    ],
    "사이클 4 (진입 #20-23)": [
        (20, 0.32, None),
        (21, 0.57, 1.78),
        (22, 0.59, 1.04),
        (23, 1.22, 2.07),
    ],
    "사이클 5 (진입 #24-27) - multiplier=2.0": [
        (24, 2.02, None),
        (25, 4.04, 2.00),
        (26, 8.08, 2.00),
        (27, 16.16, 2.00),
    ],
}

for cycle_name, entries in cycles.items():
    print(f"\n{cycle_name}")
    for entry_num, size, ratio in entries:
        if ratio:
            print(f"  진입 #{entry_num}: {size:.2f} 계약 (배율: {ratio:.2f}x)")
        else:
            print(f"  진입 #{entry_num}: {size:.2f} 계약 (첫 진입)")

print("\n" + "=" * 80)
print("🚨 발견된 문제점")
print("=" * 80)

print("""
1. 사이클 2와 5에서 정확히 multiplier=2.0으로 실행됨
   - 현재 설정은 1.1인데 왜?
   
2. 여러 사이클이 존재 (최소 5개 사이클)
   - Redis DCA count는 4인데 실제로는 27번 진입
   
3. Position size가 전혀 업데이트되지 않음
   - Redis: 32.32 계약
   - 실제 OKX: 92.47 계약
   
4. 각 사이클의 첫 진입 크기가 다름:
   - 사이클 1: 0.31
   - 사이클 2: 0.38
   - 사이클 3: 0.33
   - 사이클 4: 0.32
   - 사이클 5: 2.02 (왜 갑자기 크게?)
""")

print("\n" + "=" * 80)
print("💡 가능한 원인")
print("=" * 80)

print("""
A. Multiplier 2.0 실행 원인:
   1) 과거에 설정이 2.0이었고, 코드가 오래된 설정 캐시 사용
   2) Fallback 로직 실행 시 잘못된 계산
   3) 다른 사용자의 설정을 참조 (user_id 혼동)
   
B. Position size 불일치 원인:
   1) DCA 실행 후 Redis position size 업데이트 안 됨
   2) Position close 후 새로운 진입 시 size 초기화 안 됨
   3) 여러 position이 동시에 열려있는데 하나만 추적
   
C. DCA count 불일치 원인:
   1) Position close 시 DCA count 초기화 안 됨
   2) 새로운 진입을 DCA로 착각
   3) 여러 position의 DCA count가 합쳐짐
""")


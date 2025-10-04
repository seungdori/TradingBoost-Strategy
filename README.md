# TradingBoost-Strategy Monorepo

암호화폐 자동 트레이딩 전략 모노레포 프로젝트

## 프로젝트 구조

```
TradingBoost-Strategy/
├── HYPERRSI/          # HyperRSI 전략 (RSI + 트렌드 기반)
├── GRID/              # GRID 전략 (가격 그리드 기반)
└── shared/            # 공통 모듈
    ├── exchange_apis/ # 거래소 API 래퍼
    ├── constants/     # 공유 상수
    ├── database/      # 공유 데이터베이스
    └── utils/         # 공통 유틸리티
```

## 전략별 실행 방법

### HYPERRSI 전략

```bash
cd HYPERRSI
python main.py
```

- 포트: 8000
- 기능: RSI 지표와 트렌드 분석을 결합한 고급 매매 전략

### GRID 전략

```bash
cd GRID
python main.py --port 8012
```

- 포트: 8012
- 기능: 가격 그리드 기반의 자동화된 매매 전략

## 지원 거래소

- OKX (메인)
- Binance
- Bitget
- Upbit
- Bybit

## 기술 스택

- **Backend**: Python 3.9+, FastAPI, Celery
- **Database**: SQLite, Redis, PostgreSQL (준비 중)
- **WebSocket**: aiohttp, websockets
- **Process Management**: PM2, multiprocessing
- **Message Queue**: Redis (Celery broker)

## 개발 환경 설정

### 1. Python 가상 환경 생성

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
```

### 2. 의존성 설치

```bash
# HYPERRSI 의존성
cd HYPERRSI && pip install -r requirements.txt && cd ..

# GRID는 HYPERRSI와 동일한 의존성 사용
```

### 3. 환경 변수 설정

```bash
# HYPERRSI/.env
cp HYPERRSI/.env.example HYPERRSI/.env
```

## PYTHONPATH 설정

모노레포 구조에서는 PYTHONPATH를 설정해야 합니다:

```bash
export PYTHONPATH=/Users/seunghyun/TradingBoost-Strategy:$PYTHONPATH
```

또는 각 프로젝트 실행 시:

```bash
PYTHONPATH=/Users/seunghyun/TradingBoost-Strategy python main.py
```

## 자세한 문서

- [HYPERRSI 아키텍처](./HYPERRSI/PROJECT_ARCHITECTURE.md)
- [GRID 전략 가이드](./GRID/README.md)

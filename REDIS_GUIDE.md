# Redis 사용 가이드

## 개요

TradingBoost-Strategy는 **듀얼 Redis 아키텍처**를 사용합니다:

### 1. 원격 Redis (158.247.251.34:6379, DB 0)
**목적**: 영구 애플리케이션 데이터 저장
- **포함 데이터**: 사용자 설정, API 키 (암호화), 거래 상태, 포지션 정보
- **Redis 버전**: 8.0.1
- **데이터 보존**: TTL 기반 (API 키는 영구, 일반 데이터는 30일)
- **사용 스크립트**: `./redis-remote`

### 2. 로컬 Redis (localhost:6379, DB 1)
**목적**: Celery 작업 큐 및 일시적 데이터
- **포함 데이터**: 태스크 큐, 작업 상태, 결과 백엔드
- **데이터 특성**: 임시 데이터, 재시작 시 손실 가능
- **사용 스크립트**: `./redis-local 1`

### 왜 두 개의 Redis를 사용하나?
- **데이터 격리**: 애플리케이션 데이터와 작업 큐 분리
- **성능 최적화**: Celery 작업이 애플리케이션 데이터에 영향 없음
- **복원력**: 원격 Redis 장애 시에도 로컬 작업 큐는 동작
- **개발 편의성**: 로컬에서 Celery 개발/디버깅 가능

## 빠른 시작

### 원격 Redis 접속 (애플리케이션 데이터)

```bash
# 프로젝트 루트에서
./redis-remote PING
./redis-remote KEYS "user:*"
./redis-remote HGETALL "user:586156710277369942:api:keys"
```

### 로컬 Redis 접속 (Celery)

```bash
# 프로젝트 루트에서
./redis-local 1 PING
./redis-local 1 KEYS "celery*"
```

## 상세 사용법

### redis-remote 스크립트

원격 Redis 서버에 자동으로 연결합니다. `.env` 파일의 설정을 사용합니다.

**사용 예시:**
```bash
# 연결 테스트
./redis-remote PING

# 특정 사용자 키 확인
./redis-remote KEYS "user:586156710277369942:*"

# API 키 확인
./redis-remote HGETALL "user:586156710277369942:api:keys"

# 트레이딩 상태 확인
./redis-remote GET "user:586156710277369942:trading:status"

# 트레이딩 시작
./redis-remote SET "user:586156710277369942:trading:status" "running"

# 대화형 모드
./redis-remote
```

### redis-local 스크립트

로컬 Redis 서버에 연결합니다 (주로 Celery 디버깅용).

**사용 예시:**
```bash
# Celery DB (1) 확인
./redis-local 1 PING
./redis-local 1 KEYS "*"

# 대기 중인 Celery 작업 수 확인
./redis-local 1 LLEN "celery"
```

**⚠️ 주의**: `./redis-local 0`은 로컬 Redis DB 0으로, 애플리케이션 데이터가 **없습니다**. 애플리케이션 데이터는 원격 Redis (`./redis-remote`)에 있습니다.

## Redis 키 패턴 가이드

### 사용자 관리 키
```bash
# API 키 (HASH, 암호화 저장, TTL 없음 - 영구)
user:{okx_uid}:api:keys

# 사용자 설정 (STRING/JSON, TTL 7일)
user:{user_id}:settings

# 사용자 선호도 (HASH)
user:{user_id}:preferences
```

### 트레이딩 상태 키
```bash
# 트레이딩 상태 (STRING: "running"|"stopped"|"error")
user:{okx_uid}:trading:status

# 텔레그램 ID 기반 상태 (대체 키)
user:{telegram_id}:trading:status

# 트레이딩 통계
user:{user_id}:stats
```

### 포지션 관리 키
```bash
# 포지션 데이터
user:{user_id}:position:{symbol}:{side}

# 포지션 상태
user:{user_id}:position:{symbol}:position_state

# DCA 카운터
user:{user_id}:position:{symbol}:{side}:dca_count

# 진입 가격
user:{user_id}:position:{symbol}:{side}:entry_price
```

### GRID 전략 전용 키
```bash
# 기본 설정 (HASH)
{exchange_name}:default_settings

# 사용자 ID 목록 (SET)
{exchange_name}:user_ids

# GRID 사용자별 데이터
{exchange_name}:user:{user_id}:*
```

### Celery 키 (로컬 Redis DB 1)
```bash
# Celery 작업 큐
celery

# Celery 결과
celery-task-meta-*
```

## 환경 설정

`.env` 파일의 Redis 설정:

```bash
# 애플리케이션 Redis (원격) - 영구 데이터
REDIS_HOST=158.247.251.34
REDIS_PORT=6379
REDIS_DB=0
REDIS_PASSWORD=moggle_temp_3181
REDIS_MAX_CONNECTIONS=50  # 연결 풀 크기 (기본값 50, 최대 500)

# Celery Redis (로컬) - 임시 작업 데이터
CELERY_BROKER_URL_OVERRIDE=redis://localhost:6379/1
CELERY_RESULT_BACKEND_OVERRIDE=redis://localhost:6379/1

# API 키 암호화 (필수)
ENCRYPTION_KEY=your-fernet-encryption-key-here
```

### TTL (Time-To-Live) 정책

| 데이터 유형 | TTL | 비고 |
|------------|-----|------|
| API 키 | 없음 (영구) | 암호화 저장 |
| 사용자 데이터 | 없음 (영구) | 일반적인 사용자 정보 |
| 사용자 설정 | 없음 (영구) | 설정 및 선호도 |
| 사용자 세션 | 1일 | 임시 세션 데이터 |
| Celery 작업 | 1시간 | 작업 완료 후 자동 삭제 |

## 일반적인 작업

### 사용자 트레이딩 상태 확인

```bash
# OKX UID로 조회
./redis-remote GET "user:586156710277369942:trading:status"

# 모든 활성 사용자 찾기
./redis-remote KEYS "user:*:trading:status" | while read key; do
    status=$(./redis-remote GET "$key")
    echo "$key: $status"
done
```

### API 키 확인

```bash
# 특정 사용자 API 키 (암호화된 상태로 표시됨)
./redis-remote HGETALL "user:586156710277369942:api:keys"

# API 키가 있는 모든 사용자
./redis-remote KEYS "user:*:api:keys"
```

**⚠️ API 키 암호화 참고**:
- 2025년 10월부터 모든 API 키는 Fernet 암호화되어 저장됩니다
- Redis에서 조회하면 `gAAAAA...` 같은 base64 형태로 표시됩니다
- 애플리케이션에서 자동으로 복호화하여 사용합니다
- 암호화 키는 `.env`의 `ENCRYPTION_KEY`에 설정합니다

### Preferences 확인

```bash
./redis-remote HGETALL "user:586156710277369942:preferences"
```

### Celery 태스크 확인

```bash
# Celery 큐 상태
./redis-local 1 KEYS "celery*"

# 대기 중인 작업
./redis-local 1 LLEN "celery"
```

## 트러블슈팅

### "API keys not found" 오류

```bash
# 1. 원격 Redis에 API 키가 있는지 확인
./redis-remote HGETALL "user:YOUR_OKX_UID:api:keys"

# 2. 없으면 텔레그램에서 /setapi 재실행
```

### "EncryptionError" 또는 API 키 복호화 실패

```bash
# 1. ENCRYPTION_KEY 환경변수가 설정되어 있는지 확인
grep ENCRYPTION_KEY .env

# 2. 키가 없으면 생성
python scripts/generate_encryption_key.py

# 3. .env 파일에 추가 후 애플리케이션 재시작

# 4. 텔레그램에서 /setapi로 API 키 재등록 (암호화되어 저장됨)
```

### "활성 트레이더가 없습니다" 경고

```bash
# 1. 트레이딩 상태 확인
./redis-remote GET "user:YOUR_OKX_UID:trading:status"

# 2. stopped 상태면 텔레그램에서 /start 실행
```

### 로컬 vs 원격 Redis 혼동

**중요: 어떤 Redis를 사용해야 할까?**

| 작업 | 사용할 Redis | 명령어 |
|------|-------------|--------|
| 사용자 데이터 조회 | 원격 | `./redis-remote` |
| API 키 확인 | 원격 | `./redis-remote` |
| 트레이딩 상태 조회 | 원격 | `./redis-remote` |
| 포지션 정보 확인 | 원격 | `./redis-remote` |
| Celery 작업 디버깅 | 로컬 | `./redis-local 1` |
| 작업 큐 상태 확인 | 로컬 | `./redis-local 1` |

**❌ 주의사항**:
- 일반 `redis-cli` 명령어는 로컬 Redis에만 연결됩니다
- 로컬 Redis에는 애플리케이션 데이터가 **없습니다**
- 애플리케이션 데이터는 항상 원격 Redis (`./redis-remote`)에 있습니다

## 고급 기능 및 성능

### 연결 풀 관리

TradingBoost-Strategy는 Redis 연결 풀을 사용하여 성능을 최적화합니다:

```bash
# .env 설정
REDIS_MAX_CONNECTIONS=50  # 최대 연결 수 (기본값 50, 최대 500)
REDIS_SOCKET_TIMEOUT=5    # 소켓 타임아웃 (초)
REDIS_HEALTH_CHECK_INTERVAL=30  # 헬스 체크 간격 (초)
```

**연결 풀 특징**:
- 자동 연결 재사용으로 성능 향상
- 30초마다 자동 헬스 체크
- Circuit breaker 패턴으로 장애 대응

### 타임아웃 설정

모든 Redis 작업에는 타임아웃 보호가 적용됩니다:

| 작업 유형 | 타임아웃 | 예시 |
|----------|---------|------|
| 빠른 작업 | 2초 | GET, SET, EXISTS |
| 일반 작업 | 5초 | HGETALL, MGET |
| 느린 작업 | 10초 | SCAN, 복잡한 쿼리 |
| 파이프라인 | 15초 | 다중 명령 실행 |

### 최신 사용 패턴 (권장)

새로운 코드에서는 `redis_context()` 컨텍스트 매니저를 사용하세요:

```python
from shared.database.redis_patterns import redis_context

# 권장 방법 (자동 연결 정리)
async with redis_context() as redis:
    value = await redis.get("key")
    await redis.set("key2", "value")

# 구버전 방법 (레거시)
from shared.database.redis import get_redis
redis = await get_redis()
try:
    value = await redis.get("key")
finally:
    await redis.close()
```

**redis_context() 장점**:
- 자동 연결 정리 및 에러 핸들링
- 타임아웃 보호 내장
- Circuit breaker 자동 적용

### Circuit Breaker 패턴

Redis 연결은 장애 대응을 위한 Circuit breaker를 사용합니다:

- **정상 상태**: 모든 요청 정상 처리
- **장애 감지**: 연속 실패 시 Circuit Open
- **반개방 상태**: 일부 요청으로 복구 확인
- **복구**: 정상 작동 확인 시 Circuit Close

이를 통해 Redis 장애 시 애플리케이션 전체 장애를 방지합니다.

## 참고사항

### 보안
- 원격 Redis는 비밀번호로 보호됩니다
- `.env` 파일을 Git에 커밋하지 마세요
- `redis-remote` 스크립트는 자동으로 인증합니다
- API 키는 Fernet 암호화로 보호됩니다 (2025년 10월~)

### 성능
- 원격 Redis는 네트워크 지연이 있을 수 있습니다 (일반적으로 10-50ms)
- 대량 작업은 파이프라인 사용을 권장합니다
- 프로덕션 데이터를 조심히 다루세요
- 연결 풀을 통해 성능이 자동으로 최적화됩니다

### 데이터 백업
원격 Redis 데이터는 중요합니다. 정기적으로 백업하세요:
```bash
# 모든 키 덤프 (예시)
./redis-remote --scan --pattern "*" > redis_keys_backup.txt
```

### 모니터링
```bash
# Redis 정보 확인
./redis-remote INFO

# 키 공간 정보 (DB별 키 개수)
./redis-remote INFO keyspace

# 메모리 사용량
./redis-remote INFO memory

# 연결된 클라이언트 수
./redis-remote INFO clients
```

## 추가 도구

### shell alias 추가 (선택사항)

`~/.zshrc` 또는 `~/.bashrc`에 추가:

```bash
alias redis-app='redis-cli -h 158.247.251.34 -p 6379 -a moggle_temp_3181 --no-auth-warning'
alias redis-celery='redis-cli -n 1'
```

그 후:
```bash
source ~/.zshrc  # 또는 ~/.bashrc
redis-app PING
redis-celery PING
```

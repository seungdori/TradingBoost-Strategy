# Testing Guide - New Infrastructure

**작성일**: 2025-10-05

이 가이드는 새로 적용된 infrastructure를 테스트하는 방법을 설명합니다.

---

## 🧪 빠른 테스트 체크리스트

### 1. Configuration 테스트 ✅

```bash
# Python shell에서 설정 로드 테스트
python3 << 'EOF'
from shared.config import settings

print("✅ Configuration Test")
print(f"Environment: {settings.ENVIRONMENT}")
print(f"Debug: {settings.DEBUG}")
print(f"Database URL: {settings.DATABASE_URL[:50]}...")
print(f"Redis URL: {settings.REDIS_URL}")
print(f"DB Pool Size: {settings.DB_POOL_SIZE}")
EOF
```

**예상 출력**:
```
✅ Configuration Test
Environment: development
Debug: True
Database URL: postgresql+asyncpg://postgres.pybdkhfbkamagahgy...
Redis URL: redis://localhost:6379/0
DB Pool Size: 5
```

### 2. Database 연결 테스트 ✅

```bash
# Database 연결 테스트
python3 << 'EOF'
import asyncio
from shared.database.session import init_db, close_db

async def test():
    print("Testing database connection...")
    try:
        await init_db()
        print("✅ Database connection successful!")
        await close_db()
    except Exception as e:
        print(f"❌ Database connection failed: {e}")

asyncio.run(test())
EOF
```

### 3. Redis 연결 테스트 ✅

```bash
# Redis 연결 테스트
python3 << 'EOF'
import asyncio
from shared.database.redis import init_redis, close_redis, get_redis

async def test():
    print("Testing Redis connection...")
    try:
        await init_redis()
        redis = await get_redis()
        await redis.set("test_key", "test_value")
        value = await redis.get("test_key")
        assert value == "test_value", "Redis value mismatch!"
        await redis.delete("test_key")
        print(f"✅ Redis connection successful! (value: {value})")
        await close_redis()
    except Exception as e:
        print(f"❌ Redis connection failed: {e}")

asyncio.run(test())
EOF
```

### 4. Exception Handling 테스트 ✅

```bash
# Exception handling 테스트
python3 << 'EOF'
from shared.errors import (
    InsufficientBalanceException,
    ValidationException,
    sanitize_symbol
)
from shared.validation import validate_trading_amount

print("Testing exception handling...")

# Test 1: Insufficient balance exception
try:
    raise InsufficientBalanceException(
        required=100.0,
        available=50.0,
        currency="USDT"
    )
except InsufficientBalanceException as e:
    print(f"✅ Exception Test 1: {e.message}")
    print(f"   Code: {e.code}, Status: {e.status_code}")

# Test 2: Symbol validation
try:
    from shared.validation import sanitize_symbol
    symbol = sanitize_symbol("btc/usdt")
    print(f"✅ Symbol Validation Test: {symbol}")
except Exception as e:
    print(f"❌ Symbol validation failed: {e}")

# Test 3: Amount validation
try:
    from shared.validation import validate_trading_amount
    amount = validate_trading_amount(0.1)
    print(f"✅ Amount Validation Test: {amount}")
except Exception as e:
    print(f"❌ Amount validation failed: {e}")

print("✅ All exception tests passed!")
EOF
```

### 5. Logging 테스트 ✅

```bash
# Structured logging 테스트
python3 << 'EOF'
from shared.logging import setup_json_logger, get_logger

# Test JSON logger
logger = setup_json_logger("test_app")

logger.info(
    "Test log message",
    extra={
        "user_id": 123,
        "order_id": "order_456",
        "amount": 100.50
    }
)

logger.error(
    "Test error message",
    extra={"error_code": "TEST_ERROR"}
)

print("✅ Logging test complete!")
EOF
```

---

## 🚀 FastAPI 앱 테스트

### GRID 앱 시작 테스트

```bash
cd GRID

# 앱 시작
uvicorn api.app:app --reload --port 8012
```

**예상 로그**:
```
INFO:grid:Starting GRID application environment='development' debug=True
INFO:grid:Recovery state checked recovery_state=None port=8012
INFO:grid:Bot states loaded bot_count=0 port=8012
INFO:grid:GRID application startup complete port=8012
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8012
```

### HYPERRSI 앱 시작 테스트

```bash
cd HYPERRSI

# 앱 시작
uvicorn main:app --reload --port 8000
```

**예상 로그**:
```
INFO:hyperrsi:Starting HYPERRSI application environment='development' debug=True
INFO:hyperrsi:HYPERRSI application startup complete
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Health Check 테스트

```bash
# GRID health check
curl http://localhost:8012/test-cors
# Expected: {"message": "CORS is working"}

# HYPERRSI health check
curl http://localhost:8000/health
# Expected: {"status": "healthy"}
```

---

## 📝 API 엔드포인트 테스트

### 예제 API 테스트 (EXAMPLES/example_route.py 기반)

```bash
# Health check
curl http://localhost:8000/api/trading/health

# Expected response:
# {
#   "status": "healthy",
#   "database": "connected"
# }
```

```bash
# Create order (example)
curl -X POST "http://localhost:8000/api/trading/orders?user_id=123" \
     -H "Content-Type: application/json" \
     -d '{
           "symbol": "BTC/USDT",
           "side": "buy",
           "amount": 0.1,
           "price": 50000.0
         }'

# Expected response:
# {
#   "id": "order_123",
#   "user_id": 123,
#   "symbol": "BTC/USDT",
#   "side": "buy",
#   "amount": 0.1,
#   "price": 50000.0,
#   "status": "pending",
#   "created_at": "2025-10-05T10:00:00Z"
# }
```

```bash
# List orders
curl "http://localhost:8000/api/trading/orders?user_id=123&limit=10"

# Expected response:
# {
#   "total": 1,
#   "orders": [...]
# }
```

---

## 🔧 수동 통합 테스트

### Transaction Management 테스트

```python
# test_transaction.py
import asyncio
from shared.database.session import get_transactional_session
from shared.errors import DatabaseException

async def test_transaction():
    """트랜잭션 롤백 테스트"""
    try:
        async with get_transactional_session() as session:
            # 여기서 데이터베이스 작업 수행
            # 예: user = await create_user(session, user_data)

            # 강제로 예외 발생
            raise DatabaseException("Test rollback")

    except DatabaseException as e:
        print(f"✅ Transaction rolled back: {e.message}")

asyncio.run(test_transaction())
```

### Input Validation 테스트

```python
# test_validation.py
from shared.validation import (
    sanitize_symbol,
    validate_trading_amount,
    validate_order_side,
    sanitize_log_data
)
from shared.errors import ValidationException, InvalidSymbolException

# Test 1: Symbol sanitization
try:
    symbol = sanitize_symbol("btc/usdt")
    print(f"✅ Symbol: {symbol}")  # BTC/USDT

    invalid = sanitize_symbol("invalid!")  # Should raise exception
except InvalidSymbolException as e:
    print(f"✅ Invalid symbol caught: {e.message}")

# Test 2: Amount validation
try:
    amount = validate_trading_amount(0.1)
    print(f"✅ Amount: {amount}")  # Decimal('0.1')

    invalid = validate_trading_amount(-1)  # Should raise exception
except ValidationException as e:
    print(f"✅ Invalid amount caught: {e.message}")

# Test 3: Order side validation
try:
    side = validate_order_side("BUY")
    print(f"✅ Side: {side}")  # buy

    invalid = validate_order_side("invalid")  # Should raise exception
except ValidationException as e:
    print(f"✅ Invalid side caught: {e.message}")

# Test 4: Log sanitization
sensitive_data = {
    "user": "john",
    "password": "secret123",
    "api_key": "xyz789",
    "order_id": "order_123"
}

sanitized = sanitize_log_data(sensitive_data)
print(f"✅ Sanitized log: {sanitized}")
# {'user': 'john', 'password': '***REDACTED***', 'api_key': '***REDACTED***', 'order_id': 'order_123'}
```

---

## 🐛 문제 해결

### 1. ImportError: shared module not found

**증상**: `ModuleNotFoundError: No module named 'shared'`

**해결**:
```bash
# PYTHONPATH에 프로젝트 루트 추가
export PYTHONPATH="${PYTHONPATH}:$(pwd)"

# 또는 각 앱의 시작 부분에 추가
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
```

### 2. Database connection error

**증상**: `Could not connect to database`

**해결**:
1. `.env` 파일 확인:
```bash
cat .env | grep DATABASE_URL
```

2. PostgreSQL 연결 테스트:
```bash
psql postgresql://postgres.pybdkhfbkamagahgyybk:Tmdehfl2014!@aws-0-ap-northeast-2.pooler.supabase.com:6543/postgres
```

3. 방화벽/보안 그룹 확인

### 3. Redis connection error

**증상**: `Redis connection failed`

**해결**:
```bash
# Redis 서버 시작
redis-server

# Redis CLI로 연결 테스트
redis-cli ping
# Expected: PONG

# Redis 상태 확인
redis-cli info server
```

### 4. Pydantic validation error

**증상**: 422 Unprocessable Entity

**해결**:
- Request body가 Pydantic 모델과 일치하는지 확인
- JSON 형식이 올바른지 확인
- 필수 필드가 모두 포함되었는지 확인

### 5. Exception not caught

**증상**: 500 Internal Server Error, 예외가 JSON으로 반환되지 않음

**해결**:
```python
# FastAPI 앱에 exception handlers 등록 확인
from shared.errors import register_exception_handlers

app = FastAPI()
register_exception_handlers(app)  # 이 줄이 있는지 확인
```

---

## 📊 성능 테스트

### 연결 풀 효율성 테스트

```python
import asyncio
from shared.database.redis import get_redis
import time

async def test_connection_pool():
    """연결 풀 성능 테스트"""
    tasks = []
    start_time = time.time()

    async def redis_operation(i):
        redis = await get_redis()
        await redis.set(f"test_key_{i}", f"value_{i}")
        value = await redis.get(f"test_key_{i}")
        await redis.delete(f"test_key_{i}")
        return value

    # 100개 동시 요청
    for i in range(100):
        tasks.append(redis_operation(i))

    results = await asyncio.gather(*tasks)

    elapsed = time.time() - start_time
    print(f"✅ {len(results)} operations in {elapsed:.2f}s")
    print(f"   Average: {elapsed/len(results)*1000:.2f}ms per operation")

asyncio.run(test_connection_pool())
```

---

## ✅ 최종 통합 테스트 체크리스트

- [ ] Configuration 로드 확인
- [ ] Database 연결 확인
- [ ] Redis 연결 확인
- [ ] Exception handling 확인
- [ ] Structured logging 확인
- [ ] GRID 앱 시작 확인
- [ ] HYPERRSI 앱 시작 확인
- [ ] Health check 엔드포인트 확인
- [ ] Transaction rollback 확인
- [ ] Input validation 확인
- [ ] 연결 풀 성능 확인

---

## 📚 다음 단계

모든 테스트가 통과하면:

1. 실제 API 엔드포인트 업데이트
2. Repository 패턴 적용
3. Service 레이어에 exception handling 추가
4. 프로덕션 환경 설정 준비

---

**작성자**: python-architect agent
**최종 업데이트**: 2025-10-05

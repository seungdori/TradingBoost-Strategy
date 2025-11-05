# Telegram Bot 운영 가이드

마이크로서비스 방식으로 Telegram Bot을 독립적으로 운영하기 위한 가이드입니다.

## 📋 목차

- [개요](#개요)
- [주요 기능](#주요-기능)
- [사용 방법](#사용-방법)
- [운영 명령어](#운영-명령어)
- [문제 해결](#문제-해결)

## 개요

`bot.py`는 HYPERRSI 전략의 Telegram 봇을 독립적으로 실행할 수 있는 마이크로서비스입니다.

**주요 특징:**
- ✅ PID 파일 기반 중복 실행 방지
- ✅ Graceful shutdown (SIGTERM, SIGINT 처리)
- ✅ 자동 재시도 로직 (Telegram API 연결 실패 시)
- ✅ 백그라운드/포그라운드 실행 모드
- ✅ 로그 파일 자동 생성 및 관리

## 주요 기능

### 1. 중복 실행 방지

PID 파일(`bot.pid`)을 사용하여 동일한 봇이 여러 번 실행되는 것을 방지합니다.

```python
# bot.py 내부 로직
- PID 파일 존재 여부 확인
- 기존 프로세스 실행 중인지 검증
- 새 프로세스만 실행 허용
```

### 2. Graceful Shutdown

시그널을 받으면 안전하게 종료합니다:
- Redis 연결 정리
- Telegram API 세션 종료
- PID 파일 제거

### 3. 자동 로그 관리

실행 시마다 새로운 로그 파일을 생성합니다:
```
logs/bot_20251030_143000.log
```

## 사용 방법

### 사전 요구사항

1. **가상환경 활성화**
   ```bash
   cd /Users/seunghyun/TradingBoost-Strategy
   source .venv/bin/activate
   ```

2. **환경 변수 설정**
   ```bash
   # .env 파일에 다음 항목이 설정되어 있어야 함:
   TELEGRAM_BOT_TOKEN=your_bot_token
   OWNER_ID=your_telegram_user_id
   REDIS_HOST=localhost
   REDIS_PORT=6379
   ```

3. **Redis 실행 확인**
   ```bash
   redis-cli ping  # PONG 응답 확인
   ```

### 기본 실행

#### 백그라운드 모드 (권장)
```bash
cd HYPERRSI
./start_bot.sh
```

#### 포그라운드 모드 (디버깅용)
```bash
cd HYPERRSI
./start_bot.sh --foreground
```

#### 직접 실행
```bash
cd HYPERRSI
python bot.py
```

## 운영 명령어

### 1. 봇 시작: `start_bot.sh`

**사용법:**
```bash
./start_bot.sh [옵션]
```

**옵션:**
- `--background` / `-b` : 백그라운드 모드 (기본값)
- `--foreground` / `-f` : 포그라운드 모드

**예시:**
```bash
# 백그라운드로 시작
./start_bot.sh

# 포그라운드로 시작 (로그 직접 확인)
./start_bot.sh --foreground
```

**출력 예시:**
```
==========================================
  Telegram Bot Startup Script
==========================================
✓ Activating virtual environment...
✓ Starting Telegram Bot in background mode...
Log: /Users/seunghyun/TradingBoost-Strategy/HYPERRSI/logs/bot_20251030_143000.log
✓ Bot started successfully (PID: 12345)
Use './stop_bot.sh' to stop the bot
Use 'tail -f logs/bot_20251030_143000.log' to view logs
```

### 2. 봇 종료: `stop_bot.sh`

**사용법:**
```bash
./stop_bot.sh [옵션]
```

**옵션:**
- 옵션 없음: Graceful shutdown (30초 타임아웃)
- `--force` / `-f` : 강제 종료 (SIGKILL)

**예시:**
```bash
# 정상 종료
./stop_bot.sh

# 강제 종료
./stop_bot.sh --force
```

**출력 예시:**
```
==========================================
  Telegram Bot Shutdown Script
==========================================
✓ Stopping Telegram Bot (PID: 12345)...
Sending SIGTERM for graceful shutdown...
.....
✓ Bot stopped gracefully
```

### 3. 봇 상태 확인: `status_bot.sh`

**사용법:**
```bash
./status_bot.sh [옵션]
```

**옵션:**
- 옵션 없음: 기본 상태 정보
- `--verbose` / `-v` : 최근 로그 포함
- `--quick` : 빠른 실행 여부 체크 (exit code만)

**예시:**
```bash
# 기본 상태 확인
./status_bot.sh

# 상세 정보 + 최근 로그
./status_bot.sh --verbose

# 스크립트에서 사용 (실행 여부만 체크)
if ./status_bot.sh --quick; then
    echo "Bot is running"
fi
```

**출력 예시:**
```
==========================================
  Telegram Bot Status
==========================================

PID File: /Users/seunghyun/TradingBoost-Strategy/HYPERRSI/bot.pid
PID: 12345
✓ Status: RUNNING

Process Information:
  PID  PPID  %CPU %MEM     ELAPSED COMMAND
12345     1   0.5  0.3    00:15:30 python bot.py

Latest Log: /Users/seunghyun/TradingBoost-Strategy/HYPERRSI/logs/bot_20251030_143000.log
Log Size: 1.2M

Use './status_bot.sh --verbose' to see recent logs

✓ Bot is running normally
```

## 문제 해결

### 1. 중복 실행 오류

**증상:**
```
Bot is already running with PID 12345
If you're sure it's not running, remove bot.pid
```

**해결:**
```bash
# 1. 상태 확인
./status_bot.sh

# 2-a. 실제로 실행 중이면 종료
./stop_bot.sh

# 2-b. 실행 중이 아니면 PID 파일 제거
rm bot.pid
```

### 2. Telegram API Conflict 오류

**증상:**
```
TelegramConflictError: Telegram server says - Conflict:
terminated by other getUpdates request
```

**원인:**
동일한 봇 토큰으로 여러 프로세스가 실행 중

**해결:**
```bash
# 1. 모든 bot.py 프로세스 확인
pgrep -fl "python.*bot.py"

# 2. 중복 프로세스 종료
./stop_bot.sh

# 3. 프로세스가 남아있다면 수동 종료
kill -15 <PID>

# 4. 재시작
./start_bot.sh
```

### 3. Redis 연결 실패

**증상:**
```
Failed to initialize Redis connection
```

**해결:**
```bash
# 1. Redis 실행 확인
redis-cli ping

# 2. Redis가 실행되지 않았다면 시작
brew services start redis  # macOS
# 또는
sudo systemctl start redis  # Linux

# 3. .env 파일의 Redis 설정 확인
cat ../.env | grep REDIS
```

### 4. 로그 확인

**최근 로그 보기:**
```bash
# 가장 최근 로그 파일 찾기
ls -lt logs/bot_*.log | head -1

# 실시간 로그 보기
tail -f logs/bot_20251030_143000.log

# 에러만 필터링
tail -f logs/bot_20251030_143000.log | grep ERROR
```

### 5. 강제 종료 후 정리

봇이 비정상 종료되었을 때:
```bash
# 1. PID 파일 확인
cat bot.pid

# 2. 프로세스 확인
ps -p <PID>

# 3. PID 파일 제거
rm bot.pid

# 4. 재시작
./start_bot.sh
```

## 마이크로서비스 운영 팁

### 1. 자동 재시작 (선택사항)

Cron이나 systemd를 사용하여 자동 재시작 설정:

**Cron 예시:**
```bash
# crontab -e
*/5 * * * * cd /path/to/HYPERRSI && ./status_bot.sh --quick || ./start_bot.sh
```

### 2. 로그 로테이션

로그 파일이 너무 커지지 않도록 주기적 정리:
```bash
# 7일 이상 된 로그 삭제
find logs/ -name "bot_*.log" -mtime +7 -delete
```

### 3. 모니터링

**간단한 헬스체크 스크립트:**
```bash
#!/bin/bash
if ! ./status_bot.sh --quick; then
    echo "Bot is down! Restarting..."
    ./start_bot.sh
    # Telegram 알림 전송 (선택사항)
fi
```

### 4. 다른 서비스와 통합

**app.py와 함께 실행:**
```bash
# 1. 메인 앱 시작
cd HYPERRSI
python app.py &

# 2. 봇 시작
./start_bot.sh

# 3. 상태 확인
./status_bot.sh
ps aux | grep python | grep HYPERRSI
```

## 디렉토리 구조

```
HYPERRSI/
├── bot.py                  # 봇 메인 파일
├── bot.pid                 # PID 파일 (실행 중일 때만 존재)
├── start_bot.sh           # 시작 스크립트
├── stop_bot.sh            # 종료 스크립트
├── status_bot.sh          # 상태 확인 스크립트
├── logs/                  # 로그 디렉토리
│   └── bot_*.log         # 타임스탬프별 로그 파일
└── src/bot/              # 봇 핸들러 및 로직
    └── handlers.py
```

## 추가 리소스

- **CLAUDE.md**: 프로젝트 전체 가이드
- **src/bot/handlers.py**: 봇 핸들러 구현
- **shared/logging.py**: 로깅 설정
- **shared/config.py**: 환경 설정

## 문의

문제가 지속되면 로그 파일(`logs/bot_*.log`)을 확인하거나 개발팀에 문의하세요.

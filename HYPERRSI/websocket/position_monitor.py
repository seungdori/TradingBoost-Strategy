import asyncio
import base64
import hmac
import json
import logging
import os
import signal
import ssl
import subprocess
import time
import traceback

import websockets

from shared.database.redis import get_redis
from shared.logging import get_logger
from shared.utils import get_contract_size
from HYPERRSI.src.bot.telegram_message import send_telegram_message

# Session/State management services (PostgreSQL SSOT)
from HYPERRSI.src.services.state_service import get_state_service
from HYPERRSI.src.services.state_change_logger import get_state_change_logger
from HYPERRSI.src.core.models.state_change import ChangeType, TriggeredBy

# Trailing stop handler
from HYPERRSI.src.trading.monitoring.trailing_stop_handler import (
    check_trailing_stop,
    get_active_trailing_stops,
    clear_trailing_stop,
)

# Trade stats for PostgreSQL recording
from HYPERRSI.src.trading.stats import update_trading_stats

logger = get_logger(__name__)


def kill_existing_processes():
    """기존에 실행 중인 position_monitor.py 프로세스를 종료"""
    try:
        current_pid = os.getpid()

        # 현재 실행 중인 position_monitor.py 프로세스 찾기
        result = subprocess.run(
            ['ps', 'aux'],
            capture_output=True,
            text=True
        )

        killed_count = 0
        for line in result.stdout.split('\n'):
            if 'position_monitor.py' in line and 'python' in line:
                parts = line.split()
                if len(parts) < 2:
                    continue

                pid = int(parts[1])

                # 자기 자신은 제외
                if pid == current_pid:
                    continue

                try:
                    logger.info(f"🔴 기존 프로세스 종료 중: PID {pid}")
                    os.kill(pid, signal.SIGTERM)
                    killed_count += 1

                    # 프로세스가 종료될 때까지 잠시 대기
                    time.sleep(0.5)

                    # 강제 종료가 필요한 경우
                    try:
                        os.kill(pid, 0)  # 프로세스가 아직 살아있는지 확인
                        logger.warning(f"⚠️ PID {pid} 강제 종료 시도 (SIGKILL)")
                        os.kill(pid, signal.SIGKILL)
                    except ProcessLookupError:
                        # 프로세스가 이미 종료됨
                        pass

                except ProcessLookupError:
                    # 프로세스가 이미 종료됨
                    pass
                except PermissionError:
                    logger.error(f"❌ PID {pid} 종료 권한 없음")
                except Exception as e:
                    logger.error(f"❌ PID {pid} 종료 중 오류: {e}")

        if killed_count > 0:
            logger.info(f"✅ {killed_count}개의 기존 프로세스 종료 완료")
            # 안전을 위해 추가 대기
            time.sleep(1)
        else:
            logger.info("ℹ️ 종료할 기존 프로세스 없음")

    except Exception as e:
        logger.error(f"프로세스 종료 중 오류: {e}")
        logger.error(traceback.format_exc())

# WebSocket URL
OKX_PUBLIC_WS_URL = "wss://ws.okx.com:8443/ws/v5/public"
OKX_PRIVATE_WS_URL = "wss://ws.okx.com:8443/ws/v5/private"

# Rate Limit 설정
CONNECTION_DELAY = 0.5  # 각 사용자 연결 사이 대기 시간 (초) - 200명: 100초 소요
MAX_CONCURRENT_CONNECTIONS = 200  # 최대 동시 연결 수

class OKXWebsocketClient:
    def __init__(
        self,
        user_id: str,
        api_key: str,
        api_secret: str,
        passphrase: str,
        options: dict = None
    ):
        self.user_id = user_id

        self.api_key = api_key
        self.api_secret = api_secret
        self.passphrase = passphrase
        self.options = options or {}

        if not all([self.api_key, self.api_secret, self.passphrase]):
            logger.warning("[OKX] API credentials not found. Private channels will be disabled.")
            self.private_enabled = False
        else:
            self.private_enabled = True

        self.logger = logging.getLogger("OKX_WS_Manager")
        self.public_ws = None
        self.private_ws = None
        self.running = True

        # 이전 포지션 정보 저장 (변경 감지용)
        self.previous_positions = {}

        # 재연결 관련 설정
        self.reconnect_delay = 1  # 초기 재연결 대기 시간 (초)
        self.max_reconnect_delay = 60  # 최대 재연결 대기 시간 (초)
        self.reconnect_attempts = 0
        self.max_reconnect_attempts = 20  # 최대 재연결 시도 횟수

        # 재연결 진행 중 플래그
        self._reconnecting_public = False
        self._reconnecting_private = False

        # 트레일링 스탑 체크 관련
        self._last_trailing_check_time = 0
        self._trailing_check_interval = 1.0  # 1초마다 체크

    async def connect(self):
        """Public/Private WebSocket 모두 연결"""
        ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ssl_context.check_hostname = False
        ssl_context.verify_mode = ssl.CERT_NONE

        # 1) 공개 채널 연결
        self.public_ws = await websockets.connect(OKX_PUBLIC_WS_URL, ssl=ssl_context)
        logger.info("[OKX] Connected to Public WebSocket")

        # 공개 채널: Ticker 구독
        subscribe_public = {
            "op": "subscribe",
            "args": [
                {
                    "channel": "tickers",
                    "instId": "BTC-USDT-SWAP"  # 이 부분이 실제 트레이딩 심볼과 일치해야 함
                }
            ]
        }
        await self.public_ws.send(json.dumps(subscribe_public))
        logger.info("[OKX] Subscribed to public channel (tickers)")

        # 2) 개인 채널 연결 (API 키 있는 경우)
        if self.private_enabled:
            try:
                self.private_ws = await websockets.connect(
                    OKX_PRIVATE_WS_URL,
                    ssl=ssl_context,  # SSL 컨텍스트 추가
                    ping_interval=20,
                    ping_timeout=10
                )
                logger.info("[OKX] Private WebSocket connected")

                # 로그인 시도 (login() 함수 내부에서 응답 처리)
                login_success = await self.login()

                if login_success:
                    # 로그인 성공 후 포지션 및 주문 채널 구독
                    await self.subscribe_private_channels()
                else:
                    logger.error("[OKX] Login failed, skipping channel subscription")
                    self.private_ws = None

            except Exception as e:
                logger.error(f"[OKX] Connection error: {str(e)}")
                self.private_ws = None

    async def login(self):
        """OKX WebSocket 로그인"""
        timestamp = str(int(time.time()))
        message = timestamp + 'GET' + '/users/self/verify'

        # HMAC-SHA256 서명 생성
        mac = hmac.new(
            bytes(self.api_secret, encoding='utf-8'),
            bytes(message, encoding='utf-8'),
            digestmod='sha256'
        )
        d = mac.digest()
        signature = base64.b64encode(d).decode()

        login_message = {
            "op": "login",
            "args": [{
                "apiKey": self.api_key,
                "passphrase": self.passphrase,
                "timestamp": timestamp,
                "sign": signature
            }]
        }

        # 로그인 요청 전송
        await self.private_ws.send(json.dumps(login_message))
        logger.info("[OKX] Sent login request")

        # 로그인 응답 대기
        response = await self.private_ws.recv()
        response_data = json.loads(response)

        if response_data.get('event') == 'login' and response_data.get('code') == '0':
            logger.info("[OKX] Login successful")
            return True
        else:
            logger.error(f"[OKX] Login failed: {response_data}")
            return False

    async def subscribe_private_channels(self):
        """개인 채널 구독 (포지션, 주문, 잔고)"""
        if not self.private_ws:
            logger.warning("[OKX] Private WebSocket not connected, skipping subscription")
            return

        # 포지션 채널 구독 (instType: SWAP = 무기한 선물)
        subscribe_positions = {
            "op": "subscribe",
            "args": [
                {
                    "channel": "positions",
                    "instType": "SWAP"
                }
            ]
        }
        await self.private_ws.send(json.dumps(subscribe_positions))
        logger.info("[OKX] Subscribed to positions channel (SWAP)")

        # 주문 채널 구독
        subscribe_orders = {
            "op": "subscribe",
            "args": [
                {
                    "channel": "orders",
                    "instType": "SWAP"
                }
            ]
        }
        await self.private_ws.send(json.dumps(subscribe_orders))
        logger.info("[OKX] Subscribed to orders channel (SWAP)")

        # 계좌 잔고 채널 구독 (선택사항)
        subscribe_account = {
            "op": "subscribe",
            "args": [
                {
                    "channel": "account"
                }
            ]
        }
        await self.private_ws.send(json.dumps(subscribe_account))
        logger.info("[OKX] Subscribed to account channel")

    async def reconnect_public(self):
        """Public WebSocket 재연결 (Exponential Backoff)"""
        if self._reconnecting_public:
            logger.debug("[OKX] Public 재연결 이미 진행 중...")
            return False

        self._reconnecting_public = True
        delay = self.reconnect_delay

        try:
            for attempt in range(1, self.max_reconnect_attempts + 1):
                if not self.running:
                    logger.info("[OKX] 클라이언트 종료 중 - Public 재연결 취소")
                    return False

                try:
                    logger.info(f"🔄 [OKX] Public WebSocket 재연결 시도 {attempt}/{self.max_reconnect_attempts}...")

                    # 기존 연결 정리
                    if self.public_ws:
                        try:
                            await self.public_ws.close()
                        except Exception:
                            pass
                        self.public_ws = None

                    # 새 연결 생성
                    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                    self.public_ws = await websockets.connect(
                        OKX_PUBLIC_WS_URL,
                        ssl=ssl_context,
                        ping_interval=20,
                        ping_timeout=10
                    )

                    # Ticker 구독
                    subscribe_public = {
                        "op": "subscribe",
                        "args": [{"channel": "tickers", "instId": "BTC-USDT-SWAP"}]
                    }
                    await self.public_ws.send(json.dumps(subscribe_public))

                    logger.info(f"✅ [OKX] Public WebSocket 재연결 성공 (시도 {attempt}회)")
                    self.reconnect_attempts = 0  # 성공 시 카운터 리셋
                    return True

                except Exception as e:
                    logger.warning(f"⚠️ [OKX] Public 재연결 실패 (시도 {attempt}): {e}")
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self.max_reconnect_delay)  # Exponential Backoff

            logger.error(f"❌ [OKX] Public 재연결 최대 시도 횟수 초과 ({self.max_reconnect_attempts}회)")
            return False

        finally:
            self._reconnecting_public = False

    async def reconnect_private(self):
        """Private WebSocket 재연결 (Exponential Backoff)"""
        if not self.private_enabled:
            return False

        if self._reconnecting_private:
            logger.debug("[OKX] Private 재연결 이미 진행 중...")
            return False

        self._reconnecting_private = True
        delay = self.reconnect_delay

        try:
            for attempt in range(1, self.max_reconnect_attempts + 1):
                if not self.running:
                    logger.info("[OKX] 클라이언트 종료 중 - Private 재연결 취소")
                    return False

                try:
                    logger.info(f"🔄 [OKX] Private WebSocket 재연결 시도 {attempt}/{self.max_reconnect_attempts}...")

                    # 기존 연결 정리
                    if self.private_ws:
                        try:
                            await self.private_ws.close()
                        except Exception:
                            pass
                        self.private_ws = None

                    # 새 연결 생성
                    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE

                    self.private_ws = await websockets.connect(
                        OKX_PRIVATE_WS_URL,
                        ssl=ssl_context,
                        ping_interval=20,
                        ping_timeout=10
                    )

                    # 로그인
                    login_success = await self.login()
                    if not login_success:
                        raise Exception("로그인 실패")

                    # 채널 구독
                    await self.subscribe_private_channels()

                    logger.info(f"✅ [OKX] Private WebSocket 재연결 성공 (시도 {attempt}회)")
                    self.reconnect_attempts = 0
                    return True

                except Exception as e:
                    logger.warning(f"⚠️ [OKX] Private 재연결 실패 (시도 {attempt}): {e}")
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, self.max_reconnect_delay)

            logger.error(f"❌ [OKX] Private 재연결 최대 시도 횟수 초과 ({self.max_reconnect_attempts}회)")
            return False

        finally:
            self._reconnecting_private = False

    async def handle_service_upgrade_notice(self, ws_type: str, data: dict):
        """64008 서비스 업그레이드 알림 처리 - 선제적 재연결"""
        code = data.get('code', '')
        if code == '64008':
            logger.warning(f"⚠️ [OKX] {ws_type} 서비스 업그레이드 예고 감지! 선제적 재연결 시작...")

            # 약간의 딜레이 후 재연결 (즉시 하면 기존 연결이 아직 유효해서 충돌 가능)
            await asyncio.sleep(2)

            if ws_type == "Public":
                success = await self.reconnect_public()
            else:  # Private
                success = await self.reconnect_private()

            if success:
                logger.info(f"✅ [OKX] {ws_type} 선제적 재연결 완료")
            else:
                logger.error(f"❌ [OKX] {ws_type} 선제적 재연결 실패")

            return True  # 64008 처리됨
        return False  # 64008이 아님

    async def handle_public_messages(self):
        """공개 채널(tickers)에서 들어오는 메시지를 Redis에 저장 (자동 재연결 포함)"""
        redis = await get_redis()
        while self.running:
            try:
                # WebSocket 연결 확인
                if not self.public_ws:
                    logger.warning("[OKX] Public WebSocket 연결 없음 - 재연결 시도...")
                    if not await self.reconnect_public():
                        await asyncio.sleep(5)
                        continue

                message = await self.public_ws.recv()
                data = json.loads(message)

                if "event" in data:
                    logger.info(f"[OKX] Public event: {data}")

                    # 64008 서비스 업그레이드 알림 처리 (선제적 재연결)
                    if data.get('code') == '64008':
                        asyncio.create_task(self.handle_service_upgrade_notice("Public", data))
                        continue

                elif "data" in data:
                    channel = data.get("arg", {}).get("channel")
                    inst_id = data.get("arg", {}).get("instId", "unknown")
                    if channel == "tickers":
                        redis_key = f"ws:okx:tickers:{inst_id}"
                        await redis.set(redis_key, json.dumps(data["data"]))

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"[OKX] Public WebSocket 연결 종료: {e}")
                if self.running:
                    logger.info("[OKX] Public WebSocket 자동 재연결 시도...")
                    if await self.reconnect_public():
                        continue  # 재연결 성공 시 루프 계속
                    else:
                        logger.error("[OKX] Public WebSocket 재연결 실패 - 5초 후 재시도")
                        await asyncio.sleep(5)
                        continue
                else:
                    break

            except Exception as e:
                logger.error(f"[OKX] Error in public message loop: {e}")
                from HYPERRSI.src.utils.error_logger import async_log_error_to_db
                await async_log_error_to_db(
                    error=e,
                    severity="ERROR",
                    metadata={"component": "websocket_public_message_loop"}
                )
                await asyncio.sleep(1)

    async def handle_private_messages(self, user_id: str):
        """
        개인 채널(positions, orders) 메시지를 Redis에 저장 (자동 재연결 포함).
        posSide가 net/long/short인지에 따라 key를 달리 저장할 수 있음.
        """
        if not self.private_enabled:
            logger.warning("[OKX] Private websocket is disabled.")
            return

        redis = await get_redis()
        while self.running:
            try:
                # WebSocket 연결 확인
                if not self.private_ws:
                    logger.warning("[OKX] Private WebSocket 연결 없음 - 재연결 시도...")
                    if not await self.reconnect_private():
                        await asyncio.sleep(5)
                        continue

                message = await self.private_ws.recv()
                data = json.loads(message)
                logger.debug(f"[OKX] Private Message: {data}")

                # 🔄 WebSocket heartbeat 업데이트 (core.py 폴백 판단용)
                # 메시지를 받을 때마다 heartbeat 갱신 (2분 TTL)
                heartbeat_key = "ws:position_monitor:heartbeat"
                await redis.set(heartbeat_key, str(time.time()), ex=120)

                if "event" in data:
                    logger.info(f"[OKX] Private event: {data}")

                    # 64008 서비스 업그레이드 알림 처리 (선제적 재연결)
                    if data.get('code') == '64008':
                        asyncio.create_task(self.handle_service_upgrade_notice("Private", data))
                        continue
                elif "data" in data:
                    channel = data.get("arg", {}).get("channel")
                    inst_id = data.get("arg", {}).get("instId", "unknown")
                    inst_type = data.get("arg", {}).get("instType", "unknown")
                    payload = data["data"]  # 실제 포지션/오더 정보 리스트

                    if channel == "positions":
                        # OKX Position 모드(net/long/short 등) 유의
                        # payload가 여러 포지션일 수도 있음
                        position_changed = False
                        for pos in payload:
                            # 예: posSide가 "net"인 경우 -> side="net"
                            side = pos.get("posSide", "unknown").lower()
                            symbol = pos.get("instId", inst_id)
                            pos_size = pos.get("pos", "0")

                            # 포지션 키 생성
                            position_key = f"{symbol}:{side}"

                            # 이전 포지션 사이즈와 비교
                            previous_size = self.previous_positions.get(position_key, "0")

                            # 포지션 변경 감지 (사이즈 변경 또는 새로운 포지션)
                            if previous_size != pos_size:
                                position_changed = True
                                self.previous_positions[position_key] = pos_size

                                # 변경된 포지션만 로그 출력
                                if float(pos_size) == 0:
                                    logger.info(f"🔴 포지션 청산: {symbol} | Side: {side} | 이전: {previous_size}")

                                    # 수동 청산 감지 및 텔레그램 알림
                                    # (TP/SL 체결이 아닌 경우 = Redis에 pending_manual_close가 설정되지 않은 경우)
                                    try:
                                        # 수동 청산 여부 확인 (최근 1초 이내에 TP/SL 주문 체결이 없었는지 확인)
                                        manual_close_check_key = f"ws:position_closed:{user_id}:{symbol}:{side}"
                                        is_manual_close = await redis.get(manual_close_check_key)

                                        # Redis에서 활성화된 TP/SL/브레이크이븐 주문 확인 (타이밍 이슈 대비)
                                        has_active_exit_orders = False
                                        if not is_manual_close:
                                            # monitor 주문 패턴으로 검색 (break_even, sl, tp1, tp2, tp3)
                                            monitor_pattern = f"monitor:user:{user_id}:{symbol}:order:*"
                                            monitor_keys = await redis.keys(monitor_pattern)

                                            for key in monitor_keys:
                                                order_info = await redis.hgetall(key)
                                                if order_info:
                                                    order_type = order_info.get("order_type", "")
                                                    order_name = order_info.get("order_name", "")
                                                    pos_side_in_order = order_info.get("pos_side", "")

                                                    # 같은 포지션 방향의 청산 주문 확인
                                                    if pos_side_in_order == side:
                                                        # order_type이나 order_name에 tp/sl/break_even이 포함되어 있으면
                                                        if any(exit_type in order_type.lower() for exit_type in ["tp", "sl", "break_even"]) or \
                                                           any(exit_type in order_name.lower() for exit_type in ["tp", "sl", "break_even"]):
                                                            has_active_exit_orders = True
                                                            logger.info(f"🔍 활성 청산 주문 감지: {order_type or order_name}, Key: {key}")
                                                            break

                                        if not is_manual_close and not has_active_exit_orders:
                                            # 수동 청산으로 판단 - 중복 알림 방지 플래그 설정 (5초 TTL)
                                            await redis.set(manual_close_check_key, "1", ex=5)

                                            # 포지션 정보 조회
                                            position_key = f"user:{user_id}:position:{symbol}:{side}"
                                            position_data = await redis.hgetall(position_key)

                                            # PnL 계산
                                            entry_price = float(position_data.get(b"entry_price" if isinstance(list(position_data.keys())[0], bytes) else "entry_price", "0")) if position_data else 0

                                            # 현재가 조회 (청산 시점의 가격)
                                            avg_px = pos.get("avgPx", "")
                                            mark_px = pos.get("markPx", "")

                                            # avgPx 우선, 없거나 빈 문자열이면 markPx 사용
                                            try:
                                                current_price = float(avg_px) if avg_px and avg_px != "" else (float(mark_px) if mark_px and mark_px != "" else 0)
                                            except (ValueError, TypeError):
                                                logger.warning(f"가격 변환 실패: avgPx={avg_px}, markPx={mark_px}")
                                                current_price = 0

                                            pnl_text = ""
                                            if entry_price > 0 and current_price > 0:
                                                leverage = float(position_data.get(b"leverage" if isinstance(list(position_data.keys())[0], bytes) else "leverage", "1")) if position_data else 1

                                                if side == "long":
                                                    pnl_percent = ((current_price / entry_price) - 1) * 100
                                                else:  # short
                                                    pnl_percent = ((entry_price / current_price) - 1) * 100

                                                pnl_icon = "📈" if pnl_percent > 0 else "📉"
                                                pnl_text = f"\n{pnl_icon} 수익률: {pnl_percent:.2f}%"

                                                if leverage > 1:
                                                    leveraged_pnl = pnl_percent * leverage
                                                    pnl_text += f" (레버리지 x{leverage} 적용: {leveraged_pnl:.2f}%)"

                                            # 텔레그램 메시지 전송
                                            # contract 수량을 실제 수량으로 변환
                                            contract_size = await get_contract_size(symbol, redis)
                                            actual_size = float(previous_size) * contract_size
                                            # 수량 포맷팅 (trailing zeros 제거, 천단위 콤마)
                                            size_formatted = f"{actual_size:,}" if actual_size >= 1000 else f"{actual_size:g}"

                                            price_text = f"{current_price:,.3f}" if current_price > 0 else "정보 없음"
                                            message = (
                                                f"🔵  수동 청산 감지\n"
                                                f"━━━━━━━━━━━━━━━\n"
                                                f"심볼: {symbol}\n"
                                                f"방향: {side.upper()}\n"
                                                f"청산 수량: {size_formatted}\n"
                                                f"청산가격: {price_text}{pnl_text}"
                                            )

                                            await send_telegram_message(message, user_id)
                                            logger.info(f"✉️  수동 청산 텔레그램 알림 전송: {user_id}, {symbol}, {side}")

                                            # 상태 변경 로깅 (PostgreSQL SSOT) - 수동 청산
                                            try:
                                                state_change_logger = get_state_change_logger()
                                                await state_change_logger.log_change(
                                                    okx_uid=user_id,
                                                    symbol=symbol,
                                                    change_type=ChangeType.MANUAL_CLOSE,
                                                    previous_state=dict(position_data) if position_data else None,
                                                    new_state=None,
                                                    price=current_price if current_price > 0 else None,
                                                    pnl_percent=pnl_percent if entry_price > 0 and current_price > 0 else None,
                                                    triggered_by=TriggeredBy.EXCHANGE,
                                                    trigger_source='position_monitor.manual_close',
                                                    extra_data={
                                                        'side': side,
                                                        'close_price': current_price,
                                                        'entry_price': entry_price,
                                                        'previous_size': previous_size
                                                    }
                                                )
                                                logger.debug(f"📝  수동 청산 기록: {user_id}, {symbol}, {side}")
                                            except Exception as log_err:
                                                logger.warning(f"상태 변경 로깅 실패 (무시됨): {log_err}")

                                            # PostgreSQL 거래 기록 저장 (hyperrsi_trades 테이블)
                                            try:
                                                from datetime import datetime

                                                # position_data가 bytes 키를 사용하는지 확인
                                                is_bytes_key = position_data and len(position_data) > 0 and isinstance(list(position_data.keys())[0], bytes)

                                                def get_pos_value(key: str, default: str = "") -> str:
                                                    """position_data에서 값을 안전하게 추출"""
                                                    if not position_data:
                                                        return default
                                                    k = key.encode() if is_bytes_key else key
                                                    val = position_data.get(k, default)
                                                    if isinstance(val, bytes):
                                                        return val.decode()
                                                    return str(val) if val else default

                                                # 필수 필드 추출
                                                entry_time_str = get_pos_value("entry_time", "")
                                                leverage = int(float(get_pos_value("leverage", "1") or "1"))
                                                dca_count = int(get_pos_value("dca_count", "0") or "0")
                                                avg_entry_price_str = get_pos_value("avg_entry_price", "")
                                                avg_entry_price = float(avg_entry_price_str) if avg_entry_price_str else None
                                                entry_order_id = get_pos_value("entry_order_id", "")

                                                # 수수료 정보 (OKX에서 제공되는 경우)
                                                entry_fee = float(get_pos_value("entry_fee", "0") or "0")
                                                exit_fee = float(pos.get("fee", "0") or "0") if pos.get("fee") else 0.0

                                                # PnL 계산 (실제 금액)
                                                pnl_amount = 0.0
                                                if entry_price > 0 and current_price > 0 and actual_size > 0:
                                                    if side == "long":
                                                        pnl_amount = (current_price - entry_price) * actual_size
                                                    else:  # short
                                                        pnl_amount = (entry_price - current_price) * actual_size

                                                exit_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                                                await update_trading_stats(
                                                    user_id=user_id,
                                                    symbol=symbol,
                                                    entry_price=entry_price,
                                                    exit_price=current_price,
                                                    position_size=actual_size,
                                                    pnl=pnl_amount,
                                                    side=side,
                                                    entry_time=entry_time_str if entry_time_str else exit_time_str,
                                                    exit_time=exit_time_str,
                                                    close_type="manual",
                                                    leverage=leverage,
                                                    dca_count=dca_count,
                                                    avg_entry_price=avg_entry_price,
                                                    entry_fee=entry_fee,
                                                    exit_fee=abs(exit_fee),  # 수수료는 양수로 저장
                                                    entry_order_id=entry_order_id if entry_order_id else None,
                                                    extra_data={
                                                        "source": "websocket_manual_close",
                                                        "previous_size_contracts": previous_size,
                                                    }
                                                )
                                                logger.info(f"📊  거래 기록 DB 저장: {user_id}, {symbol}, {side}, PnL={pnl_amount:.4f}, DCA={dca_count}")
                                            except Exception as db_err:
                                                logger.warning(f"거래 기록 DB 저장 실패 (무시됨): {db_err}")

                                    except Exception as e:
                                        logger.error(f"수동 청산 알림 전송 실패: {e}")
                                        traceback.print_exc()

                                elif float(previous_size) == 0:
                                    logger.info(f"🟢 포지션 진입: {symbol} | Side: {side} | Size: {pos_size}")
                                else:
                                    logger.info(f"📊 포지션 변경: {symbol} | Side: {side} | {previous_size} → {pos_size}")

                                logger.debug(f"  📝 Full data: {pos}")

                            # 예시) ws:user:1709556958:BTC-USDT-SWAP:long
                            redis_key = f"ws:user:{user_id}:{symbol}:{side}"
                            await redis.set(redis_key, json.dumps(pos))

                            # 🔹 트레일링 스탑 체크 (포지션이 존재하고 유효한 가격이 있을 때만)
                            if float(pos_size) > 0 and side in ["long", "short"]:
                                try:
                                    # 현재가 추출 (markPx 우선, 없으면 avgPx)
                                    mark_px = pos.get("markPx", "")
                                    avg_px = pos.get("avgPx", "")

                                    try:
                                        current_price = float(mark_px) if mark_px and mark_px != "" else (float(avg_px) if avg_px and avg_px != "" else 0)
                                    except (ValueError, TypeError):
                                        current_price = 0

                                    if current_price > 0:
                                        # 트레일링 스탑 체크 (1초 간격 제한)
                                        current_check_time = time.time()
                                        if current_check_time - self._last_trailing_check_time >= self._trailing_check_interval:
                                            self._last_trailing_check_time = current_check_time

                                            # 트레일링 스탑 조건 체크 (비동기 태스크로 실행하여 메인 루프 차단 방지)
                                            asyncio.create_task(self._check_trailing_stop_for_position(
                                                user_id=user_id,
                                                symbol=symbol,
                                                direction=side,
                                                current_price=current_price
                                            ))
                                except Exception as ts_err:
                                    logger.debug(f"트레일링 스탑 체크 중 오류 (무시됨): {ts_err}")

                    elif channel == "orders":
                        logger.info(f"📝  Order Update - instType: {inst_type}, count: {len(payload)}")
                        # 주문 정보도 여러 개가 들어올 수 있음 => 통째로 저장
                        for order in payload:
                            symbol = order.get("instId", inst_id)
                            order_id = order.get("ordId", "unknown")
                            order_type = order.get("ordType", "unknown")
                            state = order.get("state", "unknown")
                            side = order.get("side", "unknown")
                            pos_side = order.get("posSide", "unknown")
                            filled_size = order.get("accFillSz", "0")
                            price_str = order.get("avgPx", order.get("px", "0"))
                            reduce_only = order.get("reduceOnly", "false")

                            logger.info(f"  📋 Order: {symbol} | ID: {order_id} | Type: {order_type} | Side: {side} | State: {state}")

                            # TP/SL 주문 체결 감지 및 Telegram 알림 (limit 주문이면서 reduceOnly인 경우)
                            if state == "filled" and order_type == "limit" and reduce_only == "true":
                                try:
                                    # 중복 알림 방지: Redis에 15초 TTL로 알림 전송 이력 저장
                                    notification_key = f"ws_notification:user:{user_id}:order:{order_id}"
                                    already_notified = await redis.get(notification_key)

                                    if already_notified:
                                        logger.info(f"⏭️ 이미 WebSocket 알림 전송됨: {order_id}, 중복 방지")
                                        continue

                                    # TP/SL 주문 체결 시 수동 청산 알림 방지 플래그 설정
                                    # (포지션 변화 감지보다 주문 체결이 먼저 올 수도, 나중에 올 수도 있음)
                                    manual_close_check_key = f"ws:position_closed:{user_id}:{symbol}:{pos_side}"
                                    await redis.set(manual_close_check_key, "1", ex=5)  # 5초 TTL

                                    # Redis에서 주문 정보 조회하여 order_type 확인
                                    monitor_order_key = f"monitor:user:{user_id}:{symbol}:order:{order_id}"
                                    order_data_from_redis = await redis.hgetall(monitor_order_key)

                                    # order_type 추출 (tp1, tp2, tp3, sl, break_even 등)
                                    actual_order_type = order_data_from_redis.get("order_type", "unknown") if order_data_from_redis else "unknown"
                                    order_name = order_data_from_redis.get("order_name", "") if order_data_from_redis else ""

                                    # order_type이 limit/market이면 order_name 확인
                                    if actual_order_type in ["limit", "market", "unknown"]:
                                        actual_order_type = order_name if order_name else actual_order_type

                                    # Redis에서 포지션 정보 조회하여 PnL 계산
                                    position_key = f"user:{user_id}:position:{symbol}:{pos_side}"
                                    position_data = await redis.hgetall(position_key)

                                    price = float(price_str)
                                    entry_price = float(position_data.get("entry_price", "0")) if position_data else 0
                                    leverage = float(position_data.get("leverage", "1")) if position_data else 1

                                    # PnL 계산
                                    pnl_text = ""
                                    if entry_price > 0:
                                        if pos_side == "long":
                                            pnl_percent = ((price / entry_price) - 1) * 100
                                        else:  # short
                                            pnl_percent = ((entry_price / price) - 1) * 100

                                        pnl_icon = "📈" if pnl_percent > 0 else "📉"
                                        pnl_text = f"\n{pnl_icon} 수익률: {pnl_percent:.2f}%"

                                        # 레버리지 적용 수익률
                                        if leverage > 1:
                                            leveraged_pnl = pnl_percent * leverage
                                            pnl_text += f" (레버리지 x{leverage} 적용: {leveraged_pnl:.2f}%)"

                                    # 메시지 타이틀 설정 (order_type 기반)
                                    if actual_order_type == "break_even":
                                        title = "🟡 브레이크이븐 체결 완료"
                                    elif actual_order_type == "sl":
                                        title = "🔴 손절(SL) 체결 완료"
                                    elif actual_order_type == "tp3":
                                        title = "🟢 익절(TP3) 체결 완료"
                                    elif actual_order_type == "tp2":
                                        title = "🟢 익절(TP2) 체결 완료"
                                    elif actual_order_type == "tp1":
                                        title = "🟢 익절(TP1) 체결 완료"
                                    else:
                                        title = "✅ 주문 체결 완료"

                                    message = (
                                        f"{title}\n"
                                        f"━━━━━━━━━━━━━━━\n"
                                        f"심볼: {symbol}\n"
                                        f"방향: {pos_side.upper()}\n"
                                        f"체결가격: {round(price, 3)}\n"
                                        f"체결수량: {round(float(filled_size), 4)}{pnl_text}"
                                    )

                                    # 알림 전송 (파라미터 순서: message, okx_uid)
                                    await send_telegram_message(message, user_id)

                                    # 알림 전송 성공 후 Redis에 이력 저장 (15초 TTL)
                                    await redis.set(notification_key, "1", ex=15)

                                    logger.info(f"✉️ [WebSocket] Telegram 알림 전송 완료: {user_id}, 메시지: {title}")

                                    # 상태 변경 로깅 (PostgreSQL SSOT) - TP/SL 체결
                                    try:
                                        state_change_logger = get_state_change_logger()

                                        # change_type 결정
                                        if "손절(SL)" in title:
                                            change_type = ChangeType.SL_HIT
                                        elif "브레이크이븐" in title:
                                            change_type = ChangeType.BREAK_EVEN_HIT
                                        elif "익절(TP" in title:
                                            change_type = ChangeType.TP_HIT
                                        else:
                                            change_type = ChangeType.ORDER_FILLED

                                        # PnL 계산값 추출 (위에서 이미 계산됨)
                                        pnl_percent_value = None
                                        if entry_price > 0:
                                            if pos_side == "long":
                                                pnl_percent_value = ((price / entry_price) - 1) * 100
                                            else:  # short
                                                pnl_percent_value = ((entry_price / price) - 1) * 100

                                        await state_change_logger.log_change(
                                            okx_uid=user_id,
                                            symbol=symbol,
                                            change_type=change_type,
                                            previous_state=dict(position_data) if position_data else None,
                                            new_state={'order_id': order_id, 'filled_size': filled_size},
                                            price=price,
                                            pnl_percent=pnl_percent_value,
                                            triggered_by=TriggeredBy.EXCHANGE,
                                            trigger_source='position_monitor.order_filled',
                                            extra_data={
                                                'order_id': order_id,
                                                'order_type': actual_order_type,
                                                'pos_side': pos_side,
                                                'entry_price': entry_price,
                                                'fill_price': price,
                                                'filled_size': filled_size
                                            }
                                        )
                                        logger.debug(f"📝 [StateChange] 주문 체결 기록: {user_id}, {symbol}, {actual_order_type}")
                                    except Exception as log_err:
                                        logger.warning(f"상태 변경 로깅 실패 (무시됨): {log_err}")

                                    # PostgreSQL 거래 기록 저장 (hyperrsi_trades 테이블) - TP/SL 체결
                                    try:
                                        from datetime import datetime

                                        # close_type 결정
                                        if "손절(SL)" in title:
                                            close_type_for_db = "stop_loss"
                                        elif "브레이크이븐" in title:
                                            close_type_for_db = "break_even"
                                        elif "TP3" in title:
                                            close_type_for_db = "take_profit_3"
                                        elif "TP2" in title:
                                            close_type_for_db = "take_profit_2"
                                        elif "TP1" in title:
                                            close_type_for_db = "take_profit_1"
                                        else:
                                            close_type_for_db = "take_profit"

                                        # position_data에서 필드 추출 (안전하게)
                                        entry_time_str = position_data.get("entry_time", "") if position_data else ""
                                        dca_count = int(position_data.get("dca_count", "0") or "0") if position_data else 0
                                        avg_entry_price_str = position_data.get("avg_entry_price", "") if position_data else ""
                                        avg_entry_price = float(avg_entry_price_str) if avg_entry_price_str else None
                                        entry_order_id = position_data.get("entry_order_id", "") if position_data else ""
                                        entry_fee = float(position_data.get("entry_fee", "0") or "0") if position_data else 0.0

                                        # 주문에서 수수료 추출
                                        exit_fee = abs(float(order.get("fee", "0") or "0"))

                                        # 실제 수량 계산 (contracts -> quantity)
                                        contract_size = await get_contract_size(symbol, redis)
                                        actual_size = float(filled_size) * contract_size

                                        # PnL 계산 (실제 금액)
                                        pnl_amount = 0.0
                                        if entry_price > 0 and price > 0 and actual_size > 0:
                                            if pos_side == "long":
                                                pnl_amount = (price - entry_price) * actual_size
                                            else:  # short
                                                pnl_amount = (entry_price - price) * actual_size

                                        exit_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                                        await update_trading_stats(
                                            user_id=user_id,
                                            symbol=symbol,
                                            entry_price=entry_price,
                                            exit_price=price,
                                            position_size=actual_size,
                                            pnl=pnl_amount,
                                            side=pos_side,
                                            entry_time=entry_time_str if entry_time_str else exit_time_str,
                                            exit_time=exit_time_str,
                                            close_type=close_type_for_db,
                                            leverage=int(leverage),
                                            dca_count=dca_count,
                                            avg_entry_price=avg_entry_price,
                                            entry_fee=entry_fee,
                                            exit_fee=exit_fee,
                                            entry_order_id=entry_order_id if entry_order_id else None,
                                            exit_order_id=order_id,
                                            extra_data={
                                                "source": "websocket_order_filled",
                                                "order_type": actual_order_type,
                                                "filled_size_contracts": filled_size,
                                            }
                                        )
                                        logger.info(f"📊 [WebSocket] TP/SL 거래 기록 DB 저장: {user_id}, {symbol}, {pos_side}, close_type={close_type_for_db}, PnL={pnl_amount:.4f}, DCA={dca_count}")
                                    except Exception as db_err:
                                        logger.warning(f"TP/SL 거래 기록 DB 저장 실패 (무시됨): {db_err}")

                                    # TP 주문 체결 시 브레이크이븐/트레일링스탑 처리
                                    if "익절(TP" in title:
                                        try:
                                            # TP 레벨 추출 (TP1, TP2, TP3)
                                            if "TP1" in title:
                                                order_type_for_breakeven = "tp1"
                                                tp_level = 1
                                            elif "TP2" in title:
                                                order_type_for_breakeven = "tp2"
                                                tp_level = 2
                                            elif "TP3" in title:
                                                order_type_for_breakeven = "tp3"
                                                tp_level = 3
                                            else:
                                                order_type_for_breakeven = "tp1"
                                                tp_level = 1

                                            # Lazy import to avoid circular dependency
                                            from HYPERRSI.src.trading.monitoring.break_even_handler import process_break_even_settings
                                            from HYPERRSI.src.trading.monitoring.utils import is_true_value
                                            from HYPERRSI.src.trading.monitoring.telegram_service import get_identifier
                                            from shared.database.redis_helper import get_redis_client
                                            from shared.utils.redis_utils import get_user_settings

                                            # 사용자 설정 확인
                                            try:
                                                # user_id를 OKX UID로 변환
                                                okx_uid = await get_identifier(str(user_id))
                                                redis_client = await get_redis_client()
                                                settings = await get_user_settings(redis_client, okx_uid)
                                                use_break_even_tp1 = is_true_value(settings.get('use_break_even', False))
                                                use_break_even_tp2 = is_true_value(settings.get('use_break_even_tp2', False))
                                                use_break_even_tp3 = is_true_value(settings.get('use_break_even_tp3', False))
                                                trailing_stop_active = is_true_value(settings.get('trailing_stop_active', False))
                                                trailing_start_point = str(settings.get('trailing_start_point', 'tp3')).lower()

                                                # 브레이크이븐 발동 여부 체크
                                                breakeven_will_trigger = False
                                                trailing_will_trigger = False

                                                if tp_level == 1 and use_break_even_tp1:
                                                    breakeven_will_trigger = True
                                                elif tp_level == 2 and use_break_even_tp2:
                                                    breakeven_will_trigger = True
                                                elif tp_level == 3 and use_break_even_tp3:
                                                    breakeven_will_trigger = True

                                                # 트레일링스탑 발동 여부 체크
                                                current_tp = f"tp{tp_level}"
                                                if trailing_stop_active and current_tp.lower() == trailing_start_point:
                                                    trailing_will_trigger = True

                                                # 추가 알림 메시지 구성
                                                additional_info = ""
                                                if breakeven_will_trigger:
                                                    additional_info += "\n🔧 브레이크이븐 발동 예정 (SL 이동)"
                                                if trailing_will_trigger:
                                                    additional_info += "\n🔹 트레일링스탑 활성화 예정"

                                                if additional_info:
                                                    # 추가 정보가 있으면 별도 메시지 전송
                                                    await send_telegram_message(
                                                        f"━━━━━━━━━━━━━━━\n{additional_info.strip()}",
                                                        user_id
                                                    )
                                                    logger.info(f"🔔 [WebSocket] 추가 기능 알림 전송: {additional_info.strip()}")

                                            except Exception as settings_error:
                                                logger.error(f"설정 확인 중 오류: {settings_error}")

                                            # 브레이크이븐 처리 (비동기 태스크로 실행)
                                            asyncio.create_task(process_break_even_settings(
                                                user_id=user_id,
                                                symbol=symbol,
                                                order_type=order_type_for_breakeven,
                                                position_data=position_data
                                            ))
                                            logger.info(f"🔧 [WebSocket] 브레이크이븐 처리 시작: {user_id}, {symbol}, {order_type_for_breakeven}")
                                        except Exception as breakeven_error:
                                            logger.error(f"브레이크이븐 처리 중 오류: {breakeven_error}")
                                            traceback.print_exc()

                                except Exception as e:
                                    logger.error(f"Telegram 알림 전송 실패: {e}")
                                    traceback.print_exc()

                        redis_key = f"ws:user:{user_id}:{inst_id}:open_orders"
                        await redis.set(redis_key, json.dumps(payload))

                    elif channel == "account":
                        logger.debug(f"💰 [OKX] Account Update - details: {len(payload)} items")
                        for acc_detail in payload:
                            logger.debug(f"  Account detail: {acc_detail}")

            except websockets.exceptions.ConnectionClosed as e:
                logger.warning(f"[OKX] Private WebSocket 연결 종료: {e}")
                if self.running:
                    logger.info("[OKX] Private WebSocket 자동 재연결 시도...")
                    if await self.reconnect_private():
                        continue  # 재연결 성공 시 루프 계속
                    else:
                        logger.error("[OKX] Private WebSocket 재연결 실패 - 5초 후 재시도")
                        await asyncio.sleep(5)
                        continue
                else:
                    break

            except Exception as e:
                logger.error(f"[OKX] Error in private message loop: {e}")
                from HYPERRSI.src.utils.error_logger import async_log_error_to_db
                await async_log_error_to_db(
                    error=e,
                    user_id=user_id,
                    severity="ERROR",
                    metadata={"component": "websocket_private_message_loop"}
                )
                await asyncio.sleep(1)

    async def run(self, user_id: str):
        """Public/Private WebSocket 연결 후, 메시지 처리 루프 실행"""
        await self.connect()
        public_task = asyncio.create_task(self.handle_public_messages())
        private_task = None

        if self.private_enabled:
            private_task = asyncio.create_task(self.handle_private_messages(user_id))

        if private_task:
            await asyncio.gather(public_task, private_task)
        else:
            await public_task

    async def _check_trailing_stop_for_position(
        self,
        user_id: str,
        symbol: str,
        direction: str,
        current_price: float
    ):
        """
        특정 포지션에 대해 트레일링 스탑 조건을 체크합니다.

        Args:
            user_id: 사용자 ID (OKX UID)
            symbol: 심볼 (예: BTC-USDT-SWAP)
            direction: 포지션 방향 (long/short)
            current_price: 현재 가격
        """
        try:
            redis = await get_redis()

            # 트레일링 스탑 키 확인
            trailing_key = f"trailing:user:{user_id}:{symbol}:{direction}"

            if not await redis.exists(trailing_key):
                return  # 트레일링 스탑이 활성화되지 않음

            # 트레일링 스탑 데이터 조회
            ts_data = await redis.hgetall(trailing_key)
            if not ts_data:
                return

            # bytes를 str로 변환
            def decode_value(v):
                return v.decode() if isinstance(v, bytes) else v

            active = decode_value(ts_data.get(b"active") or ts_data.get("active", "false"))
            if active.lower() != "true":
                return

            # 이미 triggered 상태이면 스킵
            status = decode_value(ts_data.get(b"status") or ts_data.get("status", ""))
            if status == "triggered":
                return

            # check_trailing_stop 함수 호출 (trailing_stop_handler.py의 함수)
            ts_hit = await check_trailing_stop(user_id, symbol, direction, current_price)

            if ts_hit:
                logger.info(f"🔔 [WebSocket] 트레일링 스탑 조건 충족: {user_id} {symbol} {direction} @ {current_price}")

        except Exception as e:
            logger.error(f"[WebSocket] 트레일링 스탑 체크 오류: {user_id} {symbol} {direction} - {str(e)}")
            traceback.print_exc()

    def stop(self):
        """루프 종료"""
        self.running = False


async def get_active_users() -> list:
    """
    Celery worker에서 실행 중인 활성 사용자 목록을 가져옵니다.
    심볼별 상태에서 running인 사용자를 찾아 중복 제거 후 반환합니다.

    Returns:
        활성 사용자 ID 리스트
    """
    redis = await get_redis()
    active_users = set()  # 중복 제거를 위해 set 사용

    try:
        # Redis에서 모든 user:*:symbol:*:status 키 패턴 검색 (심볼별 상태)
        pattern = "user:*:symbol:*:status"
        keys = await redis.keys(pattern)

        logger.debug(f"총 {len(keys)}개의 symbol:status 키 발견: {keys}")

        for key in keys:
            # key 형식: user:{okx_uid}:symbol:{symbol}:status
            key_str = key.decode('utf-8') if isinstance(key, bytes) else key
            logger.debug(f"키 확인 중: {key_str}")

            # String 타입으로 저장됨 (값: "running" 또는 "stopped")
            trading_status = await redis.get(key)

            if trading_status:
                # bytes를 str로 변환
                status_str = trading_status.decode('utf-8') if isinstance(trading_status, bytes) else trading_status
                logger.debug(f"키 {key_str}의 status: {status_str}")

                if status_str == 'running':
                    # user_id 추출 (user:586156710277369942:symbol:BTC-USDT-SWAP:status -> 586156710277369942)
                    parts = key_str.split(':')
                    user_id = parts[1]
                    active_users.add(user_id)  # set에 추가하여 중복 자동 제거
                    logger.debug(f"✅ 활성 사용자 발견: {user_id}")
                else:
                    logger.debug(f"status가 'running'이 아님: {status_str}")
            else:
                logger.warning(f"키 {key_str}에 값이 없음")

        result = list(active_users)
        logger.debug(f"최종 활성 사용자 목록: {result}")
        return result
    except Exception as e:
        logger.error(f"활성 사용자 조회 실패: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return []


async def get_user_api_keys(user_id: str) -> dict:
    """
    사용자 API 키를 Redis에서 가져옵니다.

    Args:
        user_id: 사용자 ID (OKX UID)

    Returns:
        API 키 딕셔너리 (api_key, api_secret, passphrase)
    """
    redis = await get_redis()
    key = f"user:{user_id}:api:keys"

    try:
        key_type = await redis.type(key)

        # Hash 타입인 경우
        if key_type == b'hash' or key_type == 'hash':
            api_keys = await redis.hgetall(key)
            if not api_keys:
                logger.error(f"사용자 {user_id}의 API 키를 찾을 수 없습니다")
                return None

            # bytes 키를 str로 변환
            return {
                'api_key': api_keys.get(b'api_key', b'').decode('utf-8') if isinstance(api_keys.get(b'api_key'), bytes) else api_keys.get('api_key', ''),
                'api_secret': api_keys.get(b'api_secret', b'').decode('utf-8') if isinstance(api_keys.get(b'api_secret'), bytes) else api_keys.get('api_secret', ''),
                'passphrase': api_keys.get(b'passphrase', b'').decode('utf-8') if isinstance(api_keys.get(b'passphrase'), bytes) else api_keys.get('passphrase', '')
            }

        # String 타입인 경우 (JSON)
        else:
            api_keys = await redis.get(key)
            if not api_keys:
                logger.error(f"사용자 {user_id}의 API 키를 찾을 수 없습니다")
                return None

            api_keys_json = json.loads(api_keys)
            return {
                'api_key': api_keys_json.get("api_key"),
                'api_secret': api_keys_json.get("api_secret"),
                'passphrase': api_keys_json.get("passphrase")
            }

    except Exception as e:
        logger.error(f"사용자 {user_id} API 키 조회 실패: {str(e)}")
        return None


async def monitor_active_users():
    """
    활성 사용자를 모니터링하고 WebSocket 연결을 관리합니다.
    사용자가 없어도 계속 대기하면서 주기적으로 체크합니다.
    """
    clients = []
    tasks = []
    current_users = set()
    is_first_run = True

    logger.info("🔄 포지션 모니터 시작: 활성 사용자 감지 대기 중...")

    while True:
        try:
            # 활성 사용자 목록 가져오기
            active_users = await get_active_users()
            new_users = set(active_users)

            # 사용자 변경 감지 (최초 실행 또는 변경사항이 있을 때만)
            if new_users != current_users:
                # 새로운 사용자 추가
                added_users = new_users - current_users
                removed_users = current_users - new_users

                if added_users:
                    logger.info(f"➕ 새로운 활성 사용자 감지: {list(added_users)}")

                if removed_users:
                    logger.info(f"➖ 비활성화된 사용자: {list(removed_users)}")
                    # 비활성화된 사용자의 WebSocket 연결 종료
                    for client in clients[:]:
                        if client.user_id in removed_users:
                            client.stop()
                            clients.remove(client)
                            logger.info(f"🔴 사용자 {client.user_id} WebSocket 연결 종료")

                # 새로운 사용자에 대한 WebSocket 연결 시작
                for user_id in added_users:
                    # 최대 연결 수 체크
                    if len(clients) >= MAX_CONCURRENT_CONNECTIONS:
                        logger.warning(
                            f"⚠️ 최대 연결 수({MAX_CONCURRENT_CONNECTIONS}) 도달. "
                            f"사용자 {user_id}는 대기합니다."
                        )
                        continue

                    # API 키 가져오기
                    api_keys = await get_user_api_keys(user_id)

                    if not api_keys:
                        logger.error(f"사용자 {user_id}의 API 키를 찾을 수 없습니다. 건너뜁니다.")
                        continue

                    # WebSocket 클라이언트 생성
                    client = OKXWebsocketClient(
                        user_id=user_id,
                        api_key=api_keys['api_key'],
                        api_secret=api_keys['api_secret'],
                        passphrase=api_keys['passphrase']
                    )

                    clients.append(client)

                    # 비동기 태스크 생성
                    task = asyncio.create_task(client.run(user_id))
                    tasks.append(task)

                    logger.info(f"✅ 사용자 {user_id} WebSocket 모니터링 시작")

                    # Rate Limit 방지
                    await asyncio.sleep(CONNECTION_DELAY)

                current_users = new_users

                # 최초 실행 시에만 상태 로그 출력
                if is_first_run:
                    if current_users:
                        logger.info(f"📊 현재 모니터링 중인 사용자: {len(current_users)}명")
                    else:
                        logger.info("⏳ 활성 사용자 없음 - 대기 중...")
                    is_first_run = False

            # 30초마다 체크
            await asyncio.sleep(30)

        except KeyboardInterrupt:
            logger.info("🛑 사용자 중단 요청 (Ctrl+C)")
            break
        except Exception as e:
            logger.error(f"모니터링 루프 에러: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            # errordb 로깅
            from HYPERRSI.src.utils.error_logger import async_log_error_to_db
            await async_log_error_to_db(
                error=e,
                error_type="PositionMonitorLoopError",
                severity="CRITICAL",
                metadata={"component": "position_monitor.monitor_active_users", "active_users": len(current_users)}
            )
            # 에러 발생 시 10초 대기 후 재시도
            await asyncio.sleep(10)

    # 종료 시 모든 클라이언트 정리
    logger.info("🧹 모든 WebSocket 연결 종료 중...")
    for client in clients:
        client.stop()

    if tasks:
        # 실행 중인 태스크 취소
        for task in tasks:
            if not task.done():
                task.cancel()

        # 모든 태스크가 완료될 때까지 대기
        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info("✅ 포지션 모니터 종료 완료")


async def main():
    """
    활성 사용자들의 포지션을 WebSocket으로 모니터링합니다.
    사용자가 없어도 계속 실행되며, 주기적으로 활성 사용자를 체크합니다.
    """
    try:
        # 0. 기존 프로세스 종료
        logger.info("=" * 50)
        logger.info("🔍 기존 position_monitor.py 프로세스 확인 중...")
        kill_existing_processes()
        logger.info("=" * 50)

        # 1. 지속적인 모니터링 시작
        await monitor_active_users()

    except KeyboardInterrupt:
        logger.info("🛑 사용자 중단 요청 (Ctrl+C)")
    except Exception as e:
        logger.error(f"에러 발생: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())

if __name__ == "__main__":
    asyncio.run(main())

# src/services/websocket_service.py
#이거, 포지션 정보 잘 작동함. 02 26 10시 확인
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import ssl
import time
from datetime import datetime
from typing import Dict, List, Optional, Set, Union

import aiohttp
import certifi

from HYPERRSI.src.bot.telegram_message import send_telegram_message
from HYPERRSI.src.core.logger import get_logger
from shared.database.redis import get_redis
from shared.database.redis_patterns import scan_keys_pattern

logger = get_logger(__name__)

class OKXWebsocketManager:
    def __init__(self):
        self.ws_private_url = "wss://ws.okx.com:8443/ws/v5/private"
        self.active_connections: Dict[str, aiohttp.ClientWebSocketResponse] = {}
        self.active_users: Set[str] = set()
        self.running = False
        self.reconnect_interval = 5  # seconds
        self.ping_interval = 15  # seconds
        self.last_log_time = 0  # 마지막 로깅 시간 추적

    async def start(self):
        """서비스 시작"""
        if self.running:
            return
        
        self.running = True
        await self.monitor_active_users()

    async def stop(self):
        """서비스 중지"""
        self.running = False
        for user_id, ws in self.active_connections.items():
            if not ws.closed:
                await ws.close()
        self.active_connections = {}
        self.active_users = set()

    async def monitor_active_users(self):
        """활성 사용자 모니터링 및 웹소켓 연결 관리"""
        print("monitor_active_users 실행")
        while self.running:
            try:
                current_time = time.time()
                # Redis에서 활성 사용자 목록 가져오기
                redis = await get_redis()
                # Use SCAN instead of KEYS to avoid blocking Redis
                keys = await scan_keys_pattern("user:*:trading:status", redis=redis)
                active_user_ids = []
                
                for key in keys:
                    status = await redis.get(key)
                    if status == "running":
                        user_id = key.split(":")[1]
                        active_user_ids.append(user_id)

                # 15분(900초)마다 활성 사용자 로깅
                if current_time - self.last_log_time >= 900:
                    logger.info(f"현재 연결된 활성 사용자: {list(self.active_users)}")
                    self.last_log_time = current_time

                # 새로운 활성 사용자에 대해 웹소켓 연결 생성
                for user_id in active_user_ids:
                    if user_id not in self.active_users:
                        api_key_hash = f"user:{user_id}:api:keys"
                        api_info = await redis.hgetall(api_key_hash)
                        
                        if api_info and 'api_key' in api_info and 'api_secret' in api_info and 'passphrase' in api_info:
                            asyncio.create_task(self.connect_user_websocket(
                                user_id,
                                api_info['api_key'],
                                api_info['api_secret'],
                                api_info['passphrase']
                            ))
                            self.active_users.add(user_id)

                # 비활성 사용자의 웹소켓 연결 종료
                for user_id in list(self.active_users):
                    if user_id not in active_user_ids:
                        if user_id in self.active_connections:
                            ws = self.active_connections[user_id]
                            if not ws.closed:
                                await ws.close()
                            del self.active_connections[user_id]
                        self.active_users.remove(user_id)

                await asyncio.sleep(10)  # 10초마다 확인
                
            except Exception as e:
                logger.error(f"Error in monitor_active_users: {e}")
                await asyncio.sleep(self.reconnect_interval)

    async def connect_user_websocket(self, user_id: str, api_key: str, api_secret: str, passphrase: str):
        """사용자별 웹소켓 연결 생성"""
        logger.info(f"Starting websocket connection for user: {user_id}")
        
        # 이미 연결이 있으면 닫기
        if user_id in self.active_connections and not self.active_connections[user_id].closed:
            await self.active_connections[user_id].close()
            
        retry_count = 0
        max_retries = 5
        
        while retry_count < max_retries and user_id in self.active_users:
            try:
                # SSL 컨텍스트 생성 및 인증서 검증 비활성화
                ssl_context = ssl.create_default_context(cafile=certifi.where())
                
                session = aiohttp.ClientSession()
                ws = await session.ws_connect(self.ws_private_url, ssl=ssl_context)
                self.active_connections[user_id] = ws
                
                # 로그인
                await self._login(ws, api_key, api_secret, passphrase)
                
                # 구독
                await self._subscribe(ws, [
                    {"channel": "orders", "instType": "SWAP"},
                    {"channel": "positions", "instType": "SWAP"},
                ])
                
                # 메시지 처리
                ping_task = asyncio.create_task(self._ping_connection(ws, user_id))
                
                try:
                    await self._process_messages(ws, user_id)
                finally:
                    ping_task.cancel()
                    
                break
                
            except Exception as e:
                logger.error(f"Websocket error for user {user_id}: {e}")
                retry_count += 1
                await asyncio.sleep(self.reconnect_interval)
                
            finally:
                if 'session' in locals():
                    await session.close()
        
        if retry_count >= max_retries:
            logger.error(f"Failed to establish websocket connection for user {user_id} after {max_retries} attempts")
            if user_id in self.active_users:
                self.active_users.remove(user_id)

    async def _login(self, ws: aiohttp.ClientWebSocketResponse, api_key: str, api_secret: str, passphrase: str):
        """OKX 웹소켓 로그인"""
        timestamp = str(int(time.time()))
        message = timestamp + 'GET' + '/users/self/verify'
        
        # HMAC-SHA256 서명 생성
        signature = base64.b64encode(
            hmac.new(
                api_secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        
        login_request = {
            "op": "login",
            "args": [{
                "apiKey": api_key,
                "passphrase": passphrase,
                "timestamp": timestamp,
                "sign": signature
            }]
        }
        
        await ws.send_json(login_request)
        response = await ws.receive_json()
        
        if response.get('event') != 'login' or response.get('code') != '0':
            raise Exception(f"Login failed: {response}")
        
        logger.info("Websocket login successful")

    async def _subscribe(self, ws: aiohttp.ClientWebSocketResponse, channels: List[Dict]):
        """채널 구독"""
        subscription = {
            "op": "subscribe",
            "args": channels
        }
        
        await ws.send_json(subscription)
        
        # 각 채널에 대한 응답을 개별적으로 처리
        for _ in range(len(channels)):
            try:
                response = await ws.receive_json(timeout=5.0)
                logger.info(f"Subscription response: {response}")
                
                # OKX API는 성공적인 구독 시 'event': 'subscribe'와 'arg' 필드를 포함합니다
                if 'event' in response and response.get('event') == 'subscribe' and 'arg' in response:
                    logger.info(f"Successfully subscribed to channel: {response.get('arg', {}).get('channel')}")
                elif 'code' in response and response.get('code') != '0':
                    logger.warning(f"Subscription warning: {response}")
            
            except Exception as e:
                logger.error(f"Error receiving subscription response: {e}")
        
        logger.info(f"Completed subscription process for channels: {channels}")

    async def _ping_connection(self, ws: aiohttp.ClientWebSocketResponse, user_id: str):
        """주기적인 ping 전송으로 연결 유지"""
        try:
            while not ws.closed and user_id in self.active_users:
                await ws.send_json({"op": "ping"})
                await asyncio.sleep(self.ping_interval)
        except Exception as e:
            logger.error(f"Error sending ping for user {user_id}: {e}")

    async def _process_messages(self, ws: aiohttp.ClientWebSocketResponse, user_id: str):
        """웹소켓 메시지 처리"""
        while not ws.closed and user_id in self.active_users:
            try:
                msg = await ws.receive()
                
                if msg.type == aiohttp.WSMsgType.TEXT:
                    data = json.loads(msg.data)
                    
                    # ping 응답
                    if 'event' in data and data['event'] == 'pong':
                        continue
                    
                    # 데이터 처리
                    if 'data' in data and len(data['data']) > 0:
                        await self._handle_data(user_id, data)
                
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    logger.info(f"Websocket connection closed for user {user_id}")
                    break
                    
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logger.error(f"Websocket error for user {user_id}: {ws.exception()}")
                    break
                    
            except Exception as e:
                logger.error(f"Error processing websocket message for user {user_id}: {e}")
                if not ws.closed:
                    await ws.close()
                break

    async def _handle_data(self, user_id: str, data: Dict):
        """받은 데이터 처리 및 Redis에 저장"""
        try:
            channel = data.get('arg', {}).get('channel')
            
            if not channel or not data.get('data'):
                return
                
            if channel == 'positions':
                await self._handle_positions(user_id, data['data'])
            elif channel == 'orders':
                await self._handle_orders(user_id, data['data'])
            elif channel == 'orders-history':
                await self._handle_orders_history(user_id, data['data'])
                
        except Exception as e:
            logger.error(f"Error handling data for user {user_id}: {e}")
    
    async def _handle_positions(self, user_id: str, positions: List[Dict]):
        """포지션 정보 처리 및 TP 레벨 체크"""
        try:
            redis = await get_redis()
            # 기존 포지션 정보 가져오기 (TP 정보 포함)
            existing_positions = {}
            position_pattern = f"user:{user_id}:position"
            # Use SCAN instead of KEYS to avoid blocking Redis
            existing_keys = await scan_keys_pattern(position_pattern, redis=redis)
            
            for key in existing_keys:
                if ":summary" not in key:  # 요약 정보 제외
                    # 키가 해시 타입인지 확인
                    key_type = await redis.type(key)
                    if key_type == "hash":
                        pos_data = await redis.hgetall(key)
                        if pos_data:
                            existing_positions[key] = pos_data
                    else:
                        # 해시 타입이 아닌 경우 삭제하고 로그 기록
                        logger.warning(f"Deleting non-hash key: {key} of type {key_type}")
                        await redis.delete(key)
            
            # 새 포지션 정보 처리
            for position in positions:
                if float(position.get('pos', '0')) != 0:  # 실제 포지션이 있는 경우만 처리
                    symbol = position.get('instId', '')
                    side = position.get('posSide', '').lower()
                    
                    # 롱/숏 구분을 위한 방향 설정
                    direction = "long" if side == "long" else "short"
                    position_key = f"user:{user_id}:position:{symbol}:{direction}"
                    
                    # 현재가 가져오기
                    current_price = float(position.get('markPx', '0'))
                    if current_price == 0:
                        current_price = float(position.get('last', '0'))
                    
                    # tp_state 가져오기
                    tp_state = await redis.hget(position_key, "tp_state")
                    if tp_state is None:
                        tp_state = "0"
                    
                    # TP 정보 가져오기
                    tp_data_str = None
                    if position_key in existing_positions:
                        old_data = existing_positions[position_key]
                        tp_data_str = old_data.get('tp_data')
                    
                    # tp_data 가져오기
                    tp_prices = []
                    tp_sizes = []
                    tp_data = []
                    
                    if tp_data_str:
                        try:
                            tp_data = json.loads(tp_data_str)
                            # active 상태인 TP만 필터링
                            active_tps = [tp for tp in tp_data if tp.get('status') == 'active']
                            tp_prices = [float(tp.get('price', 0)) for tp in active_tps]
                            tp_sizes = [float(tp.get('size', 0)) for tp in active_tps]
                        except (json.JSONDecodeError, TypeError):
                            logger.error(f"Invalid tp_data format: {tp_data_str}")
                    else:
                        # 기존 방식으로 TP 정보 가져오기 (하위 호환성)
                        if position_key in existing_positions:
                            old_data = existing_positions[position_key]
                            if 'tp_prices' in old_data:
                                try:
                                    tp_prices = json.loads(old_data['tp_prices'])
                                except (json.JSONDecodeError, TypeError):
                                    tp_prices = []
                            
                            if 'tp_sizes' in old_data:
                                try:
                                    tp_sizes = json.loads(old_data['tp_sizes'])
                                except (json.JSONDecodeError, TypeError):
                                    tp_sizes = []
                    
                    # TP 도달 체크 및 업데이트
                    if tp_prices and current_price > 0 and tp_data:
                        entry_price = float(position.get('avgPx', '0'))
                        contracts_amount = float(position.get('pos', '0'))
                        
                        for tp in tp_data:
                            if tp.get('status') != 'active':
                                continue
                                
                            tp_level = tp.get('level', 0)
                            tp_price = float(tp.get('price', 0))
                            
                            # 롱 포지션: 현재가가 TP보다 높으면 도달
                            # 숏 포지션: 현재가가 TP보다 낮으면 도달
                            if (direction == "long" and current_price >= tp_price) or \
                               (direction == "short" and current_price <= tp_price):
                                
                                # tp_state 업데이트
                                current_tp_state = int(tp_state)
                                if current_tp_state < tp_level:
                                    tp_state = str(tp_level)
                                    await redis.hset(position_key, "tp_state", str(tp_state))
                                
                                # TP 상태 업데이트
                                tp['status'] = 'filled'
                                
                                # get_tp 키 설정
                                get_tp_key = f"get_tp{tp_level}"
                                await redis.hset(position_key, get_tp_key, "true")
                                
                                # 알림 전송
                                filled_qty = float(tp.get('size', 0))
                                filled_price = tp_price
                                
                                # PnL 계산
                                if direction == "long":
                                    pnl = (filled_price - entry_price) * filled_qty
                                else:  # short
                                    pnl = (entry_price - filled_price) * filled_qty
                                
                                # TP 체결 알림 전송
                                await self._send_tp_alert(
                                    user_id, symbol, direction, tp_level, 
                                    tp_price, current_price, pnl, filled_qty
                                )
                                
                                # PnL 데이터 저장
                                await self._save_tp_pnl_data(
                                    user_id, symbol, f"tp{tp_level}", tp_level, 
                                    pnl, filled_price, filled_qty, entry_price, 
                                    direction, side
                                )
                                
                                # 브레이크이븐 처리
                                settings = await redis.hgetall(f"user:{user_id}:settings")
                                use_break_even_tp1 = settings.get('use_break_even', 'false').lower() == 'true'
                                use_break_even_tp2 = settings.get('use_break_even_tp2', 'false').lower() == 'true'
                                use_break_even_tp3 = settings.get('use_break_even_tp3', 'false').lower() == 'true'
                                
                                # TP 레벨에 따른 브레이크이븐 설정
                                if (use_break_even_tp1 and tp_level == 1):
                                    await self._move_sl_to_break_even(
                                        user_id, symbol, direction, entry_price, 
                                        contracts_amount, tp_level
                                    )
                                    await redis.hset(position_key, "sl_price", str(entry_price))
                                    
                                elif (use_break_even_tp2 and tp_level == 2 and len(tp_prices) > 0):
                                    # TP1 가격으로 이동
                                    tp1_price = next((float(tp.get('price', 0)) for tp in tp_data 
                                                    if tp.get('level') == 1), None)
                                    if tp1_price:
                                        await self._move_sl_to_break_even(
                                            user_id, symbol, direction, tp1_price, 
                                            contracts_amount, tp_level
                                        )
                                        await redis.hset(position_key, "sl_price", tp1_price)
                                        
                                elif (use_break_even_tp3 and tp_level == 3 and len(tp_prices) > 1):
                                    # TP2 가격으로 이동
                                    tp2_price = next((float(tp.get('price', 0)) for tp in tp_data 
                                                    if tp.get('level') == 2), None)
                                    if tp2_price:
                                        await self._move_sl_to_break_even(
                                            user_id, symbol, direction, tp2_price, 
                                            contracts_amount, tp_level
                                        )
                                        await redis.hset(position_key, "sl_price", tp2_price)
                        
                        # 모든 TP가 체결되었는지 확인
                        is_last_tp = all(tp.get('status') != 'active' for tp in tp_data)
                        if is_last_tp:
                            # 거래 히스토리에 저장
                            await self._save_to_completed_history(
                                user_id, existing_positions.get(position_key, {}), 
                                {"avgPrice": current_price, "fillSize": contracts_amount}, 
                                "TP"
                            )
                        
                        # 업데이트된 tp_data 저장
                        await redis.hset(position_key, "tp_data", json.dumps(tp_data))
                    
                    # 포지션 정보를 해시로 저장
                    position_data = {
                        "symbol": symbol,
                        "size": position.get('pos', '0'),
                        "direction": direction,
                        "entry_price": position.get('avgPx', '0'),
                        "current_price": str(current_price),
                        "unrealized_pnl": position.get('upl', '0'),
                        "margin": position.get('margin', '0'),
                        "leverage": position.get('lever', '0'),
                        "liquidation_price": position.get('liqPx', '0'),
                        "tp_data": json.dumps(tp_data) if tp_data else "[]",
                        "tp_prices": json.dumps(tp_prices),
                        "tp_sizes": json.dumps(tp_sizes),
                        "tp_state": tp_state,
                        "updated_at": datetime.now().isoformat()
                    }
                    
                    await redis.hset(position_key, mapping=position_data)
                    await redis.expire(position_key, 86400)  # 24시간 유효기간 설정
            
            # 종합 포지션 상태 업데이트
            summary_key = f"user:{user_id}:position:summary"
            summary_data = {
                "count": len(positions),
                "updated_at": datetime.now().isoformat()
            }
            await redis.hset(summary_key, mapping=summary_data)
                    
        except Exception as e:
            logger.error(f"Error handling positions for user {user_id}: {e}")
    
    async def _send_tp_alert(self, user_id: str, symbol: str, direction: str, tp_level: int,
                            tp_price: Union[str, float], current_price: float,
                            pnl: float = 0, filled_qty: float = 0):
        """TP 도달 시 알림 전송"""
        try:
            redis = await get_redis()
            # 텔레그램 봇 설정 가져오기
            direction_emoji = "🟢 롱" if direction == "long" else "🔴 숏"
            
            # 알림 메시지 구성
            message = (
                f"🎯 TP{tp_level} 체결 확인\n"
                f" - 심볼: {symbol}\n"
                f" - 방향: {direction_emoji}\n"
                f" - 체결가격: {float(tp_price):.2f}\n"
                f" - 수량: {filled_qty}\n"
                f" - PnL: {pnl:.2f} USDT\n"
            )
            
            # 알림 전송
            await send_telegram_message(message, user_id)
            
            # 알림 로그 저장
            alert_key = f"user:{user_id}:alert:{int(time.time())}"
            alert_data = {
                "type": "tp_hit",
                "symbol": symbol,
                "direction": direction,
                "tp_level": str(tp_level),
                "tp_price": str(tp_price),
                "current_price": str(current_price),
                "pnl": str(pnl),
                "timestamp": datetime.now().isoformat()
            }
            await redis.hset(alert_key, mapping=alert_data)
            await redis.expire(alert_key, 604800)  # 7일간 유효
            
        except Exception as e:
            logger.error(f"Error sending TP alert for user {user_id}: {e}")
    
    async def _move_sl_to_break_even(self, user_id: str, symbol: str, side: str,
                                    break_even_price: float, contracts_amount: float,
                                    tp_index: int = 0):
        """거래소 API를 사용해 SL(Stop Loss) 가격을 break_even_price로 업데이트"""
        try:
            redis = await get_redis()
            from HYPERRSI.src.api.routes.order import update_stop_loss_order

            # side가 long 또는 buy이면 order_side는 sell, side가 short 또는 sell이면 order_side는 buy
            order_side = "sell" if side == "long" or side == "buy" else "buy"
            
            result = await update_stop_loss_order(
                new_sl_price=break_even_price,
                symbol=symbol,
                side=side,
                order_side=order_side,
                contracts_amount=contracts_amount,
                user_id=user_id,
                order_type="break_even"
            )
            
            if isinstance(result, dict) and not result.get('success', True):
                logger.info(f"SL 업데이트 건너뜀: {result.get('message')}")
                return None
                
                
                
            asyncio.create_task(send_telegram_message(
                f"🔒 TP{tp_index} 체결 후 SL을 브레이크이븐({break_even_price:.2f})으로 이동",
                user_id
            ))
            
            position_key = f"user:{user_id}:position:{symbol}:{side}"
            await redis.hset(position_key, "sl_price", break_even_price)
            return result
            
        except Exception as e:
            logger.error(f"move_sl_to_break_even 오류: {str(e)}")
            asyncio.create_task(send_telegram_message(f"SL 이동 오류: {str(e)}", user_id, debug=True))
            return None
            
    async def _save_tp_pnl_data(self, user_id: str, symbol: str, order_id: str,
                               tp_index: int, pnl: float, filled_price: float,
                               filled_qty: float, entry_price: float, side: str,
                               pos_side: str, expiry_days: int = 7):
        """TP 체결 시 PnL 정보를 Redis에 저장하는 함수"""
        try:
            redis = await get_redis()
            # 개별 TP PnL 데이터 저장
            pnl_key = f"user:{user_id}:pnl:{symbol}:{order_id}:tp{tp_index}"
            pnl_data = {
                "pnl": str(pnl),
                "filled_price": str(filled_price),
                "filled_qty": str(filled_qty),
                "entry_price": str(entry_price),
                "timestamp": str(int(time.time())),
                "side": side,
                "pos_side": pos_side
            }
            await redis.hset(pnl_key, mapping=pnl_data)
            
            # 만료 시간 설정
            await redis.expire(pnl_key, 60 * 60 * 24 * expiry_days)
            
            # 누적 PnL 업데이트
            total_pnl_key = f"user:{user_id}:total_pnl:{symbol}"
            current_total_pnl = float(await redis.get(total_pnl_key) or 0)
            await redis.set(total_pnl_key, str(current_total_pnl + pnl))
            
            logger.info(f"Saved TP{tp_index} PnL data for user {user_id}: {pnl_data}")
            
        except Exception as e:
            logger.error(f"Error saving PnL data: {str(e)}")
    
    async def _save_to_completed_history(self, user_id: str, position_data: dict,
                                        order_info: dict, close_type: str):
        """완료된 거래를 completed_history에 저장하는 함수"""
        try:
            redis = await get_redis()
            symbol = position_data.get("symbol")
            if not symbol:
                logger.error(f"Symbol not found in position data for user {user_id}")
                return
                
            pos_direction = position_data.get("direction", position_data.get("side", ""))
            if pos_direction == "buy":
                pos_direction = "long"
            elif pos_direction == "sell":
                pos_direction = "short"
                
            cooldown_key = f"user:{user_id}:cooldown:{symbol}:{pos_direction}"
            # Get cooldown_time from user settings (default 300 seconds)
            settings_str = await redis.get(f"user:{user_id}:settings")
            cooldown_seconds = 300  # default
            if settings_str:
                try:
                    user_settings = json.loads(settings_str)
                    use_cooldown = user_settings.get('use_cooldown', True)
                    if use_cooldown:
                        cooldown_seconds = int(user_settings.get('cooldown_time', 300))
                    else:
                        cooldown_seconds = 0  # Skip cooldown if disabled
                except (json.JSONDecodeError, ValueError):
                    pass
            if cooldown_seconds > 0:
                await redis.set(cooldown_key, "true", ex=cooldown_seconds)
            completed_key = f"user:{user_id}:completed_history"
            
            if order_info:
                exit_price = float(order_info.get("avgPrice", 0))
                size = float(order_info.get("fillSize", 0))
            else:
                exit_price = float(position_data.get("exit_price", 0))
                size = float(position_data.get("size", 0))
                
            # 거래 정보 구성
            trade_info = {
                "symbol": symbol,
                "side": position_data.get("direction", position_data.get("side", "")),
                "posSide": position_data.get("posSide", "net"),
                "entry_price": float(position_data.get("entry_price", 0)),
                "exit_price": exit_price,
                "size": size,
                "close_type": close_type,  # "TP" 또는 "SL"
                "entry_time": position_data.get("entry_time", datetime.now().isoformat()),
                "exit_time": datetime.now().isoformat(),
                "pnl": None,  # 아래에서 계산
                "pnl_percent": None,
                "tp_prices": position_data.get("tp_prices", "[]"),
                "sl_price": position_data.get("sl_price", "0")
            }

            # PnL 계산
            entry_price = trade_info["entry_price"]
            exit_price = trade_info["exit_price"]
            size = trade_info["size"]
            is_long = trade_info["side"] == "long"

            if entry_price > 0 and size > 0:
                if is_long:
                    pnl = (exit_price - entry_price) * size
                else:
                    pnl = (entry_price - exit_price) * size
                
                trade_info["pnl"] = pnl
                trade_info["pnl_percent"] = (pnl / (entry_price * size)) * 100 if entry_price * size > 0 else 0

            # completed_history에 저장
            await redis.lpush(completed_key, json.dumps(trade_info))
            
            # 옵션: 히스토리 크기 제한 (예: 최근 1000개만 유지)
            await redis.ltrim(completed_key, 0, 999)
            
            logger.info(f"Saved to completed history - user:{user_id}, symbol:{trade_info['symbol']}, pnl:{trade_info['pnl']}")
            
        except Exception as e:
            logger.error(f"Error saving to completed history: {str(e)}")

    async def _handle_orders(self, user_id: str, orders: List[Dict]):
        """활성 주문 정보 처리"""
        try:
            redis = await get_redis()
            # 열린 주문 파이프라인
            pipeline = redis.pipeline()
            
            for order in orders:
                symbol = order.get('instId', '')
                order_id = order.get('ordId', '')
                
                if not symbol or not order_id:
                    continue
                
                order_key = f"user:{user_id}:order:{symbol}"
                order_status = order.get('state', '')
                
                # 주문 상태에 따라 처리
                # live: 활성 주문, canceled: 취소됨, filled: 체결됨
                if order_status in ['live']:
                    # 활성 주문 정보 저장
                    order_data = {
                        "order_id": order_id,
                        "symbol": symbol,
                        "type": order.get('ordType', ''),
                        "side": order.get('side', ''),
                        "position_side": order.get('posSide', ''),
                        "price": order.get('px', '0'),
                        "size": order.get('sz', '0'),
                        "filled": order.get('accFillSz', '0'),
                        "status": order_status,
                        "created_at": self._parse_timestamp(order.get('cTime', '')),
                        "updated_at": self._parse_timestamp(order.get('uTime', ''))
                    }
                    
                    pipeline.hset(f"{order_key}:{order_id}", mapping=order_data)
                    pipeline.expire(f"{order_key}:{order_id}", 86400)  # 24시간 유효
                
                elif order_status in ['canceled', 'filled']:
                    # 취소되거나 체결된 주문은 히스토리로 이동
                    # 먼저 기존 활성 주문에서 삭제
                    pipeline.delete(f"{order_key}:{order_id}")
                    
                    # 히스토리에 추가 (orders-history 채널에서 처리하므로 여기서는 생략)
            
            await pipeline.execute()
            print("orders 처리 완료")
        except Exception as e:
            logger.error(f"Error handling orders for user {user_id}: {e}")

    async def _handle_orders_history(self, user_id: str, orders: List[Dict]):
        """체결된 주문 히스토리 처리"""
        try:
            redis = await get_redis()
            pipeline = redis.pipeline()
            
            for order in orders:
                symbol = order.get('instId', '')
                order_id = order.get('ordId', '')
                
                if not symbol or not order_id:
                    continue
                
                # 체결 이력 저장
                history_key = f"user:{user_id}:order:history:{symbol}"
                
                order_data = {
                    "order_id": order_id,
                    "symbol": symbol,
                    "type": order.get('ordType', ''),
                    "side": order.get('side', ''),
                    "position_side": order.get('posSide', ''),
                    "price": order.get('avgPx', '0'),  # 평균 체결가
                    "size": order.get('sz', '0'),
                    "filled": order.get('accFillSz', '0'),
                    "status": order.get('state', ''),
                    "pnl": order.get('pnl', '0'),
                    "fee": order.get('fee', '0'),
                    "created_at": self._parse_timestamp(order.get('cTime', '')),
                    "updated_at": self._parse_timestamp(order.get('uTime', ''))
                }
                
                pipeline.hset(f"{history_key}:{order_id}", mapping=order_data)
                pipeline.expire(f"{history_key}:{order_id}", 604800)  # 7일 유효
                
                # 활성 주문에서 삭제 (이미 orders 채널에서 처리했을 수 있음)
                active_order_key = f"user:{user_id}:order:{symbol}:{order_id}"
                pipeline.delete(active_order_key)
            
            await pipeline.execute()
            print("order history 처리 완료")
        except Exception as e:
            logger.error(f"Error handling order history for user {user_id}: {e}")

    def _parse_timestamp(self, timestamp: str) -> str:
        """OKX 타임스탬프를 ISO 형식으로 변환"""
        if not timestamp:
            return datetime.now().isoformat()
            
        try:
            # OKX는 Unix 타임스탬프를 밀리초로 반환
            ts = int(timestamp)
            dt = datetime.fromtimestamp(ts / 1000)
            return dt.isoformat()
        except (ValueError, TypeError):
            return datetime.now().isoformat()



# 테스트용
if __name__ == "__main__":
    asyncio.run(OKXWebsocketManager().start())
# Redis key patterns
USER_TRADING_STATUS = "user:{user_id}:trading:status"  # 트레이딩 상태
USER_API_KEYS = "user:{user_id}:api:keys"             # API 키 정보
USER_STATS = "user:{user_id}:stats"                   # 트레이딩 통계
USER_POSITION = "user:{user_id}:position:{symbol}:{side}"             # 현재 포지션

USER_POSITION_DCA_COUNT = "user:{user_id}:position:{symbol}:{side}:dca_count"             # 현재 포지션 DCA 카운트
USER_POSITION_STATE = "user:{user_id}:position:{symbol}:position_state"             # 현재 포지션 상태 <-- 방향 상관 없이, position_state에서 +-로 구분

USER_POSITION_ENTRY_PRICE = "user:{user_id}:position:{symbol}:{side}:entry_price"             # 현재 포지션 진입가

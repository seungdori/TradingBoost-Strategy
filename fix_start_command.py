#!/usr/bin/env python3
"""
/start 명령어 수정 패치
기존 telegram_id 연결을 먼저 제거하고 새로 연결하도록 수정
"""

# 수정해야 할 부분 (line 110 근처):

"""
원래 코드:
---
        record = await TimescaleUserService.set_telegram_link(
            str(okx_uid),
            str(user_id),
            display_name=display_name or None,
            telegram_username=username,
        )
---

수정된 코드:
---
        # 먼저 기존 telegram_id 연결 제거
        try:
            # DB에서 이 telegram_id를 사용하는 모든 계정의 연결 해제
            async with TimescalePool.acquire() as conn:
                await conn.execute(
                    '''
                    UPDATE app_users
                    SET telegram_id = NULL,
                        telegram_linked = FALSE,
                        updated_at = now()
                    WHERE telegram_id = $1
                    ''',
                    str(user_id)
                )
        except Exception as e:
            logger.warning(f"기존 연결 해제 중 오류 (무시됨): {e}")

        # 새로운 연결 생성
        record = await TimescaleUserService.set_telegram_link(
            str(okx_uid),
            str(user_id),
            display_name=display_name or None,
            telegram_username=username,
        )
---
"""

print("""
파일 위치: HYPERRSI/src/bot/command/basic.py
수정 위치: Line 110 근처 (start_uid_command 함수 내부)

위 수정을 적용하면:
1. 기존 telegram_id 연결이 자동으로 해제됨
2. 새로운 okx_uid와 연결됨
3. 중복 에러 없이 계정 전환 가능
""")
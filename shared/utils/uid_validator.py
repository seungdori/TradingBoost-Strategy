"""
UID 검증 유틸리티

OKX UID와 Telegram ID를 구분하고 검증합니다.
"""

import re
from typing import Tuple

from shared.logging import get_logger

logger = get_logger(__name__)


class UIDType:
    """UID 타입 상수"""

    OKX_UID = "okx_uid"
    TELEGRAM_ID = "telegram_id"
    UNKNOWN = "unknown"


class UIDValidator:
    """UID 검증 및 타입 판별"""

    # OKX UID: 일반적으로 18-19자리 숫자
    OKX_UID_MIN_LENGTH = 18
    OKX_UID_MAX_LENGTH = 19

    # Telegram ID: 일반적으로 9-10자리 숫자 (최대 15자리까지 가능)
    TELEGRAM_ID_MIN_LENGTH = 9
    TELEGRAM_ID_MAX_LENGTH = 15

    @classmethod
    def detect_uid_type(cls, uid: str) -> str:
        """
        UID 타입 자동 감지

        Args:
            uid: 검증할 UID 문자열

        Returns:
            UIDType 상수 ('okx_uid', 'telegram_id', 'unknown')
        """
        if not uid or not isinstance(uid, str):
            return UIDType.UNKNOWN

        # 숫자만 있는지 확인
        if not uid.isdigit():
            return UIDType.UNKNOWN

        length = len(uid)

        # OKX UID 범위
        if cls.OKX_UID_MIN_LENGTH <= length <= cls.OKX_UID_MAX_LENGTH:
            return UIDType.OKX_UID

        # Telegram ID 범위
        if cls.TELEGRAM_ID_MIN_LENGTH <= length <= cls.TELEGRAM_ID_MAX_LENGTH:
            return UIDType.TELEGRAM_ID

        # 범위를 벗어남
        return UIDType.UNKNOWN

    @classmethod
    def is_okx_uid(cls, uid: str) -> bool:
        """OKX UID인지 확인"""
        return cls.detect_uid_type(uid) == UIDType.OKX_UID

    @classmethod
    def is_telegram_id(cls, uid: str) -> bool:
        """Telegram ID인지 확인"""
        return cls.detect_uid_type(uid) == UIDType.TELEGRAM_ID

    @classmethod
    def validate_and_detect(
        cls, uid: str, expected_type: str = None
    ) -> Tuple[bool, str, str]:
        """
        UID를 검증하고 타입을 감지

        Args:
            uid: 검증할 UID
            expected_type: 예상되는 타입 ('okx_uid' 또는 'telegram_id')

        Returns:
            (is_valid, detected_type, error_message)
        """
        if not uid:
            return False, UIDType.UNKNOWN, "UID가 제공되지 않았습니다"

        if not isinstance(uid, str):
            uid = str(uid)

        detected_type = cls.detect_uid_type(uid)

        if detected_type == UIDType.UNKNOWN:
            return (
                False,
                UIDType.UNKNOWN,
                f"알 수 없는 UID 형식입니다 (길이: {len(uid)})",
            )

        # 예상 타입이 지정된 경우 검증
        if expected_type:
            if expected_type != detected_type:
                return (
                    False,
                    detected_type,
                    f"예상 타입 ({expected_type})과 다릅니다. 감지된 타입: {detected_type}",
                )

        return True, detected_type, ""

    @classmethod
    def ensure_okx_uid(cls, uid: str) -> str:
        """
        OKX UID 검증 및 반환

        Args:
            uid: 검증할 UID

        Returns:
            검증된 OKX UID

        Raises:
            ValueError: OKX UID가 아닌 경우
        """
        is_valid, detected_type, error_msg = cls.validate_and_detect(
            uid, expected_type=UIDType.OKX_UID
        )

        if not is_valid:
            error_detail = f"OKX UID 검증 실패: {error_msg} (입력: {uid}, 길이: {len(uid)})"
            logger.error(error_detail)
            raise ValueError(error_detail)

        return uid

    @classmethod
    def ensure_telegram_id(cls, uid: str) -> str:
        """
        Telegram ID 검증 및 반환

        Args:
            uid: 검증할 ID

        Returns:
            검증된 Telegram ID

        Raises:
            ValueError: Telegram ID가 아닌 경우
        """
        is_valid, detected_type, error_msg = cls.validate_and_detect(
            uid, expected_type=UIDType.TELEGRAM_ID
        )

        if not is_valid:
            error_detail = f"Telegram ID 검증 실패: {error_msg} (입력: {uid}, 길이: {len(uid)})"
            logger.error(error_detail)
            raise ValueError(error_detail)

        return uid

    @classmethod
    def log_uid_info(cls, uid: str, context: str = ""):
        """UID 정보 로깅 (디버깅용)"""
        is_valid, detected_type, error_msg = cls.validate_and_detect(uid)

        log_msg = f"[{context}] UID: {uid}, 길이: {len(uid)}, 타입: {detected_type}"
        if error_msg:
            log_msg += f", 오류: {error_msg}"

        if is_valid:
            logger.info(log_msg)
        else:
            logger.warning(log_msg)


# 편의 함수들
def is_okx_uid(uid: str) -> bool:
    """OKX UID인지 확인"""
    return UIDValidator.is_okx_uid(uid)


def is_telegram_id(uid: str) -> bool:
    """Telegram ID인지 확인"""
    return UIDValidator.is_telegram_id(uid)


def detect_uid_type(uid: str) -> str:
    """UID 타입 자동 감지"""
    return UIDValidator.detect_uid_type(uid)


def ensure_okx_uid(uid: str) -> str:
    """OKX UID 검증"""
    return UIDValidator.ensure_okx_uid(uid)


def ensure_telegram_id(uid: str) -> str:
    """Telegram ID 검증"""
    return UIDValidator.ensure_telegram_id(uid)


# 테스트 코드
if __name__ == "__main__":
    test_cases = [
        ("587662504768345929", UIDType.OKX_UID),  # OKX UID (18자리)
        ("1709556958", UIDType.TELEGRAM_ID),  # Telegram ID (10자리)
        ("646396755365762614", UIDType.OKX_UID),  # OKX UID (18자리)
        ("7097155337", UIDType.TELEGRAM_ID),  # Telegram ID (10자리)
        ("12345", UIDType.UNKNOWN),  # 너무 짧음
        ("123456789012345678901", UIDType.UNKNOWN),  # 너무 김
        ("abc123", UIDType.UNKNOWN),  # 숫자 아님
    ]

    print("="*60)
    print("UID 검증 테스트")
    print("="*60)

    for uid, expected_type in test_cases:
        detected_type = detect_uid_type(uid)
        is_correct = detected_type == expected_type
        status = "✅" if is_correct else "❌"

        print(f"{status} UID: {uid} (길이: {len(uid)})")
        print(f"   예상: {expected_type}, 감지: {detected_type}")
        print()

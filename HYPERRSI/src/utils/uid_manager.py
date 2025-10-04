from typing import Optional, Tuple
from HYPERRSI.src.utils.check_invitee import get_uid_from_api_keys
from sqlalchemy.orm import Session
from HYPERRSI.src.core.models.database import UserModel

async def get_or_create_okx_uid(
    db: Session, 
    telegram_id: int,
    api_key: str,
    api_secret: str,
    passphrase: str
) -> Tuple[bool, str]:
    """
    사용자의 OKX UID를 가져오거나 생성합니다.
    
    Args:
        db: 데이터베이스 세션
        telegram_id: 사용자의 텔레그램 ID
        api_key: OKX API 키
        api_secret: OKX Secret 키
        passphrase: OKX Passphrase
    
    Returns:
        Tuple[bool, str]: (성공 여부, OKX UID)
    """
    # 1. 먼저 데이터베이스에서 사용자 조회
    user = db.query(UserModel).filter(UserModel.telegram_id == telegram_id).first()
    
    # 이미 okx_uid가 있으면 반환
    if user and user.okx_uid:
        # 인증된 사용자인지 확인 (이 부분은 필요에 따라 추가)
        return True, user.okx_uid
    
    # 2. API 키로 OKX UID 가져오기 시도
    try:
        is_invitee, okx_uid = get_uid_from_api_keys(api_key, api_secret, passphrase)
        
        # UID를 얻지 못했으면 실패
        if not okx_uid:
            return False, "UID를 확인할 수 없습니다."
        
        # 사용자가 존재하면 업데이트
        if user:
            user.okx_uid = okx_uid
            db.commit()
        # 사용자가 없으면 새로 생성 (필요한 경우)
        # else:
        #     new_user = UserModel(telegram_id=telegram_id, okx_uid=okx_uid)
        #     db.add(new_user)
        #     db.commit()
        
        return is_invitee, okx_uid
        
    except Exception as e:
        # 오류 처리
        db.rollback()
        return False, f"오류 발생: {str(e)}"

async def get_telegram_id_by_okx_uid(db: Session, okx_uid: str) -> Optional[int]:
    """
    OKX UID로부터 텔레그램 ID를 조회합니다.
    
    Args:
        db: 데이터베이스 세션
        okx_uid: OKX UID
    
    Returns:
        Optional[int]: 텔레그램 ID 또는 None
    """
    user = db.query(UserModel).filter(UserModel.okx_uid == okx_uid).first()
    return user.telegram_id if user else None

async def get_okx_uid_by_telegram_id(db: Session, telegram_id: int) -> Optional[str]:
    """
    텔레그램 ID로부터 OKX UID를 조회합니다.
    
    Args:
        db: 데이터베이스 세션
        telegram_id: 텔레그램 ID
        
    Returns:
        Optional[str]: OKX UID 또는 None
    """
    user = db.query(UserModel).filter(UserModel.telegram_id == telegram_id).first()
    return user.okx_uid if user else None

async def update_user_okx_uid(db: Session, telegram_id: int, okx_uid: str) -> bool:
    """
    사용자의 OKX UID를 업데이트합니다.
    
    Args:
        db: 데이터베이스 세션
        telegram_id: 텔레그램 ID
        okx_uid: OKX UID
        
    Returns:
        bool: 업데이트 성공 여부
    """
    try:
        user = db.query(UserModel).filter(UserModel.telegram_id == telegram_id).first()
        if user:
            user.okx_uid = okx_uid
            db.commit()
            return True
        return False
    except Exception:
        db.rollback()
        return False 
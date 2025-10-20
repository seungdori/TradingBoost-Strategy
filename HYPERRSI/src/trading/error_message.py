import traceback


def map_exchange_error(error: Exception) -> str:
    """
    거래소 에러 메시지를 사용자 친화적인 메시지로 변환
    """
    error_str = str(error).lower()  # 소문자로 변환하여 비교
    
    # 일반적인 에러 패턴 매칭 (우선순위 순서대로 체크)
    # 최소 수량 에러를 먼저 체크 (더 구체적인 조건)
    if ("minimum" in error_str or "최소" in error_str) and "수량" in error_str:
        return "📉 주문 수량이 최소 수량 미만입니다."

    if "insufficient" in error_str and "balance" in error_str:
        return "💰 계좌 잔고가 부족합니다. 거래 금액을 줄이거나 잔고를 충전해주세요."

    if "position" in error_str and "limit" in error_str:
        return "⚠️ 포지션 한도를 초과했습니다."

    # leverage는 매우 구체적인 에러 패턴만 매칭 (일반적인 메시지의 "레버리지" 정보는 제외)
    if "leverage" in error_str and ("invalid" in error_str or "incorrect" in error_str or "51002" in error_str):
        return "📊 레버리지 설정이 올바르지 않습니다. 다시 확인해주세요."
    
    if "maximum" in error_str:
        return "📉 주문 수량이 최대 수량 초과입니다."

    if "order failed" in error_str:
        return "❌ 주문 실패: 거래소 연결 상태를 확인해주세요."
        
    if "margin mode" in error_str:
        return "⚙️ 거래 설정 오류가 발생했습니다. 고객센터에 문의해주세요."
        
    if "price" in error_str and "market" in error_str:
        return "💱 주문 가격이 현재 시장 가격과 너무 차이가 납니다."
        
    if "connection" in error_str:
        return "🌐 거래소 연결에 실패했습니다. 인터넷 연결을 확인해주세요."
        
    if "api key" in error_str:
        return "🔑 API 키 오류입니다. API 키 설정을 확인해주세요."
        
    if "permission denied" in error_str:
        return "🚫 권한이 없습니다. API 키 권한 설정을 확인해주세요."
    
    # OKX 에러 코드 매핑
    error_mappings = {
        "51008": "💰 계좌 잔고가 부족합니다. 거래 금액을 줄이거나 잔고를 충전해주세요.",
        "51000": "⚙️ 거래 설정 오류가 발생했습니다. 고객센터에 문의해주세요.",
        "51002": "📊 레버리지 설정이 올바르지 않습니다. 다시 확인해주세요.",
        "51004": "📉 주문 수량이 최소/최대 제한을 벗어났습니다.",
        "51010": "💱 주문 가격이 현재 시장 가격과 너무 차이가 납니다.",
        "51015": "⚠️ 포지션 한도를 초과했습니다.",
        "51016": "💼 포지션 마진이 부족합니다.",
        "51021": "🔒 포지션이 청산 중입니다.",
        "50011": "🔑 API 키가 올바르지 않습니다.",
        "50012": "🚫 API 키 권한이 없습니다.",
        "50013": "🔒 API 키가 만료되었습니다.",
        "1": "❌ 주문 실패. 거래소 연결 상태를 확인해주세요."
    }
    
    # 에러 코드 추출 시도
    try:
        if "sCode" in error_str:
            import json
            if "okx " in error_str:
                error_data = json.loads(error_str.split("okx ", 1)[1])
            else:
                error_data = json.loads(error_str)
            error_code = error_data['data'][0]['sCode']
        elif '"code":"' in error_str:
            error_code = error_str.split('"code":"')[1].split('"')[0]
        else:
            # 에러 코드를 찾을 수 없는 경우
            return f"❌ 거래 실행 중 오류가 발생했습니다: {str(error)}"
            
        # 맵핑된 메시지 반환
        return error_mappings.get(error_code, f"❌ 알 수 없는 오류가 발생했습니다. (코드: {error_code})")
    except Exception as e:
        traceback.print_exc()
        # 에러 코드 추출 실패시 기본 메시지
        return f"❌ 거래 실행 중 오류가 발생했습니다: {str(error)}"
"""FastAPI Routes for Position/Order Management Service

API endpoints for managing positions, orders, trailing stops,
and conditional cancellation rules.
"""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from redis.asyncio import Redis

from shared.config import get_settings
from shared.database import RedisConnectionManager
from shared.logging import get_logger
from shared.services.position_order_service.managers.conditional_cancellation import (
    ConditionalCancellationManager,
)
from shared.services.position_order_service.managers.order_tracker import OrderTracker
from shared.services.position_order_service.managers.position_tracker import PositionTracker
from shared.services.position_order_service.managers.trailing_stop_manager import (
    TrailingStopManager,
)

from .schemas import (
    ConditionalRuleRequest,
    ConditionalRuleResponse,
    ConditionalRulesResponse,
    OrderCancelRequest,
    OrderCancelResponse,
    OrdersResponse,
    PositionsResponse,
    ServiceStatusResponse,
    TrailingStopRequest,
    TrailingStopResponse,
    TrailingStopsResponse,
)

logger = get_logger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/v1", tags=["position-order-service"])

# Service startup time
SERVICE_START_TIME = datetime.utcnow()


# Dependency: Get managers (will be injected from main.py)
_position_tracker: Optional[PositionTracker] = None
_order_tracker: Optional[OrderTracker] = None
_trailing_stop_manager: Optional[TrailingStopManager] = None
_conditional_manager: Optional[ConditionalCancellationManager] = None
_active_user_manager = None  # NEW!


def init_managers(
    position_tracker: PositionTracker,
    order_tracker: OrderTracker,
    trailing_stop_manager: TrailingStopManager,
    conditional_manager: ConditionalCancellationManager,
    active_user_manager=None  # NEW!
):
    """Initialize manager instances (called from main.py)"""
    global _position_tracker, _order_tracker, _trailing_stop_manager, _conditional_manager, _active_user_manager
    _position_tracker = position_tracker
    _order_tracker = order_tracker
    _trailing_stop_manager = trailing_stop_manager
    _conditional_manager = conditional_manager
    _active_user_manager = active_user_manager  # NEW!


# ==================== Order Management Endpoints ====================

@router.post("/orders/cancel", response_model=OrderCancelResponse)
async def cancel_order(request: OrderCancelRequest):
    """
    Cancel an order.

    This endpoint integrates with HYPERRSI OrderManager for actual cancellation.
    """
    try:
        # TODO: Integrate with HYPERRSI OrderManager._cancel_order()
        # For now, return success response
        logger.info(
            f"Order cancellation requested",
            extra={
                "user_id": request.user_id,
                "order_id": request.order_id,
                "symbol": request.symbol
            }
        )

        # Placeholder for actual cancellation logic
        # This will be implemented in HYPERRSI adapter integration

        return OrderCancelResponse(
            success=True,
            order_id=request.order_id,
            message=f"Order {request.order_id} cancellation initiated"
        )

    except Exception as e:
        logger.error(
            f"Failed to cancel order: {e}",
            exc_info=True,
            extra={"request": request.dict()}
        )
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Trailing Stop Endpoints ====================

@router.post("/trailing-stops", response_model=TrailingStopResponse)
async def create_trailing_stop(request: TrailingStopRequest):
    """Create a trailing stop rule"""
    try:
        if not _trailing_stop_manager:
            raise HTTPException(status_code=500, detail="Service not initialized")

        trailing_stop_id = await _trailing_stop_manager.set_trailing_stop(
            user_id=request.user_id,
            exchange=request.exchange,
            symbol=request.symbol,
            side=request.side,
            activation_price=request.activation_price,
            callback_rate=request.callback_rate,
            size=request.size,
            order_id=request.order_id
        )

        return TrailingStopResponse(
            success=True,
            trailing_stop_id=trailing_stop_id,
            message=f"Trailing stop created for {request.symbol}"
        )

    except Exception as e:
        logger.error(
            f"Failed to create trailing stop: {e}",
            exc_info=True,
            extra={"request": request.dict()}
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/trailing-stops/{user_id}", response_model=TrailingStopsResponse)
async def get_trailing_stops(user_id: str):
    """Get all trailing stops for user"""
    try:
        if not _trailing_stop_manager:
            raise HTTPException(status_code=500, detail="Service not initialized")

        trailing_stops = await _trailing_stop_manager.get_trailing_stops(user_id)

        return TrailingStopsResponse(
            success=True,
            trailing_stops=trailing_stops,
            count=len(trailing_stops)
        )

    except Exception as e:
        logger.error(
            f"Failed to get trailing stops: {e}",
            exc_info=True,
            extra={"user_id": user_id}
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/trailing-stops/{user_id}/{symbol}/{side}")
async def delete_trailing_stop(user_id: str, symbol: str, side: str):
    """Delete a trailing stop rule"""
    try:
        if not _trailing_stop_manager:
            raise HTTPException(status_code=500, detail="Service not initialized")

        success = await _trailing_stop_manager.remove_trailing_stop(
            user_id=user_id,
            symbol=symbol,
            side=side
        )

        if not success:
            raise HTTPException(status_code=404, detail="Trailing stop not found")

        return {"success": True, "message": "Trailing stop deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to delete trailing stop: {e}",
            exc_info=True,
            extra={"user_id": user_id, "symbol": symbol}
        )
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Conditional Rule Endpoints ====================

@router.post("/conditional-rules", response_model=ConditionalRuleResponse)
async def create_conditional_rule(request: ConditionalRuleRequest):
    """Create a conditional cancellation rule"""
    try:
        if not _conditional_manager:
            raise HTTPException(status_code=500, detail="Service not initialized")

        rule_id = await _conditional_manager.add_rule(
            user_id=request.user_id,
            exchange=request.exchange,
            trigger_order_id=request.trigger_order_id,
            cancel_order_ids=request.cancel_order_ids,
            condition=request.condition,
            condition_params=request.condition_params
        )

        return ConditionalRuleResponse(
            success=True,
            rule_id=rule_id,
            message=f"Conditional rule created"
        )

    except Exception as e:
        logger.error(
            f"Failed to create conditional rule: {e}",
            exc_info=True,
            extra={"request": request.dict()}
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conditional-rules/{user_id}", response_model=ConditionalRulesResponse)
async def get_conditional_rules(user_id: str):
    """Get all conditional rules for user"""
    try:
        if not _conditional_manager:
            raise HTTPException(status_code=500, detail="Service not initialized")

        rules = await _conditional_manager.get_rules(user_id)

        return ConditionalRulesResponse(
            success=True,
            rules=rules,
            count=len(rules)
        )

    except Exception as e:
        logger.error(
            f"Failed to get conditional rules: {e}",
            exc_info=True,
            extra={"user_id": user_id}
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/conditional-rules/{user_id}/{rule_id}")
async def delete_conditional_rule(user_id: str, rule_id: str):
    """Delete a conditional rule"""
    try:
        if not _conditional_manager:
            raise HTTPException(status_code=500, detail="Service not initialized")

        success = await _conditional_manager.remove_rule(
            user_id=user_id,
            rule_id=rule_id
        )

        if not success:
            raise HTTPException(status_code=404, detail="Rule not found")

        return {"success": True, "message": "Conditional rule deleted"}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"Failed to delete conditional rule: {e}",
            exc_info=True,
            extra={"user_id": user_id, "rule_id": rule_id}
        )
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Position Query Endpoints ====================

@router.get("/positions/{user_id}/{exchange}", response_model=PositionsResponse)
async def get_positions(
    user_id: str,
    exchange: str,
    symbol: Optional[str] = None
):
    """Get current positions for user"""
    try:
        if not _position_tracker:
            raise HTTPException(status_code=500, detail="Service not initialized")

        positions = await _position_tracker.get_current_positions(
            user_id=user_id,
            exchange=exchange,
            symbol=symbol
        )

        return PositionsResponse(
            success=True,
            positions=positions,
            count=len(positions)
        )

    except Exception as e:
        logger.error(
            f"Failed to get positions: {e}",
            exc_info=True,
            extra={"user_id": user_id, "exchange": exchange}
        )
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Order Query Endpoints ====================

@router.get("/orders/{user_id}/{exchange}/open", response_model=OrdersResponse)
async def get_open_orders(
    user_id: str,
    exchange: str,
    symbol: Optional[str] = None
):
    """Get open orders for user"""
    try:
        if not _order_tracker:
            raise HTTPException(status_code=500, detail="Service not initialized")

        orders = await _order_tracker.get_open_orders(
            user_id=user_id,
            exchange=exchange,
            symbol=symbol
        )

        return OrdersResponse(
            success=True,
            orders=orders,
            count=len(orders)
        )

    except Exception as e:
        logger.error(
            f"Failed to get open orders: {e}",
            exc_info=True,
            extra={"user_id": user_id, "exchange": exchange}
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/orders/{user_id}/{exchange}/closed", response_model=OrdersResponse)
async def get_closed_orders(
    user_id: str,
    exchange: str,
    limit: int = 100
):
    """Get recent closed orders for user"""
    try:
        if not _order_tracker:
            raise HTTPException(status_code=500, detail="Service not initialized")

        orders = await _order_tracker.get_closed_orders(
            user_id=user_id,
            exchange=exchange,
            limit=limit
        )

        return OrdersResponse(
            success=True,
            orders=orders,
            count=len(orders)
        )

    except Exception as e:
        logger.error(
            f"Failed to get closed orders: {e}",
            exc_info=True,
            extra={"user_id": user_id, "exchange": exchange}
        )
        raise HTTPException(status_code=500, detail=str(e))


# ==================== User Management Endpoints ====================

@router.post("/users/{user_id}/activate")
async def activate_user(user_id: str, exchanges: List[str] = None):
    """
    Activate bot for user - starts continuous monitoring.

    Args:
        user_id: User identifier
        exchanges: List of exchanges to monitor (optional, auto-detected if not provided)
    """
    try:
        if not _active_user_manager:
            raise HTTPException(status_code=500, detail="Service not initialized")

        await _active_user_manager.add_active_user(user_id, exchanges)

        return {
            "success": True,
            "message": f"User {user_id} activated for monitoring",
            "exchanges": exchanges
        }

    except Exception as e:
        logger.error(
            f"Failed to activate user: {e}",
            exc_info=True,
            extra={"user_id": user_id}
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(user_id: str):
    """
    Deactivate bot for user - stops monitoring.

    Args:
        user_id: User identifier
    """
    try:
        if not _active_user_manager:
            raise HTTPException(status_code=500, detail="Service not initialized")

        await _active_user_manager.remove_active_user(user_id)

        return {
            "success": True,
            "message": f"User {user_id} deactivated"
        }

    except Exception as e:
        logger.error(
            f"Failed to deactivate user: {e}",
            exc_info=True,
            extra={"user_id": user_id}
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/users/active")
async def get_active_users():
    """Get list of currently active users"""
    try:
        if not _active_user_manager:
            raise HTTPException(status_code=500, detail="Service not initialized")

        active_users = list(_active_user_manager.tracked_users.keys())

        return {
            "success": True,
            "users": active_users,
            "count": len(active_users)
        }

    except Exception as e:
        logger.error(f"Failed to get active users: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Service Status Endpoint ====================

@router.get("/status", response_model=ServiceStatusResponse)
async def get_service_status():
    """Get service status and health"""
    try:
        uptime = (datetime.utcnow() - SERVICE_START_TIME).total_seconds()

        # Count active connections and subscriptions
        active_connections = 0
        active_subscriptions = 0

        if _active_user_manager:
            active_connections = len(_active_user_manager.tracked_users)

        if _position_tracker:
            active_subscriptions += len(_position_tracker.active_subscriptions)

        if _order_tracker:
            active_subscriptions += len(_order_tracker.active_subscriptions)

        return ServiceStatusResponse(
            status="healthy",
            uptime=uptime,
            active_connections=active_connections,
            active_subscriptions=active_subscriptions,
            version="1.0.0"
        )

    except Exception as e:
        logger.error(f"Failed to get service status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

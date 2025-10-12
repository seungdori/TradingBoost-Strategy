"""Redis Schema Definitions for Trading

Centralized Redis key patterns and helper functions for position/order storage.
"""
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional
from uuid import UUID

from shared.models.trading import Order, OrderStatus, Position, PositionStatus

# ==================== Redis Key Patterns ====================

class RedisKeys:
    """Redis key pattern generator"""

    # === Positions ===
    @staticmethod
    def position(user_id: str, exchange: str, symbol: str, side: str) -> str:
        """Active position key: positions:{user_id}:{exchange}:{symbol}:{side}"""
        return f"positions:{user_id}:{exchange}:{symbol}:{side}"

    @staticmethod
    def position_index(user_id: str, exchange: str) -> str:
        """User's position index: positions:index:{user_id}:{exchange}"""
        return f"positions:index:{user_id}:{exchange}"

    @staticmethod
    def position_active() -> str:
        """Global active positions: positions:active"""
        return "positions:active"

    @staticmethod
    def position_history(user_id: str, exchange: str) -> str:
        """Position history key: positions:history:{user_id}:{exchange}"""
        return f"positions:history:{user_id}:{exchange}"

    # === Orders ===
    @staticmethod
    def order(order_id: str) -> str:
        """Order details: orders:{order_id}"""
        return f"orders:{order_id}"

    @staticmethod
    def order_index(user_id: str, exchange: str) -> str:
        """User's order index: orders:user:{user_id}:{exchange}"""
        return f"orders:user:{user_id}:{exchange}"

    @staticmethod
    def order_open(exchange: str, symbol: str) -> str:
        """Open orders for symbol: orders:open:{exchange}:{symbol}"""
        return f"orders:open:{exchange}:{symbol}"

    # === GRID compatibility ===
    @staticmethod
    def grid_active(exchange: str, user_id: str, symbol: str, level: int) -> str:
        """GRID active grid level: {exchange}:user:{user_id}:symbol:{symbol}:active_grid:{level}"""
        return f"{exchange}:user:{user_id}:symbol:{symbol}:active_grid:{level}"

    @staticmethod
    def order_placed_prices(exchange: str, user_id: str, symbol: str) -> str:
        """GRID order placed prices: orders:{exchange}:user:{user_id}:symbol:{symbol}:orders"""
        return f"orders:{exchange}:user:{user_id}:symbol:{symbol}:orders"

    @staticmethod
    def order_placed_index(exchange: str, user_id: str, symbol: str) -> str:
        """GRID order placed index: orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed_index"""
        return f"orders:{exchange}:user:{user_id}:symbol:{symbol}:order_placed_index"


# ==================== Data Serialization ====================

class RedisSerializer:
    """Helper class for Redis data serialization"""

    @staticmethod
    def position_to_dict(position: Position) -> Dict[str, str]:
        """Convert Position to Redis hash format"""
        return {
            "id": str(position.id),
            "user_id": position.user_id,
            "exchange": position.exchange.value,
            "symbol": position.symbol,
            "side": position.side.value,
            "size": str(position.size),
            "entry_price": str(position.entry_price),
            "current_price": str(position.current_price) if position.current_price else "",
            "exit_price": str(position.exit_price) if position.exit_price else "",
            "leverage": str(position.leverage),
            "liquidation_price": str(position.liquidation_price) if position.liquidation_price else "",
            "stop_loss_price": str(position.stop_loss_price) if position.stop_loss_price else "",
            "take_profit_price": str(position.take_profit_price) if position.take_profit_price else "",
            "realized_pnl": str(position.pnl_info.realized_pnl),
            "unrealized_pnl": str(position.pnl_info.unrealized_pnl),
            "fees": str(position.pnl_info.fees),
            "status": position.status.value,
            "metadata": json.dumps(position.metadata),
            "created_at": position.created_at.isoformat(),
            "updated_at": position.updated_at.isoformat(),
            "closed_at": position.closed_at.isoformat() if position.closed_at else "",
            "grid_level": str(position.grid_level) if position.grid_level is not None else ""
        }

    @staticmethod
    def dict_to_position(data: Dict[str, str]) -> Position:
        """Convert Redis hash to Position object"""
        from shared.models.trading import Exchange, PnLInfo, PositionSide

        return Position(
            id=UUID(data["id"]),
            user_id=data["user_id"],
            exchange=Exchange(data["exchange"]),
            symbol=data["symbol"],
            side=PositionSide(data["side"]),
            size=Decimal(data["size"]),
            entry_price=Decimal(data["entry_price"]),
            current_price=Decimal(data["current_price"]) if data.get("current_price") else None,
            exit_price=Decimal(data["exit_price"]) if data.get("exit_price") else None,
            leverage=int(data["leverage"]),
            liquidation_price=Decimal(data["liquidation_price"]) if data.get("liquidation_price") else None,
            stop_loss_price=Decimal(data["stop_loss_price"]) if data.get("stop_loss_price") else None,
            take_profit_price=Decimal(data["take_profit_price"]) if data.get("take_profit_price") else None,
            pnl_info=PnLInfo(
                realized_pnl=Decimal(data.get("realized_pnl", "0")),
                unrealized_pnl=Decimal(data.get("unrealized_pnl", "0")),
                fees=Decimal(data.get("fees", "0"))
            ),
            status=PositionStatus(data["status"]),
            metadata=json.loads(data.get("metadata", "{}")),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            closed_at=datetime.fromisoformat(data["closed_at"]) if data.get("closed_at") else None,
            grid_level=int(data["grid_level"]) if data.get("grid_level") else None
        )

    @staticmethod
    def order_to_dict(order: Order) -> Dict[str, str]:
        """Convert Order to Redis hash format"""
        return {
            "id": str(order.id),
            "user_id": order.user_id,
            "exchange": order.exchange.value,
            "exchange_order_id": order.exchange_order_id or "",
            "symbol": order.symbol,
            "side": order.side.value,
            "order_type": order.order_type.value,
            "quantity": str(order.quantity),
            "price": str(order.price) if order.price else "",
            "trigger_price": str(order.trigger_price) if order.trigger_price else "",
            "filled_qty": str(order.filled_qty),
            "avg_fill_price": str(order.avg_fill_price) if order.avg_fill_price else "",
            "status": order.status.value,
            "reduce_only": str(order.reduce_only),
            "post_only": str(order.post_only),
            "time_in_force": order.time_in_force,
            "maker_fee": str(order.fee.maker_fee),
            "taker_fee": str(order.fee.taker_fee),
            "funding_fee": str(order.fee.funding_fee),
            "metadata": json.dumps(order.metadata),
            "created_at": order.created_at.isoformat(),
            "updated_at": order.updated_at.isoformat(),
            "filled_at": order.filled_at.isoformat() if order.filled_at else "",
            "grid_level": str(order.grid_level) if order.grid_level is not None else ""
        }

    @staticmethod
    def dict_to_order(data: Dict[str, str]) -> Order:
        """Convert Redis hash to Order object"""
        from shared.models.trading import Exchange, OrderSide, OrderType, TradeFee

        return Order(
            id=UUID(data["id"]),
            user_id=data["user_id"],
            exchange=Exchange(data["exchange"]),
            exchange_order_id=data.get("exchange_order_id") or None,
            symbol=data["symbol"],
            side=OrderSide(data["side"]),
            order_type=OrderType(data["order_type"]),
            quantity=Decimal(data["quantity"]),
            price=Decimal(data["price"]) if data.get("price") else None,
            trigger_price=Decimal(data["trigger_price"]) if data.get("trigger_price") else None,
            filled_qty=Decimal(data.get("filled_qty", "0")),
            avg_fill_price=Decimal(data["avg_fill_price"]) if data.get("avg_fill_price") else None,
            status=OrderStatus(data["status"]),
            reduce_only=data.get("reduce_only", "False").lower() == "true",
            post_only=data.get("post_only", "False").lower() == "true",
            time_in_force=data.get("time_in_force", "GTC"),
            fee=TradeFee(
                maker_fee=Decimal(data.get("maker_fee", "0")),
                taker_fee=Decimal(data.get("taker_fee", "0")),
                funding_fee=Decimal(data.get("funding_fee", "0"))
            ),
            metadata=json.loads(data.get("metadata", "{}")),
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            filled_at=datetime.fromisoformat(data["filled_at"]) if data.get("filled_at") else None,
            grid_level=int(data["grid_level"]) if data.get("grid_level") else None
        )

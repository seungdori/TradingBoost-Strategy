"""
Event logger for recording backtest events and decisions.
"""

from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field
from enum import Enum

from shared.logging import get_logger

logger = get_logger(__name__)


class EventType(str, Enum):
    """Event type enumeration."""
    SIGNAL_GENERATED = "signal_generated"
    POSITION_OPENED = "position_opened"
    POSITION_CLOSED = "position_closed"
    STOP_LOSS_HIT = "stop_loss_hit"
    TAKE_PROFIT_HIT = "take_profit_hit"
    TRAILING_STOP_ACTIVATED = "trailing_stop_activated"
    TRAILING_STOP_UPDATED = "trailing_stop_updated"
    TRAILING_STOP_HIT = "trailing_stop_hit"
    BALANCE_UPDATED = "balance_updated"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class BacktestEvent:
    """Single backtest event record."""

    timestamp: datetime
    event_type: EventType
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    severity: str = "info"  # info, warning, error


class EventLogger:
    """Records and manages backtest events."""

    def __init__(self, max_events: int = 10000):
        """
        Initialize event logger.

        Args:
            max_events: Maximum number of events to store
        """
        self.max_events = max_events
        self.events: List[BacktestEvent] = []
        self._event_counts: Dict[EventType, int] = {}

        logger.info(f"EventLogger initialized with max_events={max_events}")

    def log_event(
        self,
        event_type: EventType,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        severity: str = "info"
    ) -> None:
        """
        Log a backtest event.

        Args:
            event_type: Type of event
            message: Event description
            data: Additional event data
            severity: Event severity level
        """
        event = BacktestEvent(
            timestamp=datetime.utcnow(),
            event_type=event_type,
            message=message,
            data=data or {},
            severity=severity
        )

        self.events.append(event)

        # Update counts
        self._event_counts[event_type] = self._event_counts.get(event_type, 0) + 1

        # Trim events if exceeding max
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]

        # Log to console for important events
        if severity == "error":
            logger.error(f"[{event_type.value}] {message}")
        elif severity == "warning":
            logger.warning(f"[{event_type.value}] {message}")
        elif event_type in [
            EventType.POSITION_OPENED,
            EventType.POSITION_CLOSED,
            EventType.STOP_LOSS_HIT,
            EventType.TAKE_PROFIT_HIT
        ]:
            logger.info(f"[{event_type.value}] {message}")

    def log_signal(
        self,
        timestamp: datetime,
        signal_type: str,
        reason: str,
        indicators: Dict[str, Any]
    ) -> None:
        """
        Log trading signal generation.

        Args:
            timestamp: Signal timestamp
            signal_type: Signal type (long/short/none)
            reason: Signal reason
            indicators: Indicator values
        """
        self.log_event(
            EventType.SIGNAL_GENERATED,
            f"Signal generated: {signal_type} - {reason}",
            data={
                "timestamp": timestamp.isoformat(),
                "signal_type": signal_type,
                "reason": reason,
                "indicators": indicators
            }
        )

    def log_position_open(
        self,
        timestamp: datetime,
        side: str,
        entry_price: float,
        quantity: float,
        leverage: float,
        reason: Optional[str] = None,
        indicators: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log position opening.

        Args:
            timestamp: Entry timestamp
            side: Position side
            entry_price: Entry price
            quantity: Position size
            leverage: Leverage used
            reason: Entry reason/signal description
            indicators: Indicator values at entry
        """
        data = {
            "timestamp": timestamp.isoformat(),
            "side": side,
            "entry_price": entry_price,
            "quantity": quantity,
            "leverage": leverage
        }

        if reason:
            data["reason"] = reason
        if indicators:
            data["indicators"] = indicators

        self.log_event(
            EventType.POSITION_OPENED,
            f"Position opened: {side} @ {entry_price:.2f}",
            data=data
        )

    def log_position_close(
        self,
        timestamp: datetime,
        side: str,
        exit_price: float,
        pnl: float,
        pnl_percent: float,
        reason: str
    ) -> None:
        """
        Log position closing.

        Args:
            timestamp: Exit timestamp
            side: Position side
            exit_price: Exit price
            pnl: Realized P&L
            pnl_percent: P&L percentage
            reason: Exit reason
        """
        self.log_event(
            EventType.POSITION_CLOSED,
            f"Position closed: {side} @ {exit_price:.2f}, PNL={pnl:.2f} ({pnl_percent:.2f}%)",
            data={
                "timestamp": timestamp.isoformat(),
                "side": side,
                "exit_price": exit_price,
                "pnl": pnl,
                "pnl_percent": pnl_percent,
                "reason": reason
            }
        )

    def log_stop_loss(
        self,
        timestamp: datetime,
        stop_price: float,
        filled_price: float,
        pnl: float
    ) -> None:
        """
        Log stop loss hit.

        Args:
            timestamp: Hit timestamp
            stop_price: Stop loss price
            filled_price: Actual filled price
            pnl: Realized P&L
        """
        self.log_event(
            EventType.STOP_LOSS_HIT,
            f"Stop loss hit @ {stop_price:.2f}, filled @ {filled_price:.2f}",
            data={
                "timestamp": timestamp.isoformat(),
                "stop_price": stop_price,
                "filled_price": filled_price,
                "pnl": pnl,
                "slippage": abs(filled_price - stop_price)
            },
            severity="warning"
        )

    def log_take_profit(
        self,
        timestamp: datetime,
        tp_price: float,
        pnl: float
    ) -> None:
        """
        Log take profit hit.

        Args:
            timestamp: Hit timestamp
            tp_price: Take profit price
            pnl: Realized P&L
        """
        self.log_event(
            EventType.TAKE_PROFIT_HIT,
            f"Take profit hit @ {tp_price:.2f}, PNL={pnl:.2f}",
            data={
                "timestamp": timestamp.isoformat(),
                "tp_price": tp_price,
                "pnl": pnl
            }
        )

    def log_trailing_stop_update(
        self,
        timestamp: datetime,
        old_price: Optional[float],
        new_price: float,
        current_price: float
    ) -> None:
        """
        Log trailing stop update.

        Args:
            timestamp: Update timestamp
            old_price: Previous trailing stop price
            new_price: New trailing stop price
            current_price: Current market price
        """
        self.log_event(
            EventType.TRAILING_STOP_UPDATED,
            f"Trailing stop updated: {old_price} -> {new_price:.2f}",
            data={
                "timestamp": timestamp.isoformat(),
                "old_price": old_price,
                "new_price": new_price,
                "current_price": current_price
            }
        )

    def log_error(
        self,
        message: str,
        error: Exception,
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Log error event.

        Args:
            message: Error message
            error: Exception object
            context: Additional context
        """
        self.log_event(
            EventType.ERROR,
            message,
            data={
                "error_type": type(error).__name__,
                "error_message": str(error),
                "context": context or {}
            },
            severity="error"
        )

    def get_events(
        self,
        event_type: Optional[EventType] = None,
        limit: Optional[int] = None
    ) -> List[BacktestEvent]:
        """
        Get logged events.

        Args:
            event_type: Filter by event type
            limit: Maximum number of events to return

        Returns:
            List of events
        """
        events = self.events

        if event_type:
            events = [e for e in events if e.event_type == event_type]

        if limit:
            events = events[-limit:]

        return events

    def get_event_summary(self) -> Dict[str, Any]:
        """
        Get summary of logged events.

        Returns:
            Event summary statistics
        """
        return {
            "total_events": len(self.events),
            "event_counts": {
                event_type.value: count
                for event_type, count in self._event_counts.items()
            },
            "errors": len([e for e in self.events if e.severity == "error"]),
            "warnings": len([e for e in self.events if e.severity == "warning"])
        }

    def export_events(self) -> List[Dict[str, Any]]:
        """
        Export events to dictionary format.

        Returns:
            List of event dictionaries
        """
        return [
            {
                "timestamp": event.timestamp.isoformat(),
                "event_type": event.event_type.value,
                "message": event.message,
                "data": event.data,
                "severity": event.severity
            }
            for event in self.events
        ]

    def clear(self) -> None:
        """Clear all logged events."""
        self.events.clear()
        self._event_counts.clear()
        logger.info("EventLogger cleared")

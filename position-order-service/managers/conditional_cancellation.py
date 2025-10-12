"""Conditional Order Cancellation Manager

Manages conditional rules for automatic order cancellation based on
trigger conditions (e.g., cancel Order B when Order A fills).
"""

import asyncio
import json
from typing import Optional, Dict, Any, List
from datetime import datetime
from decimal import Decimal
from uuid import uuid4

from redis.asyncio import Redis
import ccxt.async_support as ccxt

from shared.logging import get_logger

from core.event_types import ConditionalRuleEvent, EventType, OrderEvent
from core.pubsub_manager import PubSubManager

logger = get_logger(__name__)


class ConditionalRule:
    """Conditional cancellation rule"""

    def __init__(
        self,
        rule_id: str,
        user_id: str,
        exchange: str,
        trigger_order_id: str,
        cancel_order_ids: List[str],
        condition: str,  # 'filled', 'canceled', 'price_reached'
        condition_params: Optional[Dict[str, Any]] = None
    ):
        self.rule_id = rule_id
        self.user_id = user_id
        self.exchange = exchange
        self.trigger_order_id = trigger_order_id
        self.cancel_order_ids = cancel_order_ids
        self.condition = condition
        self.condition_params = condition_params or {}

        self.triggered = False
        self.created_at = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for Redis storage"""
        return {
            "rule_id": self.rule_id,
            "user_id": self.user_id,
            "exchange": self.exchange,
            "trigger_order_id": self.trigger_order_id,
            "cancel_order_ids": json.dumps(self.cancel_order_ids),
            "condition": self.condition,
            "condition_params": json.dumps(self.condition_params),
            "triggered": str(self.triggered),
            "created_at": self.created_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'ConditionalRule':
        """Create from dictionary"""
        rule = cls(
            rule_id=data['rule_id'],
            user_id=data['user_id'],
            exchange=data['exchange'],
            trigger_order_id=data['trigger_order_id'],
            cancel_order_ids=json.loads(data['cancel_order_ids']),
            condition=data['condition'],
            condition_params=json.loads(data.get('condition_params', '{}'))
        )
        rule.triggered = data.get('triggered', 'False') == 'True'

        if data.get('created_at'):
            rule.created_at = datetime.fromisoformat(data['created_at'])

        return rule


class ConditionalCancellationManager:
    """
    Conditional order cancellation management service.

    Features:
    - Order-based triggers (filled, canceled)
    - Price-based triggers
    - Multiple order cancellation
    - Pub/sub notifications
    """

    def __init__(
        self,
        redis_client: Redis,
        pubsub_manager: PubSubManager
    ):
        """
        Args:
            redis_client: Redis client
            pubsub_manager: PubSub manager for events
        """
        self.redis_client = redis_client
        self.pubsub_manager = pubsub_manager

        # Active rules: {rule_id -> ConditionalRule}
        self.active_rules: Dict[str, ConditionalRule] = {}

    async def add_rule(
        self,
        user_id: str,
        exchange: str,
        trigger_order_id: str,
        cancel_order_ids: List[str],
        condition: str = "filled",
        condition_params: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Add a conditional cancellation rule.

        Args:
            user_id: User identifier
            exchange: Exchange identifier
            trigger_order_id: Order ID that triggers the rule
            cancel_order_ids: List of order IDs to cancel
            condition: Trigger condition ('filled', 'canceled', 'price_reached')
            condition_params: Additional parameters for condition

        Returns:
            Rule ID
        """
        try:
            # Generate rule ID
            rule_id = str(uuid4())

            # Create rule
            rule = ConditionalRule(
                rule_id=rule_id,
                user_id=user_id,
                exchange=exchange,
                trigger_order_id=trigger_order_id,
                cancel_order_ids=cancel_order_ids,
                condition=condition,
                condition_params=condition_params
            )

            # Store in Redis
            redis_key = f"conditional_rules:{user_id}:{rule_id}"
            await self.redis_client.hset(redis_key, mapping=rule.to_dict())
            await self.redis_client.expire(redis_key, 86400)  # 24 hours

            # Add to active tracking
            self.active_rules[rule_id] = rule

            # Add to user's rule index
            index_key = f"conditional_rules:index:{user_id}"
            await self.redis_client.sadd(index_key, rule_id)

            logger.info(
                f"Added conditional rule: {rule_id}",
                extra={
                    "user_id": user_id,
                    "trigger_order": trigger_order_id,
                    "cancel_orders": cancel_order_ids,
                    "condition": condition
                }
            )

            return rule_id

        except Exception as e:
            logger.error(
                f"Failed to add conditional rule: {e}",
                exc_info=True,
                extra={"user_id": user_id}
            )
            raise

    async def check_and_execute(self, order_event: OrderEvent):
        """
        Check if order event triggers any conditional rules and execute.

        This is called by OrderTracker for every order event.

        Args:
            order_event: OrderEvent instance
        """
        try:
            # Find rules that match this order
            for rule_id, rule in list(self.active_rules.items()):
                if rule.user_id != order_event.user_id:
                    continue

                if rule.exchange != order_event.exchange:
                    continue

                if rule.trigger_order_id != order_event.order_id:
                    continue

                # Check if condition is met
                condition_met = False

                if rule.condition == 'filled' and order_event.status == 'filled':
                    condition_met = True
                elif rule.condition == 'canceled' and order_event.status == 'canceled':
                    condition_met = True
                elif rule.condition == 'partially_filled' and order_event.status == 'partially_filled':
                    condition_met = True

                if condition_met:
                    await self._execute_rule(rule, order_event)

        except Exception as e:
            logger.error(
                f"Error checking conditional rules: {e}",
                exc_info=True,
                extra={"order_event": order_event.dict()}
            )

    async def _execute_rule(
        self,
        rule: ConditionalRule,
        trigger_event: OrderEvent
    ):
        """
        Execute conditional rule by canceling specified orders.

        Args:
            rule: ConditionalRule instance
            trigger_event: OrderEvent that triggered the rule
        """
        try:
            logger.warning(
                f"Conditional rule TRIGGERED: {rule.rule_id}",
                extra={
                    "user_id": rule.user_id,
                    "trigger_order": rule.trigger_order_id,
                    "condition": rule.condition
                }
            )

            # Cancel all specified orders
            # (This would integrate with OrderManager from HYPERRSI)
            # For now, we'll publish an event

            # Publish conditional rule triggered event
            event = ConditionalRuleEvent(
                event_type=EventType.CONDITIONAL_RULE_TRIGGERED,
                user_id=rule.user_id,
                exchange=rule.exchange,
                rule_id=rule.rule_id,
                trigger_order_id=rule.trigger_order_id,
                cancel_order_ids=rule.cancel_order_ids,
                condition=rule.condition,
                triggered=True,
                metadata={
                    "trigger_event": trigger_event.dict()
                }
            )

            await self.pubsub_manager.publish_conditional_rule_event(event)

            # Mark rule as triggered
            rule.triggered = True

            # Update Redis state
            redis_key = f"conditional_rules:{rule.user_id}:{rule.rule_id}"
            await self.redis_client.hset(redis_key, mapping=rule.to_dict())

            # Remove from active tracking
            if rule.rule_id in self.active_rules:
                del self.active_rules[rule.rule_id]

            logger.info(
                f"Conditional rule executed",
                extra={
                    "rule_id": rule.rule_id,
                    "cancel_orders": rule.cancel_order_ids
                }
            )

        except Exception as e:
            logger.error(
                f"Error executing conditional rule: {e}",
                exc_info=True,
                extra={"rule": rule.to_dict()}
            )

    async def remove_rule(
        self,
        user_id: str,
        rule_id: str
    ) -> bool:
        """
        Remove conditional cancellation rule.

        Args:
            user_id: User identifier
            rule_id: Rule ID

        Returns:
            True if removed successfully
        """
        try:
            # Remove from active tracking
            if rule_id in self.active_rules:
                del self.active_rules[rule_id]

            # Remove from Redis
            redis_key = f"conditional_rules:{user_id}:{rule_id}"
            await self.redis_client.delete(redis_key)

            # Remove from index
            index_key = f"conditional_rules:index:{user_id}"
            await self.redis_client.srem(index_key, rule_id)

            logger.info(
                f"Removed conditional rule",
                extra={"user_id": user_id, "rule_id": rule_id}
            )

            return True

        except Exception as e:
            logger.error(
                f"Failed to remove conditional rule: {e}",
                exc_info=True,
                extra={"user_id": user_id, "rule_id": rule_id}
            )
            return False

    async def get_rules(
        self,
        user_id: str
    ) -> List[Dict[str, Any]]:
        """
        Get all conditional rules for user.

        Args:
            user_id: User identifier

        Returns:
            List of rule dictionaries
        """
        try:
            rules = []

            # Get rule IDs from index
            index_key = f"conditional_rules:index:{user_id}"
            rule_ids = await self.redis_client.smembers(index_key)

            for rule_id in rule_ids:
                redis_key = f"conditional_rules:{user_id}:{rule_id}"
                data = await self.redis_client.hgetall(redis_key)

                if data:
                    rules.append(data)

            return rules

        except Exception as e:
            logger.error(
                f"Failed to get conditional rules: {e}",
                exc_info=True,
                extra={"user_id": user_id}
            )
            return []

    async def load_active_rules(self, user_id: str):
        """
        Load all active rules for user into memory.

        Args:
            user_id: User identifier
        """
        try:
            rules_data = await self.get_rules(user_id)

            for data in rules_data:
                rule = ConditionalRule.from_dict(data)

                # Only load non-triggered rules
                if not rule.triggered:
                    self.active_rules[rule.rule_id] = rule

            logger.info(
                f"Loaded {len(self.active_rules)} active conditional rules",
                extra={"user_id": user_id}
            )

        except Exception as e:
            logger.error(
                f"Failed to load active rules: {e}",
                exc_info=True,
                extra={"user_id": user_id}
            )

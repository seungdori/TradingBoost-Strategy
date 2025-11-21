#!/usr/bin/env python3
"""
Check OKX order history for ETH-USDT-SWAP short position
"""
import asyncio
import os
from datetime import datetime, timedelta

# Add project root to path
import sys
sys.path.insert(0, '/Users/seunghyun/TradingBoost-Strategy')

from shared.database.redis_helper import get_redis_client
from HYPERRSI.src.trading.services.order_wrapper import OrderWrapper
from shared.security.encryption import decrypt_api_key


async def check_order_history():
    user_id = "586156710277369942"
    symbol = "ETH-USDT-SWAP"

    # Get API keys from Redis
    redis = await get_redis_client()
    api_data = await redis.hgetall(f"user:{user_id}:api:keys")

    if not api_data:
        print(f"❌ No API keys found for user {user_id}")
        return

    api_keys = {
        'api_key': decrypt_api_key(api_data['api_key']),
        'api_secret': decrypt_api_key(api_data['api_secret']),
        'passphrase': decrypt_api_key(api_data['passphrase'])
    }

    # Create exchange wrapper
    exchange = OrderWrapper(user_id, api_keys)

    try:
        # Fetch recent orders (last 7 days)
        since = int((datetime.now() - timedelta(days=7)).timestamp() * 1000)

        print(f"📊 Fetching trade history for {symbol}...")
        print(f"   User: {user_id}")
        print(f"   Since: {datetime.fromtimestamp(since/1000)}")
        print("=" * 80)

        # Get filled trades using fetch_my_trades
        trades = await exchange.exchange.fetch_my_trades(
            symbol=symbol,
            since=since,
            limit=100
        )

        # Filter for short positions (sell to open)
        short_trades = []
        for trade in trades:
            info = trade.get('info', {})
            pos_side = info.get('posSide', '')
            # 포지션 side가 short이고, buy가 아닌 sell (진입)
            if pos_side == 'short' and trade.get('side') == 'sell':
                short_trades.append(trade)

        print(f"\n📈 Found {len(short_trades)} SHORT entry trades")
        print("=" * 80)

        # Sort by timestamp
        short_trades.sort(key=lambda x: x['timestamp'])

        # Group trades by order ID to get entry sizes
        from collections import defaultdict
        entries_by_order = defaultdict(list)
        for trade in short_trades:
            order_id = trade.get('order')
            entries_by_order[order_id].append(trade)

        # Calculate total size per entry
        entries = []
        for order_id, trades_list in entries_by_order.items():
            total_amount = sum(float(t.get('amount', 0)) for t in trades_list)
            avg_price = sum(float(t.get('price', 0)) * float(t.get('amount', 0)) for t in trades_list) / total_amount if total_amount > 0 else 0
            timestamp = trades_list[0]['timestamp']
            entries.append({
                'timestamp': timestamp,
                'amount': total_amount,
                'price': avg_price,
                'order_id': order_id
            })

        # Sort entries by timestamp
        entries.sort(key=lambda x: x['timestamp'])

        total_size = 0.0
        for i, entry in enumerate(entries, 1):
            amount = entry['amount']
            total_size += amount

            timestamp = datetime.fromtimestamp(entry['timestamp'] / 1000)
            price = entry['price']

            print(f"\n진입 #{i}")
            print(f"   시간: {timestamp}")
            print(f"   크기: {amount:.4f} 계약")
            print(f"   가격: ${price:,.2f}")
            print(f"   누적: {total_size:.4f} 계약")

            # Calculate ratio if previous exists
            if i > 1:
                prev_amount = entries[i-2]['amount']
                if prev_amount > 0:
                    ratio = amount / prev_amount
                    print(f"   배율: {ratio:.4f}x (이전 대비)")

        print("\n" + "=" * 80)
        print(f"📊 총 포지션 크기: {total_size:.4f} 계약")
        print(f"📊 Redis size: 32.32 계약")
        print(f"📊 차이: {abs(total_size - 32.32):.4f} 계약")

    finally:
        await exchange.close()


if __name__ == "__main__":
    asyncio.run(check_order_history())

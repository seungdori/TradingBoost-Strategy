"""ETH 일치율 검증"""
import asyncio
from verify_match_rate import verify_match_rate

async def main():
    for tf in ["15m", "1m", "3m", "5m", "30m", "1h", "4h"]:
        await verify_match_rate("eth_usdt", tf, days=30 if tf in ["1m"] else 365)
        print()

if __name__ == "__main__":
    asyncio.run(main())

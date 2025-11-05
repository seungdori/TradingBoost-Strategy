#!/usr/bin/env python3
"""Telegram API Health Check Utility

Diagnoses connection issues with the Telegram Bot API by testing:
- DNS resolution
- Network connectivity
- API endpoint reachability
- Bot token validity
"""
import asyncio
import sys
import socket
from pathlib import Path

# Auto-configure PYTHONPATH
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import aiohttp
from aiohttp import ClientTimeout
from HYPERRSI.src.config import TELEGRAM_BOT_TOKEN


async def check_dns_resolution(hostname: str = "api.telegram.org") -> bool:
    """Check DNS resolution for Telegram API"""
    print(f"\n🔍 Checking DNS resolution for {hostname}...")
    try:
        ip_addresses = socket.getaddrinfo(hostname, 443, socket.AF_INET)
        if ip_addresses:
            ips = [addr[4][0] for addr in ip_addresses]
            print(f"✅ DNS resolved successfully: {', '.join(ips)}")
            return True
        else:
            print(f"❌ DNS resolution failed: No IP addresses found")
            return False
    except socket.gaierror as e:
        print(f"❌ DNS resolution failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error during DNS check: {e}")
        return False


async def check_network_connectivity(hostname: str = "api.telegram.org", port: int = 443) -> bool:
    """Check basic network connectivity"""
    print(f"\n🌐 Checking network connectivity to {hostname}:{port}...")
    try:
        # Try to establish a TCP connection
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(hostname, port),
            timeout=10.0
        )
        writer.close()
        await writer.wait_closed()
        print(f"✅ Network connection successful")
        return True
    except asyncio.TimeoutError:
        print(f"❌ Connection timeout after 10 seconds")
        return False
    except Exception as e:
        print(f"❌ Network connection failed: {e}")
        return False


async def check_telegram_api(bot_token: str, timeout_seconds: int = 15) -> bool:
    """Check Telegram Bot API endpoint"""
    print(f"\n🤖 Checking Telegram Bot API with token...")

    url = f"https://api.telegram.org/bot{bot_token}/getMe"

    timeout = ClientTimeout(
        total=timeout_seconds,
        connect=10,
        sock_read=10,
        sock_connect=5
    )

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            print(f"   Requesting: {url[:50]}...")
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    if data.get("ok"):
                        bot_info = data.get("result", {})
                        print(f"✅ Bot API connection successful!")
                        print(f"   Bot username: @{bot_info.get('username')}")
                        print(f"   Bot name: {bot_info.get('first_name')}")
                        print(f"   Bot ID: {bot_info.get('id')}")
                        return True
                    else:
                        print(f"❌ API response not OK: {data}")
                        return False
                else:
                    error_text = await response.text()
                    print(f"❌ API request failed with status {response.status}")
                    print(f"   Error: {error_text}")
                    return False
    except asyncio.TimeoutError:
        print(f"❌ API request timeout after {timeout_seconds} seconds")
        return False
    except aiohttp.ClientConnectorError as e:
        print(f"❌ Connection error: {e}")
        return False
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return False


async def check_proxy_settings() -> None:
    """Check system proxy settings"""
    print(f"\n🔧 Checking proxy settings...")
    import os

    proxy_vars = ["HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "NO_PROXY", "no_proxy"]
    proxy_found = False

    for var in proxy_vars:
        value = os.getenv(var)
        if value:
            print(f"   {var}: {value}")
            proxy_found = True

    if not proxy_found:
        print(f"   No proxy settings detected")


async def main():
    """Run all health checks"""
    print("=" * 60)
    print("🏥 Telegram Bot API Health Check")
    print("=" * 60)

    # Check proxy settings first
    await check_proxy_settings()

    # Check DNS resolution
    dns_ok = await check_dns_resolution()

    # Check network connectivity
    if dns_ok:
        network_ok = await check_network_connectivity()
    else:
        network_ok = False
        print("\n⚠️  Skipping network check due to DNS failure")

    # Check Telegram API
    if network_ok:
        api_ok = await check_telegram_api(TELEGRAM_BOT_TOKEN)
    else:
        api_ok = False
        print("\n⚠️  Skipping API check due to network failure")

    # Summary
    print("\n" + "=" * 60)
    print("📋 Health Check Summary")
    print("=" * 60)
    print(f"DNS Resolution:      {'✅ PASS' if dns_ok else '❌ FAIL'}")
    print(f"Network Connectivity: {'✅ PASS' if network_ok else '❌ FAIL'}")
    print(f"Telegram API:        {'✅ PASS' if api_ok else '❌ FAIL'}")
    print("=" * 60)

    if not (dns_ok and network_ok and api_ok):
        print("\n🔴 Issues detected! Troubleshooting suggestions:")
        if not dns_ok:
            print("   • Check your DNS settings")
            print("   • Try using a different DNS server (e.g., 8.8.8.8, 1.1.1.1)")
        if dns_ok and not network_ok:
            print("   • Check your firewall settings")
            print("   • Verify internet connectivity")
            print("   • Check if Telegram is blocked in your region")
        if network_ok and not api_ok:
            print("   • Verify your bot token is correct")
            print("   • Check if the bot was deleted or token revoked")
        print("\n   Consider using a VPN if Telegram is blocked in your region.")
        return 1
    else:
        print("\n🟢 All checks passed! Telegram bot should work correctly.")
        return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n⚠️  Health check interrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Fatal error: {e}")
        sys.exit(1)

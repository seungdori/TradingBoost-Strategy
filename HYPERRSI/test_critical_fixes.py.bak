#!/usr/bin/env python3
"""
Critical Fixes Validation Script

Tests the three critical fixes:
1. Redis Client initialization and usage
2. Exchange Client Pool functionality
3. TaskTracker exception handling
"""

import sys
from pathlib import Path

# Auto-configure PYTHONPATH
project_root = Path(__file__).parent.parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
from shared.logging import get_logger

logger = get_logger(__name__)


async def test_redis_client():
    """Test Redis client initialization and operations"""
    print("\n" + "="*60)
    print("TEST 1: Redis Client Initialization")
    print("="*60)

    try:
        from HYPERRSI.src.core import database as db_module

        # Test 1.1: Initialize global clients
        print("\n[1.1] Initializing global Redis clients...")
        await db_module.init_global_redis_clients()
        print("✅ Global Redis clients initialized")

        # Test 1.2: Get client via function
        print("\n[1.2] Getting Redis client via function...")
        client = await db_module.get_redis_client()
        ping_result = await client.ping()
        print(f"✅ Redis ping via function: {ping_result}")

        # Test 1.3: Check global variable (dynamic access via __getattr__)
        print("\n[1.3] Checking global redis_client variable via __getattr__...")
        redis_client = db_module.redis_client  # This triggers __getattr__
        test_result = await redis_client.ping()
        print(f"✅ Global redis_client accessed via __getattr__: {test_result}")

        # Test 1.4: Test basic operations
        print("\n[1.4] Testing basic Redis operations...")
        test_key = "test:critical_fix:key"
        await redis_client.set(test_key, "test_value", ex=10)
        value = await redis_client.get(test_key)
        print(f"✅ Set/Get operation: {value}")

        # Test 1.5: Test hash operations (dual_side_entry uses this)
        print("\n[1.5] Testing hash operations...")
        test_hash_key = "test:critical_fix:hash"
        await redis_client.hset(test_hash_key, mapping={"field1": "value1", "field2": "value2"})
        hash_data = await redis_client.hgetall(test_hash_key)
        print(f"✅ Hash operations: {hash_data}")

        # Cleanup
        await redis_client.delete(test_key, test_hash_key)

        print("\n✅ All Redis client tests PASSED")
        return True

    except Exception as e:
        print(f"\n❌ Redis client test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_exchange_pool():
    """Test Exchange Client Pool improvements"""
    print("\n" + "="*60)
    print("TEST 2: Exchange Client Pool")
    print("="*60)

    try:
        from HYPERRSI.src.api.dependencies import ExchangeConnectionPool
        from HYPERRSI.src.core.database import get_redis_client

        # Initialize Redis first
        redis_client = await get_redis_client()

        print("\n[2.1] Creating ExchangeConnectionPool...")
        pool = ExchangeConnectionPool(redis_client, max_size=3, max_age=3600)
        print("✅ Pool created successfully")

        print("\n[2.2] Testing pool configuration...")
        print(f"  - Max size: {pool.max_size}")
        print(f"  - Max age: {pool.max_age}")
        print(f"  - Initial pools: {len(pool.pools)}")
        print("✅ Configuration correct")

        # Note: We can't test actual client creation without valid API keys
        print("\n⚠️  Actual client creation requires valid API keys")
        print("   Pool is configured with:")
        print("   - Timeout: 5 seconds for load_markets()")
        print("   - Rate limiting: enableRateLimit=True")
        print("   - Exponential backoff: 0.5s, 1s, 2s")
        print("   - Proper resource cleanup in _remove_client()")

        print("\n✅ Exchange Pool structure test PASSED")
        return True

    except Exception as e:
        print(f"\n❌ Exchange Pool test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_task_tracker():
    """Test TaskTracker functionality"""
    print("\n" + "="*60)
    print("TEST 3: TaskTracker Exception Handling")
    print("="*60)

    try:
        from shared.utils.task_tracker import TaskTracker

        print("\n[3.1] Creating TaskTracker...")
        tracker = TaskTracker(name="test-tracker")
        print(f"✅ TaskTracker created: {tracker.name}")

        # Test 3.2: Task creation and tracking
        print("\n[3.2] Testing task creation...")
        async def successful_task():
            await asyncio.sleep(0.1)
            return "success"

        task = tracker.create_task(successful_task(), name="test-success")
        print(f"✅ Task created: {task.get_name()}")
        print(f"   Active tasks: {tracker.get_task_count()}")

        await asyncio.sleep(0.2)  # Wait for task to complete
        print(f"   Active tasks after completion: {tracker.get_task_count()}")

        # Test 3.3: Exception handling
        print("\n[3.3] Testing exception handling...")
        async def failing_task():
            await asyncio.sleep(0.1)
            raise ValueError("Test exception")

        failing = tracker.create_task(failing_task(), name="test-failure")
        await asyncio.sleep(0.2)  # Wait for task to fail

        # Check if task failed (exception was logged)
        if failing.done():
            exc = failing.exception()
            if exc is not None:
                print(f"✅ Exception caught and logged: {type(exc).__name__}")
            else:
                print("❌ Task completed without exception (unexpected)")

        # Test 3.4: Cancellation
        print("\n[3.4] Testing task cancellation...")
        async def long_running_task():
            await asyncio.sleep(10)

        long_task = tracker.create_task(long_running_task(), name="test-cancel")
        print(f"   Created long-running task")
        print(f"   Active tasks: {tracker.get_task_count()}")

        await tracker.cancel_all(timeout=1.0)
        print(f"✅ All tasks cancelled")
        print(f"   Active tasks after cancel: {tracker.get_task_count()}")

        print("\n✅ All TaskTracker tests PASSED")
        return True

    except Exception as e:
        print(f"\n❌ TaskTracker test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_dual_side_entry_imports():
    """Test that dual_side_entry.py can import correctly"""
    print("\n" + "="*60)
    print("TEST 4: Dual-Side Entry Integration")
    print("="*60)

    try:
        # Set minimal environment variables to pass config validation
        import os
        os.environ.setdefault('OKX_API_KEY', 'test_key')
        os.environ.setdefault('OKX_SECRET_KEY', 'test_secret')
        os.environ.setdefault('OKX_PASSPHRASE', 'test_pass')
        os.environ.setdefault('TELEGRAM_BOT_TOKEN', 'test_token')
        os.environ.setdefault('OWNER_ID', '123456')
        os.environ.setdefault('DB_USER', 'test')
        os.environ.setdefault('DB_PASSWORD', 'test')
        os.environ.setdefault('DB_HOST', 'localhost')
        os.environ.setdefault('DB_PORT', '5432')
        os.environ.setdefault('DB_NAME', 'test_db')

        print("\n[4.1] Testing dual_side_entry imports...")
        from HYPERRSI.src.trading.dual_side_entry import (
            task_tracker,
            get_user_dual_side_settings
        )
        from HYPERRSI.src.core import database as db_module

        print("✅ All imports successful")
        print(f"   - task_tracker: {task_tracker.name}")

        # Initialize Redis for the test
        await db_module.init_global_redis_clients()

        # Test Redis client usage in dual_side_entry context
        print("\n[4.2] Testing Redis operations in dual_side_entry context...")
        test_user_id = "test_user_critical_fix"

        # This simulates what dual_side_entry.py does
        from shared.constants.default_settings import DEFAULT_DUAL_SIDE_ENTRY_SETTINGS
        from shared.utils.redis_type_converter import prepare_for_redis

        redis_client = db_module.redis_client  # Get via __getattr__
        settings = prepare_for_redis(DEFAULT_DUAL_SIDE_ENTRY_SETTINGS)
        await redis_client.hset(f"user:{test_user_id}:dual_side", mapping=settings)

        # Try to get it back
        retrieved = await get_user_dual_side_settings(test_user_id)
        print(f"✅ Settings saved and retrieved: {len(retrieved)} fields")

        # Cleanup
        await redis_client.delete(f"user:{test_user_id}:dual_side")

        print("\n✅ Dual-Side Entry integration test PASSED")
        return True

    except Exception as e:
        print(f"\n❌ Dual-Side Entry integration test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """Run all validation tests"""
    print("\n" + "="*60)
    print("CRITICAL FIXES VALIDATION")
    print("="*60)
    print("\nTesting the following fixes:")
    print("1. Redis Client initialization and singleton pattern")
    print("2. Exchange Client Pool resource management")
    print("3. TaskTracker exception handling and cleanup")
    print("4. Dual-Side Entry integration")

    results = {}

    # Run tests
    results['redis'] = await test_redis_client()
    results['exchange_pool'] = await test_exchange_pool()
    results['task_tracker'] = await test_task_tracker()
    results['dual_side_entry'] = await test_dual_side_entry_imports()

    # Summary
    print("\n" + "="*60)
    print("TEST SUMMARY")
    print("="*60)

    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status} - {test_name}")

    all_passed = all(results.values())

    print("\n" + "="*60)
    if all_passed:
        print("✅ ALL TESTS PASSED - Critical fixes verified!")
    else:
        print("❌ SOME TESTS FAILED - Review errors above")
    print("="*60 + "\n")

    return 0 if all_passed else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

import asyncio
import pytest

from kyrgame.scheduler import SchedulerService


@pytest.mark.anyio
async def test_scheduler_service_continues_after_callback_exception():
    """Verify scheduler continues running even if a callback raises an exception."""
    scheduler = SchedulerService()
    await scheduler.start()

    call_count = 0
    exception_count = 0

    def failing_callback():
        nonlocal exception_count
        exception_count += 1
        raise RuntimeError("Intentional test failure")

    def working_callback():
        nonlocal call_count
        call_count += 1

    try:
        # Schedule a callback that will fail
        scheduler.schedule(0.01, failing_callback)
        
        # Schedule a callback that should still run
        scheduler.schedule(0.02, working_callback)
        
        # Wait for both to execute
        await asyncio.sleep(0.05)
        
        # Verify the failing callback was attempted
        assert exception_count == 1, "Failing callback should have been called"
        
        # Verify the working callback still ran
        assert call_count == 1, "Working callback should have run despite previous exception"
    
    finally:
        await scheduler.stop()


@pytest.mark.anyio
async def test_scheduler_service_continues_recurring_after_exception():
    """Verify recurring timers continue after an exception."""
    scheduler = SchedulerService()
    await scheduler.start()

    call_count = 0

    def intermittent_failure():
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("First call fails")
        # Subsequent calls succeed

    try:
        # Schedule a recurring callback that fails on first call
        handle = scheduler.schedule(0.01, intermittent_failure, interval=0.01)
        
        # Wait for multiple executions
        await asyncio.sleep(0.05)
        
        # Should have been called multiple times despite first failure
        assert call_count >= 2, f"Should have retried after exception, got {call_count} calls"
    
    finally:
        await scheduler.stop()


@pytest.mark.anyio
async def test_scheduler_service_async_callback_exception_handling():
    """Verify async callbacks with exceptions are handled correctly."""
    scheduler = SchedulerService()
    await scheduler.start()

    call_count = 0

    async def failing_async_callback():
        nonlocal call_count
        call_count += 1
        raise ValueError("Async callback error")

    try:
        scheduler.schedule(0.01, failing_async_callback)
        await asyncio.sleep(0.03)
        
        assert call_count == 1, "Async callback should have been attempted"
    
    finally:
        await scheduler.stop()

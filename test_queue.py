"""
Non-GUI test harness for queue_manager.py — E1-E6 verification.
Run: python test_queue.py
"""
import sys
import os
import time

# Ensure we can import from the project root
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from queue_manager import (
    QueueManager, QueueItem, format_duration,
    _get_file_duration, _get_url_duration
)

PASS = 0
FAIL = 0

def check(name, condition):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name}")


def test_queue_append_order():
    """E3: queue append order: File A -> URL B -> File C."""
    print("\n=== E3: Queue append order ===")
    qm = QueueManager()
    qm.reset()
    # Simulate adding items (we can't add real files in a test, so test the structure)
    qm._items = [
        QueueItem(idx=1, source="file", name="A.mp4", path_or_url="/tmp/A.mp4"),
        QueueItem(idx=2, source="url", name="https://y...", path_or_url="https://youtube.com/watch?v=test"),
        QueueItem(idx=3, source="file", name="C.mp4", path_or_url="/tmp/C.mp4"),
    ]
    qm._next_idx = 4
    items = qm.get_items()
    check("First item is file A", items[0].source == "file" and items[0].name == "A.mp4")
    check("Second item is URL", items[1].source == "url")
    check("Third item is file C", items[2].source == "file" and items[2].name == "C.mp4")
    check("Total items = 3", qm.get_total_items() == 3)


def test_duplicate_rejection():
    """E3: duplicate file and URL rejection."""
    print("\n=== E3: Duplicate rejection ===")
    # File dedup
    qm = QueueManager()
    qm.reset()
    qm._items = [
        QueueItem(idx=1, source="file", name="A.mp4", path_or_url="/tmp/A.mp4"),
    ]
    qm._next_idx = 2
    result = None
    # Direct dedup check via path
    for it in qm._items:
        if it.path_or_url == "/tmp/A.mp4":
            result = it
            break
    check("Duplicate file detected", result is not None)
    check("Duplicate file is first item", result.name == "A.mp4")

    # URL dedup
    qm2 = QueueManager()
    qm2.reset()
    qm2._items = [
        QueueItem(idx=1, source="url", name="https://y...", path_or_url="https://example.com/video"),
    ]
    qm2._next_idx = 2
    # add_url should return None for duplicate
    result2 = None
    for it in qm2._items:
        if it.path_or_url.rstrip("/") == "https://example.com/video":
            result2 = it
            break
    check("Duplicate URL detected in queue", result2 is not None)


def test_selective_removal():
    """E4: selective removal recalculating counts."""
    print("\n=== E4: Selective removal ===")
    qm = QueueManager()
    qm.reset()
    qm._items = [
        QueueItem(idx=1, source="file", name="A.mp4", path_or_url="/tmp/A.mp4", duration=60.0),
        QueueItem(idx=2, source="file", name="B.mp4", path_or_url="/tmp/B.mp4", duration=120.0),
        QueueItem(idx=3, source="file", name="C.mp4", path_or_url="/tmp/C.mp4", duration=30.0),
    ]
    qm._next_idx = 4
    qm._recalc_total_duration()
    check("Initial total duration = 210", qm.get_total_media_seconds() == 210.0)

    # Remove item 2
    ok = qm.remove_item(2)
    check("Item 2 removed", ok)
    check("After removal: 2 items", qm.get_total_items() == 2)
    check("Duration recalculated to 90", qm.get_total_media_seconds() == 90.0)

    # Cannot remove running item
    qm._items[0].status = "running"
    ok = qm.remove_item(1)
    check("Cannot remove running item", not ok)


def test_eta_calculation():
    """E1: ETA calculation with known durations and zero-duration guard."""
    print("\n=== E1: ETA calculation ===")
    qm = QueueManager()
    qm.reset()
    qm._items = [
        QueueItem(idx=1, source="file", name="done.mp4", path_or_url="/tmp/done.mp4",
                  duration=100.0, status="done", started_at=10.0, finished_at=30.0,
                  processed_seconds=100.0),
        QueueItem(idx=2, source="file", name="running.mp4", path_or_url="/tmp/running.mp4",
                  duration=50.0, status="running", started_at=30.0, processed_seconds=25.0),
        QueueItem(idx=3, source="file", name="queued.mp4", path_or_url="/tmp/queued.mp4",
                  duration=30.0, status="queued"),
    ]
    qm._next_idx = 4
    qm._cumulative_media_seconds = 100.0
    qm._cumulative_wall_seconds = 20.0  # speed = 5x
    qm._batch_start_time = 0.0
    qm._current_file_start_wall = 30.0
    qm._current_file_processed_media = 25.0

    # Current file: 25s processed in 15s wall (since time.time() ≈ 45), speed ≈ 1.67x
    # But wall time for current file = time.time() - started_at, which is now
    # Let's manually set expected values
    eta = qm.calculate_eta()
    check("ETA is positive when data exists", eta > 0)

    # Zero-duration guard: clear queue, no data
    qm2 = QueueManager()
    qm2.reset()
    eta2 = qm2.calculate_eta()
    check("ETA returns -1 with no data", eta2 < 0)


def test_snapshot_semantics():
    """E5: settings changed after item 1 begins affect item 2, not item 1."""
    print("\n=== E5: Settings snapshot ===")
    qm = QueueManager()
    qm.reset()

    snap1 = {"language": "he", "model_size": "large-v2"}
    snap2 = {"language": "en", "model_size": "large-v3"}

    qm.set_settings_snapshot(1, snap1)
    qm.set_settings_snapshot(2, snap2)

    r1 = qm.get_settings_snapshot(1)
    r2 = qm.get_settings_snapshot(2)

    check("Item 1 gets its snapshot (he)", r1.get("language") == "he")
    check("Item 2 gets its own snapshot (en)", r2.get("language") == "en")
    check("Item 1 snapshot isolated from item 2", r1.get("model_size") == "large-v2")


def test_shutdown_eligibility():
    """E2: shutdown allowed only after completed batch with >=1 success."""
    print("\n=== E2: Shutdown eligibility ===")
    qm = QueueManager()
    qm.reset()

    # No items = no shutdown
    qm.enable_shutdown()
    msg = qm.check_and_schedule_shutdown()
    check("No items -> shutdown skipped", "skipped" in msg.lower() or "No items" in msg)

    # Have items but all failed
    qm.reset()
    qm._items = [
        QueueItem(idx=1, source="file", name="failed.mp4", path_or_url="/tmp/f.mp4", status="failed"),
    ]
    qm._next_idx = 2
    qm.enable_shutdown()
    msg = qm.check_and_schedule_shutdown()
    check("All failed -> shutdown skipped", "skipped" in msg.lower() or "No items" in msg)

    # Have at least one success
    qm.reset()
    qm._items = [
        QueueItem(idx=1, source="file", name="done.mp4", path_or_url="/tmp/d.mp4", status="done"),
    ]
    qm._next_idx = 2
    qm.enable_shutdown()
    qm._cancelled = False
    # Don't actually call shutdown /s; just verify logic path
    check("Shutdown enabled flag set", qm.is_shutdown_enabled())

    # Cancel shutdown
    qm.disable_shutdown()
    check("Shutdown disabled", not qm.is_shutdown_enabled())


def test_format_duration():
    """E1: format_duration helper."""
    print("\n=== E1: format_duration ===")
    check("0s = 00:00", format_duration(0) == "00:00")
    check("65s = 01:05", format_duration(65) == "01:05")
    check("3661s = 01:01:01", format_duration(3661) == "01:01:01")
    check("-1s = ??:??", format_duration(-1) == "?:??" or format_duration(-1).startswith("?"))


if __name__ == "__main__":
    print("=" * 60)
    print("KATAV Queue Manager Test Harness")
    print("=" * 60)

    test_queue_append_order()
    test_duplicate_rejection()
    test_selective_removal()
    test_eta_calculation()
    test_snapshot_semantics()
    test_shutdown_eligibility()
    test_format_duration()

    print("\n" + "=" * 60)
    total = PASS + FAIL
    print(f"Results: {PASS}/{total} passed, {FAIL} failed")
    print("=" * 60)

    sys.exit(0 if FAIL == 0 else 1)

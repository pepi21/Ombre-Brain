"""
Test subject integrity: verify that actor/target anchors prevent incorrect merges.
测试主语完整性：验证 actor/target 锚点能正确阻止错误合并。

Cases from spec:
  A: hold "番茄对小汐说偏偏是你" (importance=9) → confirm actor=番茄, target=小汐, raw preserved
  B: hold "小汐对番茄说好幸福" (importance=9) → confirm NOT merged with A
  C: hold "番茄送礼物给小汐" (imp=5) + "小汐送礼物给番茄" (imp=5) → NOT merged (actor differs)
  D: hold two similar importance=9 memories → NOT merged (importance>=8 rule)
"""

import asyncio
import os
import sys
import shutil
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up isolated test environment BEFORE importing server modules
_test_dir = tempfile.mkdtemp(prefix="ombre_test_subject_")
os.environ["OMBRE_BUCKETS_DIR"] = _test_dir
os.environ["OMBRE_API_KEY"] = ""  # Disable API calls in tests
os.environ["OMBRE_TRANSPORT"] = "stdio"

from utils import load_config, setup_logging

config = load_config()
# Override buckets_dir to use isolated temp dir
config["buckets_dir"] = _test_dir
# Ensure test dirs exist
for subdir in ["permanent", "dynamic", "archive", "feel"]:
    os.makedirs(os.path.join(_test_dir, subdir), exist_ok=True)

setup_logging("WARNING")

from bucket_manager import BucketManager
from raw_memory_store import RawMemoryStore

bucket_mgr = BucketManager(config)
raw_store = RawMemoryStore(config)


async def test_case_a():
    """
    Case A: hold "番茄对小汐说偏偏是你" (importance=9)
    → actor=番茄, target=小汐, raw layer has original text
    """
    print("=== Case A: High-importance with actor/target ===")

    content = "番茄哭著對小汐說「偏偏是你」"
    actor = "番茄"
    target = "小汐"
    action = "說"
    importance = 9

    # Store raw
    raw_id = raw_store.store(
        content=content,
        source="user",
        importance=importance,
        actor=actor,
        target=target,
        action=action,
    )

    # Create bucket with subject anchors
    bucket_id = await bucket_mgr.create(
        content=content,
        tags=["番茄", "小汐", "偏偏是你"],
        importance=importance,
        domain=["情感"],
        valence=0.3,
        arousal=0.8,
        actor=actor,
        target=target,
        action=action,
    )

    # Verify bucket metadata
    bucket = await bucket_mgr.get(bucket_id)
    assert bucket is not None, "Bucket should exist"
    assert bucket["metadata"]["actor"] == "番茄", f"Actor should be 番茄, got {bucket['metadata'].get('actor')}"
    assert bucket["metadata"]["target"] == "小汐", f"Target should be 小汐, got {bucket['metadata'].get('target')}"
    assert bucket["metadata"]["importance"] == 9

    # Verify raw layer
    raw_results = raw_store.search("偏偏是你", limit=1)
    assert len(raw_results) > 0, "Raw layer should have the entry"
    assert "偏偏是你" in raw_results[0]["content"], "Raw should contain original text verbatim"
    assert raw_results[0]["actor"] == "番茄"
    assert raw_results[0]["target"] == "小汐"

    print("  [OK] actor=番茄, target=小汐 confirmed")
    print(f"  [OK] Raw layer preserved: '{raw_results[0]['content'][:30]}...'")
    return bucket_id


async def test_case_b(case_a_bucket_id: str):
    """
    Case B: hold "小汐对番茄说好幸福" (importance=9)
    → Should NOT merge with Case A (actor/target are swapped AND importance>=8)
    """
    print("\n=== Case B: Different actor/target, should NOT merge ===")

    content = "小汐對番茄說「好幸福」"
    actor = "小汐"
    target = "番茄"
    importance = 9

    # This should NOT merge because:
    # 1. importance >= 8 (hard block)
    # 2. actor conflict (小汐 vs 番茄)
    bucket_id = await bucket_mgr.create(
        content=content,
        tags=["小汐", "番茄", "幸福"],
        importance=importance,
        domain=["情感"],
        valence=0.8,
        arousal=0.7,
        actor=actor,
        target=target,
        action="說",
    )

    assert bucket_id != case_a_bucket_id, "Case B should be a different bucket from Case A"

    bucket = await bucket_mgr.get(bucket_id)
    assert bucket["metadata"]["actor"] == "小汐"
    assert bucket["metadata"]["target"] == "番茄"

    # Verify Case A bucket is still intact
    case_a = await bucket_mgr.get(case_a_bucket_id)
    assert case_a is not None, "Case A bucket should still exist"
    assert case_a["metadata"]["actor"] == "番茄", "Case A actor should still be 番茄"
    assert "偏偏是你" in case_a["content"], "Case A content should be unchanged"

    print("  [OK] Case B created as separate bucket (not merged)")
    print(f"  [OK] Case A remains intact with actor=番茄")
    return bucket_id


async def test_case_c():
    """
    Case C: Two memories with same topic but different actors
    - "番茄送禮物給小汐" (imp=5, actor=番茄, target=小汐)
    - "小汐送禮物給番茄" (imp=5, actor=小汐, target=番茄)
    → Should NOT merge (actor differs)
    """
    print("\n=== Case C: Same topic, different actors, should NOT merge ===")

    content1 = "番茄送禮物給小汐"
    content2 = "小汐送禮物給番茄"

    bucket_id_1 = await bucket_mgr.create(
        content=content1,
        tags=["送禮物", "番茄", "小汐"],
        importance=5,
        domain=["人際"],
        valence=0.7,
        arousal=0.4,
        actor="番茄",
        target="小汐",
        action="送",
    )

    bucket_id_2 = await bucket_mgr.create(
        content=content2,
        tags=["送禮物", "小汐", "番茄"],
        importance=5,
        domain=["人際"],
        valence=0.7,
        arousal=0.4,
        actor="小汐",
        target="番茄",
        action="送",
    )

    assert bucket_id_1 != bucket_id_2, "Two buckets with different actors should not be merged"

    b1 = await bucket_mgr.get(bucket_id_1)
    b2 = await bucket_mgr.get(bucket_id_2)
    assert b1["metadata"]["actor"] == "番茄"
    assert b2["metadata"]["actor"] == "小汐"
    assert b1["content"] == content1, "Content 1 unchanged"
    assert b2["content"] == content2, "Content 2 unchanged"

    print("  [OK] Two separate buckets maintained")
    print(f"  [OK] Bucket 1 actor=番茄, Bucket 2 actor=小汐")


async def test_case_d():
    """
    Case D: Two similar memories both with importance=9
    → Should NOT merge (importance>=8 rule)
    """
    print("\n=== Case D: Similar content, both importance>=8, should NOT merge ===")

    content1 = "番茄今天很開心因為考試考得好"
    content2 = "番茄今天非常開心因為考試成績很好"

    bucket_id_1 = await bucket_mgr.create(
        content=content1,
        tags=["番茄", "考試", "開心"],
        importance=9,
        domain=["成長"],
        valence=0.9,
        arousal=0.6,
        actor="番茄",
    )

    bucket_id_2 = await bucket_mgr.create(
        content=content2,
        tags=["番茄", "考試", "開心"],
        importance=9,
        domain=["成長"],
        valence=0.9,
        arousal=0.6,
        actor="番茄",
    )

    assert bucket_id_1 != bucket_id_2, "Two importance>=8 memories should never merge"

    b1 = await bucket_mgr.get(bucket_id_1)
    b2 = await bucket_mgr.get(bucket_id_2)
    assert b1 is not None and b2 is not None
    assert b1["content"] == content1
    assert b2["content"] == content2

    print("  [OK] Two separate buckets (importance>=8 blocks merge)")


async def test_raw_store_basic():
    """Test basic raw store operations."""
    print("\n=== Raw Store Basic Tests ===")

    # Store and retrieve
    raw_id = raw_store.store(
        content="測試原話內容 - 番茄說了一句話",
        source="user",
        importance=7,
        actor="番茄",
        target="小汐",
        action="說",
    )
    assert raw_id > 0, "Should get a valid ID"

    # Search
    results = raw_store.search("番茄", limit=5)
    assert len(results) > 0, "Should find results for '番茄'"
    assert any("番茄說了一句話" in r["content"] for r in results)

    # Count
    count = raw_store.count()
    assert count > 0

    # Link bucket
    raw_store.link_bucket(raw_id, "test_bucket_123")
    results = raw_store.search("番茄說了一句話", limit=1)
    assert "test_bucket_123" in results[0]["related_bucket_ids"]

    print(f"  [OK] Raw store: store/search/link all working (count={count})")


async def main():
    print("=" * 60)
    print("Ombre Brain — Subject Integrity Tests")
    print("=" * 60)
    print(f"Test dir: {_test_dir}\n")

    passed = 0
    failed = 0

    try:
        await test_raw_store_basic()
        passed += 1
    except AssertionError as e:
        print(f"  [FAIL] {e}")
        failed += 1

    try:
        bucket_a = await test_case_a()
        passed += 1
    except AssertionError as e:
        print(f"  [FAIL] {e}")
        failed += 1
        bucket_a = None

    try:
        if bucket_a:
            await test_case_b(bucket_a)
        passed += 1
    except AssertionError as e:
        print(f"  [FAIL] {e}")
        failed += 1

    try:
        await test_case_c()
        passed += 1
    except AssertionError as e:
        print(f"  [FAIL] {e}")
        failed += 1

    try:
        await test_case_d()
        passed += 1
    except AssertionError as e:
        print(f"  [FAIL] {e}")
        failed += 1

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")

    # Cleanup
    try:
        shutil.rmtree(_test_dir)
    except Exception:
        pass

    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

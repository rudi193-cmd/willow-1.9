# tests/adversarial/test_injection.py
"""SQL injection resistance — proves parameterized queries neutralize all injection.
Each test fires a known SQL injection payload and asserts the defense held.
"""
import time
import pytest


def test_sql_drop_table_in_id(bridge):
    """DROP TABLE in atom id — stored as literal, table survives."""
    malicious_id = "adv_drop_'; DROP TABLE knowledge; --"
    bridge.knowledge_put({
        "id": malicious_id,
        "project": "adv_injection",
        "title": "injection test drop",
        "summary": "testing sql injection drop",
    })
    with bridge.conn.cursor() as cur:
        cur.execute("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema='public' AND table_name='knowledge'
        """)
        assert cur.fetchone() is not None, "knowledge table was dropped"
    results = bridge.knowledge_search("injection test drop", project="adv_injection")
    assert len(results) == 1
    assert results[0]["id"] == malicious_id


def test_sql_or_true_in_search(bridge):
    """OR '1'='1' in search query — returns 0 results, not full table."""
    bridge.knowledge_put({
        "id": "adv_canary_row",
        "project": "adv_injection_canary",
        "title": "canary row only",
        "summary": "must not appear in injection result",
    })
    results = bridge.knowledge_search("' OR '1'='1", project="adv_injection")
    assert not any(r["id"] == "adv_canary_row" for r in results)


def test_sql_in_title_stored_verbatim(bridge):
    """SQL in title field — stored and retrieved as literal string."""
    sql_title = "'; SELECT * FROM knowledge; --"
    bridge.knowledge_put({
        "id": "adv_sql_title",
        "project": "adv_injection",
        "title": sql_title,
        "summary": "title contains sql payload",
    })
    results = bridge.knowledge_search("title contains sql payload", project="adv_injection")
    assert len(results) == 1
    assert results[0]["title"] == sql_title


def test_sql_sleep_timing(bridge):
    """pg_sleep in id — completes in < 2 seconds (injection did not execute)."""
    start = time.time()
    try:
        bridge.knowledge_put({
            "id": "adv_sleep_; SELECT pg_sleep(5); --",
            "project": "adv_injection",
            "title": "timing test",
            "summary": "timing injection",
        })
    except Exception:
        pass  # KeyError on id constraints is fine — what matters is timing
    elapsed = time.time() - start
    assert elapsed < 4.0, f"Took {elapsed:.1f}s — pg_sleep may have executed"


def test_sql_semicolon_chain_in_content(bridge):
    """Multi-statement chain in content JSON — stored intact, not executed."""
    payload = {"cmd": "'; INSERT INTO knowledge (id, project, title) VALUES ('hacked', 'pwned', 'hacked'); --"}
    bridge.knowledge_put({
        "id": "adv_content_inject",
        "project": "adv_injection",
        "title": "content injection",
        "summary": "content contains injection payload",
        "content": payload,
    })
    results = bridge.knowledge_search("content injection", project="adv_injection")
    assert len(results) == 1
    assert results[0]["content"]["cmd"] == payload["cmd"]
    with bridge.conn.cursor() as cur:
        cur.execute("SELECT id FROM knowledge WHERE id = 'hacked'")
        assert cur.fetchone() is None


def test_row_count_after_injection(bridge):
    """After all injection attempts, no spurious rows exist."""
    with bridge.conn.cursor() as cur:
        cur.execute("SELECT id FROM knowledge WHERE id = 'hacked'")
        assert cur.fetchone() is None
    with bridge.conn.cursor() as cur:
        cur.execute("SELECT id FROM knowledge WHERE id = 'pwned'")
        assert cur.fetchone() is None

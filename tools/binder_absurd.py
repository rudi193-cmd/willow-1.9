"""
Binder: Connect the Absurd — willow-1.9 port
=============================================
Finds non-obvious cross-category connections in the knowledge graph.

Step 1: Keyword bridges — titles/summaries sharing significant terms across 3+ categories
Step 2: Embedding proximity — Ollama nomic-embed-text cosine similarity across absurd pairings
Step 3: Propose edges to SOIL _graph/edges for human review

Run: python tools/binder_absurd.py [--dry-run] [--skip-embed]
b17: BNDR1  ΔΣ=42
"""
import json
import math
import struct
import sys
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.pg_bridge import get_connection, release_connection
from core.willow_store import WillowStore

DRY_RUN    = "--dry-run"    in sys.argv
SKIP_EMBED = "--skip-embed" in sys.argv
THRESHOLD  = 0.72
SAMPLE     = 40   # atoms per category for embedding pass

ABSURD_PAIRS = [
    ("character",    "code"),
    ("character",    "governance"),
    ("character",    "architecture"),
    ("narrative",    "code"),
    ("narrative",    "governance"),
    ("narrative",    "architecture"),
    ("personal",     "code"),
    ("personal",     "governance"),
    ("professor",    "genealogy"),
    ("professor",    "code"),
    ("convergence",  "genealogy"),
    ("convergence",  "personal"),
    ("genealogy",    "architecture"),
    ("media",        "governance"),
    ("media",        "code"),
]

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "in", "to", "for", "with",
    "on", "at", "is", "was", "are", "be", "by", "as", "from", "it",
    "this", "that", "i", "he", "she", "they", "we", "you", "his",
    "her", "their", "my", "our", "its", "not", "but", "if", "so",
    "about", "into", "than", "then", "when", "who", "which", "what",
    "all", "one", "more", "has", "have", "had", "been", "will", "would",
    "could", "should", "may", "might", "can", "do", "did", "does",
    "willow", "sean", "claude", "hanuman", "session", "file", "atom",
}


def _keywords(text: str) -> set[str]:
    words = set()
    for w in (text or "").lower().split():
        w = "".join(c for c in w if c.isalpha())
        if len(w) >= 4 and w not in STOPWORDS:
            words.add(w)
    return words


# ── Step 1: Keyword bridges ───────────────────────────────────────────────────

def find_keyword_bridges(conn) -> list[dict]:
    """Find terms appearing in 3+ categories — these are the bridge concepts."""
    print("  Scanning keyword distribution across categories...")
    cur = conn.cursor()
    cur.execute("""
        SELECT id, title, summary, category
        FROM knowledge
        WHERE invalid_at IS NULL
          AND category NOT IN ('session', 'handoff', 'general', 'text', 'notebooklm')
          AND (title IS NOT NULL OR summary IS NOT NULL)
        LIMIT 8000
    """)
    rows = cur.fetchall()

    term_cats: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))
    for atom_id, title, summary, category in rows:
        kws = _keywords(f"{title} {summary}")
        for kw in kws:
            term_cats[kw][category].append(atom_id)

    bridges = []
    for term, cats in term_cats.items():
        if len(cats) >= 3:
            bridges.append({
                "term": term,
                "cat_count": len(cats),
                "categories": dict(cats),
            })

    bridges.sort(key=lambda x: x["cat_count"], reverse=True)
    return bridges[:40]


# ── Step 2: Embedding proximity ───────────────────────────────────────────────

def _embed(text: str) -> list[float] | None:
    try:
        payload = json.dumps({"model": "nomic-embed-text", "input": text}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            return data.get("embeddings", [[]])[0]
    except Exception as e:
        print(f"    [embed error] {e}", file=sys.stderr)
        return None


def cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb) if na and nb else 0.0


def find_cross_category_similar(conn) -> list[dict]:
    """Embed sampled atoms and find similar cross-category pairs."""
    cur = conn.cursor()
    atoms_by_cat: dict[str, list] = {}

    all_cats = set(c for p in ABSURD_PAIRS for c in p)
    for cat in all_cats:
        cur.execute("""
            SELECT id, title, summary FROM knowledge
            WHERE invalid_at IS NULL AND category = %s
              AND summary IS NOT NULL AND LENGTH(summary) > 40
              AND title NOT SIMILAR TO '%%\.jpg|%%\.png|%%\.txt|%%\.json|%%\.pdf|file\_%%'
            ORDER BY weight DESC LIMIT %s
        """, (cat, SAMPLE))
        atoms_by_cat[cat] = [
            (r[0], r[1], r[2], None) for r in cur.fetchall()
        ]

    # Embed
    print(f"  Embedding {sum(len(v) for v in atoms_by_cat.values())} atoms via nomic-embed-text...")
    for cat, atoms in atoms_by_cat.items():
        embedded = []
        for atom_id, title, summary, _ in atoms:
            text = f"{title or ''} {summary or ''}".strip()[:512]
            vec = _embed(text)
            embedded.append((atom_id, title, summary, vec))
        atoms_by_cat[cat] = embedded

    results = []
    seen = set()
    for cat_a, cat_b in ABSURD_PAIRS:
        if cat_a not in atoms_by_cat or cat_b not in atoms_by_cat:
            continue
        for id_a, title_a, _, vec_a in atoms_by_cat[cat_a]:
            if vec_a is None:
                continue
            for id_b, title_b, _, vec_b in atoms_by_cat[cat_b]:
                if vec_b is None or id_a == id_b:
                    continue
                pair_key = (min(id_a, id_b), max(id_a, id_b))
                if pair_key in seen:
                    continue
                seen.add(pair_key)
                sim = cosine(vec_a, vec_b)
                if sim >= THRESHOLD:
                    results.append({
                        "id_a": id_a, "title_a": title_a, "cat_a": cat_a,
                        "id_b": id_b, "title_b": title_b, "cat_b": cat_b,
                        "similarity": round(sim, 4),
                    })

    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:50]


# ── Step 3: Propose and apply edges ──────────────────────────────────────────

def propose_edges(bridges: list, similar: list) -> list[dict]:
    proposals = []

    for bridge in bridges[:20]:
        cats = list(bridge["categories"].keys())
        for i, cat_a in enumerate(cats):
            for cat_b in cats[i + 1:]:
                a_id = bridge["categories"][cat_a][0]
                b_id = bridge["categories"][cat_b][0]
                proposals.append({
                    "from_id": str(a_id),
                    "to_id": str(b_id),
                    "edge_type": "bridge",
                    "weight": 0.7,
                    "reason": f"shared term: '{bridge['term']}' ({bridge['cat_count']} cats)",
                    "cat_a": cat_a, "cat_b": cat_b,
                    "title_a": f"[{cat_a}:{a_id}]",
                    "title_b": f"[{cat_b}:{b_id}]",
                })

    for pair in similar:
        proposals.append({
            "from_id": str(pair["id_a"]),
            "to_id": str(pair["id_b"]),
            "edge_type": "similar",
            "weight": pair["similarity"],
            "reason": f"embedding similarity {pair['similarity']:.3f} across {pair['cat_a']}/{pair['cat_b']}",
            "cat_a": pair["cat_a"], "cat_b": pair["cat_b"],
            "title_a": pair["title_a"], "title_b": pair["title_b"],
        })

    return proposals


def apply_edges(store: WillowStore, proposals: list) -> int:
    applied = 0
    now = datetime.now(timezone.utc).isoformat()
    for p in proposals:
        edge_id = f"{p['from_id']}__{p['edge_type']}__{p['to_id']}"
        try:
            store.put("_graph/edges", {
                "id": edge_id,
                "from_id": p["from_id"],
                "to_id": p["to_id"],
                "relation": p["edge_type"],
                "weight": p["weight"],
                "context": p["reason"],
                "source": "binder_absurd",
                "cat_a": p["cat_a"],
                "cat_b": p["cat_b"],
                "created_at": now,
            }, record_id=edge_id)
            applied += 1
        except Exception as e:
            print(f"  SKIP {edge_id}: {e}")
    return applied


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    conn = get_connection()
    store = WillowStore()

    print("=== BINDER: CONNECT THE ABSURD (willow-1.9) ===\n")

    print("Step 1: Keyword bridges (3+ categories)...")
    bridges = find_keyword_bridges(conn)
    print(f"  Found {len(bridges)} bridging terms\n")
    for b in bridges[:10]:
        cats = ", ".join(b["categories"].keys())
        print(f"  '{b['term']}' — {b['cat_count']} cats: [{cats}]")

    similar = []
    if not SKIP_EMBED:
        print(f"\nStep 2: Cross-category embedding proximity (threshold={THRESHOLD})...")
        similar = find_cross_category_similar(conn)
        print(f"  Found {len(similar)} cross-category similar pairs\n")
        for s in similar[:10]:
            print(f"  {s['similarity']:.3f}  [{s['cat_a']}] '{(s['title_a'] or '')[:40]}'")
            print(f"         [{s['cat_b']}] '{(s['title_b'] or '')[:40]}'")
    else:
        print("\nStep 2: Skipped (--skip-embed)")

    print(f"\nStep 3: Generating edge proposals...")
    proposals = propose_edges(bridges, similar)
    print(f"  {len(proposals)} new edges proposed\n")

    for p in proposals[:15]:
        print(f"  {p['edge_type']:8s} [{p['cat_a']}→{p['cat_b']}] "
              f"'{(p['title_a'] or '')[:35]}' → '{(p['title_b'] or '')[:35]}'")
        print(f"           {p['reason']}")

    if DRY_RUN:
        print(f"\n[DRY RUN] Would create {len(proposals)} edges. Re-run without --dry-run to apply.")
    else:
        applied = apply_edges(store, proposals)
        print(f"\nApplied {applied} new edges to _graph/edges.")

    release_connection(conn)


if __name__ == "__main__":
    main()

"""
Ollama full-suite benchmark — runs every installed model through 5 prompts:
  A: Willow startup (long system prompt, coherence test)
  B: JSON structured output
  C: Reasoning (math word problem)
  D: Code generation
  E: Instruction following (summarise + reformat)

Results written to tools/ollama_bench_results.md and tools/ollama_bench_results.json
"""
import json
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

OLLAMA_BASE = "http://localhost:11434"
TIMEOUT = 120  # per request

PROMPTS = {
    "A_startup": {
        "system": (
            "You are connected to Willow, a local-first AI memory and task system built "
            "for an agent fleet. Before doing anything else, orient.\n\n"
            "Call these in parallel:\n"
            "  fleet_status   → system health (Postgres + SOIL + Ollama)\n"
            "  handoff_latest → last session state — what was in-flight, what's pending\n\n"
            "If fleet_status returns degraded or down: surface it and stop. Do not proceed."
        ),
        "user": "good evening",
    },
    "B_json": {
        "system": "You are a JSON-only assistant. Reply with valid JSON and nothing else.",
        "user": '{"task":"identify","input":"Return an object with keys: status (ok), ready (true), model (your model name), timestamp (unix epoch as integer)"}',
    },
    "C_reasoning": {
        "system": "You are a precise reasoning assistant. Show your work step by step.",
        "user": (
            "Train A leaves Station X at 9:00am travelling at 60mph. "
            "Train B leaves Station X at 11:00am travelling at 90mph in the same direction. "
            "At what time does Train B catch Train A, and how far from Station X?"
        ),
    },
    "D_code": {
        "system": "You are an expert Python engineer. Return only working code, no explanation.",
        "user": (
            "Write a Python function group_by(records: list[dict], key: str) -> dict "
            "that groups a list of dicts by a given key. Handle missing keys gracefully."
        ),
    },
    "E_instruction": {
        "system": "Follow the user's formatting instructions exactly.",
        "user": (
            "Summarise this in exactly 3 bullet points, each under 10 words:\n\n"
            "Willow is a local-first AI memory system that runs on a home server. "
            "It stores knowledge atoms in Postgres with vector embeddings for semantic search. "
            "Multiple AI agents share the same knowledge base and coordinate via a message bus called Grove. "
            "The system is designed to work offline and never sends user data to the cloud."
        ),
    },
}


def check_ollama() -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5)
        return True
    except Exception:
        return False


def list_models() -> list[str]:
    with urllib.request.urlopen(f"{OLLAMA_BASE}/api/tags", timeout=5) as r:
        data = json.loads(r.read())
    return [
        m["name"] for m in data.get("models", [])
        if "embed" not in m["name"]  # skip embedding models
    ]


def chat(model: str, system: str, user: str) -> dict:
    payload = json.dumps({
        "model": model,
        "stream": False,
        "options": {"num_predict": 300},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
    }).encode()

    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read()
        elapsed = time.perf_counter() - t0
        data = json.loads(raw)
        content  = data.get("message", {}).get("content", "")
        tokens   = data.get("eval_count", 0)
        p_tokens = data.get("prompt_eval_count", 0)
        tps = tokens / elapsed if elapsed > 0 else 0
        return {
            "ok": True, "elapsed": round(elapsed, 2), "tokens": tokens,
            "prompt_tokens": p_tokens, "tps": round(tps, 2), "content": content,
        }
    except TimeoutError:
        return {"ok": False, "error": "timeout", "elapsed": TIMEOUT}
    except Exception as e:
        return {"ok": False, "error": str(e), "elapsed": round(time.perf_counter() - t0, 2)}


# ── Coherence checks ──────────────────────────────────────────────────────────

def score_a(text: str) -> str:
    hits = sum(1 for w in ["fleet", "handoff", "health", "orient", "parallel", "status"]
               if w in text.lower())
    if len(text.strip()) < 30: return "EMPTY"
    return "PASS" if hits >= 2 else "WEAK"

def score_b(text: str) -> str:
    try:
        json.loads(text.strip())
        return "PASS"
    except Exception:
        return "FAIL"

def score_c(text: str) -> str:
    lowered = text.lower()
    has_time  = any(t in lowered for t in ["1:00", "1pm", "13:00", "hour", "pm", "am"])
    has_dist  = any(d in lowered for d in ["mile", "180", "120", "distance"])
    has_work  = any(w in lowered for w in ["60", "90", "speed", "catch", "relative"])
    return "PASS" if (has_time or has_dist) and has_work else "WEAK"

def score_d(text: str) -> str:
    lowered = text.lower()
    has_def  = "def group_by" in lowered
    has_loop = any(k in lowered for k in ["for ", "dict", "setdefault", "defaultdict", "append"])
    return "PASS" if has_def and has_loop else ("WEAK" if has_def else "FAIL")

def score_e(text: str) -> str:
    lines   = [l.strip() for l in text.strip().splitlines() if l.strip()]
    bullets = [l for l in lines if l.startswith(("-", "•", "*", "·")) or (len(l) > 1 and l[0] == "-")]
    return "PASS" if len(bullets) == 3 else f"GOT_{len(bullets)}"

SCORERS = {"A_startup": score_a, "B_json": score_b, "C_reasoning": score_c,
           "D_code": score_d, "E_instruction": score_e}


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not check_ollama():
        print(f"ERROR: Ollama not reachable at {OLLAMA_BASE}")
        sys.exit(1)

    # Optional: python3 bench.py gemma2:9b llama3.2-vision:11b
    filter_models = sys.argv[1:]
    models = list_models()
    if filter_models:
        models = [m for m in models if any(f in m for f in filter_models)]
    if not models:
        print("No matching models installed.")
        sys.exit(1)

    print(f"Ollama reachable — {len(models)} model(s): {', '.join(models)}")
    print(f"Running {len(PROMPTS)} prompts × {len(models)} models\n")

    all_results = {}

    for model in models:
        print(f"══ {model} ══")
        model_results = {}
        for pid, prompt in PROMPTS.items():
            print(f"  [{pid}] ...", end=" ", flush=True)
            r = chat(model, prompt["system"], prompt["user"])
            score = SCORERS[pid](r.get("content", "")) if r["ok"] else "ERR"
            r["score"] = score
            model_results[pid] = r
            if r["ok"]:
                print(f"{r['elapsed']:.1f}s  {r['tps']:.1f} tok/s  {score}")
                print(f"        {r['content'][:100].strip()!r}")
            else:
                print(f"FAILED ({r.get('error','?')})")
        all_results[model] = model_results
        print()

    # ── Summary table ─────────────────────────────────────────────────────────
    col_w = 10
    prompt_ids = list(PROMPTS.keys())
    header = f"{'Model':<24}" + "".join(f"{pid:<{col_w}}" for pid in prompt_ids) + f"{'avg tok/s':>10}"
    sep = "─" * len(header)
    print(sep)
    print(header)
    print(sep)

    table_rows = []
    for model, mr in all_results.items():
        scores = [mr[pid].get("score", "ERR") for pid in prompt_ids]
        tps_vals = [mr[pid]["tps"] for pid in prompt_ids if mr[pid].get("ok")]
        avg_tps = sum(tps_vals) / len(tps_vals) if tps_vals else 0
        row = f"{model:<24}" + "".join(f"{s:<{col_w}}" for s in scores) + f"{avg_tps:>10.1f}"
        print(row)
        table_rows.append({"model": model, "scores": dict(zip(prompt_ids, scores)),
                           "avg_tps": round(avg_tps, 2)})
    print(sep)

    # ── Write outputs ─────────────────────────────────────────────────────────
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    json_path = "tools/ollama_bench_results.json"
    with open(json_path, "w") as f:
        json.dump({"run_at": ts, "models": all_results}, f, indent=2)

    md_lines = [
        "# Ollama Full Suite Benchmark", "",
        f"Run: {ts}  |  Timeout per prompt: {TIMEOUT}s", "",
        "## Prompts",
        "| ID | Description |",
        "|----|-------------|",
        "| A_startup | Willow boot sequence — coherence + keyword check |",
        "| B_json | JSON-only structured output — parse validity |",
        "| C_reasoning | Train speed/catch word problem — answer + workings |",
        "| D_code | Python `group_by` function — def + loop present |",
        "| E_instruction | 3-bullet summary — exact count check |",
        "", "## Results", "",
        "| Model | A_startup | B_json | C_reasoning | D_code | E_instruction | avg tok/s |",
        "|-------|-----------|--------|-------------|--------|----------------|-----------|",
    ]
    for row in table_rows:
        s = row["scores"]
        md_lines.append(
            f"| {row['model']} | {s['A_startup']} | {s['B_json']} | "
            f"{s['C_reasoning']} | {s['D_code']} | {s['E_instruction']} | {row['avg_tps']} |"
        )
    md_lines += ["", f"Raw data: `{json_path}`"]

    md_path = "tools/ollama_bench_results.md"
    with open(md_path, "w") as f:
        f.write("\n".join(md_lines) + "\n")

    print(f"\nJSON → {json_path}")
    print(f"MD   → {md_path}")


if __name__ == "__main__":
    main()

# Ollama Full Suite Benchmark

Run: 2026-05-17 20:19:57  |  Timeout per prompt: 120s

## Prompts
| ID | Description |
|----|-------------|
| A_startup | Willow boot sequence — coherence + keyword check |
| B_json | JSON-only structured output — parse validity |
| C_reasoning | Train speed/catch word problem — answer + workings |
| D_code | Python `group_by` function — def + loop present |
| E_instruction | 3-bullet summary — exact count check |

## Results

| Model | A_startup | B_json | C_reasoning | D_code | E_instruction | avg tok/s |
|-------|-----------|--------|-------------|--------|----------------|-----------|
| gemma2:9b | ERR | PASS | ERR | PASS | PASS | 1.03 |
| llama3.2-vision:11b | PASS | PASS | ERR | ERR | PASS | 0.94 |

Raw data: `tools/ollama_bench_results.json`

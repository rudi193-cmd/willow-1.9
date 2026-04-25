# Contributors & Acknowledgments

## Built by

- **Sean Campbell** — system architecture, knowledge graph design, agent identity system

## Open Source — Used Directly

| Project | What Willow uses |
|---|---|
| [LiteLLM](https://github.com/BerriAI/litellm) (BerriAI) | Unified inference gateway — Ollama default + cloud provider abstraction |
| [Ollama](https://github.com/ollama/ollama) | Local-first LLM inference, default provider |
| [Textual](https://github.com/Textualize/textual) (Textualize) | Terminal dashboard UI framework |
| [mcp-proxy](https://github.com/TBXark/mcp-proxy) (TBXark) | MCP server aggregation pattern |
| [punkpeye/mcp-proxy](https://github.com/punkpeye/mcp-proxy) | stdio→HTTP/SSE MCP transport bridge |
| [FastMCP](https://github.com/jlowin/fastmcp) | MCP server framework |
| [psycopg2](https://github.com/psycopg/psycopg2) | Postgres adapter |
| [cryptography](https://github.com/pyca/cryptography) | Fernet vault encryption |

## Open Source — Patterns Learned From

| Project | What we learned |
|---|---|
| [SuperAGI](https://github.com/TransformerOptimus/SuperAGI) | Toolkit marketplace JSON seed pattern |
| [Khoj](https://github.com/khoj-ai/khoj) | Local-first multi-LLM agent architecture |
| [Open WebUI](https://github.com/open-webui/open-webui) | Multi-model Ollama integration patterns |
| [PrivateGPT](https://github.com/zylon-ai/private-gpt) | Local inference abstraction layer |
| [ClawHub](https://clawhub.ai) / [OpenClaw](https://github.com/openclaw/openclaw) | Skill registry protocol and distribution |

## Upstream Contributions

These projects power Willow. When their maintainers merge our PRs, they earn a place here.

| Project | Maintainer | What we contributed | Status |
|---------|-----------|---------------------|--------|
| [openclaw/openclaw](https://github.com/openclaw/openclaw) | openclaw | willow-memory-health skill — four-signal memory diagnostic | [PR #67789](https://github.com/openclaw/openclaw/pull/67789) open |
| [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent) | NousResearch | Kart task queue tool | [PR #11979](https://github.com/NousResearch/hermes-agent/pull/11979) open |
| [RyjoxTechnologies/Octopoda-OS](https://github.com/RyjoxTechnologies/Octopoda-OS) | Joe Roberts | DarkRadar fifth BrainHub signal | [PR #1](https://github.com/RyjoxTechnologies/Octopoda-OS/pull/1) open |
| [punkpeye/awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) | punkpeye | willow-mcp listed in Knowledge & Memory | [PR #5247](https://github.com/punkpeye/awesome-mcp-servers/pull/5247) open |
| [TensorBlock/awesome-mcp-servers](https://github.com/TensorBlock/awesome-mcp-servers) | TensorBlock | willow-mcp listed | [PR #432](https://github.com/TensorBlock/awesome-mcp-servers/pull/432) open |
| [modelcontextprotocol/python-sdk](https://github.com/modelcontextprotocol/python-sdk) | Anthropic | postgres-knowledge-server example | [PR #2494](https://github.com/modelcontextprotocol/python-sdk/pull/2494) open |
| [ollama/ollama](https://github.com/ollama/ollama) | Ollama | HuggingFace Hub GGUF pull docs | [PR #15765](https://github.com/ollama/ollama/pull/15765) open |
| [Textualize/textual](https://github.com/Textualize/textual) | Will McGugan | async message_feed example | [PR #6510](https://github.com/Textualize/textual/pull/6510) open |
| [Textualize/rich](https://github.com/Textualize/rich) | Will McGugan | safe_markup escaping example | [PR #4092](https://github.com/Textualize/rich/pull/4092) open |
| [encode/starlette](https://github.com/Kludex/starlette) | Tom Christie / Kludex | FilesystemAuthBackend docs | [PR #3249](https://github.com/Kludex/starlette/pull/3249) open |
| [BerriAI/litellm](https://github.com/BerriAI/litellm) | BerriAI | custom GGUF Ollama cookbook | [PR #26307](https://github.com/BerriAI/litellm/pull/26307) open |
| [unslothai/unsloth](https://github.com/unslothai/unsloth) | Daniel Han | Yggdrasil SFT+DPO recipe | [Discussion #5139](https://github.com/unslothai/unsloth/discussions/5139) |

## Contributors to Willow

<!-- ALL-CONTRIBUTORS-LIST:START -->
<!-- ALL-CONTRIBUTORS-LIST:END -->

People who have forked, contributed to, or directly improved willow-1.9. Tracked automatically via the fork-watcher workflow. When you contribute back, you get added here.

## MCP Ecosystem

Willow implements the [Model Context Protocol](https://modelcontextprotocol.io) — an open standard donated to the Agentic AI Foundation in December 2025.

Listed on [awesome-mcp-servers](https://github.com/punkpeye/awesome-mcp-servers) and [ClawHub](https://clawhub.ai).

## License

MIT. See [LICENSE](LICENSE).

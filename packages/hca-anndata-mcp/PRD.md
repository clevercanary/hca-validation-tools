# HCA AnnData MCP Server — PRD

## Overview

The hca-anndata-mcp server provides interactive, AI-assisted exploration and validation of AnnData h5ad files for the Human Cell Atlas. It is the interactive layer on top of two core libraries: a reusable data extraction library and the HCA schema validator.

## Architecture

```
hca-anndata-mcp (MCP server — interactive layer)
├── hca-anndata-tools (data extraction / summarization library)
└── hca-schema-validator (validation library, published to PyPI)
```

### hca-anndata-tools (new package)

Reusable Python library for programmatic access to AnnData file inspection, summarization, and statistics. Extracted from the current MCP server tool implementations.

**Consumers:**
- **hca-anndata-mcp** — exposes tools interactively via MCP protocol
- **dataset-validator (Batch)** — uses the same extraction logic for automated validation
- **Site/UI** — extracts summaries and stats for static display

**Capabilities:**
- File discovery (h5ad)
- Structural summaries (cell/gene counts, columns, embeddings, layers)
- HDF5 storage info (compression, chunking, sparse format)
- Descriptive statistics and value counts
- Data slicing and viewing

### hca-schema-validator (existing)

Already published as a PyPI package. Provides schema-based validation of HCA datasets.

**Integration with MCP:** Wire the validator into the MCP server so users can validate h5ad files interactively and get real-time feedback while exploring.

### hca-anndata-mcp (this package)

Thin MCP server layer that exposes both libraries as tools over the stdio JSON-RPC protocol.

## Current Tools (v0.1)

| Tool | Description | Status |
|------|-------------|--------|
| `locate_files` | Find h5ad files in a directory | Done |
| `get_summary` | Structural overview of an AnnData file | Done |
| `get_storage_info` | HDF5 compression, chunking, sparse format details | Done |
| `get_descriptive_stats` | Stats and value counts for obs/var columns | Done |
| `view_data` | View slices of any attribute | Done |
| `plot_embedding` | UMAP/PCA scatter plots colored by obs column or gene | Done |
| `get_cap_annotations` | Inspect CAP cell annotation metadata, marker genes, rationale | Done |

## Planned Work

### Phase 1: Validation Integration

Add validation tools that use hca-schema-validator:
- `validate_file` — Run full HCA schema validation on an h5ad file
- `validate_column` — Validate a specific obs column against the schema (e.g. ontology term IDs)
- Validate CAP annotation completeness (required fields per the [cell-annotation-schema](https://github.com/cellannotation/cell-annotation-schema))
- Surface validation errors interactively so users can inspect and fix issues in-session

### Phase 2: Extract hca-anndata-tools ✅

Completed. Tool implementations extracted into `packages/hca-anndata-tools/`. The MCP server now depends on the library via path dependency and registers tools directly from it. Only `plot_embedding` has a thin MCP wrapper (to convert the library's dict return to `ImageContent`).

### Phase 3: Electron Desktop App

Build an Electron + React desktop app that provides a rich visual UI for h5ad exploration and validation, powered by the MCP server and Anthropic API.

**Architecture:**
```
HCA AnnData Explorer (Electron app)
├── Renderer (React + Plotly + AG Grid)
│   ├── UMAP / embedding scatter plots (interactive, zoomable)
│   ├── Validation results dashboard
│   ├── Obs/var stats tables and charts
│   └── AI chat panel (Claude-powered exploration)
├── Main process
│   ├── Claude Agent SDK (@anthropic-ai/claude-agent-sdk)
│   │   ├── Agent loop, tool orchestration, context management
│   │   ├── Subagent support (parallel tasks, specialized roles)
│   │   └── Auth via existing Claude Code session (no separate API key)
│   └── hca-anndata-mcp (child process, stdio JSON-RPC)
└── hca-anndata-tools (shared extraction logic)
```

**Claude Agent SDK integration:**

The [Claude Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview) (`npm i @anthropic-ai/claude-agent-sdk`) provides Claude Code's full agent harness as an embeddable library. This eliminates the need to build a custom agent loop — the SDK handles tool orchestration, context management, retries, and [subagent spawning](https://platform.claude.com/docs/en/agent-sdk/subagents).

```typescript
import { query } from '@anthropic-ai/claude-agent-sdk';

const result = await query({
  prompt: "Show me the cell type distribution for this atlas",
  tools: [/* MCP tools from hca-anndata-mcp */],
  agents: [{
    name: "anndata-explorer",
    description: "Explores AnnData h5ad files for HCA",
    prompt: "You help scientists explore single-cell atlas data..."
  }]
});
```

The app embeds Claude's capabilities rather than reimplementing them. The Agent SDK handles the hard parts; the Electron app provides the UI and MCP server.

**Key capabilities:**
- Embed Claude's full agent loop via the Agent SDK — no reverse engineering needed
- Spawn `hca-anndata-mcp` as a child process, communicate via MCP protocol
- Render embedding plots with Plotly (interactive pan/zoom/hover, not static PNGs)
- Display validation errors inline with links to the problematic cells/columns
- AI chat sidebar with Claude for natural-language data exploration
- Define specialized [subagents](https://platform.claude.com/docs/en/agent-sdk/subagents) (e.g. a validation agent, an exploration agent)
- No image rendering limitations — full control over the UI

**Alternative LLM backends:**

The Claude Agent SDK is Claude-only by default, but [LiteLLM](https://docs.litellm.ai/docs/tutorials/claude_agent_sdk) can sit between the SDK and any backend — OpenAI, local models (llama.cpp, Ollama, vLLM), Bedrock, Azure, Vertex AI. Same agent code, different model underneath. This matters for:
- Customers running on-prem with private models
- Cost optimization (using smaller models for simple tasks)
- Fallback/redundancy across providers

Alternatively, the [OpenAI Agents SDK](https://openai.github.io/openai-agents-python/models/) natively supports any OpenAI-compatible endpoint, if we ever need to move off Anthropic.

**Why Electron + Agent SDK:**
- Claude Code CLI can't render images inline; Claude Desktop doesn't yet support A2UI or MCP Apps
- Building a custom agent loop from scratch is no longer practical — the harness is too sophisticated
- The Agent SDK gives us the full Claude Code agent experience as a library
- Can auth through existing Claude Code session — no separate API key management
- LiteLLM integration allows swapping to other LLM backends without changing agent code
- Same `hca-anndata-tools` library underneath — no duplicate logic
- Could later adopt A2UI components if/when the protocol matures

**Prior art:**
- [CodePilot](https://github.com/op7418/CodePilot) — Electron + Next.js GUI for Claude Code
- [Crystal](https://github.com/stravu/crystal) — Electron app managing multiple Claude Code instances
- [Claude Agent SDK guide](https://www.anthropic.com/engineering/building-agents-with-the-claude-agent-sdk) — Anthropic's official building guide

### Phase 4: Remote Zarr / S3 Support

Support reading and writing zarr-backed AnnData files directly on S3 (see [#220](https://github.com/clevercanary/hca-validation-tools/issues/220)).

**Read path (metadata-first):**
- Add `s3fs` / `fsspec` dependencies
- Accept `s3://bucket/path.zarr` paths in all tools
- Zarr's directory structure means each component (obs, var, uns, X) is a separate S3 prefix
- Most MCP tools (get_summary, get_descriptive_stats, view_data on obs/var/uns) only fetch metadata — never touch X
- Near-instant responses on remote data without downloading full files
- Works with zarr v2 (widely deployed today) and v3 (sharding benefits for matrix access)

**Write path (mutable zarr workflow):**

Zarr on S3 as the mutable working format, h5ad as the immutable distribution format:

```
S3 (zarr — living dataset, mutable)
  ↓ MCP tools read metadata/obs remotely (fast, no download)
  ↓ Curator updates obs columns via write tools (only changed columns written)
  ↓ Validation runs against the live zarr
  ↓ When ready: serialize to h5ad for publication/distribution
```

New MCP tools for the write path:
- `update_obs_column` — Write/update a single obs column on a remote zarr (only writes that column's chunks)
- `update_uns` — Update uns metadata entries
- `export_h5ad` — Serialize a remote zarr to a local or S3 h5ad file for distribution

**Zarr transport:**
- S3/GCS/Azure Blob — native home, just objects under a prefix
- Local disk — a directory of files
- Zip archive — `ZipStore` bundles into a single file for transfer (loses random access)
- Sync — `aws s3 sync` or `rclone` between S3 and local

## Technical Notes

- FastMCP v2 with `show_banner=False` and `transport="stdio"` (banner corrupts JSON-RPC)
- MCP config lives in `.mcp.json` at project root
- Python 3.10+, Poetry for dependency management
- Virtualenv managed by Poetry; run `poetry env info -p` to see the local path

## UI Rendering Options (Context)

| Approach | Status | Pros | Cons |
|----------|--------|------|------|
| Claude Code CLI | Working now | Zero setup, fast iteration | No inline images, text-only |
| Claude Desktop | Available | Renders MCP images natively | No interactive charts, limited layout |
| VS Code Extension | Available | Inline diffs, IDE integration | Still terminal-based for MCP output |
| Electron + Agent SDK (Phase 3) | Planned | Full Claude harness, interactive plots, custom UI | Build effort, separate app to maintain |
| A2UI / MCP Apps | Emerging | Standard protocol, native rendering | Not yet supported in Claude clients |

## Open Questions

- Should `hca-anndata-tools` be a separate package under `packages/` or part of `shared/`?
- What validation checks are most useful interactively vs. batch-only?
- What summary/stat views does the site need for static display?
- Electron app: standalone product or integrated into existing HCA portal tooling?
- Should the Electron app also serve as an MCP client (connecting to other MCP servers)?

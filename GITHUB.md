# Push V2 to GitHub

The codebase is git-ready. Run once from
`C:\Projects\tradingap\Trading Agent 2.0\` in Git Bash:

```bash
bash setup_github.sh <your-github-username> trading-agent-v2 private
```

The script will:
1. `git init -b main` if not already a repo
2. Stage everything and commit
3. Use `gh` CLI to create the GitHub repo and push (falls back to manual
   instructions if `gh` isn't installed)

## What's tracked vs ignored

**Tracked** (source-of-truth):
- All `.py` / `.md` / `.toml` / `.service` / `.sh` / `.bat`
- `progress_tracker.json`, `.env.example`
- `tests/` (including fixtures)
- `deploy/`, `.github/workflows/`

**Ignored** (regenerable or sensitive):
- `.env` (contains API keys — never commit)
- `__pycache__/`, `.pytest_cache/`
- `v2_ledger.json`, `v2_trade_log.jsonl`, `comparison_ledger.jsonl` (runtime state)
- `memory_v2/indexes/` (rebuild from `semantic_memory.db`)
- `models/`, `*.safetensors`, `*.pth` (too big for git; store on HF Hub or S3)

## CI

`.github/workflows/tests.yml` runs the lightweight V2 test suite on every
push. No GPU; no LLM API keys needed. The historical-replay test is
skipped in CI (depends on V1's local decision archive) but the 27 unit
tests will run.

## Coordinating with V1

V1's code lives in the parent folder (`C:\Projects\tradingap\`). The
recommended pattern is:

- V1 stays in its own git repo (or no repo, as today).
- V2 has its own repo (this one).
- No `git submodule` between them — V2 reads V1 as a sibling folder via
  `V1_REPO_PATH` env var.

If you later want one mega-repo:

```bash
cd C:\Projects\tradingap
git init -b main
git submodule add ./"Trading Agent 2.0" v2
```

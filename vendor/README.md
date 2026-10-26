# Vendored dependencies

## agent-audit

This is a **vendored snapshot** of the standalone
[`agent-audit`](../../agent-audit) library, included so that a single clone of
`deepagent_project` is runnable without requiring a sibling checkout.

- Canonical source: `../agent-audit`
- Vendored version: `0.1.2`
- Path used by `pyproject.toml`: `vendor/agent-audit`

When the canonical library changes, sync it manually:

```powershell
# from deepagent_project/
Copy-Item ..\agent-audit\agent_audit\* vendor\agent-audit\agent_audit\ -Recurse -Force
Copy-Item ..\agent-audit\pyproject.toml vendor\agent-audit\ -Force
Copy-Item ..\agent-audit\LICENSE vendor\agent-audit\ -Force
Copy-Item ..\agent-audit\README.md vendor\agent-audit\ -Force
```

Do not edit the vendored copy directly; make changes in `../agent-audit` and
sync again. The standalone repository remains the source of truth, package
tests, and releases.

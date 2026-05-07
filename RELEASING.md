# Releasing `ai-orchestrator-client`

Manual checklist for cutting a new version. The release workflow at
`.github/workflows/release.yml` handles the actual upload via PyPI
Trusted Publishing — but several one-time prerequisites must be in
place before the **first** tag push.

## One-time prerequisites (first release only)

1. **Confirm the PyPI name is unclaimed**:

   ```bash
   pip index versions ai-orchestrator-client
   ```

   Should report no project. If something else is on PyPI under this
   name, decide on a fallback name (e.g. `ai-orchestrator-py`) and
   change `pyproject.toml [project] name`, the wheel-package config,
   and references in `README.md` / `CHANGELOG.md` before continuing.

2. **Register Trusted Publisher on PyPI**: https://pypi.org/manage/account/publishing/ —
   add a publisher with:
   - Owner: `ernesto01louis`
   - Repository: `ai-orchestrator-client`
   - Workflow filename: `release.yml`
   - Environment name: `pypi`

   PyPI rejects the upload with a clear error if this isn't set up.

3. **Create the `pypi` GitHub deployment environment** (Settings →
   Environments → New). No protection rules required for an alpha;
   add reviewers later if you want gated promotions.

4. **Push the GitHub remote** if not already attached, and confirm CI
   is green on the latest `main`.

## Per-release checklist

1. Bump version in TWO places (kept in sync by
   `tests/test_smoke.py::test_user_agent_tracks_package_version`):

   - `pyproject.toml` — `[project] version`
   - `ai_orchestrator_client/__init__.py` — `__version__`

2. Add a `[X.Y.Z] — YYYY-MM-DD` section at the top of `CHANGELOG.md`
   with concrete `Added` / `Changed` / `Fixed` / `Limitations` rows.

3. Local sanity check:

   ```bash
   ruff check . && mypy && pytest -q
   python -m build
   twine check dist/*
   rm -rf dist/ build/ *.egg-info
   ```

4. Commit, push to `main` (CI runs).

5. Tag and push:

   ```bash
   git tag -a vX.Y.Z -m "vX.Y.Z"
   git push origin vX.Y.Z
   ```

6. Watch the `Release` workflow in Actions. Steps:
   1. Install package + dev deps
   2. Lint + type-check + tests (final gate)
   3. Build sdist + wheel + `twine check`
   4. Verify the tag matches the package version
   5. Publish to PyPI via Trusted Publishing

7. Verify on PyPI:

   ```bash
   pip install --pre ai-orchestrator-client==X.Y.Z
   python -c "from ai_orchestrator_client import __version__; print(__version__)"
   ```

## Pre-releases

Use PEP 440 segments — `0.1.0a0`, `0.1.0a1`, `0.1.0b0`, `0.1.0rc0`,
`0.1.0` (final), `0.1.1`, `0.2.0a0`, … Pre-release versions require
`pip install --pre ai-orchestrator-client` to install; users without
`--pre` will silently get nothing until a final version ships.

## Yanking a bad release

If `0.1.0a0` is broken, bump to `0.1.0a1` rather than re-tagging the
existing version. PyPI does not allow re-uploading the same version.
You can also Yank the bad release on PyPI (which keeps it available
for explicit pins but hides it from solvers).

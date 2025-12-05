# Backend Development Environment

This guide captures the minimal steps to install the PyYAML, Pydantic, and SQLAlchemy tooling we rely on for fixture validation and database tests.

## Install dependencies

These packages are already pinned in `requirements.txt` for use by both the application code and the tests:

- `PyYAML>=6.0,<7`
- `pydantic>=2.6,<3`
- `SQLAlchemy>=2.0,<3`

Set up a fresh virtual environment and install everything with pip:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
python -m pip install pytest
```

The final `pytest` install ensures the test runner itself is available locally even though the core dependencies are already listed for production use.

## Sanity checks

Run the test suite to confirm the tools are present and working:

```bash
pytest backend/tests/test_dependency_health.py
```

The `test_dependency_health` module exercises all three libraries:

- PyYAML parses a sample YAML payload
- Pydantic validates and coerces values into a typed model
- SQLAlchemy creates an in-memory SQLite table and round-trips a row

If you want to run the broader fixture tests after installing the dependencies, execute:

```bash
pytest backend/tests
```

## Build an offline content bundle

To package localized messages and other fixtures for offline-capable clients, run:

```bash
python -m kyrgame.scripts.package_content --output legacy/Dist/offline-content.json
```

The command emits a single JSON file with the default locale message bundle, static content fixtures, and a timestamp clients can use to validate cache freshness.

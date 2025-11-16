# Dependency Management

This document explains how to use the lock files for reproducible builds.

## Lock Files

FastAPI provides multiple lock files for different use cases:

### 1. `requirements.lock` - Core Dependencies

Contains only the core dependencies required to run FastAPI:
- `starlette`
- `pydantic`
- `typing-extensions`
- `annotated-doc`

**Use case:** Minimal FastAPI installation

```bash
pip install -r requirements.lock
```

### 2. `requirements-all.lock` - All Optional Dependencies

Contains all optional dependencies including:
- HTTP client (`httpx`)
- Templates (`jinja2`)
- Forms and files (`python-multipart`)
- Email validation (`email-validator`)
- Fast JSON libraries (`ujson`, `orjson`)
- Server (`uvicorn[standard]`)
- Settings management (`pydantic-settings`)
- Extra types (`pydantic-extra-types`)

**Use case:** Full-featured FastAPI installation

```bash
pip install -r requirements-all.lock
```

### 3. `requirements-enterprise.lock` - Enterprise Dependencies

Contains enterprise-grade dependencies:
- **Metrics**: `prometheus-client`
- **Tracing**: `opentelemetry-api`, `opentelemetry-sdk`, exporters
- **Error Tracking**: `sentry-sdk`
- **Caching**: `redis[hiredis]`
- **Performance Testing**: `locust`

**Use case:** Production enterprise deployments

```bash
pip install -r requirements-enterprise.lock
```

## Why Lock Files?

Lock files ensure **reproducible builds** by:

1. **Pinning exact versions** of all dependencies and sub-dependencies
2. **Preventing dependency drift** between environments
3. **Ensuring consistency** across development, staging, and production
4. **Faster CI/CD** with predictable dependency resolution

## Updating Lock Files

When dependencies change in `pyproject.toml`, regenerate lock files:

```bash
# Regenerate all lock files
uv pip compile pyproject.toml -o requirements.lock
uv pip compile pyproject.toml --extra all -o requirements-all.lock
uv pip compile pyproject.toml --extra enterprise -o requirements-enterprise.lock
```

Or use the provided script:

```bash
./scripts/update_lockfiles.sh
```

## Best Practices

### Development

For development, use virtual environments with lock files:

```bash
# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements-all.lock

# Install dev dependencies
pip install -r requirements-dev.txt  # If exists
```

### Production

For production deployments:

```bash
# Install core + enterprise dependencies
pip install -r requirements.lock
pip install -r requirements-enterprise.lock
```

Or use Docker multi-stage builds:

```dockerfile
FROM python:3.11-slim as builder

WORKDIR /app

# Copy lock files
COPY requirements.lock requirements-enterprise.lock ./

# Install dependencies
RUN pip install --no-cache-dir -r requirements.lock -r requirements-enterprise.lock

# ... rest of Dockerfile
```

### CI/CD

Use lock files in CI/CD for consistent testing:

```yaml
# GitHub Actions example
- name: Install dependencies
  run: |
    pip install -r requirements-all.lock
    pip install -r requirements-enterprise.lock
```

## Dependency Scanning

Lock files enable better security scanning:

```bash
# Scan for vulnerabilities
pip-audit -r requirements.lock
pip-audit -r requirements-enterprise.lock

# Check for outdated packages
pip list --outdated
```

## Troubleshooting

### Dependency Conflicts

If you encounter conflicts:

1. Check `pyproject.toml` version constraints
2. Regenerate lock files
3. Review dependency tree:

```bash
uv pip tree
```

### Platform-Specific Dependencies

Lock files are platform-independent by default. For platform-specific locks:

```bash
# Generate for specific Python version
uv pip compile pyproject.toml --python-version 3.11 -o requirements-py311.lock
```

## Migration from requirements.txt

If migrating from `requirements.txt`:

1. Keep existing `requirements.txt` for backward compatibility
2. Add lock files for reproducibility
3. Update CI/CD to use lock files
4. Eventually deprecate old `requirements.txt`

## References

- [uv Documentation](https://github.com/astral-sh/uv)
- [pip-tools](https://github.com/jazzband/pip-tools)
- [Dependency Management Best Practices](https://packaging.python.org/guides/dependency-management/)

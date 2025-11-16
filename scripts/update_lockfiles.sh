#!/bin/bash
# Update all lock files for FastAPI

set -e

echo "🔒 Updating FastAPI lock files..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ Error: uv is not installed"
    echo "Install with: pip install uv"
    exit 1
fi

echo ""
echo "📦 Generating requirements.lock (core dependencies)..."
uv pip compile pyproject.toml -o requirements.lock --quiet
echo "✅ requirements.lock updated"

echo ""
echo "📦 Generating requirements-all.lock (all optional dependencies)..."
uv pip compile pyproject.toml --extra all -o requirements-all.lock --quiet
echo "✅ requirements-all.lock updated"

echo ""
echo "📦 Generating requirements-enterprise.lock (enterprise dependencies)..."
uv pip compile pyproject.toml --extra enterprise -o requirements-enterprise.lock --quiet
echo "✅ requirements-enterprise.lock updated"

echo ""
echo "📊 Lock file sizes:"
ls -lh requirements*.lock | awk '{print "  " $9 ": " $5}'

echo ""
echo "✅ All lock files updated successfully!"
echo ""
echo "Next steps:"
echo "  1. Review changes: git diff requirements*.lock"
echo "  2. Test installation: pip install -r requirements.lock"
echo "  3. Commit changes: git add requirements*.lock && git commit -m '📦 Update lock files'"

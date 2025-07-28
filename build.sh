#!/bin/bash
# Build script for RefChecker package
# This script cleans previous builds and creates a fresh package

set -e  # Exit on any error

echo "🧹 Cleaning previous builds..."
rm -rf dist/ build/ src/*.egg-info/

echo "📦 Building package..."
python -m build

echo "✅ Build complete! Files created:"
ls -la dist/

echo ""
echo "To upload to Test PyPI:"
echo "  twine upload --repository testpypi dist/* --username __token__"
echo ""
echo "To upload to PyPI:"
echo "  twine upload dist/* --username __token__"
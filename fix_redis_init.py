#!/usr/bin/env python3
"""
Fix module-level redis_client initialization that causes import-time errors.
Replaces: redis_client = _get_redis_client()
With: # redis_client = _get_redis_client()  # Removed - causes import-time error
"""

import re
from pathlib import Path

def fix_redis_init(file_path: Path) -> bool:
    """Fix redis_client initialization in a single file."""
    try:
        content = file_path.read_text()
        original = content

        # Replace the problematic pattern
        pattern = r'^redis_client = _get_redis_client\(\)$'
        replacement = '# redis_client = _get_redis_client()  # Removed - causes import-time error'

        content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

        if content != original:
            file_path.write_text(content)
            print(f"✅ Fixed: {file_path}")
            return True
        return False
    except Exception as e:
        print(f"❌ Error fixing {file_path}: {e}")
        return False

def main():
    """Find and fix all files with the problematic pattern."""
    hyperrsi_dir = Path("HYPERRSI")

    if not hyperrsi_dir.exists():
        print("❌ HYPERRSI directory not found. Run from project root.")
        return

    fixed_count = 0
    total_count = 0

    # Find all Python files
    for py_file in hyperrsi_dir.rglob("*.py"):
        # Skip backup files
        if py_file.suffix == '.bak':
            continue

        # Check if file contains the pattern
        try:
            content = py_file.read_text()
            if re.search(r'^redis_client = _get_redis_client\(\)$', content, re.MULTILINE):
                total_count += 1
                if fix_redis_init(py_file):
                    fixed_count += 1
        except Exception as e:
            print(f"⚠️ Error reading {py_file}: {e}")

    print(f"\n📊 Summary: Fixed {fixed_count}/{total_count} files")

if __name__ == "__main__":
    main()

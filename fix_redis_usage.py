#!/usr/bin/env python3
"""
Fix all redis_client usages to use _get_redis_client() function call.
This fixes runtime errors where redis_client is accessed before initialization.
"""

import re
from pathlib import Path
from typing import Set

def fix_redis_usage(file_path: Path) -> bool:
    """Fix redis_client usage in a single file."""
    try:
        content = file_path.read_text()
        original = content

        # Skip if file doesn't have _get_redis_client function
        if '_get_redis_client()' not in content and '__getattr__' not in content:
            return False

        # Pattern 1: Direct redis_client usage (not in function definition)
        # Replace: redis_client.method() -> _get_redis_client().method()
        # But skip lines that define _get_redis_client or redis_client =

        lines = content.split('\n')
        modified = False

        for i, line in enumerate(lines):
            # Skip comments and definitions
            if (line.strip().startswith('#') or
                'def _get_redis_client' in line or
                'redis_client = ' in line or
                '"redis_client"' in line or
                "'redis_client'" in line):
                continue

            # Find redis_client usage (not preceded by def or =)
            if 'redis_client.' in line or 'redis_client)' in line:
                # Check if it's not already _get_redis_client()
                if '_get_redis_client()' not in line:
                    # Replace redis_client with _get_redis_client()
                    new_line = re.sub(
                        r'\bredis_client\b',
                        '_get_redis_client()',
                        line
                    )
                    if new_line != line:
                        lines[i] = new_line
                        modified = True

        if modified:
            content = '\n'.join(lines)
            file_path.write_text(content)
            print(f"✅ Fixed: {file_path}")
            return True
        return False

    except Exception as e:
        print(f"❌ Error fixing {file_path}: {e}")
        return False

def main():
    """Find and fix all files with redis_client usage issues."""
    hyperrsi_dir = Path("HYPERRSI")

    if not hyperrsi_dir.exists():
        print("❌ HYPERRSI directory not found. Run from project root.")
        return

    fixed_count = 0
    total_count = 0

    # Get all Python files that have redis_client usage
    for py_file in hyperrsi_dir.rglob("*.py"):
        # Skip backup files
        if py_file.suffix == '.bak':
            continue

        try:
            content = py_file.read_text()
            # Check if file uses redis_client
            if 'redis_client' in content and '_get_redis_client' in content:
                total_count += 1
                if fix_redis_usage(py_file):
                    fixed_count += 1
        except Exception as e:
            print(f"⚠️ Error reading {py_file}: {e}")

    print(f"\n📊 Summary: Fixed {fixed_count}/{total_count} files")

if __name__ == "__main__":
    main()

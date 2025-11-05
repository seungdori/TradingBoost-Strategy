#!/usr/bin/env python3
"""
Script to remove `await redis.close()` calls from GRID directory files.
These calls are problematic when using pooled connections from shared.database.redis.
"""

import os
import re
from pathlib import Path

def fix_redis_close_in_file(file_path: Path) -> tuple[bool, int]:
    """
    Remove `await redis.close()` from a file.

    Returns:
        (modified, count): Whether file was modified and number of changes
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        original_content = content

        # Pattern 1: Remove entire finally block if it only contains await redis.close()
        pattern1 = r'\s*finally:\s*\n\s*await redis\.close\(\)\s*\n'
        content = re.sub(pattern1, '\n', content)

        # Pattern 2: Remove await redis.close() line
        pattern2 = r'\s*await redis\.close\(\)\s*\n'
        content = re.sub(pattern2, '\n', content)

        # Pattern 3: Handle commented out close() calls (keep as is)
        # Already handled by patterns above (won't match #)

        if content != original_content:
            # Count changes
            count = len(re.findall(r'await redis\.close\(\)', original_content))

            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True, count

        return False, 0

    except Exception as e:
        print(f"Error processing {file_path}: {e}")
        return False, 0

def main():
    grid_dir = Path('/Users/seunghyun/TradingBoost-Strategy/GRID')

    total_files_modified = 0
    total_changes = 0
    modified_files = []

    # Find all Python files in GRID directory
    for py_file in grid_dir.rglob('*.py'):
        modified, count = fix_redis_close_in_file(py_file)

        if modified:
            total_files_modified += 1
            total_changes += count
            modified_files.append(str(py_file.relative_to(grid_dir)))
            print(f"✓ Fixed {count} close() calls in: {py_file.relative_to(grid_dir)}")

    print(f"\n{'='*60}")
    print(f"Summary:")
    print(f"  Files modified: {total_files_modified}")
    print(f"  Total close() calls removed: {total_changes}")
    print(f"{'='*60}")

    if modified_files:
        print(f"\nModified files:")
        for f in sorted(modified_files):
            print(f"  - {f}")

if __name__ == '__main__':
    main()

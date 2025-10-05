#!/usr/bin/env python3
"""
Import update script for Phase 2 migration to shared modules.
Updates imports from GRID.utils.time and HYPERRSI calc_utils to shared.utils
"""

import re
from pathlib import Path

# Mapping of old imports to new shared imports
FUNCTION_MIGRATIONS = {
    # Time helpers (from GRID.utils.time)
    'parse_timeframe': 'shared.utils',
    'calculate_current_timeframe_start': 'shared.utils',
    'calculate_next_timeframe_start': 'shared.utils',
    'calculate_sleep_duration': 'shared.utils',
    'timeframe_to_seconds': 'shared.utils',
    'timeframe_to_timedelta': 'shared.utils',
    'get_timeframe_boundaries': 'shared.utils',

    # Type converters (from calc_utils - already in shared but need to update imports)
    'safe_float': 'shared.utils',
    'safe_int': 'shared.utils',
    'safe_decimal': 'shared.utils',
    'convert_bool_to_string': 'shared.utils',
    'convert_bool_to_int': 'shared.utils',

    # Trading helpers (from calc_utils)
    'round_to_qty': 'shared.utils',
    'get_tick_size_from_redis': 'shared.utils',
    'get_minimum_qty': 'shared.utils',
    'round_to_tick_size': 'shared.utils',
    'get_contract_size': 'shared.utils',

    # Symbol helpers (from calc_utils)
    'convert_symbol_to_okx_instrument': 'shared.utils',

    # Async helpers (from trading_utils)
    'ensure_async_loop': 'shared.utils',
    'get_or_create_event_loop': 'shared.utils',
}

def update_single_line_import(line: str) -> str:
    """Update a single-line import statement"""
    # Pattern: from HYPERRSI.src.trading.services.calc_utils import func1, func2, ...
    calc_utils_pattern = r'from HYPERRSI\.src\.trading\.services\.calc_utils import (.+)'

    match = re.match(calc_utils_pattern, line)
    if match:
        imports_str = match.group(1)
        # Parse the imports (handle 'as' aliases)
        imports = [imp.strip() for imp in imports_str.split(',')]

        migrated_funcs = []
        remaining_funcs = []

        for imp in imports:
            # Handle 'func as alias' pattern
            if ' as ' in imp:
                func_name = imp.split(' as ')[0].strip()
                if func_name in FUNCTION_MIGRATIONS:
                    migrated_funcs.append(imp)
                else:
                    remaining_funcs.append(imp)
            else:
                if imp in FUNCTION_MIGRATIONS:
                    migrated_funcs.append(imp)
                else:
                    remaining_funcs.append(imp)

        # Build new import lines
        new_lines = []
        if migrated_funcs:
            new_lines.append(f"from shared.utils import {', '.join(migrated_funcs)}")
        if remaining_funcs:
            new_lines.append(f"from HYPERRSI.src.trading.services.calc_utils import {', '.join(remaining_funcs)}")

        return '\n'.join(new_lines) if new_lines else line

    return line

def update_file(file_path: Path) -> bool:
    """Update imports in a single file. Returns True if file was modified."""
    with open(file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    original_content = content
    lines = content.split('\n')
    new_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Handle GRID.utils.time multi-line imports
        if 'from GRID.utils.time import' in line and '(' in line:
            # Find the closing parenthesis
            import_lines = [line]
            i += 1
            while i < len(lines) and ')' not in lines[i-1]:
                import_lines.append(lines[i])
                i += 1

            # Extract function names
            import_text = ' '.join(import_lines)
            funcs_match = re.search(r'from GRID\.utils\.time import \(([^)]+)\)', import_text)
            if funcs_match:
                funcs = [f.strip() for f in funcs_match.group(1).split(',')]
                funcs = [f for f in funcs if f]  # Remove empty strings
                new_lines.append(f"from shared.utils import ({', '.join(funcs)})")
            else:
                new_lines.extend(import_lines)
            continue

        # Handle HYPERRSI calc_utils imports
        elif 'from HYPERRSI.src.trading.services.calc_utils import' in line:
            updated_line = update_single_line_import(line)
            new_lines.append(updated_line)
            i += 1
            continue

        # Handle HYPERRSI trading_utils imports
        elif 'from HYPERRSI.src.trading.utils.trading_utils import ensure_async_loop' in line:
            new_lines.append('from shared.utils import ensure_async_loop')
            i += 1
            continue

        new_lines.append(line)
        i += 1

    new_content = '\n'.join(new_lines)

    if new_content != original_content:
        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(new_content)
        return True

    return False

def main():
    # Files to update
    files_to_update = [
        'GRID/strategies/grid.py',
        'GRID/trading/grid_core.py',
        'HYPERRSI/src/trading/services/get_current_price.py',
        'HYPERRSI/src/trading/services/order_utils.py',
        'HYPERRSI/src/trading/services/position_utils.py',
        'HYPERRSI/src/bot/command/account.py',
        'HYPERRSI/src/trading/stats.py',
        'HYPERRSI/src/bot/command/trading.py',
        'HYPERRSI/src/trading/trading_service.py',
    ]

    project_root = Path(__file__).parent
    updated_files = []

    for file_path_str in files_to_update:
        file_path = project_root / file_path_str
        if file_path.exists():
            if update_file(file_path):
                updated_files.append(file_path_str)
                print(f"✅ Updated: {file_path_str}")
            else:
                print(f"⏭️  No changes: {file_path_str}")
        else:
            print(f"❌ Not found: {file_path_str}")

    print(f"\n📊 Summary: Updated {len(updated_files)} files")
    if updated_files:
        print("Updated files:")
        for f in updated_files:
            print(f"  - {f}")

if __name__ == '__main__':
    main()

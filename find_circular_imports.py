#!/usr/bin/env python3
"""
Find specific files causing circular dependencies
"""

import ast
from pathlib import Path
from collections import defaultdict
from typing import Set, Dict, List, Tuple

class ImportFinder(ast.NodeVisitor):
    """Find all imports in a file."""

    def __init__(self):
        self.imports: List[Tuple[str, int]] = []  # (module, line_number)

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append((alias.name, node.lineno))

    def visit_ImportFrom(self, node):
        if node.module:
            self.imports.append((node.module, node.lineno))

def find_problematic_imports(project_root: Path) -> Dict[str, List[Dict]]:
    """Find files with problematic cross-dependencies."""

    problems = {
        'shared_imports_strategies': [],
        'hyperrsi_imports_grid': [],
        'grid_imports_hyperrsi': []
    }

    # Check shared module
    shared_path = project_root / 'shared'
    if shared_path.exists():
        for py_file in shared_path.rglob('*.py'):
            if '__pycache__' in str(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read())

                finder = ImportFinder()
                finder.visit(tree)

                for module, line in finder.imports:
                    if module.startswith('HYPERRSI') or module.startswith('GRID'):
                        problems['shared_imports_strategies'].append({
                            'file': str(py_file.relative_to(project_root)),
                            'imports': module,
                            'line': line
                        })
            except Exception as e:
                pass

    # Check HYPERRSI module
    hyperrsi_path = project_root / 'HYPERRSI'
    if hyperrsi_path.exists():
        for py_file in hyperrsi_path.rglob('*.py'):
            if '__pycache__' in str(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read())

                finder = ImportFinder()
                finder.visit(tree)

                for module, line in finder.imports:
                    if module.startswith('GRID'):
                        problems['hyperrsi_imports_grid'].append({
                            'file': str(py_file.relative_to(project_root)),
                            'imports': module,
                            'line': line
                        })
            except Exception as e:
                pass

    # Check GRID module
    grid_path = project_root / 'GRID'
    if grid_path.exists():
        for py_file in grid_path.rglob('*.py'):
            if '__pycache__' in str(py_file):
                continue

            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read())

                finder = ImportFinder()
                finder.visit(tree)

                for module, line in finder.imports:
                    if module.startswith('HYPERRSI'):
                        problems['grid_imports_hyperrsi'].append({
                            'file': str(py_file.relative_to(project_root)),
                            'imports': module,
                            'line': line
                        })
            except Exception as e:
                pass

    return problems

def main():
    project_root = Path(__file__).parent

    print("="*80)
    print("FINDING SPECIFIC CIRCULAR DEPENDENCY VIOLATIONS")
    print("="*80)

    problems = find_problematic_imports(project_root)

    print("\n1️⃣  shared module importing from strategies:")
    print("-" * 80)
    if problems['shared_imports_strategies']:
        print(f"   Found {len(problems['shared_imports_strategies'])} violations:\n")
        for item in problems['shared_imports_strategies']:
            print(f"   📁 {item['file']}:{item['line']}")
            print(f"      imports: {item['imports']}\n")
    else:
        print("   ✅ No violations found\n")

    print("\n2️⃣  HYPERRSI importing from GRID:")
    print("-" * 80)
    if problems['hyperrsi_imports_grid']:
        print(f"   Found {len(problems['hyperrsi_imports_grid'])} violations:\n")
        for item in problems['hyperrsi_imports_grid']:
            print(f"   📁 {item['file']}:{item['line']}")
            print(f"      imports: {item['imports']}\n")
    else:
        print("   ✅ No violations found\n")

    print("\n3️⃣  GRID importing from HYPERRSI:")
    print("-" * 80)
    if problems['grid_imports_hyperrsi']:
        print(f"   Found {len(problems['grid_imports_hyperrsi'])} violations:\n")
        for item in problems['grid_imports_hyperrsi']:
            print(f"   📁 {item['file']}:{item['line']}")
            print(f"      imports: {item['imports']}\n")
    else:
        print("   ✅ No violations found\n")

    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    total = (len(problems['shared_imports_strategies']) +
             len(problems['hyperrsi_imports_grid']) +
             len(problems['grid_imports_hyperrsi']))
    print(f"\nTotal violations: {total}")
    print(f"  - shared → strategies: {len(problems['shared_imports_strategies'])}")
    print(f"  - HYPERRSI → GRID: {len(problems['hyperrsi_imports_grid'])}")
    print(f"  - GRID → HYPERRSI: {len(problems['grid_imports_hyperrsi'])}")
    print("\n" + "="*80)

if __name__ == '__main__':
    main()

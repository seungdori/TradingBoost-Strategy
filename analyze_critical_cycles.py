#!/usr/bin/env python3
"""
Critical Circular Dependency Analyzer
Focuses on identifying the most problematic circular dependencies.
"""

import ast
import os
from pathlib import Path
from collections import defaultdict
from typing import Dict, Set, List
import sys

class SimpleImportAnalyzer(ast.NodeVisitor):
    """Extract top-level package imports only."""

    def __init__(self):
        self.imports: Set[str] = set()

    def visit_Import(self, node):
        for alias in node.names:
            top_level = alias.name.split('.')[0]
            if top_level in ['HYPERRSI', 'GRID', 'shared']:
                self.imports.add(top_level)

    def visit_ImportFrom(self, node):
        if node.module:
            top_level = node.module.split('.')[0]
            if top_level in ['HYPERRSI', 'GRID', 'shared']:
                self.imports.add(top_level)

def analyze_module_dependencies(project_root: Path) -> Dict[str, Dict[str, Set[str]]]:
    """Analyze dependencies at module and sub-module level."""

    # Module-level dependencies (HYPERRSI, GRID, shared)
    module_deps = defaultdict(set)

    # Sub-module dependencies (e.g., HYPERRSI.src.api, GRID.services)
    submodule_deps = defaultdict(set)

    # File count per module
    file_counts = defaultdict(int)

    for module_name in ['HYPERRSI', 'GRID', 'shared']:
        module_path = project_root / module_name
        if not module_path.exists():
            continue

        for py_file in module_path.rglob('*.py'):
            if 'test' in str(py_file) or '__pycache__' in str(py_file):
                continue

            file_counts[module_name] += 1

            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    tree = ast.parse(f.read())

                analyzer = SimpleImportAnalyzer()
                analyzer.visit(tree)

                # Add to module-level dependencies
                for imp in analyzer.imports:
                    if imp != module_name:  # Don't count self-imports
                        module_deps[module_name].add(imp)

                # Get sub-module name
                rel_path = py_file.relative_to(module_path)
                submodule_parts = [module_name] + list(rel_path.parts[:-1])
                if len(submodule_parts) > 1:
                    submodule = '.'.join(submodule_parts[:2])  # e.g., HYPERRSI.src
                    for imp in analyzer.imports:
                        if not imp.startswith(module_name):
                            submodule_deps[submodule].add(imp)

            except Exception as e:
                pass  # Skip files with syntax errors

    return {
        'module_deps': dict(module_deps),
        'submodule_deps': dict(submodule_deps),
        'file_counts': dict(file_counts)
    }

def detect_critical_cycles(deps: Dict[str, Set[str]]) -> List[List[str]]:
    """Detect cycles using simple DFS."""
    cycles = []

    def find_path(start: str, end: str, visited: Set[str], path: List[str]) -> bool:
        if start == end and len(path) > 0:
            cycles.append(path + [end])
            return True

        if start in visited:
            return False

        visited.add(start)

        for neighbor in deps.get(start, set()):
            if find_path(neighbor, end, visited.copy(), path + [start]):
                return True

        return False

    # Check each module for cycles back to itself
    for module in deps.keys():
        find_path(module, module, set(), [])

    # Remove duplicate cycles
    unique_cycles = []
    seen = set()
    for cycle in cycles:
        cycle_tuple = tuple(sorted(cycle))
        if cycle_tuple not in seen:
            seen.add(cycle_tuple)
            unique_cycles.append(cycle)

    return unique_cycles

def main():
    project_root = Path(__file__).parent

    print("="*80)
    print("CRITICAL CIRCULAR DEPENDENCY ANALYSIS")
    print("="*80)

    results = analyze_module_dependencies(project_root)

    print("\n📊 Project Statistics:")
    for module, count in sorted(results['file_counts'].items()):
        print(f"   {module}: {count} files")

    print("\n📦 Top-Level Module Dependencies:")
    for module in ['HYPERRSI', 'GRID', 'shared']:
        deps = results['module_deps'].get(module, set())
        if deps:
            print(f"   {module} → {', '.join(sorted(deps))}")
        else:
            print(f"   {module} → (no external dependencies)")

    # Detect cycles at module level
    cycles = detect_critical_cycles(results['module_deps'])

    print(f"\n🔄 Circular Dependencies at Module Level:")
    if cycles:
        print(f"   ❌ Found {len(cycles)} cycle(s):")
        for i, cycle in enumerate(cycles, 1):
            print(f"\n   Cycle {i}: {' → '.join(cycle)}")
    else:
        print("   ✅ No circular dependencies at module level")

    print("\n🔍 Sub-Module Dependencies (Top 10 by external deps):")
    sorted_submods = sorted(
        results['submodule_deps'].items(),
        key=lambda x: len(x[1]),
        reverse=True
    )[:10]

    for submod, deps in sorted_submods:
        if deps:
            print(f"   {submod} → {', '.join(sorted(deps))}")

    print("\n" + "="*80)
    print("ANALYSIS SUMMARY")
    print("="*80)

    # Check if there are problematic cross-dependencies
    hyperrsi_imports_grid = 'GRID' in results['module_deps'].get('HYPERRSI', set())
    grid_imports_hyperrsi = 'HYPERRSI' in results['module_deps'].get('GRID', set())

    print("\n⚠️  Critical Issues:")

    if hyperrsi_imports_grid and grid_imports_hyperrsi:
        print("   ❌ CRITICAL: HYPERRSI and GRID have bidirectional dependencies")
        print("      This creates tight coupling between strategies.")
        print("      Recommendation: Remove cross-strategy imports, use shared module only.")
    elif hyperrsi_imports_grid:
        print("   ⚠️  WARNING: HYPERRSI imports from GRID")
        print("      Recommendation: Move shared code to 'shared' module")
    elif grid_imports_hyperrsi:
        print("   ⚠️  WARNING: GRID imports from HYPERRSI")
        print("      Recommendation: Move shared code to 'shared' module")
    else:
        print("   ✅ No critical cross-strategy dependencies")

    # Check shared module dependencies
    shared_imports_strategies = results['module_deps'].get('shared', set()) & {'HYPERRSI', 'GRID'}
    if shared_imports_strategies:
        print(f"   ❌ CRITICAL: shared module imports from strategies: {', '.join(shared_imports_strategies)}")
        print("      This violates the dependency direction (strategies should depend on shared, not vice versa)")
    else:
        print("   ✅ shared module maintains correct dependency direction")

    print("\n✨ Recommendations:")
    print("   1. Strategies (HYPERRSI, GRID) should only import from 'shared'")
    print("   2. 'shared' should never import from strategies")
    print("   3. HYPERRSI and GRID should not import from each other")
    print("   4. Move any shared code to the 'shared' module")

    print("\n" + "="*80)

    # Exit with error if critical issues found
    if (hyperrsi_imports_grid and grid_imports_hyperrsi) or shared_imports_strategies:
        sys.exit(1)

    sys.exit(0)

if __name__ == '__main__':
    main()

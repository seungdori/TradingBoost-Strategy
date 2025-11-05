#!/usr/bin/env python3
"""
Circular Dependency Analyzer for TradingBoost-Strategy
Analyzes import patterns to detect circular dependencies across the monorepo.
"""

import ast
import os
from pathlib import Path
from collections import defaultdict, deque
from typing import Dict, Set, List, Tuple
import sys

class ImportAnalyzer(ast.NodeVisitor):
    """AST visitor to extract import statements from Python files."""

    def __init__(self, module_path: str):
        self.module_path = module_path
        self.imports: Set[str] = set()

    def visit_Import(self, node):
        """Handle 'import x' statements."""
        for alias in node.names:
            self.imports.add(alias.name.split('.')[0])
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        """Handle 'from x import y' statements."""
        if node.module:
            # Get the top-level package
            top_level = node.module.split('.')[0]
            self.imports.add(top_level)
        self.generic_visit(node)

class CircularDependencyDetector:
    """Detects circular dependencies in Python project."""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.module_imports: Dict[str, Set[str]] = defaultdict(set)
        self.file_to_module: Dict[Path, str] = {}
        self.module_to_files: Dict[str, List[Path]] = defaultdict(list)

    def get_module_name(self, file_path: Path) -> str:
        """Convert file path to module name."""
        try:
            rel_path = file_path.relative_to(self.project_root)
            parts = list(rel_path.parts)

            # Remove __init__.py or .py extension
            if parts[-1] == '__init__.py':
                parts = parts[:-1]
            elif parts[-1].endswith('.py'):
                parts[-1] = parts[-1][:-3]

            return '.'.join(parts)
        except ValueError:
            return str(file_path)

    def analyze_file(self, file_path: Path):
        """Analyze a single Python file for imports."""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                tree = ast.parse(f.read(), filename=str(file_path))

            module_name = self.get_module_name(file_path)
            self.file_to_module[file_path] = module_name
            self.module_to_files[module_name].append(file_path)

            analyzer = ImportAnalyzer(module_name)
            analyzer.visit(tree)

            # Filter to only include project modules
            project_imports = {
                imp for imp in analyzer.imports
                if imp in ['HYPERRSI', 'GRID', 'shared']
            }

            self.module_imports[module_name].update(project_imports)

        except Exception as e:
            print(f"Error analyzing {file_path}: {e}", file=sys.stderr)

    def find_python_files(self) -> List[Path]:
        """Find all Python files in the project."""
        python_files = []

        # Analyze HYPERRSI, GRID, and shared directories
        for subdir in ['HYPERRSI', 'GRID', 'shared']:
            subdir_path = self.project_root / subdir
            if subdir_path.exists():
                for py_file in subdir_path.rglob('*.py'):
                    # Skip test files and migrations
                    if 'test' not in str(py_file) and 'migration' not in str(py_file):
                        python_files.append(py_file)

        return python_files

    def detect_cycles_dfs(self) -> List[List[str]]:
        """Detect cycles using depth-first search."""
        cycles = []
        visited = set()
        rec_stack = set()
        path = []

        def dfs(module: str) -> bool:
            """DFS helper to detect cycles."""
            visited.add(module)
            rec_stack.add(module)
            path.append(module)

            for neighbor in self.module_imports.get(module, set()):
                if neighbor not in visited:
                    if dfs(neighbor):
                        return True
                elif neighbor in rec_stack:
                    # Found a cycle
                    cycle_start = path.index(neighbor)
                    cycle = path[cycle_start:] + [neighbor]
                    cycles.append(cycle)
                    return True

            path.pop()
            rec_stack.remove(module)
            return False

        # Check all modules
        for module in self.module_imports.keys():
            if module not in visited:
                dfs(module)

        return cycles

    def analyze_project(self) -> Dict:
        """Analyze entire project for circular dependencies."""
        print("🔍 Analyzing project for circular dependencies...")

        # Find and analyze all Python files
        python_files = self.find_python_files()
        print(f"📂 Found {len(python_files)} Python files")

        for i, file_path in enumerate(python_files, 1):
            if i % 100 == 0:
                print(f"   Processed {i}/{len(python_files)} files...")
            self.analyze_file(file_path)

        print(f"✅ Analyzed {len(self.module_imports)} modules")

        # Detect cycles
        print("\n🔄 Detecting circular dependencies...")
        cycles = self.detect_cycles_dfs()

        # Build dependency graph statistics
        total_imports = sum(len(imports) for imports in self.module_imports.values())

        results = {
            'total_modules': len(self.module_imports),
            'total_imports': total_imports,
            'cycles': cycles,
            'cycle_count': len(cycles),
            'module_imports': dict(self.module_imports),
        }

        return results

    def print_report(self, results: Dict):
        """Print analysis report."""
        print("\n" + "="*80)
        print("CIRCULAR DEPENDENCY ANALYSIS REPORT")
        print("="*80)

        print(f"\n📊 Statistics:")
        print(f"   Total modules analyzed: {results['total_modules']}")
        print(f"   Total import relationships: {results['total_imports']}")
        print(f"   Circular dependencies found: {results['cycle_count']}")

        if results['cycles']:
            print(f"\n❌ CIRCULAR DEPENDENCIES DETECTED:")
            for i, cycle in enumerate(results['cycles'], 1):
                print(f"\n   Cycle {i}:")
                for j, module in enumerate(cycle):
                    if j < len(cycle) - 1:
                        print(f"      {module}")
                        print(f"         ↓ imports")
                    else:
                        print(f"      {module} (back to start)")
        else:
            print(f"\n✅ No circular dependencies detected!")

        # Top-level package analysis
        print(f"\n📦 Top-Level Package Dependencies:")
        package_deps = defaultdict(set)
        for module, imports in results['module_imports'].items():
            top_package = module.split('.')[0]
            package_deps[top_package].update(imports)

        for package in ['HYPERRSI', 'GRID', 'shared']:
            if package in package_deps:
                deps = package_deps[package] - {package}
                if deps:
                    print(f"   {package} → {', '.join(sorted(deps))}")
                else:
                    print(f"   {package} → (no external dependencies)")

        print("\n" + "="*80)

def main():
    """Main entry point."""
    project_root = Path(__file__).parent

    detector = CircularDependencyDetector(project_root)
    results = detector.analyze_project()
    detector.print_report(results)

    # Exit with error code if cycles found
    if results['cycle_count'] > 0:
        sys.exit(1)
    else:
        sys.exit(0)

if __name__ == '__main__':
    main()

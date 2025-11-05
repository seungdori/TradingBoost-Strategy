#!/usr/bin/env python3
"""
Comprehensive Python Error Checker
Scans all Python files for:
- Syntax errors (AST parsing)
- Import errors
- Indentation issues
- Common Python mistakes
"""

import ast
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple
import re

class PythonErrorChecker:
    def __init__(self, root_dir: str):
        self.root_dir = Path(root_dir)
        self.errors = []
        self.warnings = []
        self.files_checked = 0

    def check_all_files(self):
        """Check all Python files in the project"""
        print(f"🔍 Scanning Python files in: {self.root_dir}")
        print("=" * 80)

        # Find all Python files
        python_files = list(self.root_dir.rglob("*.py"))

        # Exclude virtual environments and cache
        python_files = [
            f for f in python_files
            if not any(part.startswith('.') or part in ['venv', 'env', '__pycache__', 'node_modules']
                      for part in f.parts)
        ]

        print(f"📁 Found {len(python_files)} Python files to check\n")

        for file_path in sorted(python_files):
            self.check_file(file_path)

        self.print_summary()

    def check_file(self, file_path: Path):
        """Check a single Python file for errors"""
        self.files_checked += 1
        relative_path = file_path.relative_to(self.root_dir)

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # Check 1: AST Parsing (syntax errors)
            try:
                ast.parse(content)
            except SyntaxError as e:
                self.errors.append({
                    'file': str(relative_path),
                    'line': e.lineno,
                    'type': 'SYNTAX ERROR',
                    'message': str(e.msg),
                    'text': e.text.strip() if e.text else ''
                })
                return  # Skip other checks if syntax error

            # Check 2: Indentation consistency
            self.check_indentation(content, relative_path)

            # Check 3: Import statement issues
            self.check_imports(content, relative_path, file_path)

            # Check 4: Common issues
            self.check_common_issues(content, relative_path)

        except Exception as e:
            self.errors.append({
                'file': str(relative_path),
                'line': 0,
                'type': 'FILE READ ERROR',
                'message': str(e),
                'text': ''
            })

    def check_indentation(self, content: str, relative_path: Path):
        """Check for indentation inconsistencies"""
        lines = content.split('\n')
        has_tabs = False
        has_spaces = False

        for i, line in enumerate(lines, 1):
            if not line.strip():
                continue

            # Check for mixed tabs and spaces
            leading = line[:len(line) - len(line.lstrip())]
            if '\t' in leading:
                has_tabs = True
            if ' ' in leading:
                has_spaces = True

            if has_tabs and has_spaces:
                self.warnings.append({
                    'file': str(relative_path),
                    'line': i,
                    'type': 'MIXED INDENTATION',
                    'message': 'File contains both tabs and spaces',
                    'text': line[:40]
                })
                break

    def check_imports(self, content: str, relative_path: Path, file_path: Path):
        """Check import statements for issues"""
        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Check for relative imports that might be problematic
            if stripped.startswith('from .') or stripped.startswith('from ..'):
                # Check if it's in a package with __init__.py
                package_dir = file_path.parent
                if not (package_dir / '__init__.py').exists():
                    self.warnings.append({
                        'file': str(relative_path),
                        'line': i,
                        'type': 'RELATIVE IMPORT WARNING',
                        'message': 'Relative import in directory without __init__.py',
                        'text': stripped
                    })

            # Check for imports without proper prefix (common in monorepo)
            if 'from strategy import' in stripped or 'from database import' in stripped:
                if 'GRID' in str(relative_path):
                    self.warnings.append({
                        'file': str(relative_path),
                        'line': i,
                        'type': 'IMPORT PATTERN WARNING',
                        'message': 'Missing GRID prefix in import (should be: from GRID.strategy import ...)',
                        'text': stripped
                    })

            # Check for circular import patterns
            if 'import' in stripped and not stripped.startswith('#'):
                # Check if importing from same package
                if 'GRID' in str(relative_path) and 'from GRID.' in stripped:
                    module_parts = str(relative_path).split('/')
                    if len(module_parts) > 1:
                        current_module = module_parts[1]
                        if f'from GRID.{current_module}' in stripped and 'import' in stripped:
                            # Potential circular import
                            pass  # Could add more sophisticated detection

    def check_common_issues(self, content: str, relative_path: Path):
        """Check for common Python issues"""
        lines = content.split('\n')

        for i, line in enumerate(lines, 1):
            stripped = line.strip()

            # Check for bare except
            if stripped == 'except:':
                self.warnings.append({
                    'file': str(relative_path),
                    'line': i,
                    'type': 'BARE EXCEPT',
                    'message': 'Bare except clause - should specify exception type',
                    'text': stripped
                })

            # Check for print statements (should use logger in production)
            if stripped.startswith('print(') and 'logger' not in content[:content.find(stripped)]:
                # Only warn in non-test files
                if 'test' not in str(relative_path).lower():
                    pass  # Too many false positives

            # Check for mutable default arguments
            if 'def ' in stripped and '=[' in stripped or '={}' in stripped:
                self.warnings.append({
                    'file': str(relative_path),
                    'line': i,
                    'type': 'MUTABLE DEFAULT ARG',
                    'message': 'Mutable default argument - may cause bugs',
                    'text': stripped
                })

    def print_summary(self):
        """Print summary of all errors and warnings"""
        print("\n" + "=" * 80)
        print("📊 ANALYSIS SUMMARY")
        print("=" * 80)
        print(f"Files checked: {self.files_checked}")
        print(f"Errors found: {len(self.errors)}")
        print(f"Warnings found: {len(self.warnings)}")

        if self.errors:
            print("\n" + "🚨 ERRORS (MUST FIX):")
            print("-" * 80)
            for error in self.errors:
                print(f"\n❌ {error['file']}:{error['line']}")
                print(f"   Type: {error['type']}")
                print(f"   Message: {error['message']}")
                if error['text']:
                    print(f"   Code: {error['text'][:100]}")

        if self.warnings:
            print("\n" + "⚠️  WARNINGS (SHOULD REVIEW):")
            print("-" * 80)

            # Group warnings by type
            warnings_by_type = {}
            for warning in self.warnings:
                warn_type = warning['type']
                if warn_type not in warnings_by_type:
                    warnings_by_type[warn_type] = []
                warnings_by_type[warn_type].append(warning)

            for warn_type, warns in warnings_by_type.items():
                print(f"\n⚠️  {warn_type} ({len(warns)} occurrences):")
                for warning in warns[:10]:  # Show first 10
                    print(f"   - {warning['file']}:{warning['line']}")
                    print(f"     {warning['message']}")
                    if warning['text']:
                        print(f"     Code: {warning['text'][:80]}")
                if len(warns) > 10:
                    print(f"   ... and {len(warns) - 10} more")

        if not self.errors and not self.warnings:
            print("\n✅ No errors or warnings found!")

        print("\n" + "=" * 80)

        # Return exit code
        return 1 if self.errors else 0

def main():
    """Main entry point"""
    root_dir = Path(__file__).parent
    checker = PythonErrorChecker(root_dir)
    exit_code = checker.check_all_files()
    sys.exit(exit_code)

if __name__ == "__main__":
    main()

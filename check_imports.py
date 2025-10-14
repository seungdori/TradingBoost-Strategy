#!/usr/bin/env python3
"""
Import 오류 체크 스크립트
모든 Python 파일의 import 문을 검사하고 문제가 있는 파일을 찾습니다.
"""
import sys
from pathlib import Path
import ast
import traceback

# PYTHONPATH 설정
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

class ImportChecker(ast.NodeVisitor):
    """AST를 사용하여 import 문을 추출하는 클래스"""

    def __init__(self):
        self.imports = []
        self.from_imports = []

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module if node.module else ''
        for alias in node.names:
            self.from_imports.append((module, alias.name))
        self.generic_visit(node)

def check_file_imports(file_path: Path):
    """파일의 import를 체크"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            tree = ast.parse(f.read(), filename=str(file_path))

        checker = ImportChecker()
        checker.visit(tree)

        return {
            'file': str(file_path),
            'imports': checker.imports,
            'from_imports': checker.from_imports,
            'error': None
        }
    except SyntaxError as e:
        return {
            'file': str(file_path),
            'imports': [],
            'from_imports': [],
            'error': f'SyntaxError: {e}'
        }
    except Exception as e:
        return {
            'file': str(file_path),
            'imports': [],
            'from_imports': [],
            'error': f'{type(e).__name__}: {e}'
        }

def test_import(module_path: str, name: str = None):
    """실제로 import가 가능한지 테스트"""
    try:
        if name:
            exec(f"from {module_path} import {name}")
        else:
            exec(f"import {module_path}")
        return True, None
    except Exception as e:
        return False, str(e)

def main():
    print("=" * 80)
    print("HYPERRSI Import 검사 시작")
    print("=" * 80)

    hyperrsi_dir = project_root / "HYPERRSI"

    # 모든 Python 파일 찾기
    python_files = list(hyperrsi_dir.rglob("*.py"))
    print(f"\n총 {len(python_files)}개 파일 검사 중...\n")

    syntax_errors = []
    import_errors = []
    suspicious_imports = []

    for py_file in python_files:
        # __pycache__ 등 무시
        if '__pycache__' in str(py_file) or '.pyc' in str(py_file):
            continue

        result = check_file_imports(py_file)

        # 구문 오류
        if result['error'] and 'SyntaxError' in result['error']:
            syntax_errors.append(result)
            continue

        # import 패턴 검사
        for module in result['imports']:
            # HYPERRSI로 시작하는 import
            if module.startswith('HYPERRSI'):
                success, error = test_import(module)
                if not success:
                    import_errors.append({
                        'file': result['file'],
                        'import': f"import {module}",
                        'error': error
                    })

        for module, name in result['from_imports']:
            # 의심스러운 상대 import 패턴
            if module.startswith('.') or module.startswith('src.'):
                suspicious_imports.append({
                    'file': result['file'],
                    'import': f"from {module} import {name}",
                    'reason': '상대 import 또는 src. 접두사 사용'
                })

            # HYPERRSI로 시작하는 import 테스트
            if module.startswith('HYPERRSI'):
                success, error = test_import(module, name)
                if not success:
                    import_errors.append({
                        'file': result['file'],
                        'import': f"from {module} import {name}",
                        'error': error
                    })

    # 결과 출력
    print("\n" + "=" * 80)
    print("검사 결과")
    print("=" * 80)

    if syntax_errors:
        print(f"\n❌ 구문 오류 ({len(syntax_errors)}개):")
        for error in syntax_errors:
            print(f"\n  파일: {error['file']}")
            print(f"  오류: {error['error']}")

    if import_errors:
        print(f"\n❌ Import 오류 ({len(import_errors)}개):")
        for error in import_errors:
            rel_path = Path(error['file']).relative_to(project_root)
            print(f"\n  파일: {rel_path}")
            print(f"  Import: {error['import']}")
            print(f"  오류: {error['error']}")

    if suspicious_imports:
        print(f"\n⚠️  의심스러운 Import 패턴 ({len(suspicious_imports)}개):")
        for item in suspicious_imports:
            rel_path = Path(item['file']).relative_to(project_root)
            print(f"\n  파일: {rel_path}")
            print(f"  Import: {item['import']}")
            print(f"  이유: {item['reason']}")

    if not syntax_errors and not import_errors and not suspicious_imports:
        print("\n✅ 모든 파일이 정상입니다!")

    print("\n" + "=" * 80)
    print(f"검사 완료: {len(python_files)}개 파일")
    print(f"구문 오류: {len(syntax_errors)}개")
    print(f"Import 오류: {len(import_errors)}개")
    print(f"의심스러운 패턴: {len(suspicious_imports)}개")
    print("=" * 80)

if __name__ == "__main__":
    main()

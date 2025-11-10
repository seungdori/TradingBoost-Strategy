#!/usr/bin/env python3
"""
전체 프로젝트 Import 오류 체크 스크립트
모든 디렉토리의 Python 파일 import 문을 검사합니다.
"""
import sys
from pathlib import Path
import ast
import importlib
import importlib.util
from collections import defaultdict
from typing import Dict, List, Tuple, Set

# PYTHONPATH 설정
project_root = Path(__file__).parent.resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))


class ImportChecker(ast.NodeVisitor):
    """AST를 사용하여 import 문을 추출하는 클래스"""

    def __init__(self):
        self.imports: List[str] = []
        self.from_imports: List[Tuple[str, str]] = []

    def visit_Import(self, node):
        for alias in node.names:
            self.imports.append(alias.name)
        self.generic_visit(node)

    def visit_ImportFrom(self, node):
        module = node.module if node.module else ''
        for alias in node.names:
            self.from_imports.append((module, alias.name))
        self.generic_visit(node)


def check_file_imports(file_path: Path) -> Dict:
    """파일의 import를 체크"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
            tree = ast.parse(content, filename=str(file_path))

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


def is_third_party_module(module_name: str) -> bool:
    """서드파티 모듈인지 확인"""
    if not module_name:
        return False
    
    # 표준 라이브러리나 서드파티 모듈 (프로젝트 내부 모듈이 아닌 것들)
    first_part = module_name.split('.')[0]
    
    # 프로젝트 내부 모듈
    project_modules = {'HYPERRSI', 'GRID', 'BACKTEST', 'shared'}
    if first_part in project_modules:
        return False
    
    # 표준 라이브러리 (일부만 체크)
    stdlib_modules = {
        'sys', 'os', 'pathlib', 'typing', 'collections', 'functools',
        'asyncio', 'json', 'datetime', 'time', 'logging', 'traceback',
        'ast', 'importlib', 'abc', 'dataclasses', 'enum', 'threading',
        'multiprocessing', 'queue', 'hashlib', 'base64', 'urllib',
        'http', 'socket', 'ssl', 'sqlite3', 'pickle', 'copy', 'itertools'
    }
    if first_part in stdlib_modules:
        return True
    
    # 나머지는 서드파티로 간주 (실제 import는 시도하지 않음)
    return True


def test_import(module_path: str, name: str = None) -> Tuple[bool, str]:
    """실제로 import가 가능한지 테스트"""
    # 서드파티 모듈은 실제 import 시도하지 않음 (환경에 따라 다를 수 있음)
    if is_third_party_module(module_path):
        return True, None
    
    try:
        # 프로젝트 내부 모듈만 실제로 import 시도
        if name:
            # from module import name
            module = importlib.import_module(module_path)
            if not hasattr(module, name):
                return False, f"Module '{module_path}' has no attribute '{name}'"
        else:
            # import module
            importlib.import_module(module_path)
        return True, None
    except ModuleNotFoundError as e:
        return False, str(e)
    except ImportError as e:
        return False, str(e)
    except AttributeError as e:
        return False, str(e)
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)}"


def check_directory(directory: Path, dir_name: str) -> Dict:
    """특정 디렉토리의 모든 Python 파일을 체크"""
    print(f"\n{'='*80}")
    print(f"📁 {dir_name} 디렉토리 검사 중...")
    print(f"{'='*80}")
    
    # 모든 Python 파일 찾기
    python_files = [
        f for f in directory.rglob("*.py")
        if '__pycache__' not in str(f) and '.pyc' not in str(f)
    ]
    
    print(f"총 {len(python_files)}개 파일 발견\n")
    
    syntax_errors: List[Dict] = []
    import_errors: List[Dict] = []
    suspicious_imports: List[Dict] = []
    
    for py_file in python_files:
        result = check_file_imports(py_file)
        
        # 구문 오류
        if result['error'] and 'SyntaxError' in result['error']:
            syntax_errors.append(result)
            continue
        
        # import 패턴 검사
        for module in result['imports']:
            # 프로젝트 내부 모듈만 체크
            if any(module.startswith(prefix) for prefix in ['HYPERRSI', 'GRID', 'BACKTEST', 'shared']):
                success, error = test_import(module)
                if not success:
                    import_errors.append({
                        'file': result['file'],
                        'import': f"import {module}",
                        'error': error
                    })
        
        for module, name in result['from_imports']:
            # 의심스러운 상대 import 패턴
            if module and (module.startswith('.') or module.startswith('src.')):
                suspicious_imports.append({
                    'file': result['file'],
                    'import': f"from {module} import {name}",
                    'reason': '상대 import 또는 src. 접두사 사용 (absolute import 권장)'
                })
            
            # 프로젝트 내부 모듈 import 테스트
            if module and any(module.startswith(prefix) for prefix in ['HYPERRSI', 'GRID', 'BACKTEST', 'shared']):
                success, error = test_import(module, name)
                if not success:
                    import_errors.append({
                        'file': result['file'],
                        'import': f"from {module} import {name}",
                        'error': error
                    })
    
    return {
        'directory': dir_name,
        'file_count': len(python_files),
        'syntax_errors': syntax_errors,
        'import_errors': import_errors,
        'suspicious_imports': suspicious_imports
    }


def print_results(results: Dict):
    """결과 출력"""
    dir_name = results['directory']
    file_count = results['file_count']
    syntax_errors = results['syntax_errors']
    import_errors = results['import_errors']
    suspicious_imports = results['suspicious_imports']
    
    print(f"\n{'='*80}")
    print(f"📊 {dir_name} 검사 결과")
    print(f"{'='*80}")
    
    if syntax_errors:
        print(f"\n❌ 구문 오류 ({len(syntax_errors)}개):")
        for error in syntax_errors[:10]:  # 최대 10개만 표시
            rel_path = Path(error['file']).relative_to(project_root)
            print(f"  • {rel_path}")
            print(f"    {error['error']}")
        if len(syntax_errors) > 10:
            print(f"  ... 외 {len(syntax_errors) - 10}개 더")
    
    if import_errors:
        print(f"\n❌ Import 오류 ({len(import_errors)}개):")
        for error in import_errors[:10]:  # 최대 10개만 표시
            rel_path = Path(error['file']).relative_to(project_root)
            print(f"  • {rel_path}")
            print(f"    {error['import']}")
            print(f"    오류: {error['error']}")
        if len(import_errors) > 10:
            print(f"  ... 외 {len(import_errors) - 10}개 더")
    
    if suspicious_imports:
        print(f"\n⚠️  의심스러운 Import 패턴 ({len(suspicious_imports)}개):")
        for item in suspicious_imports[:10]:  # 최대 10개만 표시
            rel_path = Path(item['file']).relative_to(project_root)
            print(f"  • {rel_path}")
            print(f"    {item['import']}")
            print(f"    이유: {item['reason']}")
        if len(suspicious_imports) > 10:
            print(f"  ... 외 {len(suspicious_imports) - 10}개 더")
    
    if not syntax_errors and not import_errors and not suspicious_imports:
        print(f"\n✅ {dir_name} 디렉토리의 모든 파일이 정상입니다!")
    
    print(f"\n📈 요약:")
    print(f"  • 검사 파일 수: {file_count}개")
    print(f"  • 구문 오류: {len(syntax_errors)}개")
    print(f"  • Import 오류: {len(import_errors)}개")
    print(f"  • 의심스러운 패턴: {len(suspicious_imports)}개")


def main():
    """메인 함수"""
    print("=" * 80)
    print("🔍 전체 프로젝트 Import 오류 검사 시작")
    print("=" * 80)
    
    # 검사할 디렉토리 목록
    directories_to_check = [
        (project_root / "HYPERRSI", "HYPERRSI"),
        (project_root / "GRID", "GRID"),
        (project_root / "BACKTEST", "BACKTEST"),
        (project_root / "shared", "shared"),
        (project_root / "position-order-service", "position-order-service"),
        (project_root / "scripts", "scripts"),
    ]
    
    all_results = []
    total_stats = {
        'files': 0,
        'syntax_errors': 0,
        'import_errors': 0,
        'suspicious_imports': 0
    }
    
    for directory, dir_name in directories_to_check:
        if not directory.exists():
            print(f"\n⚠️  {dir_name} 디렉토리가 존재하지 않습니다. 건너뜁니다.")
            continue
        
        result = check_directory(directory, dir_name)
        all_results.append(result)
        
        total_stats['files'] += result['file_count']
        total_stats['syntax_errors'] += len(result['syntax_errors'])
        total_stats['import_errors'] += len(result['import_errors'])
        total_stats['suspicious_imports'] += len(result['suspicious_imports'])
        
        print_results(result)
    
    # 전체 요약
    print("\n" + "=" * 80)
    print("📊 전체 프로젝트 검사 요약")
    print("=" * 80)
    print(f"  • 총 검사 파일 수: {total_stats['files']}개")
    print(f"  • 총 구문 오류: {total_stats['syntax_errors']}개")
    print(f"  • 총 Import 오류: {total_stats['import_errors']}개")
    print(f"  • 총 의심스러운 패턴: {total_stats['suspicious_imports']}개")
    
    if total_stats['syntax_errors'] == 0 and total_stats['import_errors'] == 0 and total_stats['suspicious_imports'] == 0:
        print("\n✅ 모든 디렉토리의 파일이 정상입니다!")
    else:
        print("\n⚠️  일부 오류가 발견되었습니다. 위의 상세 결과를 확인하세요.")
    
    print("=" * 80)


if __name__ == "__main__":
    main()


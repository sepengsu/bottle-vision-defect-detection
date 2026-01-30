#!/usr/bin/env python
"""
Vision System CLI
사용법:
    python cli.py web        - 웹 애플리케이션 실행
    python cli.py re         - Imagecollect-re.py 실행 (GUI)
    python cli.py re-safe    - Imagecollect-re-safe.py 실행 (GUI, 안전 모드)
    python cli.py pyside6    - Imagecollect-pyside6.py 실행 (PySide6 통합 UI)
"""
import sys
import os
import subprocess
import argparse
from pathlib import Path

# 현재 파일의 디렉토리
BASE_DIR = Path(__file__).parent.resolve()


def run_web():
    """웹 애플리케이션 실행"""
    print("🌐 웹 애플리케이션 시작 중...")
    print("📡 서버 주소: http://localhost:8000")
    print("📖 API 문서: http://localhost:8000/docs")
    print("🛑 종료하려면 Ctrl+C를 누르세요.\n")
    
    web_main_path = BASE_DIR / "web" / "main.py"
    if not web_main_path.exists():
        print(f"❌ 오류: {web_main_path} 파일을 찾을 수 없습니다.")
        sys.exit(1)
    
    # 프로젝트 루트를 Python 경로에 추가
    project_root = BASE_DIR.parent.parent.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    
    # uvicorn으로 실행 (모듈 경로 사용)
    try:
        import uvicorn
        uvicorn.run(
            "src.data_get.web.main:app",
            host="0.0.0.0",
            port=8000,
            reload=True,
            reload_dirs=[str(BASE_DIR / "web")],
            log_level="info"
        )
    except KeyboardInterrupt:
        print("\n🛑 웹 애플리케이션 종료됨")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def run_re():
    """Imagecollect-re.py 실행"""
    print("🖥️  GUI 애플리케이션 시작 중... (Imagecollect-re.py)")
    print("🛑 종료하려면 창을 닫거나 Ctrl+C를 누르세요.\n")
    
    script_path = BASE_DIR / "Imagecollect-re.py"
    if not script_path.exists():
        print(f"❌ 오류: {script_path} 파일을 찾을 수 없습니다.")
        sys.exit(1)
    
    os.chdir(BASE_DIR)
    try:
        # Python 스크립트를 직접 실행
        exec(open(script_path, encoding='utf-8').read())
    except KeyboardInterrupt:
        print("\n🛑 애플리케이션 종료됨")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def run_re_safe():
    """Imagecollect-re-safe.py 실행"""
    print("🖥️  GUI 애플리케이션 시작 중... (Imagecollect-re-safe.py - 안전 모드)")
    print("🛑 종료하려면 창을 닫거나 Ctrl+C를 누르세요.\n")
    
    script_path = BASE_DIR / "Imagecollect-re-safe.py"
    if not script_path.exists():
        print(f"❌ 오류: {script_path} 파일을 찾을 수 없습니다.")
        sys.exit(1)
    
    os.chdir(BASE_DIR)
    try:
        # Python 스크립트를 직접 실행
        exec(open(script_path, encoding='utf-8').read())
    except KeyboardInterrupt:
        print("\n🛑 애플리케이션 종료됨")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def run_pyside6():
    """Imagecollect-pyside6.py 실행"""
    print("🖥️  PySide6 통합 UI 애플리케이션 시작 중...")
    print("🛑 종료하려면 창을 닫거나 Ctrl+C를 누르세요.\n")
    
    script_path = BASE_DIR / "Imagecollect-pyside6.py"
    if not script_path.exists():
        print(f"❌ 오류: {script_path} 파일을 찾을 수 없습니다.")
        sys.exit(1)
    
    os.chdir(BASE_DIR)
    try:
        # Python 스크립트를 직접 실행
        exec(open(script_path, encoding='utf-8').read())
    except KeyboardInterrupt:
        print("\n🛑 애플리케이션 종료됨")
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Vision System CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=""" 
사용 예시:
  python cli.py web        웹 애플리케이션 실행
  python cli.py re         GUI 애플리케이션 실행 (Imagecollect-re.py)
  python cli.py re-safe    GUI 애플리케이션 실행 (안전 모드)
  python cli.py pyside6    PySide6 통합 UI 실행
        """
    )
    
    parser.add_argument(
        "mode",
        choices=["web", "re", "re-safe", "pyside6"],
        help="실행할 모드 선택"
    )
    
    args = parser.parse_args()
    
    # 모드에 따라 실행
    if args.mode == "web":
        run_web()
    elif args.mode == "re":
        run_re()
    elif args.mode == "re-safe":
        run_re_safe()
    elif args.mode == "pyside6":
        run_pyside6()


if __name__ == "__main__":
    main()

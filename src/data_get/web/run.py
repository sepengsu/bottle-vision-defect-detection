"""
Vision System Web Application 실행 스크립트
"""
import uvicorn
import os
import sys

# 프로젝트 루트를 Python 경로에 추가
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../.."))
sys.path.insert(0, project_root)

if __name__ == "__main__":
    # 현재 디렉토리를 작업 디렉토리로 설정
    os.chdir(os.path.dirname(__file__))
    
    print("🚀 Vision System Web Application 시작 중...")
    print("📡 서버 주소: http://localhost:8000")
    print("📖 API 문서: http://localhost:8000/docs")
    print("🛑 종료하려면 Ctrl+C를 누르세요.\n")
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

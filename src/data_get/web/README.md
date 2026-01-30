# Vision System Web Application

FastAPI 기반의 웹 애플리케이션으로 Vision System의 모든 기능을 웹 브라우저에서 사용할 수 있습니다.

## 기능

- ✅ 실시간 카메라 미리보기 (WebSocket 스트리밍)
- ✅ 조명 제어 (0-255 밝기 조절)
- ✅ 단일 이미지 캡처
- ✅ 자동 시퀀스 촬영 (정방향/역방향 지원)
- ✅ 카메라 저장 옵션 설정 (Cam 3 제외/전체/Cam 3만)
- ✅ 제품명, 검사 조건, 촬영 번호 관리
- ✅ 카메라 없을 때 검은 화면 표시 (안전 모드)

## 설치 및 실행

### 1. 의존성 설치

```bash
# 프로젝트 루트에서
uv sync
```

### 2. 웹 애플리케이션 실행

```bash
# 방법 1: run.py 사용
cd src/data_get/web
python run.py

# 방법 2: 직접 실행
cd src/data_get/web
python main.py

# 방법 3: uvicorn 직접 실행
cd src/data_get/web
uvicorn main:app --host 0.0.0.0 --port 8000 --reload

# 방법 4: CLI 사용 (권장)
data_get web
```

### 3. 브라우저에서 접속

- 메인 페이지: http://localhost:8000
- API 문서: http://localhost:8000/docs
- 대화형 API: http://localhost:8000/redoc

## API 엔드포인트

### 상태 조회
- `GET /api/status` - 시스템 상태 조회
- `GET /api/settings` - 현재 설정 조회

### 설정 관리
- `POST /api/settings` - 설정 업데이트
  ```json
  {
    "product": "ModelA",
    "condition": "Test_A",
    "shot_no": 1,
    "save_path": "./captured_images",
    "save_mode": 2
  }
  ```

### 조명 제어
- `POST /api/light` - 조명 밝기 설정
  ```json
  {
    "value": 100
  }
  ```

### 이미지 캡처
- `POST /api/capture` - 현재 설정으로 1회 촬영
- `POST /api/sequence` - 자동 시퀀스 촬영 시작
  ```json
  {
    "start": 30,
    "end": 120,
    "step": 10
  }
  ```

### 실시간 스트리밍
- `WebSocket /ws/preview` - 카메라 프리뷰 스트리밍

## 설정

기본 설정은 `main.py`의 상단에서 변경할 수 있습니다:

```python
TARGET_CAMS = [1, 2, 3, 4]  # 대상 카메라 ID
LIGHT_PORTS = ["COM2", "COM8", "COM9", "COM10"]  # 조명 포트
DEFAULT_SAVE_PATH = "./captured_images"  # 기본 저장 경로
```

## 주의사항

1. **카메라 없을 때**: 카메라가 연결되지 않아도 프로그램이 실행되며, 검은 화면이 표시됩니다.
2. **조명 포트**: 시스템에 맞게 COM 포트를 수정해야 할 수 있습니다.
3. **저장 경로**: 저장 경로는 상대 경로 또는 절대 경로를 사용할 수 있습니다.

## 문제 해결

### 카메라가 인식되지 않는 경우
- Basler 카메라 드라이버가 설치되어 있는지 확인
- 카메라가 USB/네트워크로 연결되어 있는지 확인
- 프로그램은 카메라 없이도 실행 가능 (검은 화면 표시)

### 조명이 작동하지 않는 경우
- COM 포트가 올바른지 확인
- 다른 프로그램이 COM 포트를 사용 중인지 확인
- 조명 컨트롤러가 올바르게 연결되어 있는지 확인

### 웹 페이지가 로드되지 않는 경우
- 포트 8000이 다른 프로그램에 의해 사용 중인지 확인
- 방화벽 설정 확인
- 브라우저 콘솔에서 오류 메시지 확인

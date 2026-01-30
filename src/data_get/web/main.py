from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, List
import cv2
import os
import numpy as np
from datetime import datetime
import threading
import time
import json
import base64
import asyncio
from pypylon import pylon
from pymodbus.client import ModbusSerialClient
import uvicorn

# =================== 설정 ===================
TARGET_CAMS = [1, 2, 3, 4]
PREVIEW_SCALE_WIDTH = 400
LIGHT_PORTS = ["COM2", "COM8", "COM9", "COM10"]
BAUDRATE = 9600
DEFAULT_SAVE_PATH = "./captured_images"
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "config.json")

# =================== 전역 변수 ===================
app = FastAPI(title="Vision System Web API")
latest_frames = {}
frame_lock = threading.Lock()
running = True
light_clients = {}
cameras = None
camera_map = {}
converter = None
cameras_available = False
active_websockets: List[WebSocket] = []

# 설정 상태
app_state = {
    "product": "ModelA",
    "condition": "Test_A",
    "shot_no": 1,
    "save_path": DEFAULT_SAVE_PATH,
    "save_mode": 2,  # 1: Cam 3 제외, 2: 전체, 3: Cam 3만
    "light_value": 100,
    "sequence_start": 30,
    "sequence_end": 120,
    "sequence_step": 10,
    "camera_width": 400,  # 카메라 미리보기 너비
    "camera_height": 300   # 카메라 미리보기 높이
}

# =================== 설정 저장/로드 ===================
def load_settings():
    """설정 파일에서 로드"""
    global app_state
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
                # 기존 설정과 병합 (기본값 유지)
                for key, value in loaded.items():
                    if key in app_state:
                        app_state[key] = value
                print(f"✅ 설정 파일 로드 완료: {SETTINGS_FILE}")
    except Exception as e:
        print(f"⚠️ 설정 파일 로드 실패: {e}")

def save_settings():
    """설정을 파일에 저장"""
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(app_state, f, indent=2, ensure_ascii=False)
        print(f"✅ 설정 파일 저장 완료: {SETTINGS_FILE}")
        return True
    except Exception as e:
        print(f"⚠️ 설정 파일 저장 실패: {e}")
        return False

# =================== 카메라 초기화 ===================
def init_cameras():
    global cameras, camera_map, converter, cameras_available
    try:
        tl_factory = pylon.TlFactory.GetInstance()
        devices = tl_factory.EnumerateDevices()
        if len(devices) == 0:
            print("⚠️ Basler 카메라가 발견되지 않았습니다. 검은 화면으로 표시됩니다.")
            cameras_available = False
            return
        
        cameras = pylon.InstantCameraArray(len(devices))
        camera_map = {}
        
        for i, cam in enumerate(cameras):
            cam.Attach(tl_factory.CreateDevice(devices[i]))
            cam.Open()
            cam.Width.SetValue(cam.Width.Max)
            cam.Height.SetValue(cam.Height.Max)
            camera_map[i + 1] = cam
        
        converter = pylon.ImageFormatConverter()
        converter.OutputPixelFormat = pylon.PixelType_BGR8packed
        converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned
        
        cameras.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)
        cameras_available = True
        print("✅ 카메라 초기화 완료")
    except Exception as e:
        print(f"⚠️ 카메라 초기화 실패: {e}. 검은 화면으로 표시됩니다.")
        cameras_available = False
        cameras = None
        camera_map = {}
        converter = None

# =================== 조명 초기화 ===================
def init_lights():
    global light_clients
    print("\n=== 조명 컨트롤러 연결 시작 ===")
    for port in LIGHT_PORTS:
        try:
            client = ModbusSerialClient(port=port, baudrate=BAUDRATE, parity='N', stopbits=1, bytesize=8, timeout=0.1)
            if client.connect():
                light_clients[port] = client
                print(f"✅ [{port}] 조명 연결 성공")
            else:
                print(f"❌ [{port}] 조명 연결 실패")
        except Exception as e:
            print(f"⚠️ [{port}] 오류: {e}")
    print("==============================\n")

# =================== 조명 제어 ===================
def send_light_packet(val):
    if val < 0:
        val = 0
    if val > 255:
        val = 255
    app_state["light_value"] = val
    val_bytes = f"{val:03d}".encode('ascii')
    packet = b'\x02' + b'A' + (val_bytes + b',') * 3 + val_bytes + b'\x03'
    for port, client in light_clients.items():
        if client and client.connected:
            try:
                client.socket.write(packet)
            except:
                pass

# =================== 카메라 프레임 가져오기 스레드 ===================
def camera_thread():
    global running, latest_frames
    while running:
        try:
            if cameras_available and cameras and camera_map:
                for idx, cam in camera_map.items():
                    if cam.IsGrabbing():
                        grabResult = cam.RetrieveResult(50, pylon.TimeoutHandling_Return)
                        if grabResult and grabResult.GrabSucceeded():
                            image = converter.Convert(grabResult)
                            with frame_lock:
                                latest_frames[idx] = image.GetArray()
                        if grabResult:
                            grabResult.Release()
            time.sleep(0.01)
        except Exception as e:
            print(f"Camera Thread Error: {e}")
            time.sleep(0.1)

# =================== 이미지 인코딩 ===================
def encode_frame(img):
    """OpenCV 이미지를 base64로 인코딩"""
    if img is None:
        return None
    _, buffer = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return base64.b64encode(buffer).decode('utf-8')

# =================== 프리뷰 이미지 생성 ===================
def get_preview_images():
    """모든 카메라의 프리뷰 이미지를 생성"""
    previews = {}
    current_mode = app_state["save_mode"]
    
    with frame_lock:
        for cam_id in sorted(TARGET_CAMS):
            if cam_id in latest_frames:
                raw_img = latest_frames[cam_id]
                h, w = raw_img.shape[:2]
                scale = PREVIEW_SCALE_WIDTH / w
                preview_img = cv2.resize(raw_img, (int(w * scale), int(h * scale)))
                
                will_save = True
                if current_mode == 1 and cam_id == 3:
                    will_save = False
                if current_mode == 3 and cam_id != 3:
                    will_save = False
                
                if will_save:
                    if cam_id == 3:
                        txt, color = "CAM 3 (ON)", (0, 255, 255)
                    else:
                        txt, color = f"CAM {cam_id} (ON)", (0, 255, 0)
                else:
                    txt, color = f"CAM {cam_id} (OFF)", (128, 128, 128)
                
                cv2.putText(preview_img, txt, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
                previews[cam_id] = encode_frame(preview_img)
            else:
                # 검은 화면 생성
                black_img = np.zeros((300, PREVIEW_SCALE_WIDTH, 3), dtype=np.uint8)
                if not cameras_available:
                    cv2.putText(black_img, f"CAM {cam_id} (No Camera)", (20, 150),
                              cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 100, 100), 2)
                else:
                    cv2.putText(black_img, f"CAM {cam_id} Off", (50, 150),
                              cv2.FONT_HERSHEY_SIMPLEX, 1, (100, 100, 100), 2)
                previews[cam_id] = encode_frame(black_img)
    
    return previews

# =================== 이미지 저장 ===================
def save_snapshot_internal(light_val):
    if not cameras_available:
        return {"success": False, "message": "카메라가 연결되지 않았습니다.", "saved_count": 0}
    
    base_path = app_state["save_path"]
    product = app_state["product"]
    cond1 = app_state["condition"]
    cond2 = f"Light_{light_val:03d}"
    shot_no = app_state["shot_no"]
    mode = app_state["save_mode"]
    
    if not product or not cond1:
        return {"success": False, "message": "제품명과 검사 조건을 입력해주세요.", "saved_count": 0}
    
    path_std = os.path.join(base_path, product, cond1, cond2)
    path_cam3 = os.path.join(base_path, "cam3", product, cond1, cond2)
    
    if mode in [1, 2]:
        os.makedirs(path_std, exist_ok=True)
    if mode in [2, 3]:
        os.makedirs(path_cam3, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    images_to_save = {}
    with frame_lock:
        for cam_id in TARGET_CAMS:
            if cam_id in latest_frames:
                images_to_save[cam_id] = latest_frames[cam_id].copy()
    
    saved_count = 0
    saved_files = []
    for cam_id, img in images_to_save.items():
        if mode == 1 and cam_id == 3:
            continue
        elif mode == 3 and cam_id != 3:
            continue
        
        filename = f"{product}_{cond1}_{cond2}_{shot_no:03d}_Cam{cam_id}_{timestamp}.png"
        filepath = os.path.join(path_cam3 if cam_id == 3 else path_std, filename)
        
        try:
            cv2.imwrite(filepath, img)
            print(f"saved: {filepath}")
            saved_count += 1
            saved_files.append(filepath)
        except Exception as e:
            print(f"Save error for cam {cam_id}: {e}")
    
    return {"success": True, "saved_count": saved_count, "files": saved_files}

# =================== Pydantic 모델 ===================
class LightRequest(BaseModel):
    value: int

class SettingsRequest(BaseModel):
    product: Optional[str] = None
    condition: Optional[str] = None
    shot_no: Optional[int] = None
    save_path: Optional[str] = None
    save_mode: Optional[int] = None
    sequence_start: Optional[int] = None
    sequence_end: Optional[int] = None
    sequence_step: Optional[int] = None
    camera_width: Optional[int] = None
    camera_height: Optional[int] = None

class SequenceRequest(BaseModel):
    start: int
    end: int
    step: int

# =================== 정적 파일 서빙 ===================
# 정적 파일 디렉토리 경로 (절대 경로 사용)
static_dir = os.path.join(os.path.dirname(__file__), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# =================== API 엔드포인트 ===================

@app.get("/", response_class=HTMLResponse)
async def read_root():
    """메인 페이지"""
    html_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if not os.path.exists(html_path):
        return HTMLResponse(
            content=f"<h1>오류</h1><p>HTML 파일을 찾을 수 없습니다: {html_path}</p>",
            status_code=500
        )
    try:
        with open(html_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except Exception as e:
        return HTMLResponse(
            content=f"<h1>오류</h1><p>HTML 파일을 읽는 중 오류 발생: {e}</p>",
            status_code=500
        )

@app.get("/api/status")
async def get_status():
    """시스템 상태 조회"""
    return {
        "cameras_available": cameras_available,
        "cameras_count": len(camera_map),
        "lights_connected": len(light_clients),
        "settings": app_state
    }

@app.get("/api/settings")
async def get_settings():
    """설정 조회"""
    return app_state

@app.post("/api/settings")
async def update_settings(settings: SettingsRequest):
    """설정 업데이트"""
    if settings.product is not None:
        app_state["product"] = settings.product
    if settings.condition is not None:
        app_state["condition"] = settings.condition
    if settings.shot_no is not None:
        app_state["shot_no"] = settings.shot_no
    if settings.save_path is not None:
        app_state["save_path"] = settings.save_path
    if settings.save_mode is not None:
        if settings.save_mode in [1, 2, 3]:
            app_state["save_mode"] = settings.save_mode
        else:
            raise HTTPException(status_code=400, detail="save_mode는 1, 2, 3 중 하나여야 합니다.")
    if settings.sequence_start is not None:
        app_state["sequence_start"] = settings.sequence_start
    if settings.sequence_end is not None:
        app_state["sequence_end"] = settings.sequence_end
    if settings.sequence_step is not None:
        app_state["sequence_step"] = settings.sequence_step
    if settings.camera_width is not None:
        app_state["camera_width"] = settings.camera_width
    if settings.camera_height is not None:
        app_state["camera_height"] = settings.camera_height
    save_settings()  # 자동 저장
    return {"success": True, "settings": app_state}

@app.post("/api/settings/save")
async def save_settings_api():
    """설정을 파일에 저장"""
    success = save_settings()
    return {"success": success}

@app.get("/api/settings/load")
async def load_settings_api():
    """설정 파일에서 로드"""
    load_settings()
    return {"success": True, "settings": app_state}

@app.post("/api/light")
async def set_light(light_req: LightRequest):
    """조명 밝기 설정"""
    if light_req.value < 0 or light_req.value > 255:
        raise HTTPException(status_code=400, detail="조명 값은 0-255 사이여야 합니다.")
    send_light_packet(light_req.value)
    save_settings()  # 자동 저장
    return {"success": True, "light_value": app_state["light_value"]}

@app.post("/api/capture")
async def capture_image():
    """현재 설정으로 1회 촬영"""
    current_light = app_state["light_value"]
    result = save_snapshot_internal(current_light)
    if result["success"] and result["saved_count"] > 0:
        app_state["shot_no"] += 1
    return result

@app.post("/api/sequence")
async def start_sequence(seq_req: SequenceRequest):
    """자동 시퀀스 촬영 시작"""
    start_val = seq_req.start
    end_val = seq_req.end
    step_val = seq_req.step
    
    # 설정에 저장
    app_state["sequence_start"] = start_val
    app_state["sequence_end"] = end_val
    app_state["sequence_step"] = step_val
    save_settings()  # 자동 저장
    
    # 유효성 검사
    if step_val == 0:
        raise HTTPException(status_code=400, detail="스텝(Step)은 0이 될 수 없습니다.")
    if step_val > 0 and start_val > end_val:
        raise HTTPException(status_code=400, detail="스텝이 양수일 때는 [Start <= End]여야 합니다.")
    if step_val < 0 and start_val < end_val:
        raise HTTPException(status_code=400, detail="스텝이 음수일 때는 [Start >= End]여야 합니다.")
    
    # 백그라운드에서 시퀀스 실행
    def run_sequence():
        offset = 1 if step_val > 0 else -1
        for val in range(start_val, end_val + offset, step_val):
            send_light_packet(val)
            print(f"--- 조명 변경: {val} ---")
            time.sleep(0.5)
            save_snapshot_internal(val)
            time.sleep(0.2)
        app_state["shot_no"] += 1
    
    threading.Thread(target=run_sequence, daemon=True).start()
    return {"success": True, "message": "시퀀스 촬영이 시작되었습니다."}

@app.websocket("/ws/preview")
async def websocket_preview(websocket: WebSocket):
    """WebSocket을 통한 실시간 프리뷰 스트리밍"""
    await websocket.accept()
    active_websockets.append(websocket)
    
    try:
        while True:
            previews = get_preview_images()
            await websocket.send_json({
                "type": "preview",
                "cameras": previews,
                "timestamp": datetime.now().isoformat()
            })
            await asyncio.sleep(0.033)  # 약 30 FPS
    except WebSocketDisconnect:
        active_websockets.remove(websocket)
    except Exception as e:
        print(f"WebSocket error: {e}")
        if websocket in active_websockets:
            active_websockets.remove(websocket)

# =================== 시작 시 초기화 ===================
@app.on_event("startup")
async def startup_event():
    try:
        load_settings()  # 설정 파일 로드
        init_cameras()
        init_lights()
        send_light_packet(app_state["light_value"])
        threading.Thread(target=camera_thread, daemon=True).start()
        print("🚀 Vision System Web API 시작됨")
    except Exception as e:
        print(f"⚠️ 초기화 중 오류 발생 (서버는 계속 실행됩니다): {e}")
        import traceback
        traceback.print_exc()

@app.on_event("shutdown")
async def shutdown_event():
    global running
    running = False
    if cameras_available and cameras:
        for cam in cameras:
            if cam.IsGrabbing():
                cam.StopGrabbing()
            cam.Close()
    for client in light_clients.values():
        client.close()
    print("🛑 Vision System Web API 종료됨")

if __name__ == "__main__":
    import asyncio
    uvicorn.run(app, host="0.0.0.0", port=8000)

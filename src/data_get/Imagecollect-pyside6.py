import cv2
import os
import numpy as np
from datetime import datetime
import threading
import time
import json
from pathlib import Path
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QRadioButton, QGroupBox,
    QFileDialog, QMessageBox, QScrollArea, QFrame
)
from PySide6.QtCore import Qt, QTimer, QThread, QSize, QPoint, Signal
from PySide6.QtGui import QImage, QPixmap, QMouseEvent
from pypylon import pylon
from pymodbus.client import ModbusSerialClient

# =================== 설정 ===================
TARGET_CAMS = [1, 2, 3, 4]
PREVIEW_SCALE_WIDTH = 400
LIGHT_PORTS = ["COM2", "COM8", "COM9", "COM10"]
BAUDRATE = 9600
DEFAULT_SAVE_PATH = "./captured_images"

# 설정 파일 경로 (web과 동일한 위치 사용)
SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "web", "config", "config.json")

# =================== 전역 변수 ===================
latest_frames = {}
frame_lock = threading.Lock()
running = True
light_clients = {}
cameras = None
camera_map = {}
converter = None
cameras_available = False

# 설정 상태 (web과 동일한 구조)
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
    "camera_width": 400,
    "camera_height": 300
}

# =================== 설정 저장/로드 ===================
def load_settings():
    """설정 파일에서 로드 (web과 동일한 방식)"""
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
                return True
    except Exception as e:
        print(f"⚠️ 설정 파일 로드 실패: {e}")
    return False

def save_settings():
    """설정을 파일에 저장 (web과 동일한 방식)"""
    try:
        # 디렉토리가 없으면 생성
        os.makedirs(os.path.dirname(SETTINGS_FILE), exist_ok=True)
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
            print("⚠️ Basler 카메라가 발견되지 않았습니다.")
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
        print(f"⚠️ 카메라 초기화 실패: {e}")
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

# =================== 이미지 저장 ===================
def save_snapshot_internal(light_val):
    if not cameras_available:
        return 0
    
    base_path = app_state["save_path"]
    product = app_state["product"]
    cond1 = app_state["condition"]
    cond2 = f"Light_{light_val:03d}"
    shot_no = app_state["shot_no"]
    mode = app_state["save_mode"]
    
    if not product or not cond1:
        return 0
    
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
        except:
            pass
    return saved_count

# =================== 카메라 스레드 ===================
class CameraThread(QThread):
    def run(self):
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

# =================== 크기 조절 가능한 카메라 위젯 ===================
class ResizableCameraWidget(QFrame):
    """마우스 드래그로 크기 조절 가능한 카메라 위젯"""
    size_changed = Signal(int, int)  # width, height
    
    def __init__(self, cam_id, parent=None):
        super().__init__(parent)
        self.cam_id = cam_id
        self.setFrameStyle(QFrame.Box)
        self.setStyleSheet("background-color: black; border: 2px solid gray;")
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        
        self.label = QLabel(f"CAM {cam_id}")
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setStyleSheet("background-color: black; color: white;")
        self.label.setScaledContents(False)
        layout.addWidget(self.label)
        
        # 초기 크기 설정
        initial_width = app_state.get("camera_width", PREVIEW_SCALE_WIDTH)
        initial_height = app_state.get("camera_height", 300)
        self.setMinimumSize(initial_width, initial_height)
        self.label.setMinimumSize(initial_width, initial_height)
        
        # 드래그 상태
        self.dragging = False
        self.drag_start_pos = None
        self.drag_start_size = None
        self.resize_handle_size = 15
        
    def mousePressEvent(self, event: QMouseEvent):
        """마우스 클릭 시 드래그 시작"""
        if event.button() == Qt.LeftButton:
            # 우하단 모서리에서 드래그 시작인지 확인
            rect = self.rect()
            corner_rect = rect.adjusted(
                rect.width() - self.resize_handle_size,
                rect.height() - self.resize_handle_size,
                0, 0
            )
            
            if corner_rect.contains(event.pos()):
                self.dragging = True
                self.drag_start_pos = event.globalPos()
                self.drag_start_size = self.size()
                self.setCursor(Qt.SizeFDiagCursor)
    
    def mouseMoveEvent(self, event: QMouseEvent):
        """마우스 이동 시 크기 조절"""
        if self.dragging:
            delta = event.globalPos() - self.drag_start_pos
            new_width = max(200, self.drag_start_size.width() + delta.x())
            new_height = max(150, self.drag_start_size.height() + delta.y())
            
            self.setMinimumSize(new_width, new_height)
            self.label.setMinimumSize(new_width, new_height)
            self.resize(new_width, new_height)
            
            # 모든 카메라에 크기 변경 신호 전송
            self.size_changed.emit(new_width, new_height)
        else:
            # 커서 변경 (우하단 모서리 확인)
            rect = self.rect()
            corner_rect = rect.adjusted(
                rect.width() - self.resize_handle_size,
                rect.height() - self.resize_handle_size,
                0, 0
            )
            if corner_rect.contains(event.pos()):
                self.setCursor(Qt.SizeFDiagCursor)
            else:
                self.setCursor(Qt.ArrowCursor)
    
    def mouseReleaseEvent(self, event: QMouseEvent):
        """마우스 릴리스 시 드래그 종료"""
        if event.button() == Qt.LeftButton:
            self.dragging = False
            self.setCursor(Qt.ArrowCursor)
    
    def set_camera_size(self, width, height):
        """외부에서 크기 설정 (동기화용) - 신호를 emit하지 않음"""
        # 드래그 중이 아닐 때만 크기 변경 (무한 루프 방지)
        if not self.dragging:
            self.setMinimumSize(width, height)
            self.label.setMinimumSize(width, height)
            self.resize(width, height)

# =================== 메인 윈도우 ===================
class VisionSystemWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        try:
            self.setWindowTitle("Vision System (PySide6 - Integrated UI)")
            self.setGeometry(100, 100, 1200, 900)
            
            # 설정 로드
            load_settings()
            
            # 중앙 위젯
            central_widget = QWidget()
            self.setCentralWidget(central_widget)
            
            # 메인 레이아웃
            main_layout = QHBoxLayout(central_widget)
            
            # 왼쪽: 컨트롤 패널
            control_panel = self.create_control_panel()
            main_layout.addWidget(control_panel, 1)
            
            # 오른쪽: 카메라 미리보기
            preview_panel = self.create_preview_panel()
            main_layout.addWidget(preview_panel, 2)
            
            # 저장된 카메라 크기로 모든 위젯 초기화
            saved_width = app_state.get("camera_width", PREVIEW_SCALE_WIDTH)
            saved_height = app_state.get("camera_height", 300)
            for widget in self.camera_widgets.values():
                widget.set_camera_size(saved_width, saved_height)
            
            # 카메라 스레드 시작
            self.camera_thread = CameraThread()
            self.camera_thread.start()
            
            # 프리뷰 업데이트 타이머
            self.preview_timer = QTimer()
            self.preview_timer.timeout.connect(self.update_previews)
            self.preview_timer.start(33)  # 약 30 FPS
            
            # 초기 조명 설정 적용
            try:
                send_light_packet(app_state["light_value"])
            except Exception as e:
                print(f"⚠️ 초기 조명 설정 실패: {e}")
        except Exception as e:
            print(f"❌ 윈도우 초기화 오류: {e}")
            import traceback
            traceback.print_exc()
            raise
        
    def create_control_panel(self):
        """왼쪽 컨트롤 패널 생성"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setSpacing(10)
        
        # 스크롤 영역
        scroll = QScrollArea()
        scroll.setWidget(panel)
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(400)
        
        # 기본 정보 그룹
        basic_group = QGroupBox("기본 설정")
        basic_layout = QVBoxLayout()
        
        basic_layout.addWidget(QLabel("제품명 (Product):"))
        self.product_edit = QLineEdit()
        self.product_edit.setText(app_state["product"])
        self.product_edit.textChanged.connect(self.update_product)
        basic_layout.addWidget(self.product_edit)
        
        basic_layout.addWidget(QLabel("검사 조건 (Condition 1):"))
        self.condition_edit = QLineEdit()
        self.condition_edit.setText(app_state["condition"])
        self.condition_edit.textChanged.connect(self.update_condition)
        basic_layout.addWidget(self.condition_edit)
        
        basic_layout.addWidget(QLabel("촬영 번호 (Shot No.):"))
        self.shot_no_spin = QSpinBox()
        self.shot_no_spin.setMinimum(1)
        self.shot_no_spin.setMaximum(9999)
        self.shot_no_spin.setValue(app_state["shot_no"])
        self.shot_no_spin.valueChanged.connect(self.update_shot_no)
        basic_layout.addWidget(self.shot_no_spin)
        
        basic_group.setLayout(basic_layout)
        layout.addWidget(basic_group)
        
        # 조명 제어 그룹
        light_group = QGroupBox("수동 조명 제어")
        light_layout = QVBoxLayout()
        
        light_layout.addWidget(QLabel("밝기 값:"))
        light_control_layout = QHBoxLayout()
        self.light_spin = QSpinBox()
        self.light_spin.setMinimum(0)
        self.light_spin.setMaximum(255)
        self.light_spin.setValue(app_state["light_value"])
        self.light_spin.valueChanged.connect(self.update_light_value)
        light_control_layout.addWidget(self.light_spin)
        
        self.light_btn = QPushButton("💡 조명 값 적용")
        self.light_btn.clicked.connect(self.apply_light)
        light_control_layout.addWidget(self.light_btn)
        light_layout.addLayout(light_control_layout)
        
        light_group.setLayout(light_layout)
        layout.addWidget(light_group)
        
        # 저장 설정 그룹
        save_group = QGroupBox("저장 설정")
        save_layout = QVBoxLayout()
        
        save_layout.addWidget(QLabel("기본 저장 위치:"))
        path_layout = QHBoxLayout()
        self.save_path_edit = QLineEdit()
        self.save_path_edit.setText(app_state["save_path"])
        self.save_path_edit.textChanged.connect(self.update_save_path)
        path_layout.addWidget(self.save_path_edit)
        
        path_btn = QPushButton("📂")
        path_btn.clicked.connect(self.select_save_path)
        path_layout.addWidget(path_btn)
        save_layout.addLayout(path_layout)
        
        save_layout.addWidget(QLabel("카메라 저장 옵션:"))
        self.save_mode_1 = QRadioButton("Cam 3 저장 안함 (1, 2, 4만)")
        self.save_mode_2 = QRadioButton("Cam 3도 저장하기 (전체)")
        self.save_mode_3 = QRadioButton("Cam 3만 저장하기")
        
        mode = app_state["save_mode"]
        if mode == 1:
            self.save_mode_1.setChecked(True)
        elif mode == 2:
            self.save_mode_2.setChecked(True)
        else:
            self.save_mode_3.setChecked(True)
        
        self.save_mode_1.toggled.connect(lambda: self.update_save_mode(1) if self.save_mode_1.isChecked() else None)
        self.save_mode_2.toggled.connect(lambda: self.update_save_mode(2) if self.save_mode_2.isChecked() else None)
        self.save_mode_3.toggled.connect(lambda: self.update_save_mode(3) if self.save_mode_3.isChecked() else None)
        
        save_layout.addWidget(self.save_mode_1)
        save_layout.addWidget(self.save_mode_2)
        save_layout.addWidget(self.save_mode_3)
        
        save_group.setLayout(save_layout)
        layout.addWidget(save_group)
        
        # 자동 시퀀스 그룹
        seq_group = QGroupBox("자동 시퀀스 설정 (역순 가능)")
        seq_layout = QVBoxLayout()
        seq_layout.addWidget(QLabel("* 역순 예시: Start=120, End=30, Step=-10", styleSheet="color: gray;"))
        
        seq_control_layout = QHBoxLayout()
        seq_control_layout.addWidget(QLabel("시작:"))
        self.seq_start_spin = QSpinBox()
        self.seq_start_spin.setMinimum(0)
        self.seq_start_spin.setMaximum(255)
        self.seq_start_spin.setValue(app_state["sequence_start"])
        self.seq_start_spin.valueChanged.connect(self.update_sequence_start)
        seq_control_layout.addWidget(self.seq_start_spin)
        
        seq_control_layout.addWidget(QLabel("종료:"))
        self.seq_end_spin = QSpinBox()
        self.seq_end_spin.setMinimum(0)
        self.seq_end_spin.setMaximum(255)
        self.seq_end_spin.setValue(app_state["sequence_end"])
        self.seq_end_spin.valueChanged.connect(self.update_sequence_end)
        seq_control_layout.addWidget(self.seq_end_spin)
        
        seq_control_layout.addWidget(QLabel("스텝:"))
        self.seq_step_spin = QSpinBox()
        self.seq_step_spin.setMinimum(-255)
        self.seq_step_spin.setMaximum(255)
        self.seq_step_spin.setValue(app_state["sequence_step"])
        self.seq_step_spin.valueChanged.connect(self.update_sequence_step)
        seq_control_layout.addWidget(self.seq_step_spin)
        seq_layout.addLayout(seq_control_layout)
        
        seq_group.setLayout(seq_layout)
        layout.addWidget(seq_group)
        
        # 버튼들
        self.single_btn = QPushButton("📸 현재 설정으로 1회 촬영")
        self.single_btn.setStyleSheet("background-color: #E91E63; color: white; font-weight: bold; padding: 10px;")
        self.single_btn.clicked.connect(self.run_single_capture)
        layout.addWidget(self.single_btn)
        
        self.auto_btn = QPushButton("🔄 자동 시퀀스 시작 (범위 적용)")
        self.auto_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 10px;")
        self.auto_btn.clicked.connect(self.run_auto_sequence)
        layout.addWidget(self.auto_btn)
        
        # 설정 저장 버튼
        save_settings_btn = QPushButton("💾 설정 저장")
        save_settings_btn.clicked.connect(self.save_settings_manual)
        layout.addWidget(save_settings_btn)
        
        layout.addStretch()
        
        return scroll
    
    def create_preview_panel(self):
        """오른쪽 카메라 미리보기 패널 생성 (2x2 그리드)"""
        panel = QWidget()
        layout = QVBoxLayout(panel)
        
        title = QLabel("카메라 미리보기 (우하단 모서리를 드래그하여 크기 조절)")
        title.setStyleSheet("font-size: 14px; font-weight: bold; padding: 10px; color: #666;")
        layout.addWidget(title)
        
        # 2x2 그리드 레이아웃
        grid_layout = QGridLayout()
        grid_layout.setSpacing(10)
        
        self.camera_widgets = {}
        initial_width = app_state.get("camera_width", PREVIEW_SCALE_WIDTH)
        initial_height = app_state.get("camera_height", 300)
        
        # 카메라를 2x2 그리드로 배치
        positions = [(0, 0), (0, 1), (1, 0), (1, 1)]  # (row, col)
        for idx, cam_id in enumerate(sorted(TARGET_CAMS)):
            widget = ResizableCameraWidget(cam_id)
            widget.setMinimumSize(initial_width, initial_height)
            widget.size_changed.connect(self.on_camera_size_changed)
            
            row, col = positions[idx]
            grid_layout.addWidget(widget, row, col)
            self.camera_widgets[cam_id] = widget
        
        layout.addLayout(grid_layout)
        layout.addStretch()
        
        return panel
    
    def on_camera_size_changed(self, width, height):
        """하나의 카메라 크기가 변경되면 모든 카메라 크기 동기화"""
        app_state["camera_width"] = width
        app_state["camera_height"] = height
        save_settings()
        
        # 크기 변경을 발생시킨 위젯 찾기
        sender_widget = self.sender()
        
        # 모든 카메라 위젯의 크기 동기화
        for cam_id, widget in self.camera_widgets.items():
            if widget != sender_widget:  # 크기 변경을 발생시킨 위젯 제외
                widget.set_camera_size(width, height)
    
    def update_previews(self):
        """카메라 미리보기 업데이트"""
        current_mode = app_state["save_mode"]
        
        with frame_lock:
            for cam_id in sorted(TARGET_CAMS):
                if cam_id not in self.camera_widgets:
                    continue
                    
                widget = self.camera_widgets[cam_id]
                label = widget.label
                label_size = label.size()
                
                if cam_id in latest_frames:
                    raw_img = latest_frames[cam_id]
                    h, w = raw_img.shape[:2]
                    
                    # 위젯 크기에 맞춰 스케일 조정
                    target_width = label_size.width()
                    target_height = label_size.height()
                    scale_w = target_width / w
                    scale_h = target_height / h
                    scale = min(scale_w, scale_h)  # 비율 유지
                    
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
                    
                    # 텍스트 크기를 위젯 크기에 맞게 조정
                    font_scale = max(0.5, min(2.0, target_width / 400))
                    thickness = max(1, int(2 * font_scale))
                    cv2.putText(preview_img, txt, (20, int(50 * font_scale)), 
                              cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness)
                    
                    # OpenCV 이미지를 QPixmap으로 변환
                    rgb_image = cv2.cvtColor(preview_img, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    bytes_per_line = ch * w
                    qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
                    pixmap = QPixmap.fromImage(qt_image)
                    label.setPixmap(pixmap.scaled(label_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                else:
                    # 검은 화면
                    target_width = label_size.width()
                    target_height = label_size.height()
                    black_img = np.zeros((target_height, target_width, 3), dtype=np.uint8)
                    
                    font_scale = max(0.5, min(2.0, target_width / 400))
                    thickness = max(1, int(2 * font_scale))
                    if not cameras_available:
                        cv2.putText(black_img, f"CAM {cam_id} (No Camera)", 
                                  (20, target_height // 2),
                                  cv2.FONT_HERSHEY_SIMPLEX, font_scale, (100, 100, 100), thickness)
                    else:
                        cv2.putText(black_img, f"CAM {cam_id} Off", 
                                  (50, target_height // 2),
                                  cv2.FONT_HERSHEY_SIMPLEX, font_scale, (100, 100, 100), thickness)
                    
                    rgb_image = cv2.cvtColor(black_img, cv2.COLOR_BGR2RGB)
                    h, w, ch = rgb_image.shape
                    bytes_per_line = ch * w
                    qt_image = QImage(rgb_image.data, w, h, bytes_per_line, QImage.Format_RGB888)
                    pixmap = QPixmap.fromImage(qt_image)
                    label.setPixmap(pixmap)
    
    # 설정 업데이트 함수들
    def update_product(self, text):
        app_state["product"] = text
        save_settings()
    
    def update_condition(self, text):
        app_state["condition"] = text
        save_settings()
    
    def update_shot_no(self, value):
        app_state["shot_no"] = value
        save_settings()
    
    def update_light_value(self, value):
        app_state["light_value"] = value
    
    def update_save_path(self, text):
        app_state["save_path"] = text
        save_settings()
    
    def update_save_mode(self, mode):
        app_state["save_mode"] = mode
        save_settings()
    
    def update_sequence_start(self, value):
        app_state["sequence_start"] = value
        save_settings()
    
    def update_sequence_end(self, value):
        app_state["sequence_end"] = value
        save_settings()
    
    def update_sequence_step(self, value):
        app_state["sequence_step"] = value
        save_settings()
    
    def select_save_path(self):
        path = QFileDialog.getExistingDirectory(self, "저장 위치 선택", app_state["save_path"])
        if path:
            self.save_path_edit.setText(path)
    
    def apply_light(self):
        val = self.light_spin.value()
        send_light_packet(val)
        self.light_btn.setText("✅ 설정됨")
        self.light_btn.setStyleSheet("background-color: #4CAF50; color: white;")
        QTimer.singleShot(1000, lambda: (
            self.light_btn.setText("💡 조명 값 적용"),
            self.light_btn.setStyleSheet("")
        ))
    
    def save_settings_manual(self):
        if save_settings():
            QMessageBox.information(self, "성공", "설정이 저장되었습니다.")
        else:
            QMessageBox.warning(self, "오류", "설정 저장에 실패했습니다.")
    
    def run_single_capture(self):
        self.single_btn.setEnabled(False)
        self.single_btn.setText("💾 저장 중...")
        threading.Thread(target=self.single_capture_logic, daemon=True).start()
    
    def single_capture_logic(self):
        try:
            current_light = app_state["light_value"]
            count = save_snapshot_internal(current_light)
            if count > 0:
                app_state["shot_no"] += 1
                QTimer.singleShot(0, lambda: self.shot_no_spin.setValue(app_state["shot_no"]))
                QTimer.singleShot(0, lambda: (
                    self.single_btn.setText("✅ 저장 완료"),
                    self.single_btn.setStyleSheet("background-color: #4CAF50; color: white;")
                ))
                QTimer.singleShot(1000, self.restore_single_button)
            else:
                QTimer.singleShot(0, lambda: QMessageBox.warning(self, "경고", "카메라가 연결되지 않았거나 이미지를 저장할 수 없습니다."))
                QTimer.singleShot(0, self.restore_single_button)
        except Exception as e:
            QTimer.singleShot(0, lambda: QMessageBox.critical(self, "오류", f"촬영 중 오류 발생: {e}"))
            QTimer.singleShot(0, self.restore_single_button)
    
    def restore_single_button(self):
        self.single_btn.setEnabled(True)
        self.single_btn.setText("📸 현재 설정으로 1회 촬영")
        self.single_btn.setStyleSheet("background-color: #E91E63; color: white; font-weight: bold; padding: 10px;")
    
    def run_auto_sequence(self):
        start_val = self.seq_start_spin.value()
        end_val = self.seq_end_spin.value()
        step_val = self.seq_step_spin.value()
        
        # 유효성 검사
        if step_val == 0:
            QMessageBox.critical(self, "Error", "스텝(Step)은 0이 될 수 없습니다.")
            return
        
        if step_val > 0 and start_val > end_val:
            QMessageBox.critical(self, "Error", "스텝이 양수일 때는 [Start <= End]여야 합니다.")
            return
        
        if step_val < 0 and start_val < end_val:
            QMessageBox.critical(self, "Error", "스텝이 음수(마이너스)일 때는 [Start >= End]여야 합니다.")
            return
        
        self.auto_btn.setEnabled(False)
        self.auto_btn.setText("⏳ 촬영 중...")
        threading.Thread(target=self.auto_sequence_logic, args=(start_val, end_val, step_val), daemon=True).start()
    
    def auto_sequence_logic(self, start_val, end_val, step_val):
        try:
            offset = 1 if step_val > 0 else -1
            
            for val in range(start_val, end_val + offset, step_val):
                # UI 업데이트는 메인 스레드에서
                QTimer.singleShot(0, lambda v=val: self.auto_btn.setText(f"⏳ 촬영 중... (밝기: {v})"))
                
                send_light_packet(val)
                print(f"--- 조명 변경: {val} ---")
                time.sleep(0.5)
                
                save_snapshot_internal(val)
                time.sleep(0.2)
            
            app_state["shot_no"] += 1
            QTimer.singleShot(0, lambda: self.shot_no_spin.setValue(app_state["shot_no"]))
            QTimer.singleShot(0, lambda: (
                self.auto_btn.setText("✅ 저장 완료!"),
                self.auto_btn.setStyleSheet("background-color: #4CAF50; color: white;")
            ))
            QTimer.singleShot(3000, self.restore_auto_button)
        except Exception as e:
            QTimer.singleShot(0, lambda: QMessageBox.critical(self, "오류", f"시퀀스 촬영 중 오류 발생: {e}"))
            QTimer.singleShot(0, self.restore_auto_button)
    
    def restore_auto_button(self):
        self.auto_btn.setEnabled(True)
        self.auto_btn.setText("🔄 자동 시퀀스 시작 (범위 적용)")
        self.auto_btn.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 10px;")
    
    def closeEvent(self, event):
        """윈도우 종료 시 정리"""
        global running
        running = False
        
        if self.camera_thread.isRunning():
            self.camera_thread.quit()
            self.camera_thread.wait()
        
        if cameras_available and cameras:
            for cam in cameras:
                if cam.IsGrabbing():
                    cam.StopGrabbing()
                cam.Close()
        
        for client in light_clients.values():
            client.close()
        
        save_settings()  # 종료 시 설정 저장
        event.accept()

# =================== 메인 실행 ===================
def main():
    import sys
    global running
    
    try:
        print("🔧 하드웨어 초기화 중...")
        # 하드웨어 초기화
        init_cameras()
        init_lights()
        print("✅ 하드웨어 초기화 완료")
        
        print("🖥️  GUI 초기화 중...")
        # GUI 실행
        app = QApplication(sys.argv)
        print("✅ QApplication 생성 완료")
        
        # 예외 처리 핸들러
        def exception_handler(exc_type, exc_value, exc_traceback):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc_value, exc_traceback)
                return
            print(f"❌ 예외 발생: {exc_type.__name__}: {exc_value}")
            import traceback
            traceback.print_exception(exc_type, exc_value, exc_traceback)
        
        sys.excepthook = exception_handler
        
        print("🪟 윈도우 생성 중...")
        window = VisionSystemWindow()
        print("✅ 윈도우 생성 완료")
        
        print("👁️  윈도우 표시 중...")
        window.show()
        print("✅ 윈도우 표시 완료")
        
        print("🚀 애플리케이션 실행 중...")
        app.exec()
        print("✅ 애플리케이션 종료")
        
    except Exception as e:
        print(f"❌ 초기화 오류: {e}")
        import traceback
        traceback.print_exc()
        input("Press Enter to exit...")  # Windows에서 콘솔이 바로 닫히는 것을 방지
    finally:
        running = False

if __name__ == "__main__":
    main()

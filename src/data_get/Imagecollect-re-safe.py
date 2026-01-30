import cv2
import os
import numpy as np
from datetime import datetime
import threading
import time
import json
from tkinter import *
from tkinter import messagebox
from tkinter import filedialog
from pypylon import pylon
from pymodbus.client import ModbusSerialClient

# =================== 설정 ===================
TARGET_CAMS = [1, 2, 3, 4]   
WINDOW_NAME = "Integrated Vision System"
PREVIEW_SCALE_WIDTH = 400     

# 조명 포트
LIGHT_PORTS = ["COM2", "COM8", "COM9", "COM10"]
BAUDRATE = 9600

# 전역 변수
latest_frames = {}
frame_lock = threading.Lock()
running = True
light_clients = {}
cameras = None
camera_map = {}
converter = None
cameras_available = False

# =================== GUI 초기화 ===================
root = Tk()
root.title("Vision System (Reverse Sequence - Safe Mode)")
root.geometry("520x950")

# =================== 1. 하드웨어 초기화 ===================
# (A) 카메라
try:
    tl_factory = pylon.TlFactory.GetInstance()
    devices = tl_factory.EnumerateDevices()
    if len(devices) == 0:
        print("⚠️ Basler 카메라가 발견되지 않았습니다. 검은 화면으로 표시됩니다.")
        cameras_available = False
    else:
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

# (B) 조명
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


# =================== UI 요소 구성 ===================

# --- 섹션 1: 기본 정보 ---
Label(root, text="[ 기본 설정 ]", font=("Arial", 12, "bold"), fg="#333").pack(pady=(15, 5))

Label(root, text="제품명 (Product):").pack(anchor="w", padx=20)
name_var = StringVar(value="ModelA")
Entry(root, textvariable=name_var).pack(fill=X, padx=20)

Label(root, text="검사 조건 (Condition 1):").pack(anchor="w", padx=20)
cond_var = StringVar(value="Test_A")
Entry(root, textvariable=cond_var).pack(fill=X, padx=20)

Label(root, text="촬영 번호 (Shot No.):").pack(anchor="w", padx=20)
shot_no_var = IntVar(value=1)
Entry(root, textvariable=shot_no_var).pack(fill=X, padx=20)


# --- 섹션 2: 수동 조명 제어 ---
Frame(root, height=2, bd=1, relief=SUNKEN).pack(fill=X, padx=10, pady=15)
Label(root, text="[ 수동 조명 제어 ]", font=("Arial", 12, "bold"), fg="blue").pack(pady=(0, 5))

light_val_str = StringVar(value="100") 

def send_light_packet(val):
    if val < 0: val = 0
    if val > 255: val = 255
    light_val_str.set(str(val))
    val_bytes = f"{val:03d}".encode('ascii')
    packet = b'\x02' + b'A' + (val_bytes + b',') * 3 + val_bytes + b'\x03'
    for port, client in light_clients.items():
        if client and client.connected:
            try: client.socket.write(packet)
            except: pass

def apply_light_setting(event=None):
    try:
        val = int(light_val_str.get().strip())
        send_light_packet(val)
        btn_set_light.config(bg="#4CAF50", text="✅ 설정됨")
        root.after(1000, lambda: btn_set_light.config(bg="#ddd", text="💡 조명 값 적용 (Set)"))
    except: pass

light_frame = Frame(root)
light_frame.pack(fill=X, padx=20, pady=5)
Label(light_frame, text="밝기 값:").pack(side=LEFT)
Entry(light_frame, textvariable=light_val_str, width=10, font=("Arial", 14, "bold"), justify="center", bg="#f0f8ff").pack(side=LEFT, padx=10)
btn_set_light = Button(light_frame, text="💡 조명 값 적용 (Set)", command=apply_light_setting, bg="#ddd", height=1)
btn_set_light.pack(side=LEFT, padx=5, fill=X, expand=True)


# --- 섹션 3: 저장 설정 ---
Frame(root, height=2, bd=1, relief=SUNKEN).pack(fill=X, padx=10, pady=15)
Label(root, text="[ 저장 설정 ]", font=("Arial", 12, "bold"), fg="#333").pack(pady=(0, 5))

Label(root, text="기본 저장 위치:").pack(anchor="w", padx=20)
path_frame = Frame(root)
path_frame.pack(fill=X, padx=20)
save_path_var = StringVar(value="./captured_images")
Entry(path_frame, textvariable=save_path_var).pack(side=LEFT, fill=X, expand=True)
Button(path_frame, text="📂 선택", command=lambda: save_path_var.set(filedialog.askdirectory() or save_path_var.get())).pack(side=RIGHT, padx=(5, 0))

Label(root, text="카메라 저장 옵션:", font=("Arial", 10, "bold")).pack(anchor="w", padx=20, pady=(10, 0))
save_mode_var = IntVar(value=2) 
radio_frame = Frame(root)
radio_frame.pack(anchor="w", padx=20, pady=5)
Radiobutton(radio_frame, text="Cam 3 저장 안함 (1, 2, 4만)", variable=save_mode_var, value=1).pack(anchor="w")
Radiobutton(radio_frame, text="Cam 3도 저장하기 (전체)", variable=save_mode_var, value=2, fg="blue").pack(anchor="w")
Radiobutton(radio_frame, text="Cam 3만 저장하기", variable=save_mode_var, value=3, fg="red").pack(anchor="w")


# =================== 자동 시퀀스 설정 UI ===================
Frame(root, height=2, bd=1, relief=SUNKEN).pack(fill=X, padx=10, pady=15)
Label(root, text="[ 자동 시퀀스 설정 (역순 가능) ]", font=("Arial", 12, "bold"), fg="#E91E63").pack(pady=(0, 5))
Label(root, text="* 역순 예시: Start=120, End=30, Step=-10", font=("Arial", 9), fg="gray").pack()

seq_frame = Frame(root)
seq_frame.pack(fill=X, padx=20)

# 최저
Label(seq_frame, text="시작(Start):").pack(side=LEFT)
seq_start_var = IntVar(value=30)
Entry(seq_frame, textvariable=seq_start_var, width=5, justify="center").pack(side=LEFT, padx=5)

# 최대
Label(seq_frame, text="종료(End):").pack(side=LEFT)
seq_end_var = IntVar(value=120)
Entry(seq_frame, textvariable=seq_end_var, width=5, justify="center").pack(side=LEFT, padx=5)

# 간격
Label(seq_frame, text="스텝(Step):").pack(side=LEFT)
seq_step_var = IntVar(value=10)
Entry(seq_frame, textvariable=seq_step_var, width=5, justify="center").pack(side=LEFT, padx=5)


# =================== 로직 함수들 ===================

def save_snapshot_internal(light_val):
    if not cameras_available:
        messagebox.showwarning("경고", "카메라가 연결되지 않았습니다. 이미지를 저장할 수 없습니다.")
        return 0
        
    base_path = save_path_var.get().strip()
    product = name_var.get().strip()
    cond1 = cond_var.get().strip()
    cond2 = f"Light_{light_val:03d}"
    shot_no = shot_no_var.get()
    mode = save_mode_var.get()

    if not product or not cond1: return 0

    path_std = os.path.join(base_path, product, cond1, cond2)
    path_cam3 = os.path.join(base_path, "cam3", product, cond1, cond2)
    
    if mode in [1, 2]: os.makedirs(path_std, exist_ok=True)
    if mode in [2, 3]: os.makedirs(path_cam3, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    images_to_save = {}
    with frame_lock:
        for cam_id in TARGET_CAMS:
            if cam_id in latest_frames:
                images_to_save[cam_id] = latest_frames[cam_id].copy()

    saved_count = 0
    for cam_id, img in images_to_save.items():
        if mode == 1 and cam_id == 3: continue 
        elif mode == 3 and cam_id != 3: continue

        filename = f"{product}_{cond1}_{cond2}_{shot_no:03d}_Cam{cam_id}_{timestamp}.png"
        filepath = os.path.join(path_cam3 if cam_id == 3 else path_std, filename)
        
        try:
            cv2.imwrite(filepath, img)
            print(f"saved: {filepath}")
            saved_count += 1
        except: pass
    return saved_count


# =================== [수정됨] 자동 시퀀스 로직 ===================
def run_auto_sequence():
    btn_auto.config(state="disabled", bg="gray")
    btn_single.config(state="disabled")
    
    try:
        start_val = seq_start_var.get()
        end_val = seq_end_var.get()
        step_val = seq_step_var.get()
        
        # [수정됨] 유효성 검사 로직 변경 (역순 허용)
        if step_val == 0:
            messagebox.showerror("Error", "스텝(Step)은 0이 될 수 없습니다.")
            restore_buttons()
            return

        # 정방향인데 시작이 더 큰 경우
        if step_val > 0 and start_val > end_val:
            messagebox.showerror("Error", "스텝이 양수일 때는 [Start <= End]여야 합니다.")
            restore_buttons()
            return

        # 역방향인데 시작이 더 작은 경우
        if step_val < 0 and start_val < end_val:
            messagebox.showerror("Error", "스텝이 음수(마이너스)일 때는 [Start >= End]여야 합니다.")
            restore_buttons()
            return
            
        threading.Thread(target=auto_sequence_logic, args=(start_val, end_val, step_val), daemon=True).start()
        
    except ValueError:
        messagebox.showerror("Error", "숫자만 입력해주세요.")
        restore_buttons()

def auto_sequence_logic(start_val, end_val, step_val):
    try:
        # [수정됨] range의 끝값 처리 (양수/음수 스텝 모두 포함되도록)
        # 스텝이 양수면 end + 1, 음수면 end - 1 까지 루프를 돌림
        offset = 1 if step_val > 0 else -1
        
        for val in range(start_val, end_val + offset, step_val):
            
            # UI 업데이트
            root.after(0, lambda v=val: btn_auto.config(text=f"⏳ 촬영 중... (밝기: {v})"))
            
            # 조명 변경
            send_light_packet(val)
            print(f"--- 조명 변경: {val} ---")
            time.sleep(0.5) 
            
            # 촬영
            save_snapshot_internal(val)
            time.sleep(0.2)

        root.after(0, sequence_finished)

    except Exception as e:
        print(f"Auto Sequence Error: {e}")
        root.after(0, restore_buttons)

def sequence_finished():
    shot_no_var.set(shot_no_var.get() + 1)
    restore_buttons()
    # messagebox.showinfo("완료", "✅ 시퀀스 촬영 완료!")
    btn_auto.config(text="✅ 저장 완료!")
    root.after(3000, lambda: btn_auto.config(text="🔄 자동 시퀀스 시작 (범위 적용)"))

def run_single_capture():
    btn_single.config(state="disabled", text="💾 저장 중...", bg="gray")
    threading.Thread(target=single_capture_logic, daemon=True).start()

def single_capture_logic():
    try:
        current_light = int(light_val_str.get())
        count = save_snapshot_internal(current_light)
        if count > 0:
            root.after(0, lambda: shot_no_var.set(shot_no_var.get() + 1))
            root.after(0, lambda: btn_single.config(text="✅ 저장 완료", bg="#4CAF50"))
            root.after(1000, restore_buttons)
        else:
            root.after(0, restore_buttons)
    except:
        root.after(0, restore_buttons)

def restore_buttons():
    btn_single.config(state="normal", text="📸 현재 설정으로 1회 촬영", bg="#E91E63")
    btn_auto.config(state="normal", text="🔄 자동 시퀀스 시작 (범위 적용)", bg="#2196F3")


# =================== 버튼 배치 ===================
btn_single = Button(root, text="📸 현재 설정으로 1회 촬영", command=run_single_capture, 
                     bg="#E91E63", fg="white", font=("Arial", 14, "bold"), height=2)
btn_single.pack(fill=X, padx=20, pady=(20, 5))

btn_auto = Button(root, text="🔄 자동 시퀀스 시작 (범위 적용)", command=run_auto_sequence, 
                     bg="#2196F3", fg="white", font=("Arial", 14, "bold"), height=2)
btn_auto.pack(fill=X, padx=20, pady=(5, 20))


# =================== 미리보기 쓰레드 ===================
def preview_thread():
    global running
    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1600, 300)

    while running:
        try:
            # 카메라가 있을 때만 프레임 가져오기
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

            display_images = []
            current_mode = save_mode_var.get() 

            with frame_lock:
                for cam_id in sorted(TARGET_CAMS):
                    if cam_id in latest_frames:
                        # 실제 프레임이 있는 경우
                        raw_img = latest_frames[cam_id]
                        h, w = raw_img.shape[:2]
                        scale = PREVIEW_SCALE_WIDTH / w
                        preview_img = cv2.resize(raw_img, (int(w * scale), int(h * scale)))
                        
                        will_save = True
                        if current_mode == 1 and cam_id == 3: will_save = False 
                        if current_mode == 3 and cam_id != 3: will_save = False 

                        if will_save:
                            if cam_id == 3: txt, color = "CAM 3 (ON)", (0, 255, 255) 
                            else: txt, color = f"CAM {cam_id} (ON)", (0, 255, 0)
                        else:
                            txt, color = f"CAM {cam_id} (OFF)", (128, 128, 128)

                        cv2.putText(preview_img, txt, (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2)
                        display_images.append(preview_img)
                    else:
                        # 카메라가 없거나 프레임이 없는 경우 검은 화면 표시
                        black_img = np.zeros((300, PREVIEW_SCALE_WIDTH, 3), dtype=np.uint8)
                        if not cameras_available:
                            cv2.putText(black_img, f"CAM {cam_id} (No Camera)", (20, 150), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 0.8, (100, 100, 100), 2)
                        else:
                            cv2.putText(black_img, f"CAM {cam_id} Off", (50, 150), 
                                      cv2.FONT_HERSHEY_SIMPLEX, 1, (100, 100, 100), 2)
                        display_images.append(black_img)

            if display_images:
                combined_view = cv2.hconcat(display_images)
                cv2.imshow(WINDOW_NAME, combined_view)

            if cv2.waitKey(10) & 0xFF == 27:
                running = False
                break
        except Exception as e:
            print(f"Preview Error: {e}")
            break
    root.quit()

# =================== 실행 ===================
apply_light_setting()
t = threading.Thread(target=preview_thread, daemon=True)
t.start()
root.mainloop()

running = False
t.join()
# 카메라가 있을 때만 정리 작업 수행
if cameras_available and cameras:
    for cam in cameras:
        if cam.IsGrabbing(): cam.StopGrabbing()
        cam.Close()
for client in light_clients.values():
    client.close()
cv2.destroyAllWindows()

import cv2 
import os 
from datetime import datetime 
import threading  
from tkinter import *

from pypylon import pylon  # Basler 카메라 제어 라이브러리

root = Tk()

# =================== 카메라 초기화 ===================
tl_factory = pylon.TlFactory.GetInstance()  # 카메라 팩토리 인스턴스 생성
devices = tl_factory.EnumerateDevices()  # 연결된 카메라 목록 가져오기
if len(devices) == 0:
    raise IOError("No Basler cameras found.")  # 카메라 없으면 예외 발생

cameras = pylon.InstantCameraArray(len(devices))  # 카메라 배열 생성
camera_map = {}  # 카메라 인덱스와 객체 매핑

for i, cam in enumerate(cameras):
    device = tl_factory.CreateDevice(devices[i])  # 각 디바이스 객체 생성
    cam.Attach(device)  # 카메라에 디바이스 연결
    cam.Open()  # 카메라 오픈
    cam.PixelFormat.SetValue("BayerGR12")  # 픽셀 포맷 설정
    cam.Width.SetValue(cam.Width.Max)  # 최대 너비 설정
    cam.Height.SetValue(cam.Height.Max)  # 최대 높이 설정
    camera_map[i + 1] = cam  # 카메라 맵에 저장

converter = pylon.ImageFormatConverter()  # 이미지 포맷 변환기 생성
converter.OutputPixelFormat = pylon.PixelType_BGR8packed  # 출력 포맷 설정
converter.OutputBitAlignment = pylon.OutputBitAlignment_MsbAligned  # 비트 정렬 설정

for cam in cameras:
    cam.StartGrabbing(pylon.GrabStrategy_LatestImageOnly)  # 최신 이미지만 가져오기 시작

latest_frames = {}  # 각 카메라의 최신 프레임 저장
preview_max_width = 640  # 미리보기 최대 너비



name_var = StringVar(value="배경")  # 제품명 변수
save_dir_var = StringVar(value="test")  # 저장 경로 변수

# =================== 저장 함수 ===================
def save_images(cam_ids):
    os.makedirs(save_dir_var.get(), exist_ok=True)  # 저장 폴더 생성
    product = name_var.get().strip()  # 제품명 가져오기

    for cam_id in cam_ids:
        if cam_id in latest_frames:
            filename = f"{name_var}.png"  # 파일명 생성
            filepath = os.path.join(save_dir_var.get(), filename)  # 파일 경로 생성
            cv2.imwrite(filepath, latest_frames[cam_id])  # 이미지 저장
            print(f"✅ Saved: {filepath}")  # 저장 완료 출력
        else:
            print(f"⚠️ Camera {cam_id} has no frame yet.")  # 프레임 없을 때 경고 출력

# =================== 버튼 ===================
Button(root, text="Capture CAM 1, 2, 4", command=lambda: save_images([1, 2, 4])).pack(pady=5)  # 1,2,4번 카메라 캡처 버튼
Button(root, text="Capture CAM 3 only", command=lambda: save_images([3])).pack(pady=5)  # 3번 카메라 캡처 버튼

# =================== 미리보기 쓰레드 ===================
def update_previews():
    while True:
        for idx, cam in camera_map.items():
            if cam.IsGrabbing():
                grabResult = cam.RetrieveResult(5000, pylon.TimeoutHandling_ThrowException)  # 이미지 가져오기
                if grabResult.GrabSucceeded():
                    image = converter.Convert(grabResult)  # 이미지 변환
                    img = image.GetArray()  # numpy 배열로 변환
                    latest_frames[idx] = img  # 최신 프레임 저장

                    h, w = img.shape[:2]  # 이미지 크기
                    scale = preview_max_width / w  # 스케일 계산
                    preview_img = cv2.resize(img, (int(w * scale), int(h * scale)))  # 미리보기 이미지 리사이즈
                    cv2.imshow(f"Camera {idx}", preview_img)  # 이미지 창에 표시
                grabResult.Release()  # 결과 해제

        if cv2.waitKey(1) & 0xFF == 27:
            break  # ESC 입력 시 종료

    for cam in cameras:
        cam.StopGrabbing()  # 이미지 가져오기 중지
        cam.Close()  # 카메라 닫기
    cv2.destroyAllWindows()  # 모든 창 닫기
    root.quit()  # 프로그램 종료

threading.Thread(target=update_previews, daemon=True).start()  # 미리보기 쓰레드 시작
root.mainloop()  # GUI 메인루프 시작

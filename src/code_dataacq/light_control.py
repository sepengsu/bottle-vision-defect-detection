import sys
import os
import json
import tkinter as tk
from tkinter import ttk
import binascii

# pymodbus 라이브러리
from pymodbus.client import ModbusSerialClient
from pymodbus.exceptions import ModbusException

class LightControlApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Vision Light Controller (Split Control)")
        self.root.geometry("550x650")
        self.root.configure(bg="#2d2d2d")

        # 설정 및 경로 설정
        self.script_dir = os.path.dirname(os.path.abspath(__file__))
        self.save_filepath = os.path.join(self.script_dir, "config", "light_settings.json")
        os.makedirs(os.path.dirname(self.save_filepath), exist_ok=True)

        # 포트 정의 (사용자 요건 반영)
        self.ports = {
            "group_124": ["COM2", "COM9", "COM8"], # CAM 1, 2, 4
            "group_3": ["COM10"]                     # CAM 3
        }

        self.clients = {}  
        self.sliders = {}
        self.is_loading = True 

        self._setup_ui()
        self._init_modbus_and_sync()
        self.is_loading = False

    def _init_modbus_and_sync(self):
        print("\n=== [Modbus 연결 및 동기화 시작] ===")
        saved_data = self._load_settings()

        all_ports = self.ports["group_124"] + self.ports["group_3"]
        for port in all_ports:
            try:
                # 메인 코드와 동일한 Modbus 설정
                client = ModbusSerialClient(
                    port=port,
                    baudrate=9600,
                    parity='N',
                    stopbits=1,
                    bytesize=8,
                    timeout=0.2
                )
                
                if client.connect():
                    self.clients[port] = client
                    print(f"[{port}] 연결 성공")
                    
                    # 그룹에 맞는 저장된 값 적용
                    group_key = "group_124" if port in self.ports["group_124"] else "group_3"
                    val = saved_data.get(group_key, 240)
                    self.sliders[group_key].set(val)
                    
                    self.send_command(group_key, force=True)
                else:
                    self.clients[port] = None
                    print(f"[{port}] 연결 실패")
            except Exception as e:
                print(f"[{port}] 초기화 에러: {e}")
        print("====================================\n")

    def _setup_ui(self):
        header = tk.Label(self.root, text="VISION LIGHT CONTROL", bg="#2d2d2d", fg="#7cfc00", 
                         font=("Arial", 14, "bold"), pady=30)
        header.pack()

        # CAM 1/2/4 통합 제어 섹션
        frame1 = tk.LabelFrame(self.root, text=" CAM 1 / 2 / 4 통합 밝기 (COM 2, 8, 10) ", 
                              bg="#2d2d2d", fg="white", font=("Arial", 11, "bold"), padx=15, pady=20)
        frame1.pack(fill="x", padx=30, pady=10)

        s1 = tk.Scale(frame1, from_=0, to=255, orient="horizontal", bg="#2d2d2d", fg="white",
                     troughcolor="#45a049", highlightthickness=0, 
                     command=lambda v: self.send_command("group_124"))
        s1.pack(fill="x", expand=True)
        self.sliders["group_124"] = s1

        # CAM 3 개별 제어 섹션
        frame2 = tk.LabelFrame(self.root, text=" CAM 3 개별 밝기 (COM 9) ", 
                              bg="#2d2d2d", fg="white", font=("Arial", 11, "bold"), padx=15, pady=20)
        frame2.pack(fill="x", padx=30, pady=10)

        s2 = tk.Scale(frame2, from_=0, to=255, orient="horizontal", bg="#2d2d2d", fg="white",
                     troughcolor="#7cfc00", highlightthickness=0, 
                     command=lambda v: self.send_command("group_3"))
        s2.pack(fill="x", expand=True)
        self.sliders["group_3"] = s2

    def send_command(self, group_key, force=False):
        """ASCII 인코딩 및 전송 확인 로그 추가"""
        if self.is_loading and not force:
            return
            
        val = self.sliders[group_key].get()
        # 숫자를 3자리 ASCII 바이트로 변환 (ex: 255 -> 0x32 0x35 0x35)
        val_bytes = f"{val:03d}".encode('ascii') 
        
        # 패킷 조립: STX + 'A' + (데이터*4) + ETX
        packet = b'\x02' + b'A' + (val_bytes + b',') * 3 + val_bytes + b'\x03'

        target_ports = self.ports[group_key]
        for port in target_ports:
            client = self.clients.get(port)
            if client and client.connected:
                try:
                    client.socket.write(packet)
                    # --- [전송 확인 라인 추가] ---
                    print(f"[{port}] 전송 확인 -> Value: {val}, Packet(HEX): {packet.hex().upper()}")
                except Exception as e:
                    print(f"[{port}] 전송 에러: {e}")

    def _load_settings(self):
        if os.path.exists(self.save_filepath):
            try:
                with open(self.save_filepath, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _save_settings(self):
        data = {key: s.get() for key, s in self.sliders.items()}
        try:
            with open(self.save_filepath, 'w') as f:
                json.dump(data, f, indent=4)
        except Exception as e:
            print(f"Save Error: {e}")

    def on_closing(self):
        print("\n[System] 자원 해제 및 종료...")
        try:
            self._save_settings()
            for client in self.clients.values():
                if client:
                    client.close()
        finally:
            self.root.destroy()

if __name__ == "__main__":
    root = tk.Tk()
    app = LightControlApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()
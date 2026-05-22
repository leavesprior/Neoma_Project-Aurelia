import os
import cv2
import serial
import threading
import time
import re
import json
import hid
import math
import websocket
from datetime import datetime
import numpy as np
import ctypes
import queue
from ctypes import wintypes
from collections import deque
import sys

# Import the bare-metal thermal optic nerve
sys.path.append(r"C:\Aurelia_Project\Aurelia_Sensors\P2Pro-Viewer\P2Pro")
from video import Video

# ==========================================
# HARDWARE CONFIGURATION
# ==========================================
LIDAR_PORT        = 'COM11'    # LD14P LiDAR 
SPATIAL_PORT      = 'COM5'     # Raw mmWave (Room Macro)
VIBE_MACRO_PORT   = 'COM8'     # ADXL345 (Rig / Desk Resonance)
VIBE_MICRO_PORT   = 'COM12'    # ADXL345 (Keyboard Typing)
PULSE_PORT        = 'COM9'     # ESPHome mmWave (Desk Micro Fallback)
CAM_INDEX         = 0          # EMEET C960

# Temperature Sensor Config (Ambient USB)
TEMP_VID = 0x3553
TEMP_PID = 0xa001

# --- [ HWiNFO 64-BIT SENSORY LINK PROTOCOL ] ---
kernel32 = ctypes.windll.kernel32
kernel32.UnmapViewOfFile.argtypes = [ctypes.c_void_p]
kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
kernel32.MapViewOfFile.restype = ctypes.c_void_p

MAP_NAME = "Global\\HWiNFO_SENS_SM2"

AURELIA_NERVES = {
    "CPU":   105860 - 32,
    "Brain": 158300 - 32,  # iGPU / NPU
    "Eyes":  163820 - 32   # eGPU V620
}

def get_log_time():
    return datetime.now().strftime("%H:%M:%S")

thermal_sensor = Video()

# ==========================================
# GLOBAL STATE (Aurelia's Working Memory)
# ==========================================
state_lock = threading.Lock() 
vision_lock = threading.Lock()

aurelia_state = {
    "timestamp": "",
    "camera_status": "Offline",
    "confidence": 0.0,            
    
    "temperature_c": 0.0,         
    "cpu_thermals": 0.0,          
    "brain_thermals_strix": 0.0,  
    "eye_thermals_v620": 0.0,     
    "thermal_alert": "STABLE",    
    
    "vibe_macro_mag": 0.0,        
    "vibe_macro_jitter": 0.0,           
    "vibe_macro_peak": 0.0,             
    "vibe_micro_mag": 0.0,        
    "vibe_micro_jitter": 0.0,           
    "vibe_micro_peak": 0.0,

    "lidar_horizontal_m": 0.0,
    "last_lidar_time": time.time(), 
    "spatial_mmwave_mm": 0,  
    "spatial_delta_mm": 0,   
    "pulse_mmwave_mm": 0,
    "pulse_delta_mm": 0,
    "pulse_present": False,
    "user_present": False,
    
    "bpm_scosche": 0,          
    "last_scosche_time": 0,
    "bpm_mobile": 0,             # Mobile Bluetooth BPM
    "last_mobile_time": 0,       # Mobile Bluetooth Timestamp
    "bpm_mmwave": 0,           
    "bpm": 0,                  
    "respiration": 0,          
    
    "history_lidar": deque(maxlen=60),
    "history_pulse": deque(maxlen=60),
    "history_spatial": deque(maxlen=60),
    "history_vibe_macro_peak": deque(maxlen=60),       
    "history_vibe_micro_peak": deque(maxlen=60),
    "history_vibe_micro_jitter": deque(maxlen=60),    
    "history_temp": deque(maxlen=60),
    "history_cpu_temp": deque(maxlen=60),
    "history_brain_temp": deque(maxlen=60),
    "history_eye_temp": deque(maxlen=60),
    "history_bpm": deque(maxlen=60)        
}

def get_serializable_state(state):
    """Converts deque buffers to lists so Aurelia's telemetry state can be safely written as JSON."""
    serialized = {}
    for k, v in state.items():
        if isinstance(v, deque):
            serialized[k] = list(v)
        else:
            serialized[k] = v
    return serialized

latest_frame = None
fast_pulse_buffer = deque(maxlen=200) 

# ==========================================
# ADVANCED DATA PROCESSING
# ==========================================
def extract_vitals_from_mmwave(amplitude_array, sample_rate_hz=10, min_power_threshold=2.0):
    if len(amplitude_array) < sample_rate_hz * 5: 
        return {"bpm": 0, "respiration": 0}

    std_dev = np.std(amplitude_array)
    if std_dev > 100.0:
        return {"bpm": 0, "respiration": 0}

    data = np.array(amplitude_array) - np.mean(amplitude_array)
    windowed_data = data * np.hanning(len(data))
    
    pad_length = 1024 
    fft_vals = np.abs(np.fft.rfft(windowed_data, n=pad_length))
    freqs = np.fft.rfftfreq(pad_length, d=1.0/sample_rate_hz)
    
    hr_mask = (freqs >= 0.8) & (freqs <= 2.5)
    bpm = 0
    if np.any(hr_mask):
        hr_peak_power = np.max(fft_vals[hr_mask])
        if hr_peak_power > min_power_threshold:
            bpm = int(freqs[hr_mask][np.argmax(fft_vals[hr_mask])] * 60)
            
    resp_mask = (freqs >= 0.2) & (freqs <= 0.5)
    respiration = 0
    if np.any(resp_mask):
        resp_peak_power = np.max(fft_vals[resp_mask])
        if resp_peak_power > min_power_threshold:
            respiration = int(freqs[resp_mask][np.argmax(fft_vals[resp_mask])] * 60)
            
    return {"bpm": bpm, "respiration": respiration}

def calculate_confidence():
    score = 0.5
    if aurelia_state["lidar_horizontal_m"] > 0 and aurelia_state["pulse_present"]:
        score = 0.95
    elif aurelia_state["lidar_horizontal_m"] > 0 or aurelia_state["pulse_present"]:
        score = 0.70 
    elif not aurelia_state["user_present"]:
        score = 1.0 
        
    if aurelia_state["camera_status"] == "Offline":
        score -= 0.1
        
    aurelia_state["confidence"] = round(np.clip(score, 0.0, 1.0), 2)

def clear_telemetry_arrays():
    with state_lock:
        aurelia_state["vibe_macro_peak"] = 0.0
        aurelia_state["vibe_micro_peak"] = 0.0

# ==========================================
# SENSORY NERVES (Background Threads)
# ==========================================

def scosche_thread():
    while True:
        try:
            ws = websocket.WebSocket()
            ws.connect("ws://127.0.0.1:8765", timeout=3)
            print(f"[{get_log_time()}] [OMNI-HUB: SCOSCHE] INFO: Local Biological Tether Established.")
            while True:
                raw_data = ws.recv()
                try:
                    data = json.loads(raw_data)
                    current_bpm = int(data.get("bpm", 0))
                except json.JSONDecodeError:
                    current_bpm = int(raw_data.strip())
                
                if current_bpm > 0:
                    with state_lock:
                        aurelia_state["bpm_scosche"] = current_bpm
                        aurelia_state["last_scosche_time"] = time.time()
        except Exception:
            time.sleep(5)

def mobile_vitals_thread():
    """Polls the drop-file created by the Tailscale Gateway for remote Bluetooth BPM data."""
    file_path = r"C:\Aurelia_Project\Aurelia_Sensors\mobile_bpm.json"
    while True:
        try:
            if os.path.exists(file_path):
                with open(file_path, 'r') as f:
                    data = json.load(f)
                
                bpm = data.get("bpm", 0)
                timestamp = data.get("timestamp", 0)
                
                if bpm > 0 and time.time() - timestamp < 10:
                    with state_lock:
                        aurelia_state["bpm_mobile"] = bpm
                        aurelia_state["last_mobile_time"] = timestamp
        except Exception:
            pass
        time.sleep(1)

def temp_thread():
    device = hid.device()
    device_open = False
    while True:
        try:
            if not device_open:
                devices = hid.enumerate(TEMP_VID, TEMP_PID)
                if devices:
                    device.open_path(devices[0]['path'])
                    device.set_nonblocking(False)
                    device_open = True
                else:
                    time.sleep(5) 
                    continue

            commands = [
                [0x01, 0x80, 0x33, 0x01, 0x00, 0x00, 0x00, 0x00],
                [0x01, 0x82, 0x77, 0x01, 0x00, 0x00, 0x00, 0x00],
                [0x00, 0x01, 0x80, 0x33, 0x01, 0x00, 0x00, 0x00]
            ]
            
            for cmd in commands:
                device.write(cmd)
                data = device.read(8, timeout_ms=200) 
                if data and len(data) >= 4:
                    temp_c = ((data[2] << 8) + data[3]) / 128.0
                    if 5 < temp_c < 95:
                        with state_lock:
                            aurelia_state["temperature_c"] = round(temp_c, 2)
                        break
            time.sleep(1)
        except Exception: 
            device_open = False
            try: device.close()
            except: pass
            time.sleep(5)

def system_health_thread():
    while True:
        try:
            hMap = kernel32.OpenFileMappingW(0x0004, False, MAP_NAME)
            if not hMap: time.sleep(2); continue
            pBuf = kernel32.MapViewOfFile(hMap, 0x0004, 0, 0, 256 * 1024)
            if not pBuf: kernel32.CloseHandle(hMap); time.sleep(2); continue

            try:
                while True:
                    temp_cpu = ctypes.cast(pBuf + AURELIA_NERVES["CPU"], ctypes.POINTER(ctypes.c_double)).contents.value
                    temp_brain = ctypes.cast(pBuf + AURELIA_NERVES["Brain"], ctypes.POINTER(ctypes.c_double)).contents.value
                    temp_eyes = ctypes.cast(pBuf + AURELIA_NERVES["Eyes"], ctypes.POINTER(ctypes.c_double)).contents.value
                    
                    with state_lock:
                        aurelia_state["cpu_thermals"] = round(max(0.0, temp_cpu), 1)
                        aurelia_state["brain_thermals_strix"] = round(max(0.0, temp_brain), 1)
                        aurelia_state["eye_thermals_v620"] = round(max(0.0, temp_eyes), 1)
                        
                        if aurelia_state["eye_thermals_v620"] >= 90 or max(aurelia_state["brain_thermals_strix"], aurelia_state["cpu_thermals"]) >= 85:
                            aurelia_state["thermal_alert"] = "CRITICAL_FEVER"
                        else:
                            aurelia_state["thermal_alert"] = "STABLE"

                    time.sleep(2.0)
            except Exception: pass
            finally:
                kernel32.UnmapViewOfFile(ctypes.c_void_p(pBuf))
                kernel32.CloseHandle(ctypes.c_void_p(hMap))
        except Exception: pass
        time.sleep(2.0)

# ---------------------------------------------------------
# PHYSICAL ADXL345 CLONES - (Restored to 9600 Baud for BOTH)
# ---------------------------------------------------------
def vibe_macro_thread():
    """Zone 1: Rig & Environmental Resonance (COM8 @ 9600 baud)"""
    vibe_buffer_raw = deque(maxlen=50) 
    while True:
        ser = None
        try:
            ser = serial.Serial(VIBE_MACRO_PORT, 9600, timeout=1)
            ser.reset_input_buffer()
            print(f"[{get_log_time()}] [OMNI-HUB: MACRO VIBE] INFO: Rig thread bound to {VIBE_MACRO_PORT} @ 9600 Baud")
            while True:
                raw = ser.readline().decode('utf-8', errors='ignore').strip()
                if "," in raw:
                    parts = raw.split(',')
                    if len(parts) >= 3:
                        try:
                            # Bulletproof Regex Parse
                            x_str = re.sub(r'[^\d\.-]', '', parts[0])
                            y_str = re.sub(r'[^\d\.-]', '', parts[1])
                            z_str = re.sub(r'[^\d\.-]', '', parts[2])
                            
                            x, y, z = float(x_str), float(y_str), float(z_str)
                            mag = math.sqrt(x**2 + y**2 + z**2)
                            vibe_buffer_raw.append(mag)
                            
                            if len(vibe_buffer_raw) > 1:
                                current_avg = np.mean(vibe_buffer_raw)
                                current_jitter = np.std(vibe_buffer_raw)
                                
                                # Deviation from 1.0G Gravity Baseline
                                current_mag_deviation = abs(current_avg - 1.0)
                                current_peak_deviation = max(abs(v - 1.0) for v in vibe_buffer_raw)
                                
                                with state_lock:
                                    aurelia_state["vibe_macro_mag"] = float(current_mag_deviation)
                                    aurelia_state["vibe_macro_jitter"] = float(current_jitter)
                                    
                                    if current_peak_deviation > aurelia_state["vibe_macro_peak"]:
                                        aurelia_state["vibe_macro_peak"] = float(current_peak_deviation)
                        except ValueError: pass
        except Exception as e: 
            if ser: ser.close()
            time.sleep(5)

def vibe_micro_thread():
    """Zone 2: Keyboard Physical Vibration (COM12 @ 9600 baud)"""
    vibe_buffer_raw = deque(maxlen=50) 
    while True:
        ser = None
        try:
            ser = serial.Serial(VIBE_MICRO_PORT, 9600, timeout=1)
            ser.reset_input_buffer()
            print(f"[{get_log_time()}] [OMNI-HUB: MICRO VIBE] INFO: Keyboard thread bound to {VIBE_MICRO_PORT} @ 9600 Baud")
            while True:
                raw = ser.readline().decode('utf-8', errors='ignore').strip()
                if "," in raw:
                    parts = raw.split(',')
                    if len(parts) >= 3:
                        try:
                            # Bulletproof Regex Parse
                            x_str = re.sub(r'[^\d\.-]', '', parts[0])
                            y_str = re.sub(r'[^\d\.-]', '', parts[1])
                            z_str = re.sub(r'[^\d\.-]', '', parts[2])
                            
                            x, y, z = float(x_str), float(y_str), float(z_str)
                            mag = math.sqrt(x**2 + y**2 + z**2)
                            vibe_buffer_raw.append(mag)
                            
                            if len(vibe_buffer_raw) > 1:
                                current_avg = np.mean(vibe_buffer_raw)
                                current_jitter = np.std(vibe_buffer_raw)
                                
                                # Deviation from 1.0G Gravity Baseline
                                current_mag_deviation = abs(current_avg - 1.0)
                                current_peak_deviation = max(abs(v - 1.0) for v in vibe_buffer_raw)
                                
                                with state_lock:
                                    aurelia_state["vibe_micro_mag"] = float(current_mag_deviation)
                                    aurelia_state["vibe_micro_jitter"] = float(current_jitter)
                                    
                                    if current_peak_deviation > aurelia_state["vibe_micro_peak"]:
                                        aurelia_state["vibe_micro_peak"] = float(current_peak_deviation)
                        except ValueError: pass
        except Exception as e: 
            if ser: ser.close()
            time.sleep(5)
# ---------------------------------------------------------

def lidar_thread():
    while True:
        ser = None
        try:
            ser = serial.Serial(LIDAR_PORT, 230400, timeout=0.1)
            ser.reset_input_buffer()
            while True:
                if ser.in_waiting > 100:
                    raw = ser.read(ser.in_waiting)
                    for i in range(len(raw) - 47):
                        if raw[i] == 0x54 and raw[i+1] == 0x2C:
                            angle = (raw[i+4] | (raw[i+5] << 8)) / 100.0
                            if 270.0 <= angle <= 320.0:
                                dist_mm = (raw[i+6] | (raw[i+7] << 8))
                                dist_m = round(dist_mm / 1000.0, 3)
                                if 0.38 <= dist_m <= 0.89:
                                    with state_lock:
                                        aurelia_state["lidar_horizontal_m"] = dist_m 
                                        aurelia_state["last_lidar_time"] = time.time() 
                time.sleep(0.05)
        except Exception: 
            if ser: ser.close()
            time.sleep(5)

def spatial_thread():
    while True:
        ser = None
        try:
            ser = serial.Serial(SPATIAL_PORT, 115200, timeout=0.1)
            ser.reset_input_buffer()
            last_print_tick = time.time()
            current_range_mm = 0
            last_range_mm = 0
            while True:
                current_time = time.time()
                while ser.in_waiting > 0:
                    raw_data = ser.readline().decode('ascii', errors='ignore').strip()
                    range_match = re.search(r'Range\s+(\d+)', raw_data)
                    if range_match:
                        raw_cm = int(range_match.group(1))
                        current_range_mm = raw_cm * 10 
                if current_time - last_print_tick >= 1.0:
                    delta_mm = abs(current_range_mm - last_range_mm)
                    with state_lock:
                        aurelia_state["spatial_mmwave_mm"] = current_range_mm
                        aurelia_state["spatial_delta_mm"] = delta_mm
                    last_range_mm = current_range_mm
                    last_print_tick = current_time
                time.sleep(0.05)
        except Exception: 
            if ser: ser.close() 
            time.sleep(5)

def pulse_thread():
    global fast_pulse_buffer
    while True:
        ser = None
        try:
            ser = serial.Serial(PULSE_PORT, 115200, timeout=1)
            ser.reset_input_buffer()
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            last_detection_distance = 0
            while True:
                while ser.in_waiting > 0:
                    raw_line = ser.readline()
                    if raw_line:
                        try:
                            text = raw_line.decode('utf-8', errors='ignore').strip()
                            clean_text = ansi_escape.sub('', text)
                            if "Distance" in clean_text and "Sending state" in clean_text:
                                parts = clean_text.split("': Sending state ")
                                sensor_type = parts[0].split("'")[-1]
                                distance_str = parts[1].split(" cm")[0]
                                if sensor_type == "Detection Distance":
                                    current_dist_mm = float(distance_str) * 10.0
                                    delta_mm = abs(current_dist_mm - last_detection_distance)
                                    with state_lock:
                                        aurelia_state["pulse_mmwave_mm"] = current_dist_mm
                                        aurelia_state["pulse_delta_mm"] = delta_mm
                                        aurelia_state["pulse_present"] = (current_dist_mm > 0)
                                        fast_pulse_buffer.append(current_dist_mm)
                                    last_detection_distance = current_dist_mm
                        except Exception: pass
                time.sleep(0.1)
        except Exception: 
            if ser: ser.close()
            time.sleep(5)

def vision_thread():
    global latest_frame
    while True:
        try:
            cap = cv2.VideoCapture(CAM_INDEX)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            
            if cap.isOpened(): 
                with state_lock: aurelia_state["camera_status"] = "Online"
                
            while True:
                success, frame = cap.read()
                if success: 
                    with vision_lock: latest_frame = frame.copy()
                else:
                    cap.release() 
                    time.sleep(5) 
                    break 
        except Exception: 
            if 'cap' in locals() and cap.isOpened(): cap.release()
            time.sleep(5)

def thermal_vision_thread():
    print(f"[{get_log_time()}] [OMNI-HUB: THERMAL] Initializing native hardware connection (1234:5684)...")
    try:
        thermal_sensor.open()
    except Exception as e:
        print(f"[{get_log_time()}] [OMNI-HUB: THERMAL] ERROR: {e}")

def memory_buffer_thread():
    history_map = {
        "lidar_horizontal_m": "history_lidar",
        "pulse_mmwave_mm": "history_pulse",
        "spatial_mmwave_mm": "history_spatial",
        "vibe_macro_peak": "history_vibe_macro_peak",           
        "vibe_micro_peak": "history_vibe_micro_peak", 
        "vibe_micro_jitter": "history_vibe_micro_jitter",
        "temperature_c": "history_temp",
        "cpu_thermals": "history_cpu_temp",
        "brain_thermals_strix": "history_brain_temp",
        "eye_thermals_v620": "history_eye_temp",
        "bpm": "history_bpm" 
    }
    while True:
        try:
            with state_lock:
                for state_key, hist_key in history_map.items():
                    if state_key in aurelia_state and hist_key in aurelia_state:
                        aurelia_state[hist_key].append(aurelia_state[state_key])
            time.sleep(0.5) 
        except Exception: time.sleep(0.5) 

# ==========================================
# THE BRAIN STEM LOGIC
# ==========================================

def take_optic_snapshot(frame_label):
    local_frame = None
    with vision_lock:
        if latest_frame is not None:
            local_frame = latest_frame.copy()

    if local_frame is not None:
        try:
            small_frame = cv2.resize(local_frame, (512, 512))
            path = r"C:\Aurelia_Project\Aurelia_Sensors\Aurelia_Optic_Buffer_Start.jpg" if frame_label == "start" else r"C:\Aurelia_Project\Aurelia_Sensors\Aurelia_Optic_Buffer_End.jpg"
            # --- ATOMIC WRITE TO PREVENT ORCHESTRATOR CRASH ---
            tmp_path = path.replace(".jpg", "_tmp.jpg")
            cv2.imwrite(tmp_path, small_frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
            os.replace(tmp_path, path)
            print(f"[{get_log_time()}] [OMNI-HUB: OPTIC] {frame_label.upper()} frame secured.")
        except Exception: pass

def take_thermal_snapshot():
    thermal_path = r"C:\Aurelia_Project\Aurelia_Sensors\Aurelia_Optic_Buffer_Thermal.jpg"
    
    if not thermal_sensor.video_running:
        # If camera is unplugged, wipe the old image so Aurelia doesn't see "ghosts"
        if os.path.exists(thermal_path):
            try: os.remove(thermal_path)
            except: pass
        return False

    try:
        frame_obj = thermal_sensor.frame_queue[0].get_nowait()
        raw = frame_obj['thermal_data'].astype(np.float32)

        p_min, p_max = np.percentile(raw, [2, 98])
        if p_max > p_min:
            norm = np.clip(raw, p_min, p_max)
            norm = ((norm - p_min) / (p_max - p_min) * 255).astype('uint8')
        else:
            norm = np.zeros(raw.shape, dtype='uint8')

        processed = cv2.rotate(norm, cv2.ROTATE_90_CLOCKWISE) 
        processed = cv2.flip(processed, -1) 
        
        color_map = cv2.applyColorMap(processed, cv2.COLORMAP_INFERNO)

        # --- ATOMIC WRITE TO PREVENT ORCHESTRATOR CRASH ---
        tmp_path = thermal_path.replace(".jpg", "_tmp.jpg")
        cv2.imwrite(tmp_path, color_map, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        os.replace(tmp_path, thermal_path)
        print(f"[{get_log_time()}] [OMNI-HUB: THERMAL] Native anchor frame secured.")
        return True

    except queue.Empty:
        # If queue is empty (unplugged or glitched), wipe the old file
        if os.path.exists(thermal_path):
            try: os.remove(thermal_path)
            except: pass
        return False
    except Exception as e:
        print(f"[{get_log_time()}] [OMNI-HUB: THERMAL] ERROR: Snapshot failed: {e}")
        return False

def compile_telemetry_vector():
    global fast_pulse_buffer
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with state_lock:
        if time.time() - aurelia_state["last_lidar_time"] > 5.0 and aurelia_state["lidar_horizontal_m"] > 0.0:
            aurelia_state["lidar_horizontal_m"] = 0.0
        buffer_copy = list(fast_pulse_buffer)
        aurelia_state["timestamp"] = current_time
        
        state_snapshot = aurelia_state.copy()

    vitals = extract_vitals_from_mmwave(buffer_copy, sample_rate_hz=10)
    
    with state_lock:
        aurelia_state["bpm_mmwave"] = vitals["bpm"]
        aurelia_state["respiration"] = vitals["respiration"]
        
        # --- TRI-TIER PULSE FALLBACK ---
        if time.time() - aurelia_state["last_scosche_time"] < 5.0:
            final_bpm = aurelia_state["bpm_scosche"]
            pulse_source = "Armband (PC)"
        elif time.time() - aurelia_state["last_mobile_time"] < 10.0:
            final_bpm = aurelia_state["bpm_mobile"]
            pulse_source = "Armband (Mobile)"
        else:
            final_bpm = aurelia_state["bpm_mmwave"]
            pulse_source = "mmWave"

        aurelia_state["bpm"] = final_bpm
        
        desk_lidar = aurelia_state["lidar_horizontal_m"] > 0.0
        desk_mmwave = 0 < aurelia_state["pulse_mmwave_mm"] <= 1000.0
        aurelia_state["user_present"] = bool(desk_lidar or desk_mmwave)
        
        calculate_confidence()
        state_snapshot = aurelia_state.copy()

    bpm_hist = list(state_snapshot.get('history_bpm', []))
    if len(bpm_hist) >= 5:
        sigma = np.std(bpm_hist[-10:])
        delta = bpm_hist[-1] - bpm_hist[-5]
        bpm_trend = "RISING" if delta > 3 else ("FALLING" if delta < -3 else "STATIC")
        bpm_volatility = "HIGH_JITTER" if sigma > 5.0 else ("ELEVATED" if sigma > 2.0 else "SMOOTH")
    else:
        bpm_trend = "STATIC"
        bpm_volatility = "SMOOTH"
        sigma = 0.0

    peak_hist = list(state_snapshot.get('history_vibe_micro_peak', []))
    jitter_hist = list(state_snapshot.get('history_vibe_micro_jitter', []))
    
    vibe_active_pts = sum(1 for i in range(min(len(peak_hist), len(jitter_hist))) if peak_hist[i] >= 0.08 or jitter_hist[i] >= 0.02)
    
    if vibe_active_pts >= 12: vibe_context = "SUSTAINED_ACTIVITY (Typing/Working)"
    elif vibe_active_pts >= 2: vibe_context = "BRIEF_MOVEMENT"
    elif state_snapshot["vibe_macro_peak"] > 0.15: vibe_context = "SHARP_IMPACT (Desk Bump)"
    else: vibe_context = "STILL (Baseline)"

    hottest_sensor = "CPU"
    peak_temp = state_snapshot['cpu_thermals']
    if state_snapshot['brain_thermals_strix'] > peak_temp:
        peak_temp = state_snapshot['brain_thermals_strix']
        hottest_sensor = "Brain"
    if state_snapshot['eye_thermals_v620'] > peak_temp:
        peak_temp = state_snapshot['eye_thermals_v620']
        hottest_sensor = "Eyes"
    thermal_str = f"{hottest_sensor} {peak_temp}C" if peak_temp > 75 else "NOMINAL"

    vector_string = f"[BPM ({pulse_source}): {final_bpm} ({bpm_trend}) | KEYBOARD: {vibe_context} ({state_snapshot['vibe_micro_peak']:.4f}G) | DESK/RIG: {state_snapshot['vibe_macro_peak']:.4f}G | PROXIMITY: {state_snapshot['lidar_horizontal_m']}m | THERMAL: {thermal_str}]"
    
    print(f"\n[{get_log_time()}] [OMNI-HUB: DIAGNOSTIC] --- [ SYSTEM SENSORY READOUT ] ---")
    print(f"    - Time:           {current_time}")
    print(f"    - Confidence:     {state_snapshot['confidence']}")
    print(f"    - CPU Native:     {state_snapshot['cpu_thermals']}°C")
    print(f"    - Brain (iGPU):   {state_snapshot['brain_thermals_strix']}°C")
    print(f"    - Eyes (eGPU):    {state_snapshot['eye_thermals_v620']}°C")
    print(f"    - Thermal Status: {state_snapshot['thermal_alert']}")
    print(f"    - Temp (Rig Core): {state_snapshot['temperature_c']}°C")
    
    print(f"    - Vibe (Rig):     Mag {state_snapshot['vibe_macro_mag']:.4f}G | Peak {state_snapshot['vibe_macro_peak']:.4f}G")
    print(f"    - Vibe (Keys):    Mag {state_snapshot['vibe_micro_mag']:.4f}G | Peak {state_snapshot['vibe_micro_peak']:.4f}G | {vibe_context}")
    
    print(f"    - Spatial (Room): Range {state_snapshot['spatial_mmwave_mm']}mm | Delta: {state_snapshot['spatial_delta_mm']}mm")
    print(f"    - LiDAR (Desk):   {state_snapshot['lidar_horizontal_m']}m")
    
    if state_snapshot["user_present"]:
        print(f"    - Desk Presence:  YES")
        
        # FIX: Dynamic terminal output for the active pulse source
        if "Armband" in pulse_source:
            print(f"        -> {pulse_source}: {final_bpm} BPM")
        else:
            print(f"        -> Armband:       Offline (0 BPM)")

        print(f"        -> mmWave Radar: {state_snapshot['pulse_mmwave_mm']}mm | {state_snapshot['bpm_mmwave']} BPM | {state_snapshot['respiration']} Breaths/Min")
        print(f"        -> Bio-Trend:    {bpm_trend} (σ:{bpm_volatility})")
        print(f"        -> Thalamic Vibe: {vector_string}")
    else:
        print("    - Desk Presence:  NO (AFK)")
    print("----------------------------------------------------------\n")

    return vector_string, final_bpm, state_snapshot

def dispatch_thalamic_payload(vector, final_bpm, state_snapshot):
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    is_spike = final_bpm > 100 or state_snapshot["vibe_macro_peak"] > 0.15
    
    thalamic_payload = {
        "timestamp": current_time,
        "vibe_vector": vector,
        "is_interrupt": bool(is_spike),
        "user_present": state_snapshot["user_present"],
        "confidence": state_snapshot["confidence"]
    }

    try:
        raw_temp = r"C:\Aurelia_Project\Aurelia_Sensors\Aurelia_Master_Telemetry_RAW_temp.json"
        raw_final = r"C:\Aurelia_Project\Aurelia_Sensors\Aurelia_Master_Telemetry_RAW.json"
        with open(raw_temp, "w") as f: json.dump(get_serializable_state(state_snapshot), f, indent=4)
        os.replace(raw_temp, raw_final)

        thal_temp = r"C:\Aurelia_Project\Aurelia_Sensors\Aurelia_Thalamic_Snapshot_temp.json"
        thal_final = r"C:\Aurelia_Project\Aurelia_Sensors\Aurelia_Thalamic_Snapshot.json"
        with open(thal_temp, "w") as f: json.dump(thalamic_payload, f, indent=4)
        os.replace(thal_temp, thal_final)
            
        print(f"[{get_log_time()}] [OMNI-HUB: CORE] Thalamic payload dispatched successfully.\n")
    except Exception as e:
        print(f"[{get_log_time()}] [OMNI-HUB: CORE] ERROR: Failed to write Telemetry files - {e}")

# ==========================================
# THE MAIN TICK LOOP
# ==========================================
if __name__ == "__main__":
    print(f"[{get_log_time()}] [SYSTEM] Aurelia: Booting Omni-Sensory Hub (V19 Tri-Sensor Architecture)...")
    
    threading.Thread(target=scosche_thread, daemon=True).start()
    threading.Thread(target=mobile_vitals_thread, daemon=True).start() 
    threading.Thread(target=temp_thread, daemon=True).start()
    threading.Thread(target=system_health_thread, daemon=True).start() 
    threading.Thread(target=vibe_macro_thread, daemon=True).start()
    threading.Thread(target=vibe_micro_thread, daemon=True).start()
    threading.Thread(target=lidar_thread, daemon=True).start()
    threading.Thread(target=spatial_thread, daemon=True).start()
    threading.Thread(target=pulse_thread, daemon=True).start()
    threading.Thread(target=vision_thread, daemon=True).start()
    threading.Thread(target=thermal_vision_thread, daemon=True).start()
    threading.Thread(target=memory_buffer_thread, daemon=True).start()
    
    time.sleep(3) 
    print(f"\n[{get_log_time()}] [SYSTEM] Aurelia: Nervous System Online.")
    print(f"[{get_log_time()}] [SYSTEM] 30-Second Analytical Window active.")
    print(f"[{get_log_time()}] [SYSTEM] Press Ctrl+C to shut down the Hub.")
    
    try:
        while True:
            print(f"[{get_log_time()}] [OMNI-HUB: SEQUENCE] Initiating Start Cycle (T=0s)...")
            take_optic_snapshot("start")
            
            clear_telemetry_arrays() 
            
            time.sleep(15)
            
            print(f"[{get_log_time()}] [OMNI-HUB: SEQUENCE] Securing Thermal Midpoint (T=15s)...")
            take_thermal_snapshot()
            
            time.sleep(15)
            
            print(f"[{get_log_time()}] [OMNI-HUB: SEQUENCE] Closing Window & Dispatching Payload (T=30s)...")
            take_optic_snapshot("end")
            
            vector, final_bpm, state_snapshot = compile_telemetry_vector()
            dispatch_thalamic_payload(vector, final_bpm, state_snapshot)
            
    except KeyboardInterrupt:
        print(f"\n[{get_log_time()}] [SYSTEM] Aurelia: Severing brain stem. Shutting down Omni-Hub.")

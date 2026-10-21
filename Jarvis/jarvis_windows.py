import urllib.request
import zipfile
import json
import sys
import os
import webbrowser
import difflib
import subprocess
import speech_recognition as sr
import pyttsx3
import socket
import ctypes
import time
import math
import threading
import glob
import re
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk
import vosk

# --- ENABLE HIGH-DPI AWARENESS (FIXES PIXELATED / BLURRY GRAPHICS ON WINDOWS) ---
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # Per-Monitor DPI Aware v2
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()   # Fallback Vista/Win7/Win10 DPI Aware
    except Exception:
        pass

# --- PATH HELPERS FOR PYINSTALLER ---
def get_app_dir():
    """Returns the permanent directory where the .exe or .py script lives."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_resource_dir():
    """Returns the internal temp folder (_MEIPASS) when frozen, for bundled assets like icon.ico."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

# --- GLOBAL CONFIGURATION & SETTINGS ---
CONFIG = {
    "wake_word": "jarvis",
    "accent_color": "#00d4ff",
    "theme": "Dark",
    "voice_index": 0,
    "language": "en-US",
    "autocorrect_mode": "Full (AI + Phonetic)",
    "listen_key": "Num Lock (OFF to Listen)",
    "chat_model": "llama3.2",
    "coder_model": "qwen2.5-coder",
    "smart_platform": "SmartThings",
    "st_token": "",
    "ha_token": "",
    "ha_url": "http://homeassistant.local:8123"
}

ACCENT_COLORS = {
    "Jarvis Cyan": "#00d4ff",
    "Mark 85 Gold": "#ffaa00",
    "Crimson Ultron": "#ff2a2a",
    "Emerald Matrix": "#00ff66",
    "Stark Purple": "#b829ff"
}

THEMES = {
    "Dark": {
        "bg": "#020408",
        "panel": "#050b14",
        "text": "#88ccee",
        "subtext": "#2a5278",
        "input_bg": "#03070e",
        "transparent_key": "#000001"
    },
    "Light": {
        "bg": "#f0f4f8",
        "panel": "#ffffff",
        "text": "#102a43",
        "subtext": "#627d98",
        "input_bg": "#d9e2ec",
        "transparent_key": "#000001"
    }
}

GUI_APP = None
AVAILABLE_VOICES = []
SMART_DEVICES = {}
VOSK_MODEL = None

def init_vosk_model():
    """Initializes the 100% offline Vosk Speech-to-Text model, downloading it once if missing."""
    global VOSK_MODEL
    vosk.SetLogLevel(-1) # Silence noisy console logs
    app_dir = get_app_dir()
    model_dir = os.path.join(app_dir, "vosk-model")
    
    if not os.path.exists(model_dir):
        print("[System] Offline voice model not found. Downloading Vosk (~40MB) for first-time setup...")
        if GUI_APP:
            GUI_APP.set_state("THINKING", "DOWNLOADING OFFLINE VOICE MODEL...")
        url = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
        zip_path = os.path.join(app_dir, "vosk_temp.zip")
        try:
            urllib.request.urlretrieve(url, zip_path)
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(app_dir)
            extracted_folder = os.path.join(app_dir, "vosk-model-small-en-us-0.15")
            if os.path.exists(extracted_folder):
                os.rename(extracted_folder, model_dir)
            if os.path.exists(zip_path):
                os.remove(zip_path)
            print("[System] Offline voice model installed successfully!")
        except Exception as e:
            print(f"[System] Failed to download Vosk model: {e}")
            return

    try:
        VOSK_MODEL = vosk.Model(model_dir)
        print("[System] Offline Vosk Speech-to-Text Engine Loaded.")
    except Exception as e:
        print(f"[System] Failed to load Vosk model: {e}")

def get_system_voices():
    """Fetches available Windows SAPI5 voices on startup."""
    global AVAILABLE_VOICES
    try:
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        AVAILABLE_VOICES = [(i, v.name, v.id) for i, v in enumerate(voices)]
    except Exception as e:
        print(f"[System] Could not enumerate voices: {e}")
        AVAILABLE_VOICES = [(0, "Default Windows Voice", None)]

def speak(text):
    """Speaks the text aloud using Windows native TTS and updates the GUI."""
    if not text:
        return
    print(f"Jarvis: {text}")
    
    if GUI_APP:
        GUI_APP.update_reply(text)
        GUI_APP.set_state("SPEAKING", "SPEAKING...")
    
    try:
        engine = pyttsx3.init()
        voices = engine.getProperty('voices')
        v_idx = CONFIG.get("voice_index", 0)
        if len(voices) > v_idx:
            engine.setProperty('voice', voices[v_idx].id)
        elif len(voices) > 0:
            engine.setProperty('voice', voices[0].id)
        
        engine.setProperty('rate', 175)
        engine.say(text)
        engine.runAndWait()
    except Exception as e:
        print(f"[System] TTS Audio Error: {e}")
        
    if GUI_APP:
        GUI_APP.set_state("IDLE", "ONLINE // STANDBY")

def ai_autocorrect(raw_text):
    """Uses the local LLM to fix phonetic typos in commands without hallucinating"""
    url = "http://localhost:11434/api/generate"
    system_prompt = (
        "You are a strict autocorrect module. "
        "Fix obvious phonetic misspellings from speech-to-text. "
        "Reply ONLY with the exact corrected text. Do NOT add quotes, formatting, or extra words."
    )
    payload = {
        "model": CONFIG.get("chat_model", "llama3.2"),
        "prompt": f"Fix this transcript: {raw_text}",
        "system": system_prompt,
        "stream": False,
        "temperature": 0.0,
        "num_predict": 20
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=4) as response:
            result = json.loads(response.read().decode('utf-8'))
            cleaned = result.get("response", raw_text).strip()
            return cleaned
    except Exception:
        return raw_text

def listen_for_audio(prompt_text, timeout_duration=None, apply_correction=False):
    """100% Offline Microphone Listener powered by Vosk."""
    if VOSK_MODEL is None:
        time.sleep(1)
        return None

    recognizer = sr.Recognizer()
    recognizer.pause_threshold = 1.5
    
    with sr.Microphone() as source:
        if prompt_text:
            print(prompt_text)
        
        try:
            audio = recognizer.listen(source, timeout=timeout_duration, phrase_time_limit=15)
            
            # Convert audio to raw 16kHz 16-bit mono PCM for offline Vosk processing
            raw_data = audio.get_raw_data(convert_rate=16000, convert_width=2)
            kaldi_rec = vosk.KaldiRecognizer(VOSK_MODEL, 16000)
            kaldi_rec.AcceptWaveform(raw_data)
            result = json.loads(kaldi_rec.FinalResult())
            raw_command = result.get("text", "").strip().lower()
            
            if not raw_command:
                return None
                
            print(f"[Offline STT] Heard: {raw_command}")
            
            mode = CONFIG.get("autocorrect_mode", "Full (AI + Phonetic)")
            
            if mode in ["Phonetic Only", "Full (AI + Phonetic)"]:
                corrections = {
                    "jiminy": "gemini",
                    "germany": "gemini",
                    "gimli": "gemini",
                    "jaromir": "jarvis",
                    "charizard": "jarvis",
                    "harvest": "jarvis",
                    "service": "jarvis",
                    "traverse": "jarvis"
                }
                for wrong, right in corrections.items():
                    if wrong in raw_command:
                        raw_command = raw_command.replace(wrong, right)
            
            if apply_correction and mode == "Full (AI + Phonetic)":
                if GUI_APP:
                    GUI_APP.set_state("THINKING", "AUTOCORRECTING...")
                print("[System] Applying AI autocorrect to combined command...")
                raw_command = ai_autocorrect(raw_command).lower()
                
            return raw_command
            
        except sr.WaitTimeoutError:
            return None
        except Exception:
            return None

def bring_window_to_front(window_name):
    """Directly commands the Windows OS to un-minimize, focus, and physically click a specific window"""
    try:
        user32 = ctypes.windll.user32
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        
        class RECT(ctypes.Structure):
            _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]
        
        def enum_cb(hwnd, lparam):
            if user32.IsWindowVisible(hwnd):
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    if window_name.lower() in buff.value.lower():
                        user32.keybd_event(0x12, 0, 0, 0) # ALT key down
                        user32.keybd_event(0x12, 0, 2, 0) # ALT key up
                        
                        user32.ShowWindow(hwnd, 9) # SW_RESTORE
                        user32.SetForegroundWindow(hwnd)
                        time.sleep(1.0)
                        
                        rect = RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        x = rect.right - 40
                        y = rect.bottom - 40
                        
                        user32.SetCursorPos(x, y)
                        user32.mouse_event(0x0002, 0, 0, 0, 0) # DOWN
                        user32.mouse_event(0x0004, 0, 0, 0, 0) # UP
                        
                        time.sleep(5.0)
                        user32.ShowWindow(hwnd, 3) # SW_MAXIMIZE
                        return False
            return True
        user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
    except Exception:
        pass

def smart_open(target_app):
    """Scans Start Menu and Windows App Registry locally before falling back to browser."""
    print(f"[System] Searching device for: '{target_app}'...")
    ps_script = f"""
    $target = "{target_app}"
    $shortcuts = Get-ChildItem -Path "$env:ProgramData\\Microsoft\\Windows\\Start Menu\\Programs", "$env:APPDATA\\Microsoft\\Windows\\Start Menu\\Programs" -Filter "*.lnk" -Recurse -ErrorAction SilentlyContinue
    $match = $shortcuts | Where-Object {{ $_.BaseName -match $target }} | Select-Object -First 1
    if ($match) {{
        Invoke-Item $match.FullName
        exit 0
    }}
    $app = Get-StartApps | Where-Object {{ $_.Name -match $target }} | Select-Object -First 1
    if ($app) {{
        Start-Process "shell:AppsFolder\\$($app.AppID)"
        exit 0
    }}
    exit 1
    """
    result = subprocess.run(["powershell", "-NoProfile", "-Command", ps_script], creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0:
        webbrowser.open(f"https://www.google.com/search?q={target_app}")

def send_to_blender(prompt):
    """Beams instructions via local network directly to Blender"""
    print(f"[System] Bridging command to Blender on Port 8081...")
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.settimeout(2.0)
        client.connect(('127.0.0.1', 8081))
        client.sendall(prompt.encode('utf-8'))
        client.close()
        return True
    except Exception:
        return False

def launch_blender_with_bridge(prompt):
    """Generates the bridge script and launches Blender with it automatically"""
    print("[System] Generating Blender bridge script...")
    coder = CONFIG.get("coder_model", "qwen2.5-coder")
    
    bridge_code = f"""import bpy
import urllib.request
import json
import re
import socket
import threading
import queue

OLLAMA_MODEL = "{coder}"
HOST = '127.0.0.1'
PORT = 8081

prompt_queue = queue.Queue()

def ask_ollama(prompt):
    url = "http://localhost:11434/api/generate"
    try:
        obj_list = [obj.name for obj in bpy.context.scene.objects]
        scene_context = f"CURRENT SCENE STATE: The scene currently contains these objects: {{', '.join(obj_list)}}. "
    except Exception:
        scene_context = ""
        
    system_prompt = (
        "You are a Blender 3D Python (bpy) coding assistant. "
        "Only output valid Python code wrapped in ```python ... ``` blocks. "
        "Do not include any explanations. Always import bpy. "
        "If the user asks to modify, scale, move, or delete an object, use the CURRENT SCENE STATE to target the exact object name. "
        "CRITICAL: If the user specifies a quantity (like '1 sphere'), select and modify EXACTLY that many objects by their specific name (e.g., bpy.data.objects['Sphere.001']). Do NOT use loops that delete everything with a similar name! "
        f"{{scene_context}}"
    )
    
    payload = {{"model": OLLAMA_MODEL, "prompt": prompt, "system": system_prompt, "stream": False, "temperature": 0.1}}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={{'Content-Type': 'application/json'}})
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get("response", "")
    except Exception:
        return ""

def process_queue():
    if not prompt_queue.empty():
        prompt = prompt_queue.get()
        response = ask_ollama(prompt)
        match = re.search(r'```python\\n(.*?)\\n```', response, re.DOTALL)
        if match:
            try:
                exec(match.group(1))
            except Exception:
                pass
    return 1.0

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, PORT))
        server.listen(1)
        while True:
            conn, addr = server.accept()
            data = conn.recv(1024).decode('utf-8')
            if data: prompt_queue.put(data)
            conn.close()
    except Exception:
        pass

for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

threading.Thread(target=start_server, daemon=True).start()
if bpy.app.timers.is_registered(process_queue): bpy.app.timers.unregister(process_queue)
bpy.app.timers.register(process_queue)
"""
    app_dir = get_app_dir()
    script_path = os.path.join(app_dir, "blender_bridge.py")
    with open(script_path, "w", encoding="utf-8") as f:
        f.write(bridge_code)
        
    blender_executable = "blender"
    possible_paths = glob.glob(r"C:\Program Files\Blender Foundation\*\blender.exe") + glob.glob(r"C:\Program Files (x86)\Steam\steamapps\common\Blender\blender.exe")
    if possible_paths: blender_executable = possible_paths[0]

    try:
        subprocess.Popen([blender_executable, "-P", script_path], creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception:
        return
    
    time.sleep(12)
    send_to_blender(prompt)
    bring_window_to_front("Blender")

def setup_map_server():
    """Automates the setup and launch of the God's Eye View map server."""
    print("\n[System] Initializing God's Eye View Tactical Map...")
    app_dir = get_app_dir()
    repo_dir = os.path.join(app_dir, "gods-eye-view")
    
    if not os.path.exists(repo_dir):
        print(f"[System] Downloading repository to: {repo_dir}")
        try:
            subprocess.run(["git", "clone", "https://github.com/bilawalsidhu/gods-eye-view.git", repo_dir], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as e:
            print(f"[System] Git Clone Failed: {e}")
            return
    else:
        print("[System] Map repository already exists. Skipping download.")
            
    print("[System] Running 'npm install'...")
    try:
        subprocess.run(["npm", "install"], cwd=repo_dir, shell=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
        print("[System] Running 'npm run dev' to start the local server...")
        subprocess.Popen(["npm", "run", "dev"], cwd=repo_dir, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
        
        print("[System] Waiting for Vite server to initialize on port 4173...")
        server_ready = False
        for _ in range(60):
            try:
                req = urllib.request.Request("http://localhost:4173/")
                with urllib.request.urlopen(req, timeout=1) as response:
                    if response.status == 200:
                        server_ready = True
                        break
            except Exception:
                pass
            time.sleep(0.5)
            
        if server_ready:
            print("[System] Satellite Uplink is ONLINE.")
            if GUI_APP:
                GUI_APP.root.after(0, GUI_APP.enable_map_tab)
        else:
            print("[System] Vite server failed to start or timed out.")
    except Exception as e:
        print(f"[System] Map Server Setup Error: {e}")

def sync_smart_home_devices():
    """Syncs the local dictionary of smart home devices based on platform settings"""
    global SMART_DEVICES
    SMART_DEVICES.clear()
    platform = CONFIG.get("smart_platform", "SmartThings")
    print(f"\n[System] Syncing {platform} devices...")
    
    if platform == "SmartThings":
        token = CONFIG.get("st_token", "")
        if not token: return
        try:
            req = urllib.request.Request("https://api.smartthings.com/v1/devices", headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                for item in data.get("items", []):
                    name = item.get("name", "").lower()
                    label = item.get("label", "").lower()
                    dev_id = item.get("deviceId", "")
                    if name: SMART_DEVICES[name] = {"id": dev_id, "type": "st"}
                    if label: SMART_DEVICES[label] = {"id": dev_id, "type": "st"}
            print(f"[System] Synced {len(SMART_DEVICES)} devices.")
        except Exception as e:
            print(f"[SmartThings Error]: {e}")
            
    elif platform == "Home Assistant":
        token = CONFIG.get("ha_token", "")
        url = CONFIG.get("ha_url", "").rstrip("/")
        if not token or not url: return
        try:
            req = urllib.request.Request(f"{url}/api/states", headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=5) as response:
                data = json.loads(response.read().decode('utf-8'))
                for item in data:
                    entity_id = item.get("entity_id", "")
                    name = item.get("attributes", {}).get("friendly_name", "").lower()
                    if name and (entity_id.startswith("light.") or entity_id.startswith("switch.")):
                        SMART_DEVICES[name] = {"id": entity_id, "type": "ha"}
            print(f"[System] Synced {len(SMART_DEVICES)} HA devices.")
        except Exception as e:
            print(f"[Home Assistant Error]: {e}")

def ask_ai(prompt):
    url = "http://localhost:11434/api/generate"
    system_prompt = "You are Jarvis, a highly efficient AI assistant. Keep responses brief, conversational, and direct. Do NOT translate or substitute words. Be completely literal."
    payload = {"model": CONFIG.get("chat_model", "llama3.2"), "prompt": prompt, "system": system_prompt, "stream": False, "temperature": 0.0, "num_predict": 150}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8')).get("response", "I'm sorry, I could not generate a response.")
    except Exception as e:
        return f"System Error connecting to local AI module: {e}"

def analyze_3d_complexity(prompt):
    url = "http://localhost:11434/api/generate"
    system_prompt = "You are a strict 3D classification router. Structural objects/physics = 'SIMPLE'. Organic/highly detailed = 'COMPLEX'. Reply with exactly one word."
    payload = {"model": CONFIG.get("chat_model", "llama3.2"), "prompt": prompt, "system": system_prompt, "stream": False, "temperature": 0.0, "num_predict": 5}
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode('utf-8')).get("response", "SIMPLE").strip().upper()
    except Exception:
        return "SIMPLE"

def process_command(command):
    command_clean = command.strip().lower()
    if GUI_APP:
        GUI_APP.update_request(command_clean)
        GUI_APP.set_state("THINKING", "PROCESSING COMMAND...")
    
    # 1. Smart Home Execution
    smart_keywords = ["turn on", "turn off", "lights", "switch", "lamp", "activate"]
    if any(word in command_clean for word in smart_keywords) and SMART_DEVICES:
        url = "http://localhost:11434/api/generate"
        system_prompt = "Extract the smart home device name and the action (on/off) from the prompt. Reply ONLY in this exact format: device_name|action"
        payload = {"model": CONFIG.get("chat_model", "llama3.2"), "prompt": command_clean, "system": system_prompt, "stream": False, "temperature": 0.0, "num_predict": 15}
        try:
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8')).get("response", "").strip().lower()
                if "|" in result:
                    dev_name, action = result.split("|", 1)
                    dev_name, action = dev_name.strip(), action.strip()
                    matches = difflib.get_close_matches(dev_name, SMART_DEVICES.keys(), n=1, cutoff=0.5)
                    if matches:
                        target = matches[0]
                        dev_info = SMART_DEVICES[target]
                        if dev_info["type"] == "st":
                            st_token = CONFIG.get("st_token", "")
                            state = "on" if action == "on" else "off"
                            st_payload = {"commands": [{"component": "main", "capability": "switch", "command": state}]}
                            st_req = urllib.request.Request(f"https://api.smartthings.com/v1/devices/{dev_info['id']}/commands", data=json.dumps(st_payload).encode('utf-8'), headers={"Authorization": f"Bearer {st_token}", "Content-Type": "application/json"}, method="POST")
                            urllib.request.urlopen(st_req, timeout=5)
                        elif dev_info["type"] == "ha":
                            ha_token = CONFIG.get("ha_token", "")
                            ha_url = CONFIG.get("ha_url", "").rstrip("/")
                            domain = dev_info["id"].split(".")[0]
                            service = "turn_on" if action == "on" else "turn_off"
                            ha_payload = {"entity_id": dev_info["id"]}
                            ha_req = urllib.request.Request(f"{ha_url}/api/services/{domain}/{service}", data=json.dumps(ha_payload).encode('utf-8'), headers={"Authorization": f"Bearer {ha_token}", "Content-Type": "application/json"}, method="POST")
                            urllib.request.urlopen(ha_req, timeout=5)
                        return f"Turning {action} the {target}."
        except Exception as e:
            print(f"[Smart Home Error]: {e}")

    # 2. Hardware/OS Bypass
    if command_clean.startswith("open ") or command_clean.startswith("launch "):
        target = command_clean.replace("open ", "").replace("launch ", "").strip()
        smart_open(target)
        return f"Opening {target}." 
    
    # 3. 3D Model Generation Pipeline
    blender_keywords = ["blender", "3d", "simulate", "simulation", "low poly", "mesh", "rigid body", "physics", "generate", "spawn", "model", "render", "ball", "sphere", "cube", "balls", "delete", "remove", "scale", "rotate", "extrude", "resize"]
    if any(word in command_clean for word in blender_keywords):
        blender_prompt = command_clean.replace("in blender", "").replace("tell blender to", "").replace("blender", "").strip()
        complexity = analyze_3d_complexity(blender_prompt)
        
        if "COMPLEX" in complexity:
            return "This requires complex organic geometry. I am routing this request to your local Text-to-3D model for offline generation. Please note, I still need you to install the Shap-E model before I can complete this!"
        else:
            success = send_to_blender(blender_prompt)
            if success:
                bring_window_to_front("Blender") 
                return "Sending instructions to Blender. Please wait a moment while it generates."
            else:
                threading.Thread(target=launch_blender_with_bridge, args=(blender_prompt,), daemon=True).start()
                return "Blender is not currently open. I am launching it for you now, securely injecting the Python bridge script, and rendering your request. Just a moment."

    # 4. General AI Conversation
    return ask_ai(command_clean)

def is_listening_allowed():
    key_setting = CONFIG.get("listen_key", "Num Lock (OFF to Listen)")
    if key_setting == "Always Listen": return True
    vk_map = {"Num Lock (OFF to Listen)": 0x90, "Caps Lock (OFF to Listen)": 0x14, "Scroll Lock (OFF to Listen)": 0x91}
    return not bool(ctypes.windll.user32.GetKeyState(vk_map.get(key_setting, 0x90)) & 0x0001)

def background_voice_loop():
    time.sleep(1.0)
    init_vosk_model()
    speak("System is online. Offline voice recognition initialized.")
    try:
        recognizer = sr.Recognizer()
        with sr.Microphone() as source: recognizer.adjust_for_ambient_noise(source, duration=2)
    except Exception: pass
    was_muted = False
        
    while True:
        if not is_listening_allowed():
            if not was_muted:
                if GUI_APP: GUI_APP.set_state("MUTED", f"MUTED ({CONFIG.get('listen_key').split(' (')[0].upper()} ON)")
                was_muted = True
            time.sleep(0.5)
            continue
        if was_muted: was_muted = False
            
        wake_word = CONFIG.get("wake_word", "jarvis").strip().lower()
        if GUI_APP: GUI_APP.set_state("IDLE", f"LISTENING FOR '{wake_word.upper()}'...")
            
        trigger = listen_for_audio("", timeout_duration=4, apply_correction=False)
        if trigger:
            if "quit" in trigger or "shut down" in trigger:
                speak("Shutting down operations. Goodbye.")
                if GUI_APP: GUI_APP.root.quit()
                sys.exit(0)
                
            if wake_word in trigger:
                command = trigger.replace(wake_word, "").strip()
                if not command:
                    speak("Yes, sir?")
                    if GUI_APP: GUI_APP.set_state("LISTENING", "LISTENING FOR COMMAND...")
                    command = listen_for_audio("", timeout_duration=5, apply_correction=True)
                else:
                    if CONFIG.get("autocorrect_mode") == "Full (AI + Phonetic)": command = ai_autocorrect(command).lower()
                
                if command:
                    response = process_command(command)
                    if response: speak(response)
                    
                    while True:
                        if not is_listening_allowed(): break
                        speak("Anything else?")
                        if GUI_APP: GUI_APP.set_state("LISTENING", "LISTENING FOR FOLLOW-UP...")
                        follow_up = listen_for_audio("", timeout_duration=3, apply_correction=True)
                        if not follow_up or any(w in follow_up for w in ["no", "that's it", "stop", "nothing"]):
                            break 
                        else:
                            response = process_command(follow_up)
                            if response: speak(response)

def _draw_oval_pill(canvas, x1, y1, x2, y2, fill, outline="", width=0, tags=None):
    w, h = x2 - x1, y2 - y1
    if w <= h + 2:
        canvas.create_oval(x1, y1, x2, y2, fill=fill, outline=outline if outline else fill, width=width, tags=tags)
        return
    r = h / 2.0
    if outline and width > 0:
        canvas.create_oval(x1, y1, x1 + h, y2, fill=outline, outline=outline, tags=tags)
        canvas.create_oval(x2 - h, y1, x2, y2, fill=outline, outline=outline, tags=tags)
        canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=outline, outline=outline, tags=tags)
        b, ih = width, h - 2 * width
        ir = ih / 2.0
        if ih > 2:
            canvas.create_oval(x1 + b, y1 + b, x1 + b + ih, y2 - b, fill=fill, outline=fill, tags=tags)
            canvas.create_oval(x2 - b - ih, y1 + b, x2 - b, y2 - b, fill=fill, outline=fill, tags=tags)
            canvas.create_rectangle(x1 + b + ir, y1 + b, x2 - b - ir, y2 - b, fill=fill, outline=fill, tags=tags)
    else:
        canvas.create_oval(x1, y1, x1 + h, y2, fill=fill, outline=fill, tags=tags)
        canvas.create_oval(x2 - h, y1, x2, y2, fill=fill, outline=fill, tags=tags)
        canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill, tags=tags)

class RoundedButton(tk.Canvas):
    def __init__(self, parent, text="", command=None, width=90, height=38, radius=19, font=("Segoe UI", 10, "bold")):
        super().__init__(parent, width=width, height=height, highlightthickness=0, bd=0, cursor="hand2")
        self.text = text
        self.command = command
        self.font = font
        self.bg_fill, self.fg_color, self.hover_fill, self.hover_fg, self.outline_color = "#101826", "#00d4ff", "#00d4ff", "#000000", ""
        self._hovered = False
        self.bind("<Enter>", lambda e: setattr(self, '_hovered', True) or self.redraw())
        self.bind("<Leave>", lambda e: setattr(self, '_hovered', False) or self.redraw())
        self.bind("<ButtonRelease-1>", lambda e: self.command() if self.command else None)
        self.bind("<Configure>", lambda e: self.redraw())

    def set_colors(self, parent_bg, bg_fill, fg_color, hover_fill=None, hover_fg=None, outline_color=""):
        self.configure(bg=parent_bg)
        self.bg_fill, self.fg_color, self.outline_color = bg_fill, fg_color, outline_color
        self.hover_fill = hover_fill if hover_fill else fg_color
        self.hover_fg = hover_fg if hover_fg else bg_fill
        self.redraw()

    def set_text(self, text):
        self.text = text
        self.redraw()

    def redraw(self):
        self.delete("all")
        w, h = max(24, self.winfo_width()), max(24, self.winfo_height())
        fill = self.hover_fill if self._hovered else self.bg_fill
        fg = self.hover_fg if self._hovered else self.fg_color
        _draw_oval_pill(self, 2, 2, w - 2, h - 2, fill=fill, outline=self.outline_color, width=1.5 if self.outline_color else 0)
        self.create_text(w / 2, h / 2, text=self.text, font=self.font, fill=fg)

class RoundedEntry(tk.Canvas):
    def __init__(self, parent, textvariable=None, font=("Segoe UI", 11), height=44, radius=22):
        super().__init__(parent, height=height, highlightthickness=0, bd=0)
        self.fill_color, self.outline_color = "#162236", "#00d4ff"
        self.entry = tk.Entry(self, textvariable=textvariable, font=font, relief=tk.FLAT, bd=0, highlightthickness=0)
        self.bind("<Configure>", self._on_configure)

    def set_colors(self, parent_bg, fill_color, fg_color, insert_color, outline_color):
        self.configure(bg=parent_bg)
        self.fill_color, self.outline_color = fill_color, outline_color
        self.entry.configure(bg=fill_color, fg=fg_color, insertbackground=insert_color)
        self._on_configure()

    def _on_configure(self, event=None):
        self.delete("bg_shape")
        w = max(50, self.winfo_width())
        h = max(28, self.winfo_height())
        _draw_oval_pill(self, 2, 2, w - 2, h - 2, fill=self.fill_color, outline=self.outline_color, width=1.5, tags="bg_shape")
        self.delete("entry_win")
        pad_x = max(28, int(h * 0.85))
        self.create_window(w / 2, h / 2, window=self.entry, width=max(10, w - pad_x), height=max(10, h - 14), tags="entry_win")

class JarvisGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("J.A.R.V.I.S.")
        self.root.geometry("500x680")
        self.root.minsize(300, 340)
        self.root.resizable(True, True)
        
        # Check both the bundled PyInstaller folder and the main folder for the latest icon.ico
        icon_path = os.path.join(get_app_dir(), "icon.ico")
        if not os.path.exists(icon_path):
            icon_path = os.path.join(get_resource_dir(), "icon.ico")
            
        if os.path.exists(icon_path):
            try:
                self.root.iconbitmap(default=icon_path)
            except Exception:
                pass

        self.state = "IDLE"
        self.hud_mode = False
        self.settings_open = False
        self.active_tab = "AI"
        self.hud_size = 240
        self.hud_hovered = False
        self._drag_x = self._drag_y = 0
        self._resizing_hud = False
        
        self.build_ui()
        self.apply_theme()
        self.animate_logo()
        
    def build_ui(self):
        self.header_frame = tk.Frame(self.root, height=48)
        self.header_frame.pack(side=tk.TOP, fill=tk.X, padx=16, pady=(12, 0))
        
        self.hud_btn = RoundedButton(self.header_frame, text="👁", width=40, height=40, font=("Segoe UI Symbol", 13), command=self.toggle_hud_mode)
        self.hud_btn.pack(side=tk.LEFT)
        
        self.settings_btn = RoundedButton(self.header_frame, text="⚙", width=40, height=40, font=("Segoe UI Symbol", 13), command=self.toggle_settings)
        self.settings_btn.pack(side=tk.RIGHT)
        
        self.tab_frame = tk.Frame(self.header_frame)
        self.tab_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        self.ai_tab = RoundedButton(self.tab_frame, text="AI", width=70, height=32, font=("Consolas", 10, "bold"), command=self.show_ai_view)
        self.ai_tab.pack(side=tk.LEFT, padx=4)
        
        self.map_tab = RoundedButton(self.tab_frame, text="MAP", width=70, height=32, font=("Consolas", 10, "bold"), command=self.show_map_view)
        self.map_tab.pack(side=tk.LEFT, padx=4)
        self.map_tab.pack_forget()

        self.map_view = tk.Frame(self.root)
        self.map_launch_btn = RoundedButton(self.map_view, text="LAUNCH TACTICAL OVERLAY", width=260, height=42, font=("Consolas", 10, "bold"), command=self.launch_map_overlay)
        self.map_launch_btn.place(relx=0.5, rely=0.5, anchor=tk.CENTER)

        self.map_container = tk.Frame(self.map_view, bg="#000000")
        self.map_container.place(relx=0, rely=0, relwidth=1.0, relheight=1.0)
        self.map_container.lower()
        
        self.main_view = tk.Frame(self.root)
        self.main_view.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        
        self.input_frame = tk.Frame(self.main_view)
        self.input_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(24, 34))
        
        self.send_btn = RoundedButton(self.input_frame, text="SEND", width=82, height=42, font=("Consolas", 10, "bold"), command=self.submit_typed_command)
        self.send_btn.pack(side=tk.RIGHT, padx=(8, 0))
        
        self.entry_var = tk.StringVar()
        self.entry_container = RoundedEntry(self.input_frame, textvariable=self.entry_var, font=("Consolas", 11), height=42)
        self.entry_container.pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.entry_box = self.entry_container.entry
        self.entry_box.bind("<Return>", self.submit_typed_command)
        
        self.chat_frame = tk.Frame(self.main_view, padx=10, pady=4, bd=0, highlightthickness=0)
        self.chat_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(2, 24))
        self.chat_frame.bind("<Configure>", lambda e: self.req_label.config(wraplength=max(140, e.width - 24)) or self.rep_label.config(wraplength=max(140, e.width - 24)))
        
        self.req_header = tk.Label(self.chat_frame, text="> REQ_LOG:", font=("Consolas", 9, "bold"), anchor="w")
        self.req_header.pack(fill=tk.X)
        self.req_label = tk.Label(self.chat_frame, text="\"Awaiting input...\"", font=("Consolas", 10), justify=tk.LEFT, anchor="w", pady=2)
        self.req_label.pack(fill=tk.X, pady=(0, 6))
        
        self.rep_header = tk.Label(self.chat_frame, text="> SYS_RSP:", font=("Consolas", 9, "bold"), anchor="w")
        self.rep_header.pack(fill=tk.X)
        self.rep_label = tk.Label(self.chat_frame, text="\"System is booting up...\"", font=("Consolas", 10), justify=tk.LEFT, anchor="w", pady=2)
        self.rep_label.pack(fill=tk.X)
        
        self.status_label = tk.Label(self.main_view, text="[ INITIALIZING ]", font=("Consolas", 10, "bold"))
        self.status_label.pack(side=tk.BOTTOM, pady=(0, 4))
        
        self.canvas = tk.Canvas(self.main_view, width=180, height=180, highlightthickness=0)
        self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=2)
        self.canvas.bind("<ButtonPress-1>", self.start_drag)
        self.canvas.bind("<B1-Motion>", self.do_drag)
        self.canvas.bind("<ButtonRelease-1>", self.stop_drag)
        self.canvas.bind("<Motion>", self.update_cursor)
        self.canvas.bind("<Double-Button-1>", lambda e: self.toggle_hud_mode() if self.hud_mode else None)

        self.settings_frame = tk.Frame(self.root, padx=22, pady=10)
        self.build_settings_panel()

    def build_settings_panel(self):
        self.settings_labels = []
        
        self.settings_canvas = tk.Canvas(self.settings_frame, highlightthickness=0)
        self.settings_scrollbar = ttk.Scrollbar(self.settings_frame, orient="vertical", command=self.settings_canvas.yview)
        self.settings_inner = tk.Frame(self.settings_canvas)
        
        self.settings_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.settings_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.settings_canvas.create_window((0, 0), window=self.settings_inner, anchor="nw", tags="inner_frame")
        self.settings_canvas.configure(yscrollcommand=self.settings_scrollbar.set)
        
        self.settings_inner.bind("<Configure>", lambda e: self.settings_canvas.configure(scrollregion=self.settings_canvas.bbox("all")))
        self.settings_canvas.bind("<Configure>", lambda e: self.settings_canvas.itemconfig("inner_frame", width=e.width))

        def _on_mousewheel(event):
            if self.settings_open: self.settings_canvas.yview_scroll(int(-1*(event.delta/120)), "units")
        self.root.bind_all("<MouseWheel>", _on_mousewheel)

        def make_label(text):
            lbl = tk.Label(self.settings_inner, text=text, font=("Consolas", 9, "bold"), anchor="w")
            lbl.pack(fill=tk.X, pady=(8, 2))
            self.settings_labels.append(lbl)

        make_label("1. WAKE WORD:")
        self.wake_var = tk.StringVar(value=CONFIG["wake_word"])
        self.wake_entry_container = RoundedEntry(self.settings_inner, textvariable=self.wake_var, font=("Consolas", 10), height=38)
        self.wake_entry_container.pack(fill=tk.X)

        local_models = ["llama3.2", "qwen2.5-coder"]
        try:
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=2) as response:
                data = json.loads(response.read().decode('utf-8'))
                local_models = [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        if "llama3.2:latest" not in local_models and "llama3.2" not in local_models: local_models.append("llama3.2")
        if "qwen2.5-coder:latest" not in local_models and "qwen2.5-coder" not in local_models: local_models.append("qwen2.5-coder")

        make_label("2. CONVERSATIONAL AI MODEL:")
        self.chat_var = tk.StringVar(value=CONFIG["chat_model"])
        self.chat_menu = ttk.Combobox(self.settings_inner, textvariable=self.chat_var, values=local_models, state="readonly")
        self.chat_menu.pack(fill=tk.X, ipady=3)

        make_label("3. BLENDER 3D CODING MODEL:")
        self.coder_var = tk.StringVar(value=CONFIG["coder_model"])
        self.coder_menu = ttk.Combobox(self.settings_inner, textvariable=self.coder_var, values=local_models, state="readonly")
        self.coder_menu.pack(fill=tk.X, ipady=3)

        make_label("4. DOWNLOAD NEW OLLAMA MODEL:")
        dl_row = tk.Frame(self.settings_inner)
        dl_row.pack(fill=tk.X)
        self.settings_dl_row = dl_row
        
        self.dl_btn = RoundedButton(dl_row, text="DOWNLOAD", width=96, height=38, radius=19, font=("Consolas", 9, "bold"), command=self.download_model)
        self.dl_btn.pack(side=tk.RIGHT)
        
        self.dl_var = tk.StringVar()
        self.dl_entry_container = RoundedEntry(dl_row, textvariable=self.dl_var, font=("Consolas", 10), height=38)
        self.dl_entry_container.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        make_label("5. ACCENT COLOR THEME:")
        self.color_var = tk.StringVar(value=next((k for k, v in ACCENT_COLORS.items() if v == CONFIG["accent_color"]), "Jarvis Cyan"))
        self.color_menu = ttk.Combobox(self.settings_inner, textvariable=self.color_var, values=list(ACCENT_COLORS.keys()), state="readonly")
        self.color_menu.pack(fill=tk.X, ipady=3)

        make_label("6. DISPLAY MODE:")
        self.theme_var = tk.StringVar(value=CONFIG["theme"])
        self.theme_menu = ttk.Combobox(self.settings_inner, textvariable=self.theme_var, values=["Dark", "Light"], state="readonly")
        self.theme_menu.pack(fill=tk.X, ipady=3)

        make_label("7. VOICE STYLE (WINDOWS SAPI5):")
        voice_names = [f"{idx}: {name}" for idx, name, _ in AVAILABLE_VOICES]
        curr_v_idx = CONFIG.get("voice_index", 0)
        self.voice_var = tk.StringVar(value=voice_names[curr_v_idx] if curr_v_idx < len(voice_names) else (voice_names[0] if voice_names else "0: Default"))
        self.voice_menu = ttk.Combobox(self.settings_inner, textvariable=self.voice_var, values=voice_names, state="readonly")
        self.voice_menu.pack(fill=tk.X, ipady=3)

        make_label("8. SPEECH RECOGNITION ENGINE:")
        self.lang_var = tk.StringVar(value="Vosk Offline (en-US)")
        self.lang_menu = ttk.Combobox(self.settings_inner, textvariable=self.lang_var, values=["Vosk Offline (en-US)"], state="readonly")
        self.lang_menu.pack(fill=tk.X, ipady=3)

        make_label("9. AUTOCORRECT PRECISION:")
        self.auto_var = tk.StringVar(value=CONFIG["autocorrect_mode"])
        self.auto_menu = ttk.Combobox(self.settings_inner, textvariable=self.auto_var, values=["Off", "Phonetic Only", "Full (AI + Phonetic)"], state="readonly")
        self.auto_menu.pack(fill=tk.X, ipady=3)

        make_label("10. LISTENING ACTIVATION KEY:")
        self.key_var = tk.StringVar(value=CONFIG["listen_key"])
        self.key_menu = ttk.Combobox(self.settings_inner, textvariable=self.key_var, values=["Always Listen", "Num Lock (OFF to Listen)", "Caps Lock (OFF to Listen)", "Scroll Lock (OFF to Listen)"], state="readonly")
        self.key_menu.pack(fill=tk.X, ipady=3)

        make_label("11. SMART HOME PLATFORM:")
        self.sh_plat_var = tk.StringVar(value=CONFIG.get("smart_platform", "SmartThings"))
        self.sh_plat_menu = ttk.Combobox(self.settings_inner, textvariable=self.sh_plat_var, values=["SmartThings", "Home Assistant"], state="readonly")
        self.sh_plat_menu.pack(fill=tk.X, ipady=3)

        make_label("12. SMARTTHINGS TOKEN (account.smartthings.com/tokens):")
        self.st_var = tk.StringVar(value=CONFIG.get("st_token", ""))
        self.st_entry = RoundedEntry(self.settings_inner, textvariable=self.st_var, font=("Consolas", 10), height=38)
        self.st_entry.pack(fill=tk.X)

        make_label("13. HOME ASSISTANT LONG-LIVED TOKEN:")
        self.ha_var = tk.StringVar(value=CONFIG.get("ha_token", ""))
        self.ha_entry = RoundedEntry(self.settings_inner, textvariable=self.ha_var, font=("Consolas", 10), height=38)
        self.ha_entry.pack(fill=tk.X)

        make_label("14. HOME ASSISTANT LOCAL IP (e.g., http://192.168.1.100:8123):")
        sh_row = tk.Frame(self.settings_inner)
        sh_row.pack(fill=tk.X)
        self.settings_sh_row = sh_row
        self.sync_btn = RoundedButton(sh_row, text="SYNC", width=96, height=38, radius=19, font=("Consolas", 9, "bold"), command=self.sync_smart_home)
        self.sync_btn.pack(side=tk.RIGHT)
        self.ha_ip_var = tk.StringVar(value=CONFIG.get("ha_url", "http://homeassistant.local:8123"))
        self.ha_ip_entry = RoundedEntry(sh_row, textvariable=self.ha_ip_var, font=("Consolas", 10), height=38)
        self.ha_ip_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        btn_row = tk.Frame(self.settings_inner)
        btn_row.pack(fill=tk.X, pady=(22, 10))
        self.settings_btn_row = btn_row

        self.cancel_btn = RoundedButton(btn_row, text="BACK", width=96, height=42, font=("Consolas", 10, "bold"), command=self.toggle_settings)
        self.cancel_btn.pack(side=tk.RIGHT)
        
        self.save_btn = RoundedButton(btn_row, text="APPLY & RETURN", width=220, height=42, font=("Consolas", 10, "bold"), command=self.save_settings)
        self.save_btn.pack(side=tk.RIGHT, padx=(0, 10))

    def download_model(self):
        target = self.dl_var.get().strip().lower()
        if not target: return
        self.dl_btn.set_text("DOWNLOADING...")
        def _pull():
            try:
                subprocess.run(["ollama", "pull", target], check=True, creationflags=subprocess.CREATE_NO_WINDOW)
                self.root.after(0, lambda: self.dl_btn.set_text("DOWNLOADED!"))
                self.root.after(2000, lambda: self.dl_btn.set_text("DOWNLOAD"))
            except Exception:
                self.root.after(0, lambda: self.dl_btn.set_text("ERROR"))
                self.root.after(2000, lambda: self.dl_btn.set_text("DOWNLOAD"))
        threading.Thread(target=_pull, daemon=True).start()

    def sync_smart_home(self):
        self.save_settings(close=False)
        self.sync_btn.set_text("SYNCING...")
        def _sync():
            sync_smart_home_devices()
            self.root.after(0, lambda: self.sync_btn.set_text("SYNCED!"))
            self.root.after(2000, lambda: self.sync_btn.set_text("SYNC"))
        threading.Thread(target=_sync, daemon=True).start()

    def save_settings(self, close=True):
        CONFIG["wake_word"] = self.wake_var.get().strip().lower() or "jarvis"
        CONFIG["accent_color"] = ACCENT_COLORS.get(self.color_var.get(), "#00d4ff")
        CONFIG["theme"] = self.theme_var.get()
        CONFIG["chat_model"] = self.chat_var.get()
        CONFIG["coder_model"] = self.coder_var.get()
        try: CONFIG["voice_index"] = int(self.voice_var.get().split(":")[0])
        except Exception: CONFIG["voice_index"] = 0
        CONFIG["autocorrect_mode"] = self.auto_var.get()
        CONFIG["listen_key"] = self.key_var.get()
        CONFIG["smart_platform"] = self.sh_plat_var.get()
        CONFIG["st_token"] = self.st_var.get().strip()
        CONFIG["ha_token"] = self.ha_var.get().strip()
        CONFIG["ha_url"] = self.ha_ip_var.get().strip()
        
        if close:
            self.toggle_settings()
            self.apply_theme()

    def show_ai_view(self):
        if self.settings_open or self.hud_mode: return
        self.active_tab = "AI"
        self.settings_btn.pack(side=tk.RIGHT)
        self.map_view.pack_forget()
        self.main_view.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.apply_theme()

    def show_map_view(self):
        if self.settings_open or self.hud_mode: return
        self.active_tab = "MAP"
        self.settings_btn.pack_forget()
        self.main_view.pack_forget()
        self.map_view.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.apply_theme()
        if not getattr(self, 'map_launched', False):
            self.launch_map_overlay()

    def toggle_settings(self):
        if self.hud_mode: return
        self.settings_open = not self.settings_open
        if self.settings_open:
            self.tab_frame.place_forget()
            self.main_view.pack_forget()
            self.map_view.pack_forget()
            self.settings_frame.pack(fill=tk.BOTH, expand=True)
            self.settings_btn.set_text("✕")
        else:
            self.tab_frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
            self.settings_frame.pack_forget()
            if self.active_tab == "AI": self.main_view.pack(fill=tk.BOTH, expand=True)
            else: self.map_view.pack(fill=tk.BOTH, expand=True)
            self.settings_btn.set_text("⚙")
        self.apply_theme()

    def apply_theme(self):
        theme_name = CONFIG.get("theme", "Dark")
        t = THEMES.get(theme_name, THEMES["Dark"])
        accent = CONFIG.get("accent_color", "#00d4ff")
        
        if self.hud_mode:
            trans_key = t["transparent_key"]
            self.root.config(bg=trans_key)
            self.main_view.config(bg=trans_key)
            self.map_view.config(bg=trans_key)
            self.canvas.config(bg=trans_key)
            self.root.attributes("-transparentcolor", trans_key)
            self.root.attributes("-topmost", True)
            self.root.overrideredirect(True)
        else:
            self.root.attributes("-transparentcolor", "")
            self.root.attributes("-topmost", False)
            self.root.overrideredirect(False)
            self.root.config(bg=t["bg"])
            self.main_view.config(bg=t["bg"])
            self.map_view.config(bg=t["bg"])
            self.canvas.config(bg=t["bg"])
            
        self.header_frame.config(bg=t["bg"])
        self.tab_frame.config(bg=t["bg"])
        self.hud_btn.set_colors(t["bg"], t["panel"], accent, hover_fill=accent, hover_fg=t["bg"])
        self.settings_btn.set_colors(t["bg"], t["panel"], accent, hover_fill=accent, hover_fg=t["bg"])
        
        if self.active_tab == "AI":
            self.ai_tab.set_colors(t["bg"], accent, "#000000", hover_fill=accent, hover_fg="#000000")
            self.map_tab.set_colors(t["bg"], t["panel"], t["subtext"], hover_fill=t["subtext"], hover_fg="#000000")
        else:
            self.ai_tab.set_colors(t["bg"], t["panel"], t["subtext"], hover_fill=t["subtext"], hover_fg="#000000")
            self.map_tab.set_colors(t["bg"], accent, "#000000", hover_fill=accent, hover_fg="#000000")
            
        self.map_container.config(bg=t["bg"])
        self.map_launch_btn.set_colors(t["bg"], t["panel"], accent, hover_fill=accent, hover_fg="#000000")
        self.status_label.config(bg=t["bg"], fg=accent)
        self.chat_frame.config(bg=t["bg"])
        self.req_header.config(bg=t["bg"], fg=t["subtext"])
        self.req_label.config(bg=t["bg"], fg=t["text"])
        self.rep_header.config(bg=t["bg"], fg=accent)
        self.rep_label.config(bg=t["bg"], fg=t["text"])
        self.input_frame.config(bg=t["bg"])
        self.entry_container.set_colors(t["bg"], t["input_bg"], t["text"], accent, accent)
        self.send_btn.set_colors(t["bg"], accent, "#000000", hover_fill=t["text"], hover_fg="#000000")

        self.settings_frame.config(bg=t["bg"])
        self.settings_inner.config(bg=t["bg"])
        self.settings_canvas.config(bg=t["bg"])
        self.settings_btn_row.config(bg=t["bg"])
        self.settings_dl_row.config(bg=t["bg"])
        self.settings_sh_row.config(bg=t["bg"])
        for lbl in self.settings_labels: lbl.config(bg=t["bg"], fg=accent)
        self.wake_entry_container.set_colors(t["bg"], t["input_bg"], t["text"], accent, accent)
        self.dl_entry_container.set_colors(t["bg"], t["input_bg"], t["text"], accent, accent)
        self.dl_btn.set_colors(t["bg"], accent, "#000000", hover_fill=t["text"], hover_fg="#000000")
        self.st_entry.set_colors(t["bg"], t["input_bg"], t["text"], accent, accent)
        self.ha_entry.set_colors(t["bg"], t["input_bg"], t["text"], accent, accent)
        self.ha_ip_entry.set_colors(t["bg"], t["input_bg"], t["text"], accent, accent)
        
        self.sync_btn.set_colors(t["bg"], accent, "#000000", hover_fill=t["text"], hover_fg="#000000")
        self.save_btn.set_colors(t["bg"], accent, "#000000", hover_fill=t["text"], hover_fg="#000000")
        self.cancel_btn.set_colors(t["bg"], t["panel"], t["text"], hover_fill=t["subtext"], hover_fg=t["bg"])

        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            value = ctypes.c_int(1 if theme_name == "Dark" else 0)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), 4) # Windows 11
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(value), 4) # Fallback Windows 10
        except Exception:
            pass

    def toggle_hud_mode(self):
        if self.settings_open: self.toggle_settings()
        self.hud_mode = not self.hud_mode
        self.hud_hovered = False
        if self.hud_mode:
            self.header_frame.pack_forget()
            self.status_label.pack_forget()
            self.chat_frame.pack_forget()
            self.input_frame.pack_forget()
            self.root.minsize(120, 120)
            self.root.geometry(f"{self.hud_size}x{self.hud_size}")
        else:
            self.root.minsize(300, 340)
            self.root.geometry("500x680")
            self.header_frame.pack(side=tk.TOP, fill=tk.X, padx=16, pady=(12, 0), before=self.main_view if self.active_tab == "AI" else self.map_view)
            self.canvas.pack_forget()
            self.input_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=(6, 34))
            self.chat_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=14, pady=2)
            self.status_label.pack(side=tk.BOTTOM, pady=(0, 4))
            self.canvas.pack(side=tk.TOP, fill=tk.BOTH, expand=True, pady=2)
            if self.active_tab == "AI":
                self.map_view.pack_forget()
                self.main_view.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
            else:
                self.main_view.pack_forget()
                self.map_view.pack(side=tk.TOP, fill=tk.BOTH, expand=True)
        self.apply_theme()

    def _is_in_resize_zone(self, x, y, cx, cy, r_pulse, w, h):
        grip_box_x = cx + r_pulse + 16
        grip_box_y = cy + r_pulse + 16
        return (grip_box_x - 30 <= x <= grip_box_x + 12) and (grip_box_y - 30 <= y <= grip_box_y + 12)

    def update_cursor(self, event):
        if not self.hud_mode:
            self.canvas.config(cursor="")
            return
        w, h = max(120, self.canvas.winfo_width()), max(120, self.canvas.winfo_height())
        scale = min(w, h) / 220.0
        r_pulse = 80 * scale
        if self._is_in_resize_zone(event.x, event.y, w/2, h/2, r_pulse, w, h): self.canvas.config(cursor="size_nw_se")
        else: self.canvas.config(cursor="fleur")

    def start_drag(self, event):
        w, h = max(120, self.canvas.winfo_width()), max(120, self.canvas.winfo_height())
        scale = min(w, h) / 220.0
        r_pulse = 80 * scale
        if self.hud_mode and self._is_in_resize_zone(event.x, event.y, w/2, h/2, r_pulse, w, h):
            self._resizing_hud = True
        else:
            self._resizing_hud, self._drag_x, self._drag_y = False, event.x, event.y

    def stop_drag(self, event): self._resizing_hud = False

    def do_drag(self, event):
        if not self.hud_mode: return
        if self._resizing_hud:
            new_size = max(130, min(800, max(event.x_root - self.root.winfo_x(), event.y_root - self.root.winfo_y())))
            self.hud_size = new_size
            self.root.geometry(f"{new_size}x{new_size}")
        else:
            self.root.geometry(f"+{self.root.winfo_x() + event.x - self._drag_x}+{self.root.winfo_y() + event.y - self._drag_y}")

    def animate_logo(self):
        self.canvas.delete("all")
        w, h = max(120, self.canvas.winfo_width()), max(120, self.canvas.winfo_height())
        cx, cy, scale = w / 2, h / 2, min(w, h) / 220.0
        accent = CONFIG.get("accent_color", "#00d4ff")
        panel_bg = THEMES.get(CONFIG.get("theme", "Dark"), THEMES["Dark"])["panel"]
        
        if self.state == "MUTED": ring_color, text_color = "#333333", accent
        elif self.state == "SPEAKING": ring_color, text_color = accent, "#333333"
        elif self.state == "LISTENING": ring_color, text_color = "#00ff88", "#333333"
        elif self.state == "THINKING": ring_color, text_color = "#ffaa00", accent
        else: ring_color, text_color = accent, "#333333"

        base_r = 80 * scale
        if self.hud_mode:
            try:
                rx, ry = self.root.winfo_pointerxy()[0] - self.canvas.winfo_rootx(), self.root.winfo_pointerxy()[1] - self.canvas.winfo_rooty()
                self.hud_hovered = self._resizing_hud or (cx - (base_r + 26) <= rx <= cx + (base_r + 26) and cy - (base_r + 26) <= ry <= cy + (base_r + 26))
            except Exception:
                self.hud_hovered = False

        self.canvas.create_oval(cx - base_r, cy - base_r, cx + base_r, cy + base_r, fill=ring_color, outline="")
        self.canvas.create_text(cx, cy, text="J.A.R.V.I.S.", font=("Consolas", max(10, int(15 * scale)), "bold"), fill=text_color)

        if self.hud_mode and self.hud_hovered:
            grip_x, grip_y = cx + base_r + 12, cy + base_r + 12
            self.canvas.create_oval(grip_x - 14, grip_y - 14, grip_x + 8, grip_y + 8, fill=panel_bg, outline=ring_color, width=1)
            self.canvas.create_text(grip_x - 3, grip_y - 3, text="◢", font=("Segoe UI Symbol", max(9, int(10 * scale))), fill=ring_color)

        self.root.after(100, self.animate_logo)

    def set_state(self, new_state, status_text=None):
        def _update():
            self.state = new_state
            if status_text: self.status_label.config(text=status_text)
        self.root.after(0, _update)

    def enable_map_tab(self):
        self.map_tab.pack(side=tk.LEFT, padx=4)
        self.apply_theme()

    def launch_map_overlay(self):
        self.map_launched = True
        self.map_launch_btn.set_text("[ CAPTURING CHROMIUM SATELLITE... ]")
        subprocess.Popen(["start", "msedge", "--app=http://localhost:4173"], shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
        
        def capture_window():
            user32 = ctypes.windll.user32
            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            hwnd_found = 0
            
            for _ in range(20):
                time.sleep(0.5)
                def enum_cb(hwnd, lparam):
                    nonlocal hwnd_found
                    if user32.IsWindowVisible(hwnd):
                        length = user32.GetWindowTextLengthW(hwnd)
                        if length > 0:
                            buff = ctypes.create_unicode_buffer(length + 1)
                            user32.GetWindowTextW(hwnd, buff, length + 1)
                            title = buff.value.lower()
                            if "localhost" in title or "vite" in title or "react" in title or "god's eye" in title or "cesium" in title:
                                hwnd_found = hwnd
                                return False
                    return True
                user32.EnumWindows(WNDENUMPROC(enum_cb), 0)
                if hwnd_found: break
            
            if hwnd_found:
                print(f"[System] Captured Map Window Handle: {hwnd_found}")
                tk_hwnd = self.map_container.winfo_id()
                GWL_STYLE = -16
                WS_VISIBLE = 0x10000000
                WS_CHILD = 0x40000000
                WS_CAPTION = 0x00C00000
                WS_THICKFRAME = 0x00040000
                WS_SYSMENU = 0x00080000
                
                style = user32.GetWindowLongW(hwnd_found, GWL_STYLE)
                new_style = (style | WS_CHILD | WS_VISIBLE) & ~WS_CAPTION & ~WS_THICKFRAME & ~WS_SYSMENU & ~0x80000000
                user32.SetWindowLongW(hwnd_found, GWL_STYLE, new_style)
                user32.SetParent(hwnd_found, tk_hwnd)
                user32.SetWindowPos(hwnd_found, 0, 0, 0, 0, 0, 0x0027)
                
                def resize_map(event=None):
                    w = self.map_container.winfo_width()
                    h = self.map_container.winfo_height()
                    user32.MoveWindow(hwnd_found, 0, -40, w, h + 40, True)
                
                self.map_container.bind("<Configure>", resize_map)
                
                def check_window_alive():
                    if not user32.IsWindow(hwnd_found):
                        self.map_launched = False
                        self.map_launch_btn.set_text("RELAUNCH TACTICAL OVERLAY")
                        self.map_container.lower()
                    else:
                        self.root.after(1000, check_window_alive)
                
                self.root.after(0, self.map_container.lift)
                self.root.after(0, resize_map)
                self.root.after(1000, check_window_alive)
            else:
                self.map_launched = False
                self.root.after(0, lambda: self.map_launch_btn.set_text("[ ERROR: COULD NOT CAPTURE ]"))
                self.root.after(0, self.map_container.lower)

        threading.Thread(target=capture_window, daemon=True).start()

    def update_request(self, text): self.root.after(0, lambda: self.req_label.config(text=f"\"{text}\""))
    def update_reply(self, text): self.root.after(0, lambda: self.rep_label.config(text=f"\"{text}\""))
    def submit_typed_command(self, event=None):
        cmd = self.entry_var.get().strip()
        if not cmd: return
        self.entry_var.set("")
        def _run_typed():
            response = process_command(cmd)
            if response: speak(response)
        threading.Thread(target=_run_typed, daemon=True).start()

if __name__ == "__main__":
    try:
        # Incrementing to mark12 forces Windows to dump the old Taskbar Icon Cache!
        myappid = 'jarvis.assistant.mark12'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

    get_system_voices()
    sync_smart_home_devices()
    
    root = tk.Tk()
    GUI_APP = JarvisGUI(root)
    threading.Thread(target=background_voice_loop, daemon=True).start()
    threading.Thread(target=setup_map_server, daemon=True).start()
    root.mainloop()
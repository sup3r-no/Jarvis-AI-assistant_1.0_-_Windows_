import bpy
import urllib.request
import json
import re
import socket
import threading
import queue

OLLAMA_MODEL = "qwen2.5-coder"
HOST = '127.0.0.1'
PORT = 8081

prompt_queue = queue.Queue()

def ask_ollama(prompt):
    url = "http://localhost:11434/api/generate"
    
    # --- NEW: LIVE SCENE CONTEXT INJECTION ---
    try:
        # Grabs a list of the exact names of every object currently in the 3D viewport
        obj_list = [obj.name for obj in bpy.context.scene.objects]
        scene_context = f"CURRENT SCENE STATE: The scene currently contains these objects: {', '.join(obj_list)}. "
    except Exception:
        scene_context = ""
        
    system_prompt = (
        "You are a Blender 3D Python (bpy) coding assistant. "
        "Only output valid Python code wrapped in ```python ... ``` blocks. "
        "Do not include any explanations. Always import bpy. "
        "If the user asks to modify, scale, move, or delete an object, use the CURRENT SCENE STATE to target the exact object name. "
        "CRITICAL: If the user specifies a quantity (like '1 sphere'), select and modify EXACTLY that many objects by their specific name (e.g., bpy.data.objects['Sphere.001']). Do NOT use loops that delete everything with a similar name! "
        "Always write robust code that checks if an object exists before altering it. "
        f"{scene_context}"
    )
    
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": system_prompt,
        "stream": False,
        "temperature": 0.1
    }
    
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            return result.get("response", "")
    except Exception as e:
        print(f"Ollama Error: {e}")
        return ""

def process_queue():
    if not prompt_queue.empty():
        prompt = prompt_queue.get()
        print(f"Jarvis received prompt: {prompt}")
        
        response = ask_ollama(prompt)
        match = re.search(r'```python\n(.*?)\n```', response, re.DOTALL)
        if match:
            code = match.group(1)
            try:
                exec(code)
            except Exception as e:
                print(f"Error executing Blender code: {e}")
    return 1.0

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server.bind((HOST, PORT))
        server.listen(1)
    except Exception as e:
        print(f"Server Bind Error: {e}")
        return
        
    while True:
        try:
            conn, addr = server.accept()
            data = conn.recv(1024).decode('utf-8')
            if data:
                prompt_queue.put(data)
            conn.close()
        except Exception:
            pass

# --- CLEAR DEFAULT SCENE ON STARTUP ---
# Safely removes the default cube, camera, and light so the AI has a clean canvas
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)

server_thread = threading.Thread(target=start_server, daemon=True)
server_thread.start()

if bpy.app.timers.is_registered(process_queue):
    bpy.app.timers.unregister(process_queue)
bpy.app.timers.register(process_queue)

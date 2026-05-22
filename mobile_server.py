# ==========================================
# AURELIA MOBILE GATEWAY (V1.2)
# Permissions & Optic Handoff Fix + Atomic Writes
# ==========================================
import os
import time
import json
import asyncio
import base64
import re
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, UploadFile, File, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
import uvicorn
import aiofiles

# --- DIRECTORY CONFIGURATION ---
BASE_DIR = Path("C:/Aurelia_Project")
MOBILE_DIR = BASE_DIR / "Aurelia_Mobile"
SENSORS_DIR = BASE_DIR / "Aurelia_Sensors"
VISION_DIR = SENSORS_DIR / "mobile_vision"
LIBRARY_DIR = MOBILE_DIR / "Library"
AUDIO_DIR = BASE_DIR / "Aurelia_Audio_Output"

OUTBOX_DIR = BASE_DIR / "Aurelia_Mobile_Outbox"
SUB_OUTBOX_DIR = BASE_DIR / "Aurelia_Mobile_Subconscious"
INBOX_DIR = BASE_DIR / "Aurelia_Mobile_Inbox"
GOAL_DIR = BASE_DIR / "Aurelia_Mobile_Goal"

for d in [MOBILE_DIR, SENSORS_DIR, VISION_DIR, LIBRARY_DIR, AUDIO_DIR, OUTBOX_DIR, SUB_OUTBOX_DIR, INBOX_DIR, GOAL_DIR]:
    d.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Aurelia Mobile Portal")

# --- CRITICAL PERMISSIONS POLICY (Fixed standing block) ---
class PermissionsPolicyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        # Direct instruction to mobile browsers to unlock hardware
        response.headers["Permissions-Policy"] = "camera=(self), bluetooth=(self), microphone=(self), accelerometer=(self)"
        return response

app.add_middleware(PermissionsPolicyMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allow all origins since it's Tailscale private
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=str(MOBILE_DIR)), name="static")
app.mount("/library_files", StaticFiles(directory=str(LIBRARY_DIR)), name="library")
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

class ConnectionManager:
    def __init__(self):
        self.portal_connections: list[WebSocket] = []
        self.system_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket, channel: str):
        await websocket.accept()
        if channel == "portal": self.portal_connections.append(websocket)
        elif channel == "system": self.system_connections.append(websocket)

    def disconnect(self, websocket: WebSocket, channel: str):
        if channel == "portal" and websocket in self.portal_connections: self.portal_connections.remove(websocket)
        elif channel == "system" and websocket in self.system_connections: self.system_connections.remove(websocket)

    async def broadcast_portal(self, message: dict):
        for c in self.portal_connections:
            try: await c.send_json(message)
            except: pass 

    async def broadcast_system(self, message: dict):
        for c in self.system_connections:
            try: await c.send_json(message)
            except: pass

manager = ConnectionManager()

def generate_safe_filename(prefix="msg"):
    return f"{prefix}_{time.time():.4f}_{uuid.uuid4().hex[:4]}"

@app.get("/", response_class=HTMLResponse)
async def get_portal():
    async with aiofiles.open(MOBILE_DIR / "index.html", 'r', encoding='utf-8') as f:
        return HTMLResponse(content=await f.read())

@app.post("/upload_image")
async def upload_mobile_vision(file: UploadFile = File(...)):
    try:
        # --- FIX: Collision-proof filenames (fractions of a second + UUID) ---
        filename = f"MOBILE_VISION_{time.time():.4f}_{uuid.uuid4().hex[:4]}.jpg"
        file_path = VISION_DIR / filename
        temp_path = file_path.with_suffix('.tmp')
        
        # --- ATOMIC WRITE ---
        async with aiofiles.open(temp_path, 'wb') as out:
            await out.write(await file.read())
            
        os.replace(temp_path, file_path) # Instantly hand off to Orchestrator
        
        return {"status": "success"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": f"Upload failed: {str(e)}"})

@app.websocket("/ws/portal")
async def websocket_portal(websocket: WebSocket):
    await manager.connect(websocket, "portal")
    try:
        while True:
            raw_data = await websocket.receive_text()
            
            # --- FIX: Drop Poison Packets ---
            try:
                payload = json.loads(raw_data)
            except json.JSONDecodeError:
                continue # Ignore malformed packets from network jitter
                
            msg_type = payload.get("type")
            
            # --- ATOMIC WRITES FOR ALL INBOUND DATA ---
            if msg_type == "chat":
                safe_name = generate_safe_filename('inbox')
                temp_path = INBOX_DIR / f"{safe_name}.tmp"
                final_path = INBOX_DIR / f"{safe_name}.txt"
                
                async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                    await f.write(payload.get("text", ""))
                os.replace(temp_path, final_path)
                
            elif msg_type == "set_goal":
                safe_name = generate_safe_filename('goal')
                temp_path = GOAL_DIR / f"{safe_name}.tmp"
                final_path = GOAL_DIR / f"{safe_name}.txt"
                
                async with aiofiles.open(temp_path, 'w', encoding='utf-8') as f:
                    await f.write(payload.get("text", ""))
                os.replace(temp_path, final_path)
                
            elif msg_type == "mobile_bpm":
                final_path = SENSORS_DIR / "mobile_bpm.json"
                temp_path = SENSORS_DIR / "mobile_bpm.tmp"
                
                async with aiofiles.open(temp_path, 'w') as f:
                    await f.write(json.dumps({"bpm": payload.get("bpm", 0), "timestamp": time.time()}))
                os.replace(temp_path, final_path)
                
    except WebSocketDisconnect:
        manager.disconnect(websocket, "portal")

@app.websocket("/ws/system")
async def websocket_system(websocket: WebSocket):
    await manager.connect(websocket, "system")
    try:
        while True:
            snapshot_path = SENSORS_DIR / "Aurelia_Master_Telemetry_RAW.json"
            if snapshot_path.exists():
                async with aiofiles.open(snapshot_path, 'r') as f:
                    try: await websocket.send_json({"type": "somatic_data", "data": json.loads(await f.read())})
                    except: pass 
            await asyncio.sleep(1.0) 
    except WebSocketDisconnect:
        manager.disconnect(websocket, "system")

async def outbox_watcher():
    loop = asyncio.get_event_loop()
    while True:
        try:
            if len(manager.portal_connections) > 0:
                for f_path in OUTBOX_DIR.glob("*.txt"):
                    async with aiofiles.open(f_path, 'r', encoding='utf-8') as f:
                        await manager.broadcast_portal({"type": "chat", "text": await f.read()})
                    await loop.run_in_executor(None, f_path.unlink)
            
            # --- FIX: Guard the system connection before unlinking ---
            if len(manager.system_connections) > 0:
                for f_path in SUB_OUTBOX_DIR.glob("*.txt"):
                    async with aiofiles.open(f_path, 'r', encoding='utf-8') as f:
                        await manager.broadcast_system({"type": "terminal_log", "text": await f.read()})
                    await loop.run_in_executor(None, f_path.unlink)
        except: pass 
        await asyncio.sleep(0.5) 

@app.on_event("startup")
async def startup_event(): asyncio.create_task(outbox_watcher())

if __name__ == "__main__":
    TAILSCALE_DOMAIN = "asher.tail3b3bf6.ts.net"
    cert = BASE_DIR / f"{TAILSCALE_DOMAIN}.crt"
    key = BASE_DIR / f"{TAILSCALE_DOMAIN}.key"
    uvicorn.run(app, host="0.0.0.0", port=443, ssl_keyfile=str(key), ssl_certfile=str(cert), log_level="warning")

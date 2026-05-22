**Aurelia** is an experimental local AI companion and autonomous workstation assistant built around a distributed, multi-model architecture. The project combines a desktop UI, mobile portal, multimodal sensor hub, persistent memory, autonomous background agent, and LM Studio-hosted local language models into a single Windows-native system.

Aurelia is designed as a **biomimetic software organism simulation**: not literally alive, conscious, or sentient, but architected as if she has specialized cognitive lobes, sensory nerves, somatic state, memory, and a subconscious action layer.

> **Status:** Experimental personal research project. Not production-ready. Built for a specific local hardware environment.

---

## Table of Contents

- [Core Idea](#core-idea)
- [Hardware Target](#hardware-target)
- [Model Topology](#model-topology)
- [System Architecture](#system-architecture)
- [Major Components](#major-components)
- [Runtime Workflow](#runtime-workflow)
- [Features](#features)
- [Repository Layout](#repository-layout)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running Aurelia](#running-aurelia)
- [Mobile Portal](#mobile-portal)
- [Memory System](#memory-system)
- [Autonomous Subconscious Agent](#autonomous-subconscious-agent)
- [Sensors and Telemetry](#sensors-and-telemetry)
- [Security and Privacy Notes](#security-and-privacy-notes)
- [Known Limitations](#known-limitations)
- [Roadmap](#roadmap)
- [License](#license)

---

## Core Idea

Aurelia is a local, embodied AI assistant that separates cognition into specialized model roles:

- A large **Executive Core** for conversation, synthesis, personality, and high-level decision-making.
- A smaller **Visual Cortex** for image, screen, workspace, and environmental interpretation.
- A small **Somatic Cortex** for translating raw machine thermals into embodied internal state.
- A separate **Subconscious Action Engine** for tool use, research, file operations, and autonomous task completion.

The goal is to create a local assistant that can:

- See the workspace and physical environment.
- Track room/body/desk telemetry.
- Maintain persistent long-term memory.
- Delegate background goals to a separate agent.
- Route visual code/debugging tasks automatically.
- Communicate through both a desktop UI and mobile web portal.
- Operate entirely on local hardware where possible.

---

## Hardware Target

This build is designed around the following local machine:

| Component | Role |
|---|---|
| Framework Desktop / Strix Halo system | Primary local compute host |
| 128 GB system RAM | Shared memory pool |
| 96 GB allocated VRAM | Hosts the 80B, 9B, and 4B local models |
| Radeon Pro V620 32 GB eGPU | Dedicated 13B Subconscious Action Engine |
| OCuLink eGPU bridge | Physical separation between executive stack and action stack |
| Windows 11 native | Runtime operating system |
| Custom open-air cooling array | Sustained local inference cooling |
| Camera, thermal camera, LiDAR, mmWave, vibration, BPM sensors | Physical/environmental telemetry |
| Mobile phone over private network/Tailscale | Remote tether, mobile camera, mobile vitals, chat, and goal input |

The system can be partially adapted to other hardware, but the current code assumes Windows paths, specific COM ports, HWiNFO shared-memory offsets, LM Studio model names, and a `C:\Aurelia_Project` workspace.

---

## Model Topology

Aurelia uses four primary model lobes.

| Lobe | Default Model Constant | Prompt File | Intended Hardware | Role |
|---|---|---|---|---|
| Executive Core | `BRAIN_MODEL` | `80B.txt` | Strix Halo VRAM pool | Conversation, persona, synthesis, delegation |
| Visual Cortex | `VISION_MODEL` | `9B.txt` | Strix Halo VRAM pool | External sensory interpretation and workspace routing |
| Somatic Cortex | `SOMATIC_MODEL` | `4B.txt` | Strix Halo VRAM pool | Hardware thermals to internal body-state language |
| Subconscious Action Engine | `AGENT_MODEL` | `13B.txt` | Radeon Pro V620 eGPU | Tool use, research, Python execution, file edits, reports |

Current model constants in the orchestrator:

```python
BRAIN_MODEL = "qwen3-next-80b-a3b-instruct-decensored-i1"
VISION_MODEL = "mradermacher/qwen3.5-9b-claude-4.6-highiq-instruct-heretic-uncensored"
AGENT_MODEL = "qwen3.5-13b-deckard-heretic-uncensored-thinking-i1"
SOMATIC_MODEL = "qwen3-4b-decensored-instruct-i1"
```

You can either load models in LM Studio using these exact names or edit the constants in `Aurelia_Asynchronous_Orchestrator.py`.

---

## System Architecture

```text
                              ┌────────────────────────┐
                              │      LM Studio API      │
                              │ http://localhost:1234   │
                              └───────────┬────────────┘
                                          │
                ┌─────────────────────────┼─────────────────────────┐
                │                         │                         │
        ┌───────▼───────┐         ┌───────▼───────┐         ┌───────▼───────┐
        │ 80B Executive │         │ 9B Visual     │         │ 4B Somatic    │
        │ Core          │         │ Cortex        │         │ Cortex        │
        └───────┬───────┘         └───────┬───────┘         └───────┬───────┘
                │                         │                         │
                │                         │                         │
        ┌───────▼─────────────────────────▼─────────────────────────▼───────┐
        │              Aurelia_Asynchronous_Orchestrator.py                  │
        │  PyQt6 UI | memory retrieval | routing | TTS | mobile sync | goals │
        └───────┬─────────────────────────┬─────────────────────────┬───────┘
                │                         │                         │
        ┌───────▼───────┐         ┌───────▼───────┐         ┌───────▼───────┐
        │ Chroma + FTS5 │         │ 13B Agent     │         │ Mobile Portal │
        │ Memory        │         │ on V620 eGPU  │         │ FastAPI/PWA   │
        └───────────────┘         └───────┬───────┘         └───────┬───────┘
                                          │                         │
                                  ┌───────▼───────┐                 │
                                  │ Tools         │                 │
                                  │ Search        │                 │
                                  │ Browse        │                 │
                                  │ Python        │                 │
                                  │ File I/O      │                 │
                                  │ Reports       │                 │
                                  └───────────────┘                 │
                                                                    │
        ┌───────────────────────────────────────────────────────────▼───────┐
        │                  Aurelia_Omni_Hub.py                               │
        │ Camera | thermal | LiDAR | mmWave | vibration | BPM | HWiNFO temps │
        └───────────────────────────────────────────────────────────────────┘
```

---

## Major Components

### `Aurelia_Asynchronous_Orchestrator.py`

The main desktop runtime.

Responsibilities:

- Launches the PyQt6 desktop interface.
- Connects to LM Studio through the OpenAI-compatible async client.
- Routes prompts to the 80B, 9B, 4B, and 13B model roles.
- Reads sensory telemetry and image buffers from the Omni Hub.
- Queries persistent memory before executive responses.
- Parses tool tags from the Executive Core.
- Registers background goals for the Subconscious Action Engine.
- Handles workspace screenshots and mobile image uploads.
- Streams responses, generates report windows, and syncs output to mobile.
- Integrates optional local TTS.

### `Aurelia_Omni_Hub.py`

The sensory brainstem.

Responsibilities:

- Reads camera, thermal camera, LiDAR, mmWave, vibration sensors, ambient temperature, system thermals, and BPM sources.
- Maintains rolling telemetry buffers.
- Derives presence, confidence, BPM trend, respiration, vibration state, and thermal state.
- Captures a 30-second visual window: start frame, thermal midpoint, end frame.
- Atomically writes telemetry JSON and thalamic snapshot files for the orchestrator.

### `Aurelia_Memory.py`

The long-term memory system.

Responsibilities:

- Stores persistent memory with ChromaDB.
- Uses `all-MiniLM-L6-v2` sentence embeddings.
- Maintains a SQLite FTS5 sparse/BM25 index.
- Performs hybrid dense + sparse retrieval.
- Tracks memory importance, access count, mood, memory type, and neural uptime.
- Deduplicates/reinforces similar conversation memories.
- Stores active and completed subconscious goals.
- Stores procedural skill memories from completed agent tasks.
- Manages agentic memory profile JSON.

### `Aurelia_Subconscious_Memory.py`

The state ledger for the 13B agent.

Responsibilities:

- Maintains a file-lock-protected `agent_state_ledger.json`.
- Tracks tool status, known bugs, and last outcomes.
- Maintains goal-specific scratchpads.
- Tracks failure counts.
- Ages pending goals to prevent starvation.
- Protects against ledger corruption with backup/reset behavior.

### `mobile_server.py`

The FastAPI mobile gateway.

Responsibilities:

- Serves the mobile PWA.
- Receives mobile chat messages.
- Receives mobile goals.
- Receives mobile camera/image uploads.
- Receives mobile Bluetooth BPM readings.
- Streams somatic telemetry to the phone.
- Broadcasts desktop/orchestrator replies back to mobile.
- Broadcasts subconscious terminal logs to mobile.

### `index.html`

The mobile portal UI.

Responsibilities:

- Terminal-style mobile chat.
- Camera capture and gallery upload.
- Web Bluetooth heart-rate pairing.
- Somatic telemetry display.
- Subconscious terminal log display.
- Audio playback.
- Goal submission.

### Prompt Files

| File | Purpose |
|---|---|
| `80B.txt` | Executive Core persona, speech, mood routing, sensory integration, delegation protocol |
| `9B.txt` | Visual Cortex prompt for environmental sensory windows and workspace routing |
| `4B.txt` | Somatic Cortex prompt for translating raw thermals into embodied internal state |
| `13B.txt` | Subconscious Action Engine prompt defining the XML tool protocol |

---

## Runtime Workflow

### Standard conversation

1. User sends a desktop or mobile message.
2. Orchestrator reads current telemetry and image buffers.
3. 4B Somatic Cortex converts raw thermals into internal body-state language.
4. 9B Visual Cortex converts camera/thermal/telemetry data into external sensory observations.
5. Memory engine retrieves relevant long-term memories and active goals.
6. 80B Executive Core receives the immediate user query plus sensory and memory context.
7. 80B produces a response, a tool tag, silence marker, report tag, image tag, or goal tag.
8. Orchestrator sanitizes display text, updates the UI, writes mobile outbox messages, and stores memory.

### Workspace snapshot routing

1. User captures or uploads a workspace image.
2. 9B Visual Cortex classifies it as `[TYPE: CODE]` or `[TYPE: TEXT]`.
3. `[TYPE: CODE]` becomes a high-priority goal for the 13B Subconscious Action Engine.
4. `[TYPE: TEXT]` routes to the 80B Executive Core for explanation or discussion.

### Autonomous background goal

1. 80B emits `<SET_GOAL>...</SET_GOAL>` or user submits a mobile goal.
2. Memory engine registers the goal with priority.
3. 13B receives the active goal, ledger state, scratchpad, and relevant procedural skill memory.
4. 13B emits exactly one XML tool call per step.
5. Orchestrator executes the tool and feeds the result back into the agent loop.
6. 13B finishes with `<REPORT>...</REPORT>`.
7. Report is shown in the desktop UI, sent to mobile, and archived in memory.

---

## Features

- Local multi-model AI architecture.
- LM Studio OpenAI-compatible backend.
- Dedicated executive, visual, somatic, and subconscious model roles.
- PyQt6 desktop UI.
- FastAPI mobile PWA.
- Mobile chat, goal submission, image upload, and optional Bluetooth BPM.
- 30-second external sensory window using start, thermal midpoint, and end frames.
- Workspace screenshot routing for code/text classification.
- Persistent ChromaDB semantic memory.
- SQLite FTS5 sparse retrieval.
- Hybrid memory retrieval with decay, reinforcement, mood matching, and active-goal injection.
- Autonomous 13B tool loop.
- Web search, browsing, DOM inspection, Python scratchpad execution, file read/edit/write, and report generation.
- Atomic drop-file communication between desktop, mobile, sensors, and agent subsystems.
- Local sensory fusion from camera, thermal, LiDAR, mmWave, vibration, heart-rate, and hardware thermals.
- Optional TTS integration.
- Local image generation route through Fooocus where configured.

---

## Repository Layout

Suggested layout:

```text
C:\Aurelia_Project\
│
├── Aurelia_Asynchronous_Orchestrator.py
├── Aurelia_Omni_Hub.py
├── Aurelia_Memory.py
├── Aurelia_Subconscious_Memory.py
├── mobile_server.py
├── index.html
│
├── 80B.txt
├── 13B.txt
├── 9B.txt
├── 4B.txt
│
├── Aurelia_DB\
│   ├── goals.json
│   ├── neural_uptime.txt
│   ├── aurelia_fts.db
│   └── agent_state_ledger.json
│
├── Aurelia_Sensors\
│   ├── aurelia_keys.json
│   ├── Aurelia_Master_Telemetry_RAW.json
│   ├── Aurelia_Thalamic_Snapshot.json
│   ├── Aurelia_Optic_Buffer_Start.jpg
│   ├── Aurelia_Optic_Buffer_Thermal.jpg
│   ├── Aurelia_Optic_Buffer_End.jpg
│   ├── mobile_bpm.json
│   └── mobile_vision\
│
├── Aurelia_Mobile\
│   ├── index.html
│   ├── manifest.json
│   └── Library\
│
├── Aurelia_Mobile_Inbox\
├── Aurelia_Mobile_Outbox\
├── Aurelia_Mobile_Goal\
├── Aurelia_Mobile_Subconscious\
│
├── Aurelia_Audio_Output\
├── Aurelia_Saved_Scripts\
│   ├── Aurelia_Agentic_Memory.json
│   └── Aurelia_Scratchpad\
│
└── aurelia_env\
```

Some directories are created automatically at runtime.

---

## Installation

### 1. Clone the repository

```powershell
git clone https://github.com/YOUR_USERNAME/Project-Aurelia.git C:\Aurelia_Project
cd C:\Aurelia_Project
```

### 2. Create a Python environment

The current build is Windows-native. The orchestrator expects an environment at:

```text
C:\Aurelia_Project\aurelia_env\Scripts\python.exe
```

Create it:

```powershell
py -m venv aurelia_env
.\aurelia_env\Scripts\activate
python -m pip install --upgrade pip
```

### 3. Install Python dependencies

There is no finalized `requirements.txt` yet. The project currently imports these major packages:

```powershell
pip install openai requests httpx pillow PyQt6 numpy opencv-python pyserial hidapi websocket-client chromadb sentence-transformers beautifulsoup4 playwright playwright-stealth ddgs tavily-python yfinance fastapi uvicorn aiofiles python-multipart filelock
```

Install Playwright browser support:

```powershell
playwright install chromium
```

Optional or hardware-specific modules may require additional setup:

- `aurelia_tts.py` / MOSS-TTS Nano integration.
- `Modules\ears` local audio module.
- P2Pro thermal camera Python viewer package.
- HWiNFO shared memory access.
- Sensor vendor drivers.
- GPU/ROCm/Vulkan/LM Studio runtime configuration.

---

## Configuration

### Workspace path

The project currently assumes:

```text
C:\Aurelia_Project
```

If using another directory, update hard-coded paths in:

- `Aurelia_Asynchronous_Orchestrator.py`
- `Aurelia_Omni_Hub.py`
- `Aurelia_Memory.py`
- `Aurelia_Subconscious_Memory.py`
- `mobile_server.py`

### API keys

Create:

```text
C:\Aurelia_Project\Aurelia_Sensors\aurelia_keys.json
```

Example:

```json
{
  "GEMINI_KEY": "",
  "SEARCH_KEY": "",
  "SEARCH_CX": "",
  "TAVILY_KEY": "",
  "TAVILY_API_KEY": "",
  "TAVILY_TOKEN": "",
  "TAVILY": "",
  "CMC_KEY": ""
}
```

For web scouting, configure at least one Tavily key or modify the search routing to use only local/free search paths.

### LM Studio

1. Start LM Studio.
2. Enable the local OpenAI-compatible server.
3. Confirm it is reachable at:

```text
http://localhost:1234/v1
```

4. Load or expose the models matching the constants in `Aurelia_Asynchronous_Orchestrator.py`.
5. If your model names differ, edit:

```python
BRAIN_MODEL = "..."
VISION_MODEL = "..."
AGENT_MODEL = "..."
SOMATIC_MODEL = "..."
```

### Mobile SSL / Tailscale

`mobile_server.py` currently expects certificate files like:

```text
C:\Aurelia_Project\asher.tail3b3bf6.ts.net.crt
C:\Aurelia_Project\asher.tail3b3bf6.ts.net.key
```

And runs:

```python
uvicorn.run(app, host="0.0.0.0", port=443, ssl_keyfile=str(key), ssl_certfile=str(cert))
```

If you are not using that exact Tailscale domain, update `TAILSCALE_DOMAIN` in `mobile_server.py`.

---

## Running Aurelia

Recommended startup order:

### 1. Start LM Studio

Make sure the OpenAI-compatible API server is active at:

```text
http://localhost:1234/v1
```

### 2. Start optional sensor support services

Depending on your hardware:

- HWiNFO with shared memory enabled.
- Scosche/BPM WebSocket bridge at `ws://127.0.0.1:8765`.
- P2Pro thermal camera service/package.
- Serial devices connected to the configured COM ports.

### 3. Start the mobile gateway

```powershell
cd C:\Aurelia_Project
.\aurelia_env\Scripts\activate
python mobile_server.py
```

By default this runs HTTPS on port `443` using the configured Tailscale certificate.

### 4. Start the Omni-Sensory Hub

```powershell
cd C:\Aurelia_Project
.\aurelia_env\Scripts\activate
python Aurelia_Omni_Hub.py
```

The hub starts all sensor threads, waits briefly, then begins the repeating 30-second analytical window.

### 5. Start the desktop orchestrator

```powershell
cd C:\Aurelia_Project
.\aurelia_env\Scripts\activate
python Aurelia_Asynchronous_Orchestrator.py
```

This launches the PyQt6 desktop UI.

---

## Mobile Portal

The mobile system is designed for private-network access, preferably through Tailscale.

Capabilities:

- Chat with Aurelia remotely.
- Submit autonomous goals.
- Capture and upload mobile camera images.
- Upload gallery images.
- Send mobile Bluetooth BPM telemetry.
- Receive Aurelia replies.
- Receive subconscious terminal logs.
- Receive somatic telemetry updates.
- Play generated audio.

Core routes:

| Route | Purpose |
|---|---|
| `GET /` | Serves the mobile portal |
| `POST /upload_image` | Uploads mobile camera/gallery images |
| `WS /ws/portal` | Chat, goals, mobile BPM input |
| `WS /ws/system` | Somatic telemetry and subconscious log stream |
| `/static` | Mobile static files |
| `/library_files` | Mobile library output |
| `/audio` | Generated audio output |

---

## Memory System

Aurelia uses multiple memory layers:

### Semantic memory

Stored in ChromaDB under:

```text
C:\Aurelia_Project\Aurelia_DB
```

Default collection:

```text
aurelia_obsession_archive
```

### Sparse keyword retrieval

SQLite FTS5 database:

```text
C:\Aurelia_Project\Aurelia_DB\aurelia_fts.db
```

Used to preserve exact keyword and filename recall.

### Hybrid retrieval

The memory engine combines:

- Dense semantic search.
- Sparse FTS5 search.
- Importance weighting.
- Mood matching.
- Neural uptime decay.
- Access-count reinforcement.
- Active goal injection.

### Procedural skill memory

Completed 13B agent tasks can be saved into:

```text
aurelia_skill_library
```

This lets the subconscious agent retrieve past solutions before attempting similar future tasks.

### Agentic memory

Aurelia’s persistent profile is loaded from:

```text
C:\Aurelia_Project\Aurelia_Saved_Scripts\Aurelia_Agentic_Memory.json
```

---

## Autonomous Subconscious Agent

The 13B Subconscious Action Engine is a background worker that does not speak directly to the user. It receives goals from the Executive Core or mobile portal and resolves them through an XML-style tool protocol.

Available tool classes:

- `<SEARCH>` web scouting.
- `<BROWSE>` webpage reading.
- `<INSPECT_DOM>` webpage structure inspection.
- `<STEALTH_SWEEP>` background trace/search.
- `<PYTHON>` scratchpad execution.
- `<READ_LINES>` file inspection.
- `<REPLACE_LINES>` surgical file patching.
- `<WRITE_FILE>` new file creation.
- `<REPORT>` goal completion report.

The orchestrator executes these tools, feeds tool results back into the agent loop, and archives completed reports.

> Important: the file tools are intended to stay inside `C:\Aurelia_Project`, but arbitrary Python execution is still powerful. Do not run this system with untrusted prompts, untrusted model weights, or public network exposure.

---

## Sensors and Telemetry

The current Omni Hub assumes the following default hardware mapping:

| Sensor | Default Port / Source | Purpose |
|---|---|---|
| LD14P LiDAR | `COM11` | Desk/user proximity |
| Room mmWave | `COM5` | Macro spatial movement |
| ADXL345 macro vibration | `COM8` | Desk/rig resonance |
| ADXL345 micro vibration | `COM12` | Keyboard/typing motion |
| ESPHome mmWave fallback | `COM9` | Pulse/presence fallback |
| EMEET C960 | Camera index `0` | Visual frame capture |
| P2Pro thermal camera | Vendor Python viewer | Thermal midpoint frame |
| HWiNFO shared memory | `Global\HWiNFO_SENS_SM2` | CPU/iGPU/eGPU thermals |
| Scosche bridge | `ws://127.0.0.1:8765` | Local armband BPM |
| Mobile BLE | `mobile_bpm.json` | Remote armband BPM |

Generated files:

```text
Aurelia_Master_Telemetry_RAW.json
Aurelia_Thalamic_Snapshot.json
Aurelia_Optic_Buffer_Start.jpg
Aurelia_Optic_Buffer_Thermal.jpg
Aurelia_Optic_Buffer_End.jpg
```

The orchestrator reads these files to generate sensory context for the 9B and 4B models.

---

## Security and Privacy Notes

This project can process highly sensitive local data:

- Camera frames.
- Thermal images.
- Room presence data.
- Vibration data.
- Heart-rate data.
- Workspace screenshots.
- Local files.
- Chat history.
- Generated autonomous reports.

Recommended precautions:

1. Keep the system on a private network.
2. Prefer Tailscale or another trusted private tunnel for mobile access.
3. Do not expose the FastAPI server directly to the public internet.
4. Do not commit `aurelia_keys.json`.
5. Do not commit local certificates or private keys.
6. Remove or replace any local API tokens before publishing.
7. Treat the 13B agent’s Python execution path as unsafe until a stricter sandbox is implemented.
8. Add `.gitignore` entries for databases, logs, mobile inbox/outbox files, generated images, generated audio, scratchpads, and secrets.

Suggested `.gitignore` entries:

```gitignore
# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.env
.venv/
aurelia_env/

# Secrets
Aurelia_Sensors/aurelia_keys.json
*.crt
*.key
*.pem

# Databases and runtime state
Aurelia_DB/
*.db
*.db-wal
*.db-shm
*.lock

# Runtime IPC
Aurelia_Mobile_Inbox/
Aurelia_Mobile_Outbox/
Aurelia_Mobile_Goal/
Aurelia_Mobile_Subconscious/
Aurelia_Sensors/*.json
Aurelia_Sensors/*.tmp
Aurelia_Sensors/*.jpg
Aurelia_Sensors/mobile_vision/

# Generated media
Aurelia_Audio_Output/
Aurelia_Saved_Scripts/Aurelia_Scratchpad/
*.wav
*.mp3
*.png

# Backups
*.bak
```

---

## Known Limitations

- Windows paths are hard-coded throughout the current build.
- Sensor COM ports are hard-coded.
- HWiNFO shared-memory offsets may break if hardware enumeration changes.
- Mobile server domain/cert names are hard-coded.
- There is no finalized `requirements.txt` yet.
- Some optional modules are referenced but not included here, such as local TTS and ears/audio modules.
- Arbitrary Python execution by the 13B agent is not a full sandbox.
- Model compliance is partly prompt-enforced rather than fully enforced by typed runtime contracts.
- The project is designed for a specific workstation and will require edits before it runs elsewhere.

---

## Roadmap

Recommended engineering upgrades:

- Add `requirements.txt` or `pyproject.toml`.
- Move all paths, COM ports, model names, and cert names into a config file.
- Add startup self-tests for LM Studio, sensors, memory, mobile server, and model availability.
- Add Pydantic schemas for telemetry, mobile messages, tool calls, and goal objects.
- Replace prompt-only tool rules with deterministic runtime validation.
- Harden the 13B Python tool with a real sandbox or allowlisted execution API.
- Add structured logging.
- Add watchdog/service supervisor for the hub, mobile server, and orchestrator.
- Add unit tests for memory retrieval, goal queue behavior, XML tool parsing, and mobile IPC.
- Add a safe degraded mode for running without physical sensors.
- Add a setup wizard for model names, sensors, API keys, and mobile certificate configuration.

---

## License

No license has been selected yet.

If this repository is public, add a license file before release. For private experimental work, keep the repository private until secrets, biometric data paths, and local machine identifiers are removed.

---

## Project Lead

Built as part of the Aurelia local embodied AI architecture project.

Project Lead: Geiger

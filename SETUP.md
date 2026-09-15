# Robot Simulation Setup

A complete, beginner-friendly guide for setting up and running the autonomous Webots robot simulation on a fresh Windows PC.

---

## 1. Requirements

Before running the simulation, install and configure the following hardware and software dependencies:

### Operating System
* **Windows 10 / 11 (64-bit)**: Required. The automation scripts (`.bat`), process management commands, and default paths are tailored for Windows.

### Required Software & Tools

| Software | Version | Purpose | Required / Optional | Verification Command |
| :--- | :--- | :--- | :--- | :--- |
| **Git** | Latest (2.x+) | Cloning repository and version tracking | **Required** | `git --version` |
| **Python** | 3.10 – 3.12 (64-bit) | Runs AI Bridge and Webots Python controller | **Required** | `python --version` or `py --version` |
| **Webots** | **R2025a** | 3D physics robotics simulator | **Required** | `& "C:\Program Files\Webots\msys64\mingw64\bin\webots.exe" --version` |
| **curl** | Built into Windows 10/11 | Health check verification in batch scripts | **Required** | `curl --version` |

> [!NOTE]
> **Webots Version**: The simulation world (`worlds/Test.wbt`) and project configuration (`worlds/.Test.wbproj`) explicitly target **Webots R2025a**. Download this version from the [Cyberbotics Webots GitHub Releases](https://github.com/cyberbotics/webots/releases/tag/R2025a).
>
> **Python Version**: Webots officially supports Python versions 3.10, 3.11, and 3.12 on Windows. Python 3.11 (64-bit) is recommended for best compatibility.

### Python Packages

Installed in the Python environment (see [Section 3](#3-python-environment)):

* **`openai`** (`>=1.0.0`): Client library used by `ai_bridge/orchestrator.py` to interact with the NVIDIA API Catalog (`integrate.api.nvidia.com`). Required.
* **`python-dotenv`** (`>=1.0.0`): Loads API keys and configurations from `ai_bridge/.env`. Required.
* **`requests`** (`>=2.28.0`): Used by `ai_bridge/vision_client.py` to send HTTP requests to the local vision server. Required.
* **`pillow`** (`>=10.0.0`): Used by `controllers/robot_controller/robot_controller.py` to convert raw Webots BGRA camera frames to JPEG base64 strings. Required.

Verify package installation:
```cmd
python -c "import openai, dotenv, requests, PIL; print('All packages successfully installed!')"
```

### Vision Inference Engine & Models (For Autonomous Vision)

The vision system runs a local multi-modal vision-language model (`Qwen3-VL`) via `llama.cpp`:

1. **`llama-server.exe`**:
   * Pre-built binary from [llama.cpp releases](https://github.com/ggerganov/llama.cpp/releases) (choose the Windows release matching your GPU, e.g. CUDA or Vulkan).
   * Purpose: Hosts an OpenAI-compatible HTTP vision inference server on `http://127.0.0.1:8090`.
   * **Where to place it** (the startup script automatically checks any of these):
     * `<project-root>\bin\llama-server.exe`
     * `<project-root>\tools\llama-server.exe`
     * `%USERPROFILE%\.docker\bin\inference\llama-server.exe`
     * Or add its folder to your Windows system `PATH`.

2. **Model Weights (GGUF)**:
   * **Model file**: `Qwen3VL-2B-Instruct-Q4_K_M.gguf` (~1.1 GB)
   * **Multimodal projector**: `mmproj-Qwen3VL-2B-Instruct-F16.gguf` (~820 MB)
   * **Where to place them** (the startup script automatically checks either of these):
     * Option 1: Inside the repository at `<project-root>\models\`
     * Option 2: In your user home folder at `%USERPROFILE%\models\` (e.g. `C:\Users\<YourUsername>\models\`)

3. **Hardware**: Dedicated GPU recommended (e.g., NVIDIA GeForce GTX 1650 4GB VRAM or higher with CUDA/Vulkan support) for real-time vision inference. CPU inference is also supported by `llama-server`.

### Cloud API Account

* **NVIDIA API Catalog Key**: Required for high-level autonomous reasoning (`nvidia/nemotron-3-super-120b-a12b`). Obtain a free/tier key from [NVIDIA Build](https://build.nvidia.com).

### Network Ports

* **TCP Port `10101`**: Local socket communication between Webots controller (`robot_controller.py`) and Python client (`webots_client.py`).
* **HTTP Port `8090`**: Local HTTP communication between vision worker (`vision_client.py`) and `llama-server.exe`.

---

## 2. Clone the Repository

Open Windows Command Prompt (`cmd.exe`) or PowerShell and clone the repository:

```cmd
git clone https://github.com/Alex93824/Robot_Simulation.git
cd Robot_Simulation
```

Verify you are in the project root:
```cmd
dir
```
You should see `ai_bridge`, `controllers`, `worlds`, `START_ROBOT.bat`, `STOP_ROBOT.bat`, and `start_vision.bat`.

---

## 3. Python Environment

It is strongly recommended to use a virtual environment (`.venv`) to isolate dependencies.

### Step 3.1: Create and Activate Virtual Environment

Run in Windows Command Prompt (`cmd.exe`):

```cmd
python --version
py -3.11 -m venv .venv
.venv\Scripts\activate
```

*(If Python 3.11 is your default Python, you can simply run `python -m venv .venv`)*.

When activated, your prompt will display `(.venv)`.

### Step 3.2: Upgrade pip and Install Dependencies

```cmd
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Verify that all required packages imported without errors:
```cmd
python -c "import openai, dotenv, requests, PIL; print('Python environment ready!')"
```

### Step 3.3: Webots Controller Python Configuration

Webots runs the robot controller (`robot_controller.py`) using its own configured Python runtime. Because `robot_controller.py` imports `PIL` (`from PIL import Image`), Webots must have access to Pillow:

1. **Option A (Recommended)**: Point Webots to your project `.venv` Python:
   * Open Webots.
   * Go to **Tools** -> **Preferences** -> **Python command**.
   * Set the field to the absolute path of your virtual environment's Python executable:
     ```text
     <full-path-to-project>\.venv\Scripts\python.exe
     ```
2. **Option B**: Install `pillow` into your global Python:
   ```cmd
   python -m pip install pillow
   ```

---

## 4. Environment Variables

The high-level autonomous brain uses NVIDIA's hosted Nemotron model. The API key is loaded from:
```text
ai_bridge/.env
```
For security reasons, `.env` contains private credentials and is excluded from Git via `.gitignore`. A safe template file is provided at `ai_bridge/.env.example`.

### Step 4.1: Create `.env` from Template

Run the following command from the project root:

```cmd
copy ai_bridge\.env.example ai_bridge\.env
```

### Step 4.2: Configure `NVIDIA_API_KEY`

Open `ai_bridge/.env` in any text editor (Notepad, VS Code, etc.):

```env
# Copy this file to ".env" and fill in your real key.
# Get your key from https://build.nvidia.com (NVIDIA API Catalog).
NVIDIA_API_KEY=your_actual_nvidia_api_key_here
```

Replace `your_actual_nvidia_api_key_here` with your real key.

#### How to get an NVIDIA API key:
1. Go to [NVIDIA Build](https://build.nvidia.com).
2. Sign in or create a free NVIDIA developer account.
3. Browse to any hosted model (for example, search for `nemotron` or select `nvidia/nemotron-3-super-120b-a12b`).
4. Click **Get API Key** / **Generate Key**.
5. Copy the generated string into `ai_bridge/.env`.

> [!WARNING]
> Never commit `ai_bridge/.env` to Git. Keep your API key private.

---

## 5. Webots Setup

### Step 5.1: Install Webots
1. Download **Webots R2025a** Windows installer (`webots-R2025a_setup.exe`) from [Webots GitHub Releases](https://github.com/cyberbotics/webots/releases/tag/R2025a).
2. Run the installer. The default Windows installation directory is:
   ```text
   C:\Program Files\Webots
   ```

### Step 5.2: Simulation Files Overview
* **World File**: `worlds/Test.wbt`
  * Features a `RectangleArena` (10m x 10m floor bounded by walls).
  * Contains a `Pioneer3at` (4-wheel mobile base) equipped with a mounted `Camera` (1080x720).
* **Controller**: `controllers/robot_controller/robot_controller.py`
  * The Pioneer3-AT robot node in `Test.wbt` has its `controller` field set to `"robot_controller"`.
  * When Webots simulation steps forward, this script opens a TCP server on `127.0.0.1:10101` and listens for motion and camera capture commands.

### Step 5.3: Opening and Running the World Manually
1. Launch Webots.
2. Click **File** -> **Open World...** (`Ctrl+O`).
3. Navigate to your cloned repository and select `worlds/Test.wbt`.
4. The simulation will load in a paused state.
5. Click the **Play** (triangle button) in the top toolbar to start the physics simulation and initialize the controller socket server.

---

## 6. Running the Simulation

The startup scripts [`START_ROBOT.bat`](START_ROBOT.bat) and [`start_vision.bat`](start_vision.bat) are fully dynamic and portable. They automatically detect:
* The repository location using `%~dp0`.
* Webots installation in standard Program Files or `PATH`.
* Virtual environment Python (`.venv\Scripts\python.exe`) or system `python`.
* `llama-server.exe` in `<repo>\bin`, `<repo>\tools`, `%USERPROFILE%\.docker\bin\inference\`, or `PATH`.
* Vision model files in `<repo>\models\` or `%USERPROFILE%\models\`.
* Presence of `ai_bridge\.env`.

### Startup Procedure A: Automated (Recommended)

1. Double-click or execute from CMD:
   ```cmd
   START_ROBOT.bat
   ```
2. What `START_ROBOT.bat` does automatically:
   - **Step 1**: Verifies that Webots, world file, model weights, `llama-server.exe`, `.env`, and orchestrator exist.
   - **Step 2**: Terminates any stale `llama-server.exe` processes.
   - **Step 3**: Spawns `start_vision.bat` in a separate window to host `llama-server.exe` on port `8090`.
   - **Step 4**: Launches Webots with `worlds/Test.wbt`.
   - **Step 5**: Polls `http://127.0.0.1:8090/health` until the vision server reports ready.
   - **Step 6**: Polls port `10101` until the Webots controller TCP socket is open.
     *(**Action required**: When Webots opens, press the **Play** button if the simulation does not auto-start).*
   - **Step 7**: Enters the interactive Mission loop in the launcher window:
     ```text
     Enter mission (or press Enter to quit): Explore the environment autonomously.
     ```
3. The AI agent will now continuously observe through the robot's camera, reason with Nemotron, and issue wheel drive commands to explore the arena!

---

### Startup Procedure B: Manual (Step-by-Step in 3 Windows)

If you prefer full control over each component or are debugging:

#### Window 1: Start Vision Server (`start_vision.bat` or `llama-server.exe`)
```cmd
start_vision.bat
```
*Or directly via llama-server:*
```cmd
llama-server.exe -m "models\Qwen3VL-2B-Instruct-Q4_K_M.gguf" --mmproj "models\mmproj-Qwen3VL-2B-Instruct-F16.gguf" -c 4096 --host 127.0.0.1 --port 8090 -ngl 99
```
*Wait until output indicates the server is listening at `http://127.0.0.1:8090`.*

#### Window 2: Launch Webots Simulation
```cmd
"C:\Program Files\Webots\msys64\mingw64\bin\webotsw.exe" "worlds\Test.wbt"
```
*In the Webots window, click **Play** (triangle button) to begin simulation.*

#### Window 3: Run AI Orchestrator
```cmd
cd ai_bridge
..\.venv\Scripts\activate
python orchestrator.py "Explore the environment autonomously."
```

---

### Stopping the Simulation

* **Stop current mission**: Press `Ctrl+C` in the orchestrator window.
* **Stop everything (Webots + Vision + Agent)**:
  Run the cleanup script:
  ```cmd
  STOP_ROBOT.bat
  ```
  Or manually close the Webots and vision server windows.

---

## 7. Commands Cheat Sheet

Copy-paste commands for setup from the project root:

```cmd
:: 1. Clone repository
git clone https://github.com/Alex93824/Robot_Simulation.git
cd Robot_Simulation

:: 2. Create and activate virtual environment
py -3.11 -m venv .venv
.venv\Scripts\activate

:: 3. Install dependencies
python -m pip install --upgrade pip
pip install -r requirements.txt

:: 4. Create environment file and add API key
copy ai_bridge\.env.example ai_bridge\.env
notepad ai_bridge\.env

:: 5. Place model files into models\ or %USERPROFILE%\models\
:: Qwen3VL-2B-Instruct-Q4_K_M.gguf
:: mmproj-Qwen3VL-2B-Instruct-F16.gguf

:: 6. Launch everything automatically
START_ROBOT.bat

:: 7. Stop everything
STOP_ROBOT.bat
```

---

## 8. Troubleshooting

### 1. `python` or `py` is not recognized
* **Cause**: Python was not added to the Windows `PATH` environment variable during installation.
* **Fix**: Re-run the Python installer, check **"Add python.exe to PATH"**, and choose **Modify/Repair**. Restart your terminal.

### 2. `ModuleNotFoundError: No module named 'PIL'` in Webots console
* **Cause**: Webots is running its internal Python interpreter or a system Python that lacks Pillow.
* **Diagnostic**: Check the Webots console tab (bottom of Webots interface).
* **Fix**:
  1. Open Webots -> **Tools** -> **Preferences** -> **Python command**.
  2. Enter the full path to your `.venv\Scripts\python.exe`.
  3. Alternatively, install pillow globally: `python -m pip install pillow`.

### 3. `[ERROR] Environment file not found: ...\ai_bridge\.env`
* **Cause**: `ai_bridge/.env` was not created from `.env.example`.
* **Fix**: Run `copy ai_bridge\.env.example ai_bridge\.env` and edit it to provide your `NVIDIA_API_KEY`.

### 4. `[ERROR] Webots was not found.`
* **Cause**: Webots is not installed in the standard `Program Files` directory and is not in your `PATH`.
* **Fix**: Install Webots R2025a or add `C:\Program Files\Webots\msys64\mingw64\bin` to your Windows `PATH`.

### 5. `[ERROR] llama-server.exe was not found.`
* **Cause**: `llama-server.exe` is not placed in `<repo>\bin`, `<repo>\tools`, `%USERPROFILE%\.docker\bin\inference\`, or in `PATH`.
* **Fix**: Download `llama-server.exe` from `llama.cpp` GitHub releases and drop it into `bin\` or `tools\` inside the repository.

### 6. `[ERROR] Model file not found: Qwen3VL-2B-Instruct-Q4_K_M.gguf`
* **Cause**: The GGUF model files were not downloaded or placed in expected paths.
* **Fix**: Download `Qwen3VL-2B-Instruct-Q4_K_M.gguf` and `mmproj-Qwen3VL-2B-Instruct-F16.gguf` and place them either in `models\` inside the cloned repo or in `%USERPROFILE%\models\`.

### 7. `[wait] Webots socket not open yet. Press PLAY in Webots if you haven't!`
* **Cause**: Webots loaded the world in paused mode, so the controller loop has not started.
* **Fix**: Switch to the Webots window and press the **Play** (triangle) button on the top toolbar. The controller will log `[robot_controller] Listening on 127.0.0.1:10101 ...` and connection will succeed.

### 8. `Port 10101` or `Port 8090` already in use
* **Cause**: A previous simulation or server process did not terminate cleanly.
* **Fix**: Run `STOP_ROBOT.bat` to kill lingering processes:
  ```cmd
  taskkill /F /IM llama-server.exe /T
  taskkill /F /IM webots.exe /T
  taskkill /F /IM webotsw.exe /T
  ```

---

## 9. Project Architecture

```text
                                  +---------------------------------------+
                                  |         NVIDIA API Catalog            |
                                  |   (nvidia/nemotron-3-super-120b-a12b) |
                                  +---------------------------------------+
                                                     ^
                                     OpenAI API      |   Tool calls &
                                     (HTTPS)         |   system prompts
                                                     v
+--------------------------------+       +---------------------------------------+
|        Local Vision Server     |       |          AI Orchestrator              |
|        (llama-server.exe)      |       |      (ai_bridge/orchestrator.py)      |
|  Qwen3-VL-2B (GGUF) on :8090   |       |                                       |
+--------------------------------+       |  • High-level autonomous brain        |
         ^                               |  • Observe -> Think -> Act loop       |
         | HTTP POST                     |  • Decision making & tool execution   |
         | (/v1/chat/completions)        +---------------------------------------+
         v                                                   ^
+--------------------------------+                           |
|        Vision Worker           |                           | Thread-safe
|   (ai_bridge/vision_client.py) |                           | method calls
|                                |                           v
|  • Serialized GPU inference    |<--------------------------+
|  • Bounded history buffer      |
|  • Frame rate limiting         |
+--------------------------------+
         ^
         | Captures frame (base64 JPEG)
         v
+--------------------------------+
|         Webots Client          |
|   (ai_bridge/webots_client.py) |
+--------------------------------+
         ^
         | TCP Socket (127.0.0.1:10101)
         | Newline-delimited JSON commands:
         |   {"cmd": "move", "left": 0.5, "right": 0.5, "duration": 2.0}
         |   {"cmd": "get_camera"}
         |   {"cmd": "stop"}
         v
+--------------------------------------------------------------------------------+
|                           Webots Simulator (R2025a)                            |
|                                                                                |
|  +--------------------------------------------------------------------------+  |
|  |             Robot Controller (controllers/.../robot_controller.py)       |  |
|  |                                                                          |  |
|  |  • Steps simulation timestep                                             |  |
|  |  • Translates JSON commands to motor velocity fractions (-1.0 to +1.0)   |  |
|  |  • Captures Camera BGRA buffer -> converts to JPEG via Pillow            |  |
|  +--------------------------------------------------------------------------+  |
|                                     |                                          |
|                                     v Motors & Camera Devices                  |
|  +--------------------------------------------------------------------------+  |
|  |       Pioneer 3-AT Robot (4 wheels, skid-steer) + Mounted Camera         |  |
|  |       Simulated inside 10x10 RectangleArena (worlds/Test.wbt)            |  |
|  +--------------------------------------------------------------------------+  |
+--------------------------------------------------------------------------------+
```

---

## 10. Fresh PC Setup Checklist

Follow this sequential checklist when setting up on a brand-new computer:

- [ ] **1. Install Git for Windows**: Download from `git-scm.com` and install.
- [ ] **2. Install Python 3.11 (64-bit)**: Download from `python.org`. Check **"Add python.exe to PATH"**.
- [ ] **3. Install Webots R2025a**: Download installer from Webots GitHub Releases and install to default location.
- [ ] **4. Clone Repository**:
  ```cmd
  git clone https://github.com/Alex93824/Robot_Simulation.git
  cd Robot_Simulation
  ```
- [ ] **5. Create Virtual Environment**:
  ```cmd
  py -3.11 -m venv .venv
  .venv\Scripts\activate
  ```
- [ ] **6. Install Dependencies**:
  ```cmd
  pip install -r requirements.txt
  ```
- [ ] **7. Setup `.env` File**:
  ```cmd
  copy ai_bridge\.env.example ai_bridge\.env
  ```
- [ ] **8. Configure `NVIDIA_API_KEY`**: Obtain key from [build.nvidia.com](https://build.nvidia.com) and paste into `ai_bridge/.env`.
- [ ] **9. Obtain Vision Server & Model Files**:
  - Download `llama-server.exe` from `llama.cpp` releases and place into `bin\` or `tools\` or `%USERPROFILE%\.docker\bin\inference\`.
  - Download `Qwen3VL-2B-Instruct-Q4_K_M.gguf` and `mmproj-Qwen3VL-2B-Instruct-F16.gguf` and place into `models\` or `%USERPROFILE%\models\`.
- [ ] **10. Start Simulation**:
  - Execute `START_ROBOT.bat`.
  - In Webots, click **Play** (triangle button).
- [ ] **11. Enter Mission**:
  - Type `Explore the environment autonomously.` and verify the robot begins moving and analyzing scenes.

---

## 11. Developer Notes

Key observations and architectural design notes:

1. **Fully Portable Paths**:
   All repository paths are resolved dynamically using `%~dp0`, and external model/server paths search `%PROJECT_DIR%models`, `%PROJECT_DIR%bin`, `%USERPROFILE%\models`, and `%USERPROFILE%\.docker\bin\inference`. Neither you nor your friend need to edit scripts after cloning.

2. **Model Weights Not in Git**:
   The vision model weights (`Qwen3VL-2B-Instruct-Q4_K_M.gguf` ~1.1GB and `mmproj-Qwen3VL-2B-Instruct-F16.gguf` ~820MB) are binary GGUF files and are not stored in Git. Collaborators can place them in `models\` inside the repo or `%USERPROFILE%\models\`.

3. **Strict GPU Serialization for Vision**:
   In `ai_bridge/vision_client.py`, a dedicated lock (`_inference_lock`) ensures that at most **one** vision inference runs concurrently. This design explicitly caters to consumer GPUs (such as the GTX 1650 4GB VRAM) to prevent CUDA out-of-memory errors.

4. **Webots Python Environment Dual Requirement**:
   `robot_controller.py` runs within the Webots process and requires `PIL` (Pillow). If Webots uses the system Python while dependencies were only installed in `.venv`, `robot_controller.py` will crash on import. Always ensure Pillow is installed in Webots' active Python environment.

5. **Single-Client Socket Architecture**:
   `robot_controller.py` only binds and accepts a single active client connection on port `10101`. If a previous connection was not closed, restarting the orchestrator may result in connection refusal until the previous connection times out or Webots simulation is reset.

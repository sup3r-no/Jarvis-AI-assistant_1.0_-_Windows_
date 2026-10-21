# J.A.R.V.I.S. for Windows

Windows version of Jarvis assistant previously made for android devices. Can have one-on-one conversations, open apps, generate 3D models/simulations, control smart devices, access God's Eye View, and more...

This repository contains a Windows desktop assistant with a voice-and-text interface. It uses local Ollama models for conversation and command routing, Windows speech services for spoken replies, Blender for 3D scene generation, and a bundled God's Eye View globe that runs locally in a browser window. SmartThings and Home Assistant controls are optional integrations.

If you just want to install, download and run the Jarvis_Setup_v1.exe

If you would like to know how it works, you can explore the Jarvis folder and/or read the rest of this.

## Install the Windows app

1. Run `Jarvis_Setup_v1.exe` from the repository root and follow the installer.
2. If Blender is not installed, install it from [blender.org](https://www.blender.org/download/) for 3D generation.
3. Install [Ollama](https://ollama.com/download) and start it. Jarvis sends local AI requests to Ollama at `http://localhost:11434`.
4. Launch **J.A.R.V.I.S.** from the Start menu or desktop shortcut.

The installer includes the God's Eye View files and installs Node.js if it is missing. Each time Jarvis starts, it runs `npm install` for the map and starts its local server. This requires an internet connection and may take a few minutes.

## Run from source

The Windows application source and bundled map are in `Jarvis`. Install Python, Node.js/npm, Ollama, and (for 3D generation) Blender. The map currently supports Node.js `>=24.14 <25` or `>=26 <27`; the packaged installer handles its own Node.js installation.

From PowerShell, install the Python packages and start the app:

```powershell
Set-Location .\Jarvis
python -m pip install SpeechRecognition pyttsx3 PyAudio
python .\jarvis_windows.py
```

Each app start runs the local God's Eye View server and `npm install` in `Jarvis\gods-eye-view`. Keep Node.js/npm available on `PATH`. The source launcher does not install Ollama or Blender; install and configure those separately. The repository does not include a Python requirements file.

## Use Jarvis

### Text commands

Type a request in the field at the bottom of the **AI** tab and press **Enter** or **Send**. For example:

- `What is the weather like?` — ask a conversational question.
- `Open Notepad` — open a Windows app or supported target.
- `Create a low-poly tree in Blender` — ask Jarvis to generate a Blender scene.
- `Turn on the desk lamp` — control a device after configuring and syncing a supported smart-home integration.

### Voice commands

Jarvis starts listening for the wake word **“Jarvis”**. Say the wake word followed by a command, or say “Jarvis” and wait for the prompt before speaking. The default listening control is **Num Lock**: when Num Lock is on, Jarvis is muted; turn it off to listen. You can change the wake word, activation key, recognition language, and autocorrect behavior in **Settings**.

Voice recognition uses Google's speech-recognition service, so it needs a working microphone and internet access. Typed requests do not require microphone access. Spoken responses use Windows text-to-speech.

### Settings and optional integrations

Open **Settings** with the gear button. You can select the local chat and coding models, download Ollama models, adjust voice and appearance, or configure smart-home access. The defaults are `llama3.2` for conversation and `qwen2.5-coder` for Blender coding; Ollama must be running and the selected models must be installed. Use the model download field in Settings or run `ollama pull llama3.2` and `ollama pull qwen2.5-coder` in a terminal.

For smart-home control, choose **SmartThings** or **Home Assistant**, enter the matching access token (and the Home Assistant URL when applicable), then select **Sync**. Only connect accounts and devices you trust. Tokens entered in Settings are held only for the current app run; settings are not saved between launches, so you will need to enter them again after restarting Jarvis. Do not share your tokens.

### Blender and 3D generation

Install Blender before asking for a model or simulation. Jarvis can open Blender and send it instructions using a local bridge. Keep Ollama running with the selected coding model installed. Basic structural scenes and simple simulations are the intended path; complex organic, text-to-3D generation is not ready out of the box and requires a separate Shap-E setup.

### God's Eye View

When the map server is ready, select the **MAP** tab and launch the tactical overlay. Jarvis opens and embeds a Microsoft Edge app window showing God's Eye View, an interactive globe with public-data layers such as flights, ships, satellites, earthquakes, and cameras. The map is bundled under `Jarvis\gods-eye-view`; its data feeds and features may require internet access. Some optional map imagery and services may also require provider keys or accounts.

Thanks to: Bilawal Sidhu at https://github.com/bilawalsidhu/gods-eye-view 

## Troubleshooting

- **Jarvis cannot answer:** Confirm Ollama is installed, running, and has the selected model. The app connects to `localhost:11434`.
- **Voice input does not work:** Check Windows microphone permission and the selected input device; verify Num Lock is off with the default listening-key setting. Speech recognition also needs internet access.
- **Blender commands do not run:** Install Blender and an Ollama coding model, then restart Jarvis.
- **The MAP tab does not appear:** Wait for `npm install` and local server startup. Check that Node.js/npm are installed and available on `PATH`, and that port `4173` is available.
- **Settings reset after closing:** This is expected; the current app keeps settings in memory for the active run only.

## Notes

Jarvis runs as a local Windows application, but voice transcription is sent to Google's speech-recognition service. Ollama prompts are sent to the local Ollama service. God's Eye View connects to its configured online data providers. Review the relevant providers' terms and privacy policies before use.

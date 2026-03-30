# GLaDOS Desktop Buddy

A fully self‑contained, interactive desktop companion that brings GLaDOS from Portal to life. It slides onto your screen, speaks with her authentic voice, and holds sarcastic conversations using a local AI.

---

## Features

- Frameless, Always‑on‑Top Window: No title bar; stays above all other applications.
- Sliding Entrance/Exit: Drops down from above the screen on startup and slides up on shutdown.
- State‑Based Animations: Separate GIFs for startup, idle, talking, and shutdown states.
- Flipping Logic: The buddy automatically faces the correct direction when dragged to the right side of the screen.
- Click Detection: Only reacts when you click on the actual character (transparent backgrounds are ignored).
- Dragging with Edge Clamping: The window stays tethered to the top edge and cannot be dragged off‑screen.
- Authentic GLaDOS Voice: Uses a neural TTS engine trained on Ellen McLain’s voice.
- Local AI Chatbot: Powered by Ollama with a sarcastic, Portal-themed system prompt.
- Portal‑Themed Chat Window: Features a custom title bar, scrollbar, resizing, and minimisation.
- Taskbar Icon: Appears with your own custom icon.

---

## Requirements

1. Python 3.13
Other versions may work, but 3.13 is actively tested and recommended.

2. Ollama
Install it from ollama.com and pull the required model via your terminal:
ollama pull llama3.2

3. GLaDOS TTS Module
This project requires the neural voice engine. Clone it from the original repository and copy the glados folder into your project root:
git clone https://github.com/nimaid/GLaDOS-TTS.git
cp -r GLaDOS-TTS/glados ./

4. Python Packages
Install the required dependencies:
pip install -r requirements.txt

## How to Run

1. Prepare the Environment
- Ensure Python 3.13 is installed.
- Ensure the Ollama service is running and the llama3.2 model is downloaded.
- Place the glados folder in your project root.
- Install the Python dependencies using pip install -r requirements.txt.

2. Run the Script
Execute the project from the terminal:
python src/main.py

3. Build a Standalone Executable (Optional)
To package the project into a portable .exe file on Windows:
pip install pyinstaller
py -3.13 -m PyInstaller --onefile --windowed --add-data "assets;assets" --add-data "glados;glados" --add-data "GLaDOSicon.ico;." --icon=GLaDOSicon.ico src/main.py

The generated executable will be located in the dist/ folder.

---

## How It Works

The Chatbot
The AI uses Ollama with the llama3.2 model. A custom system prompt forces the model to behave exactly like GLaDOS: sarcastic, witty, and brief. The last 5 exchanges are kept in memory for conversational context.

The Voice
The glados module is a neural TTS engine trained on Ellen McLain’s original GLaDOS voice lines. When generated, it saves a waveform to a temporary WAV file and plays it via pygame.mixer. 

Flipping Logic
When dragged, the program checks its centre relative to the screen's center. A dead zone of 200px (100px on each side) prevents rapid flipping. Moving past this threshold triggers the buddy to flip directions.

Click Detection
The program reads the alpha channel of the current animation frame on click. If you click on a fully transparent pixel (Alpha = 0), the click is ignored. Clicking the actual sprite triggers a custom prompt.

Offline Capability
The entire program runs fully offline after the initial setup. Only the initial package installations and model downloads require an internet connection.

---

## Assets Credits

- GIF animations – created by thumbsdown on Newgrounds.
View the original artwork

- Window icon – based on a vector by a Reddit user (original post deleted).
Source discussion

---

## Troubleshooting

- glados module not found: Ensure the glados folder is directly in the project root (on the same level as src/ and assets/).
- Ollama not responding: Ensure the Ollama service is actively running in the background (ollama serve) and you pulled llama3.2.
- No audio: Check your system volume and ensure that pygame can initialize the mixer properly. Error logs will print to the console.
- Taskbar icon not showing: This is a known Windows OS issue with frameless applications. Compiling the project into an .exe usually resolves this.

---

## Contributing

This project is a personal creation and is strictly closed to external contributions. Please do not open pull requests or submit code modifications, as they will not be reviewed or merged. Feel free to fork the repository for your own personal use in accordance with the license.

---

## License & Acknowledgements

- This project is open-source and licensed under the MIT License.
- Special thanks to the creators of GLaDOS-TTS for the neural voice engine and Ollama for the local LLM interaction.
- Portal and GLaDOS are trademarks of Valve Corporation. This project is a non-commercial fan creation and is not affiliated with Valve.

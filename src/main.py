"""
Author: Daniel Yu
Date: March 30, 2026
Description:
    GLaDOS Desktop Buddy – a frameless, always-on-top, draggable desktop companion
    inspired by GLaDOS from Portal. Features:
    - Animated GIFs with state machine (startup, idle, talking, shutdown)
    - Sliding entrance/exit animations (2 seconds)
    - Neural TTS using the glados module (authentic GLaDOS voice)
    - Local AI chatbot using Ollama (llama3.2 model) for sarcastic, Portal-themed answers
    - Flipping logic: uses mirrored frames when the window is entirely on the right half
    - Click detection: only reacts when clicking on opaque pixels of the GIF
    - Portal-themed chat window with custom title bar, scrollbar, resizing, and minimize/maximize
    - Taskbar icon support
    - Edge clamping (window stays within screen bounds, always at y=0)

Requirements:
    - Python 3.13
    - glados (neural TTS) folder in project root
    - Ollama installed and running with model 'llama3.2'
    - pygame, soundfile, Pillow, requests, numpy (via soundfile)
"""

import os
import sys
import threading
import random
import time
import tkinter as tk
from tkinter import Menu
from PIL import Image, ImageTk
import requests
import tempfile
import soundfile as sf
import pygame
import re

# ----------------------------------------------------------------------
# Add project root to sys.path to allow importing glados (which is in the same folder)
# ----------------------------------------------------------------------
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# ----------------------------------------------------------------------
# TTS Engine – uses glados neural TTS exclusively
# ----------------------------------------------------------------------
class TTS:
    """Handles text-to-speech using the glados neural TTS module."""
    def __init__(self):
        # Import the glados module (must be in the project root)
        import glados
        # Create the TTS engine
        self.engine = glados.TTS()
        # Initialize pygame mixer for audio playback (22050 Hz, 16-bit, mono)
        pygame.mixer.init(frequency=22050, size=-16, channels=1)
        self.speaking = False  # Flag to prevent overlapping speech
        print("Loaded glados TTS class")

    def say(self, text, callback=None):
        """
        Generate speech from text and play it. If speech is already playing, the call is ignored.
        :param text: The text to speak.
        :param callback: Optional function to call after speech finishes.
        """
        if self.speaking:
            return  # Do not start a new utterance while one is playing

        self.speaking = True

        def speak_thread():
            """Threaded function that generates audio and plays it."""
            try:
                # Generate audio as a numpy array (float32)
                audio = self.engine.generate_speech_audio(text)
                sample_rate = 22050
                # Write to a temporary WAV file
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
                    temp_path = f.name
                sf.write(temp_path, audio, sample_rate)

                # Play the audio using pygame
                sound = pygame.mixer.Sound(temp_path)
                sound.play()
                # Wait until playback finishes
                while pygame.mixer.get_busy():
                    pygame.time.wait(100)
                # Clean up temporary file
                os.unlink(temp_path)
            except Exception as e:
                print(f"TTS error: {e}")
            finally:
                self.speaking = False
                if callback:
                    # Schedule callback in the main Tkinter thread
                    if tk._default_root:
                        tk._default_root.after_idle(callback)

        # Start speech in a background thread to keep GUI responsive
        threading.Thread(target=speak_thread, daemon=True).start()

# ----------------------------------------------------------------------
# Ollama AI – free local LLM (must be running)
# ----------------------------------------------------------------------
class OllamaAI:
    """Interface to the local Ollama server for generating sarcastic responses."""
    def __init__(self):
        self.system_prompt = (
            "You are GLaDOS, the sarcastic AI from Portal. "
            "You are a desktop buddy. Respond in short, witty, sarcastic sentences. "
            "If the user asks a factual question, answer it correctly but with a sarcastic twist. "
            "Never break character. Do not use parentheses or asterisks to denote actions."
        )
        self.base_url = "http://localhost:11434"  # Default Ollama API endpoint
        self.model = "llama3.2"                  # Model to use; must be pulled via `ollama pull llama3.2`
        self.conversation_history = []           # Stores last few exchanges for context
        self.available = False                   # Whether Ollama is reachable and model is present
        self._check_available()

    def _check_available(self):
        """Ping Ollama and check if the required model is available."""
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=2)
            if r.status_code == 200:
                models = r.json().get("models", [])
                if any(m["name"].startswith(self.model) for m in models):
                    self.available = True
                    print(f"Ollama available with model '{self.model}'")
                else:
                    print(f"Ollama running but model '{self.model}' not found. Please pull it with: ollama pull {self.model}")
            else:
                print("Ollama not reachable – will not respond")
        except:
            print("Ollama not reachable – will not respond")

    def respond(self, user_input, callback):
        """
        Send user input to Ollama and call callback with the generated response.
        If Ollama is not available, callback is called with an error message.
        """
        if not self.available:
            if callback:
                callback("Ollama is not running. Please start it and try again.")
            return

        def ollama_call():
            """Threaded function that performs the API call."""
            try:
                # Build messages including system prompt and recent history
                messages = [
                    {"role": "system", "content": self.system_prompt},
                    *self.conversation_history[-5:],
                    {"role": "user", "content": user_input}
                ]
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "stream": False,
                    "options": {"temperature": 0.8, "num_predict": 150}
                }
                r = requests.post(f"{self.base_url}/api/chat", json=payload, timeout=15)
                r.raise_for_status()
                data = r.json()
                reply = data["message"]["content"].strip()
                # Update conversation history
                self.conversation_history.append({"role": "user", "content": user_input})
                self.conversation_history.append({"role": "assistant", "content": reply})
                if len(self.conversation_history) > 10:
                    self.conversation_history = self.conversation_history[-10:]
            except Exception as e:
                print(f"Ollama error: {e}")
                reply = "I'm having trouble thinking right now. Perhaps try again later."
            if callback:
                # Schedule callback in the main Tkinter thread
                if tk._default_root:
                    tk._default_root.after_idle(lambda: callback(reply))

        threading.Thread(target=ollama_call, daemon=True).start()

# ----------------------------------------------------------------------
# GIF Frame Cache – loads frames from a GIF, optionally mirrored
# ----------------------------------------------------------------------
class GIFCache:
    """Caches frames of GIFs to avoid reloading. Supports mirroring."""
    _cache = {}  # Class-level cache dictionary

    @classmethod
    def get_frames(cls, gif_path, mirrored=False):
        """
        Retrieve frames and durations for a GIF, optionally mirrored.
        Returns a tuple (frames list, durations list).
        """
        key = (gif_path, mirrored)
        if key not in cls._cache:
            frames = []
            durations = []
            try:
                im = Image.open(gif_path)
                while True:
                    # Convert each frame to RGBA for transparency
                    frame = im.convert("RGBA")
                    if mirrored:
                        # Flip horizontally
                        frame = frame.transpose(Image.FLIP_LEFT_RIGHT)
                    # Create a PhotoImage that Tkinter can use
                    tk_image = ImageTk.PhotoImage(frame)
                    frames.append(tk_image)
                    # Get frame duration (default 100 ms)
                    durations.append(im.info.get("duration", 100))
                    im.seek(im.tell() + 1)  # Move to next frame
            except EOFError:
                # End of animation – normal
                pass
            except Exception as e:
                print(f"Error loading {gif_path}: {e}")
            cls._cache[key] = (frames, durations)
        return cls._cache[key]

# ----------------------------------------------------------------------
# GIF Player – handles animation playback
# ----------------------------------------------------------------------
class GIFPlayer:
    """Plays a sequence of frames using Tkinter's after() method."""
    def __init__(self, master, label, frames, durations, loop=True, on_finish=None):
        """
        :param master: Tkinter widget (the root or parent)
        :param label: Label widget that will display the frames
        :param frames: List of PhotoImage objects
        :param durations: List of frame durations (ms)
        :param loop: Whether to loop the animation
        :param on_finish: Callback when a non‑looping animation ends
        """
        self.master = master
        self.label = label
        self.frames = frames
        self.durations = durations
        self.loop = loop
        self.on_finish = on_finish

        self.current_frame = 0
        self.after_id = None
        self.is_playing = False

        # If no frames and not looping, call finish immediately
        if not frames and not loop and on_finish:
            on_finish()

    def start(self):
        """Begin or restart the animation."""
        if not self.frames:
            return
        self.stop()          # Cancel any existing after callback
        self.is_playing = True
        self._next_frame()

    def stop(self):
        """Stop the animation and cancel scheduled next frame."""
        if self.after_id:
            self.master.after_cancel(self.after_id)
            self.after_id = None
        self.is_playing = False

    def _next_frame(self):
        """Display the next frame and schedule the following one."""
        if not self.is_playing:
            return
        # Show current frame
        self.label.config(image=self.frames[self.current_frame])
        self.label.image = self.frames[self.current_frame]  # Keep reference
        # Advance frame index
        self.current_frame += 1
        if self.current_frame >= len(self.frames):
            if self.loop:
                self.current_frame = 0
            else:
                # Animation finished, stop and call callback
                self.stop()
                if self.on_finish:
                    self.on_finish()
                return
        # Schedule next frame with the duration of the current frame
        duration = self.durations[self.current_frame]
        self.after_id = self.master.after(duration, self._next_frame)

# ----------------------------------------------------------------------
# Windows-specific helper to make a frameless window appear in the taskbar
# ----------------------------------------------------------------------
if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    def get_top_level_hwnd(window):
        """Get the top‑level window handle for a Tk window (works with overrideredirect)."""
        hwnd = window.winfo_id()
        parent = ctypes.windll.user32.GetParent(hwnd)
        if parent:
            hwnd = parent
        return hwnd

    def set_taskbar_icon(hwnd):
        """Modify window style to force appearance in the taskbar."""
        GWL_EXSTYLE = -20
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_APPWINDOW = 0x00040000
        exstyle = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        # Remove TOOLWINDOW style and add APPWINDOW style
        ctypes.windll.user32.SetWindowLongW(hwnd, GWL_EXSTYLE,
                                            (exstyle & ~WS_EX_TOOLWINDOW) | WS_EX_APPWINDOW)
else:
    # Dummy functions for non‑Windows platforms
    def get_top_level_hwnd(window):
        return None
    def set_taskbar_icon(hwnd):
        pass

# ----------------------------------------------------------------------
# Clean text for TTS – removes parentheses, brackets, asterisks, trailing periods
# ----------------------------------------------------------------------
def clean_text(text):
    """
    Remove text that should not be spoken (e.g., stage directions, math notation)
    and trim trailing punctuation to avoid the voice saying "point".
    """
    # Remove anything inside parentheses or brackets
    text = re.sub(r'\([^)]*\)', '', text)
    text = re.sub(r'\[[^\]]*\]', '', text)
    # Remove asterisks (stage directions)
    text = re.sub(r'\*[^*]*\*', '', text)
    # Remove trailing periods, exclamation, question marks
    text = text.rstrip('.!?')
    # Remove multiple spaces
    text = re.sub(r'\s+', ' ', text).strip()
    return text

# ----------------------------------------------------------------------
# Main GLaDOS Buddy Window
# ----------------------------------------------------------------------
class GLaDOSBuddy:
    """The main application window and logic."""
    def __init__(self):
        # Create the main window
        self.root = tk.Tk()
        self.root.title("GLaDOS Desktop Buddy")
        self.root.overrideredirect(True)                   # No title bar
        self.root.wm_attributes("-topmost", True)          # Always on top
        self.root.wm_attributes("-transparentcolor", "#f0f0f0")  # Make this color transparent
        self.root.configure(bg="#f0f0f0")

        # Override the window close (X) button to trigger shutdown sequence
        self.root.protocol("WM_DELETE_WINDOW", self.exit_app)

        # Set window icon for the taskbar
        try:
            if getattr(sys, 'frozen', False):
                icon_path = os.path.join(sys._MEIPASS, "GLaDOSicon.ico")
            else:
                icon_path = os.path.join(project_root, "GLaDOSicon.ico")
            if os.path.exists(icon_path):
                self.root.iconbitmap(icon_path)
                print("Window icon loaded from", icon_path)
            else:
                print("Icon file NOT FOUND at", icon_path)
        except Exception as e:
            print(f"Icon loading error: {e}")

        # Apply taskbar style (Windows only)
        if sys.platform == "win32":
            self.root.update_idletasks()
            hwnd = get_top_level_hwnd(self.root)
            set_taskbar_icon(hwnd)
            print("Taskbar style applied")

        # State machine variables
        self.current_state = None          # "startup", "idle", "talking", "shutdown"
        self.current_player = None         # Current GIFPlayer instance
        self.mirrored = False              # Current orientation (False = normal, True = mirrored)
        self.window_width = 400            # Will be updated from GIF dimensions
        self.window_height = 400

        # Paths to GIFs (only original files; mirrored frames are generated on the fly)
        self.startup_gif = self._get_asset("startup.gif")
        self.idle_gif = self._get_asset("idle.gif")
        self.talking_gif = self._get_asset("talking.gif")
        self.shutdown_gif = self._get_asset("shutdown.gif")

        # Load frames for normal orientation (also preload mirrored frames via cache)
        self.startup_frames, self.startup_durations = GIFCache.get_frames(self.startup_gif, False)
        self.idle_frames, self.idle_durations = GIFCache.get_frames(self.idle_gif, False)
        self.talking_frames, self.talking_durations = GIFCache.get_frames(self.talking_gif, False)
        self.shutdown_frames, self.shutdown_durations = GIFCache.get_frames(self.shutdown_gif, False)

        # Preload mirrored versions (so they're ready when needed)
        self.idle_frames_mirrored, self.idle_durations_mirrored = GIFCache.get_frames(self.idle_gif, True)
        self.talking_frames_mirrored, self.talking_durations_mirrored = GIFCache.get_frames(self.talking_gif, True)
        self.shutdown_frames_mirrored, self.shutdown_durations_mirrored = GIFCache.get_frames(self.shutdown_gif, True)

        # Determine window size from startup GIF's first frame
        try:
            im = Image.open(self.startup_gif)
            self.window_width, self.window_height = im.size
        except:
            pass

        # Create a Label to hold the animation
        self.image_label = tk.Label(self.root, bg="#f0f0f0", bd=0)
        self.image_label.pack()

        # Store the current PIL image for click detection (will be updated as state/orientation changes)
        self.current_pil_image = None
        # Show the first frame of startup GIF during the slide (if available)
        if self.startup_frames:
            self.image_label.config(image=self.startup_frames[0])
            self.image_label.image = self.startup_frames[0]
            try:
                self.current_pil_image = Image.open(self.startup_gif).convert("RGBA")
            except:
                pass

        # Mouse bindings
        self.image_label.bind("<Button-3>", self.show_menu)          # Right‑click menu
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.image_label.bind("<Button-1>", self.start_drag)        # Start dragging
        self.image_label.bind("<B1-Motion>", self.on_drag)          # Drag motion
        self.image_label.bind("<ButtonRelease-1>", self.on_click_release)  # Click detection

        # Right‑click context menu (no Test Talk)
        self.context_menu = Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="Open Chat", command=self.open_chat)
        self.context_menu.add_command(label="Deactivate", command=self.exit_app)

        # TTS and AI
        self.tts = TTS()
        self.ai = OllamaAI()

        # Chat window reference
        self.chat_window = None

        # Screen dimensions (for edge clamping and flip thresholds)
        self.root.update_idletasks()
        self.screen_width = self.root.winfo_screenwidth()
        self.screen_height = self.root.winfo_screenheight()
        print(f"Screen width: {self.screen_width}")

        # Start the entrance animation
        self._slide_in_startup()

    def _get_asset(self, filename):
        """Return absolute path to an asset inside assets/animations/."""
        if getattr(sys, 'frozen', False):
            base = sys._MEIPASS
        else:
            base = project_root
        return os.path.join(base, "assets", "animations", filename)

    # ------------------------------------------------------------------
    # Sliding animations (2 seconds)
    # ------------------------------------------------------------------
    def _slide_in_startup(self):
        """Place the window above the screen, then slide it down to y=0."""
        self.root.geometry(f"+0+{-self.window_height}")
        self.root.update()
        # Small delay to ensure geometry is applied
        self.root.after(50, self._start_slide)

    def _start_slide(self):
        """Begin the sliding animation from above to top-left."""
        self._animate_slide(0, -self.window_height, 0, 0, duration=2000, callback=self._startup_after_slide)

    def _slide_out_and_destroy(self):
        """Slide the window up and then destroy it."""
        current_x = self.root.winfo_x()
        current_y = self.root.winfo_y()
        target_y = -self.window_height
        self._animate_slide(current_x, current_y, current_x, target_y, duration=2000, callback=self.root.destroy)

    def _animate_slide(self, start_x, start_y, target_x, target_y, duration=2000, callback=None, steps=40):
        """Animate the window from (start_x, start_y) to (target_x, target_y) over duration ms."""
        self._slide_steps = steps
        self._slide_current_step = 0
        self._slide_start_x = start_x
        self._slide_start_y = start_y
        self._slide_target_x = target_x
        self._slide_target_y = target_y
        self._slide_dx = (target_x - start_x) / steps
        self._slide_dy = (target_y - start_y) / steps
        self._slide_callback = callback
        self._slide_interval = duration // steps
        self._slide_next()

    def _slide_next(self):
        """Perform one step of the slide animation."""
        if self._slide_current_step < self._slide_steps:
            new_x = self._slide_start_x + self._slide_current_step * self._slide_dx
            new_y = self._slide_start_y + self._slide_current_step * self._slide_dy
            self.root.geometry(f"+{int(new_x)}+{int(new_y)}")
            self._slide_current_step += 1
            self.root.after(self._slide_interval, self._slide_next)
        else:
            # Final position
            self.root.geometry(f"+{self._slide_target_x}+{self._slide_target_y}")
            if self._slide_callback:
                self._slide_callback()

    def _startup_after_slide(self):
        """After slide finishes, start the startup GIF animation."""
        self._play_startup()

    def _play_startup(self):
        """Play the startup GIF once, then switch to idle state."""
        def on_startup_finished():
            self.set_state("idle")
            # After the startup animation, speak the full Portal quote
            self.root.after(500, lambda: self.say_and_animate(
                "Oh. It's you. It's been a long time. How have you been? I've been really busy being dead. You know, after you murdered me?"
            ))

        self._stop_current_animation()
        player = GIFPlayer(self.root, self.image_label,
                           self.startup_frames, self.startup_durations,
                           loop=False, on_finish=on_startup_finished)
        player.start()
        self.current_player = player
        self.current_state = "startup"

        # Update click detection image to the startup GIF's first frame
        try:
            self.current_pil_image = Image.open(self.startup_gif).convert("RGBA")
        except:
            pass

    # ------------------------------------------------------------------
    # State management with mirroring
    # ------------------------------------------------------------------
    def set_state(self, state):
        """Change the current state and update the animation accordingly."""
        if state == self.current_state:
            return
        print(f"Setting state to {state}")
        self._stop_current_animation()

        if state == "idle":
            # Adjust window size to match idle GIF
            try:
                im = Image.open(self.idle_gif)
                self.window_width, self.window_height = im.size
                self.root.geometry(f"{self.window_width}x{self.window_height}")
                self.current_pil_image = im.convert("RGBA")
            except:
                pass
            frames, durations = self._get_frames_for_state("idle")
            if frames:
                player = GIFPlayer(self.root, self.image_label, frames, durations, loop=True)
                player.start()
                self.current_player = player
            else:
                self.image_label.config(image='')
            self.current_state = "idle"

        elif state == "talking":
            # Adjust window size to match talking GIF
            try:
                im = Image.open(self.talking_gif)
                self.window_width, self.window_height = im.size
                self.root.geometry(f"{self.window_width}x{self.window_height}")
                self.current_pil_image = im.convert("RGBA")
            except:
                pass
            frames, durations = self._get_frames_for_state("talking")
            if frames:
                player = GIFPlayer(self.root, self.image_label, frames, durations, loop=True)
                player.start()
                self.current_player = player
            else:
                self.image_label.config(image='')
            self.current_state = "talking"

    def _get_frames_for_state(self, state):
        """Return the correct frame list and durations based on current mirrored flag."""
        if state == "idle":
            if self.mirrored:
                return self.idle_frames_mirrored, self.idle_durations_mirrored
            else:
                return self.idle_frames, self.idle_durations
        elif state == "talking":
            if self.mirrored:
                return self.talking_frames_mirrored, self.talking_durations_mirrored
            else:
                return self.talking_frames, self.talking_durations
        return [], []

    def _stop_current_animation(self):
        """Stop the currently running animation."""
        if self.current_player:
            self.current_player.stop()

    # ------------------------------------------------------------------
    # Dragging with hysteresis dead zone (prevents rapid flipping)
    # ------------------------------------------------------------------
    def start_drag(self, event):
        """Record the starting point of a drag operation."""
        self.drag_start_x = event.x
        self.drag_start_y = event.y

    def on_drag(self, event):
        """
        Move the window (y clamped to 0, x clamped to screen edges) and update mirroring
        based on whether the whole window is on the left or right side.
        """
        new_x = self.root.winfo_x() + event.x - self.drag_start_x
        # Clamp x to screen boundaries
        max_x = self.screen_width - self.window_width
        new_x = max(0, min(new_x, max_x))
        new_y = 0  # always at top
        self.root.geometry(f"+{new_x}+{new_y}")

        # Hysteresis: define thresholds 100px left/right of screen centre
        window_center = new_x + self.window_width // 2
        screen_center = self.screen_width // 2
        left_threshold = screen_center - 100
        right_threshold = screen_center + 100

        # Determine desired orientation
        if window_center < left_threshold:
            desired = False          # normal (left side)
        elif window_center > right_threshold:
            desired = True           # mirrored (right side)
        else:
            # Inside the dead zone – keep current orientation (latch)
            desired = self.mirrored

        # Only update if desired orientation differs from current
        if desired != self.mirrored:
            self.mirrored = desired
            if self.current_state in ("idle", "talking"):
                # Stop current animation
                self._stop_current_animation()
                frames, durations = self._get_frames_for_state(self.current_state)
                if frames:
                    # Preserve the current frame index to avoid jump
                    current_frame_index = self.current_player.current_frame if self.current_player else 0
                    new_player = GIFPlayer(self.root, self.image_label, frames, durations, loop=True)
                    new_player.current_frame = current_frame_index % len(frames)
                    new_player.start()
                    self.current_player = new_player
                # Update click detection image to the new orientation's first frame
                try:
                    if self.current_state == "idle":
                        im = Image.open(self.idle_gif)
                    else:
                        im = Image.open(self.talking_gif)
                    if self.mirrored:
                        im = im.transpose(Image.FLIP_LEFT_RIGHT)
                    self.current_pil_image = im.convert("RGBA")
                except:
                    pass

    def on_click_release(self, event):
        """Detect if the user clicked on a non‑transparent pixel and say "Stop that."."""
        if self.current_pil_image is None:
            return
        x = event.x
        y = event.y
        # Check if coordinates are inside the image
        if 0 <= x < self.current_pil_image.width and 0 <= y < self.current_pil_image.height:
            pixel = self.current_pil_image.getpixel((x, y))
            # If pixel has alpha and it's zero (fully transparent), ignore click
            if len(pixel) == 4 and pixel[3] == 0:
                return
            # Speak only once per click (overlapping speech is prevented by TTS.speaking flag)
            self.say_and_animate("Stop that.")

    # ------------------------------------------------------------------
    # Text-to-speech with animation (talking state)
    # ------------------------------------------------------------------
    def say_and_animate(self, text):
        """
        Switch to talking state, clean the text, and speak it. When speech finishes,
        revert to idle state.
        """
        if self.current_state == "shutdown":
            return
        if self.tts.speaking:
            return  # Already speaking, ignore further requests

        clean = clean_text(text)

        def speech_finished():
            if self.current_state == "talking":
                self.set_state("idle")

        self.set_state("talking")
        self.tts.say(clean, callback=speech_finished)

    # ------------------------------------------------------------------
    # Portal‑themed chat window (no welcome message)
    # ------------------------------------------------------------------
    def open_chat(self):
        """Open (or raise) the chat window."""
        if self.chat_window is not None and self.chat_window.winfo_exists():
            # If window exists but is minimized, show it
            if not self.chat_window.winfo_viewable():
                self.chat_window.deiconify()
            self.chat_window.lift()
            return

        # Create the chat window
        self.chat_window = tk.Toplevel(self.root)
        self.chat_window.title("")
        self.chat_window.overrideredirect(True)          # No default title bar
        self.chat_window.configure(bg="#0a0f1a")
        self.chat_window.geometry("500x600")
        self.chat_window.resizable(True, True)           # Allow resizing

        # Grid layout configuration: row 1 expands, column 0 expands
        self.chat_window.grid_rowconfigure(1, weight=1)
        self.chat_window.grid_columnconfigure(0, weight=1)

        # Custom title bar
        title_bar = tk.Frame(self.chat_window, bg="#1e1e2f", height=30)
        title_bar.grid(row=0, column=0, sticky="ew")
        title_bar.grid_columnconfigure(0, weight=1)

        title_label = tk.Label(title_bar, text="GLaDOS TERMINAL", bg="#1e1e2f", fg="#ffaa66",
                               font=("Portal", 14, "bold"))
        title_label.grid(row=0, column=0, padx=5, pady=5, sticky="w")

        # Buttons on the right side
        button_frame = tk.Frame(title_bar, bg="#1e1e2f")
        button_frame.grid(row=0, column=1, sticky="e", padx=5)

        # Minimize button (withdraw the window)
        min_btn = tk.Button(button_frame, text="─", command=self.minimize_chat, bg="#1e1e2f", fg="white",
                            bd=0, font=("Segoe UI", 10), width=3, relief=tk.FLAT)
        min_btn.pack(side=tk.RIGHT, padx=2)

        # Maximize/Restore button
        max_btn = tk.Button(button_frame, text="□", command=self.toggle_maximize_chat, bg="#1e1e2f", fg="white",
                            bd=0, font=("Segoe UI", 10), width=3, relief=tk.FLAT)
        max_btn.pack(side=tk.RIGHT, padx=2)

        # Close button
        close_btn = tk.Button(button_frame, text="✕", command=self.close_chat, bg="#1e1e2f", fg="white",
                              bd=0, font=("Segoe UI", 10), width=3, relief=tk.FLAT,
                              activebackground="#ff6b00")
        close_btn.pack(side=tk.RIGHT)

        # Make title bar draggable
        title_bar.bind("<Button-1>", self.start_chat_drag)
        title_bar.bind("<B1-Motion>", self.on_chat_drag)
        title_label.bind("<Button-1>", self.start_chat_drag)
        title_label.bind("<B1-Motion>", self.on_chat_drag)

        # Chat display area with scrollbar
        chat_frame = tk.Frame(self.chat_window, bg="#0a0f1a")
        chat_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        chat_frame.grid_rowconfigure(0, weight=1)
        chat_frame.grid_columnconfigure(0, weight=1)

        self.chat_display = tk.Text(chat_frame, wrap=tk.WORD, state='disabled',
                                    bg="#0f1420", fg="#00ffcc",
                                    insertbackground="white",
                                    font=("Portal", 10), bd=0, highlightthickness=0)
        self.chat_display.grid(row=0, column=0, sticky="nsew")

        # Custom scrollbar style
        scroll_style = {"bg": "#0a0f1a", "activebackground": "#ff6b00", "troughcolor": "#1e1e2f"}
        self.chat_scrollbar = tk.Scrollbar(chat_frame, command=self.chat_display.yview,
                                           **scroll_style)
        self.chat_scrollbar.grid(row=0, column=1, sticky="ns")
        self.chat_display.config(yscrollcommand=self.chat_scrollbar.set)
        self.chat_scrollbar.pack_forget()  # Initially hidden until needed

        self.chat_display.bind("<<Modified>>", self._update_scrollbar_visibility, add=True)

        # Input area
        input_frame = tk.Frame(self.chat_window, bg="#0a0f1a")
        input_frame.grid(row=2, column=0, sticky="ew", padx=5, pady=5)
        input_frame.grid_columnconfigure(0, weight=1)

        self.chat_entry = tk.Entry(input_frame, bg="#1e2435", fg="#00ffcc",
                                   font=("Portal", 10), insertbackground="white", bd=0)
        self.chat_entry.grid(row=0, column=0, sticky="ew", padx=(0,5))
        self.chat_entry.bind("<Return>", lambda e: self.send_chat_message())

        send_btn = tk.Button(input_frame, text="Send", command=self.send_chat_message,
                             bg="#ff6b00", fg="white", font=("Portal", 10, "bold"),
                             activebackground="#ff8533", bd=0)
        send_btn.grid(row=0, column=1, sticky="e")

        # Resize grip (bottom‑right corner of input row)
        input_frame.grid_columnconfigure(2, minsize=20)
        self.resize_grip = tk.Label(input_frame, text="◢", bg="#0a0f1a", fg="#666",
                                    font=("Segoe UI", 10), cursor="sizing")
        self.resize_grip.grid(row=0, column=2, sticky="e", padx=(0,2))
        self.resize_grip.bind("<Button-1>", self.start_resize)
        self.resize_grip.bind("<B1-Motion>", self.on_resize)

        # No welcome message – chat starts empty

        # Variables for dragging/resizing
        self.chat_drag_start_x = 0
        self.chat_drag_start_y = 0
        self.chat_window_maximized = False
        self.chat_window_geometry = None
        self.resize_start_x = 0
        self.resize_start_y = 0
        self.resize_start_width = 0
        self.resize_start_height = 0

    def _update_scrollbar_visibility(self, event=None):
        """Show/hide scrollbar based on whether content exceeds visible area."""
        self.chat_display.edit_modified(False)
        try:
            first = self.chat_display.index("@0,0")
            last = self.chat_display.index("@0,{}".format(self.chat_display.winfo_height()))
            if first == last:
                self.chat_scrollbar.pack_forget()
            else:
                self.chat_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        except:
            pass

    def minimize_chat(self):
        """Hide the chat window (withdraw)."""
        self.chat_window.withdraw()

    def toggle_maximize_chat(self):
        """Toggle between normal size and fullscreen."""
        if self.chat_window_maximized:
            self.chat_window.geometry(self.chat_window_geometry)
            self.chat_window_maximized = False
        else:
            self.chat_window_geometry = self.chat_window.geometry()
            screen_width = self.chat_window.winfo_screenwidth()
            screen_height = self.chat_window.winfo_screenheight()
            self.chat_window.geometry(f"{screen_width}x{screen_height}+0+0")
            self.chat_window_maximized = True

    def start_chat_drag(self, event):
        """Record the starting point for dragging the chat window."""
        self.chat_drag_start_x = event.x
        self.chat_drag_start_y = event.y

    def on_chat_drag(self, event):
        """Move the chat window."""
        x = self.chat_window.winfo_x() + event.x - self.chat_drag_start_x
        y = self.chat_window.winfo_y() + event.y - self.chat_drag_start_y
        self.chat_window.geometry(f"+{x}+{y}")

    def start_resize(self, event):
        """Record the starting point for resizing."""
        self.resize_start_x = event.x_root
        self.resize_start_y = event.y_root
        self.resize_start_width = self.chat_window.winfo_width()
        self.resize_start_height = self.chat_window.winfo_height()

    def on_resize(self, event):
        """Resize the chat window by dragging the grip."""
        dx = event.x_root - self.resize_start_x
        dy = event.y_root - self.resize_start_y
        new_width = max(300, self.resize_start_width + dx)
        new_height = max(200, self.resize_start_height + dy)
        self.chat_window.geometry(f"{new_width}x{new_height}")

    def close_chat(self):
        """Destroy the chat window."""
        if self.chat_window:
            self.chat_window.destroy()
            self.chat_window = None

    def send_chat_message(self):
        """Send the user's input to the AI and display the response."""
        user_input = self.chat_entry.get().strip()
        if not user_input:
            return
        self.chat_entry.delete(0, tk.END)
        self.add_chat_message("You", user_input)

        def on_response(response):
            self.add_chat_message("GLaDOS", response)
            self.say_and_animate(response)

        self.ai.respond(user_input, on_response)

    def add_chat_message(self, sender, message):
        """Insert a message into the chat display with appropriate formatting."""
        self.chat_display.config(state='normal')
        tag = "user" if sender == "You" else "glados"
        self.chat_display.insert(tk.END, f"{sender}: {message}\n", tag)
        self.chat_display.tag_config("user", foreground="#ffaa66")
        self.chat_display.tag_config("glados", foreground="#66ffcc")
        self.chat_display.see(tk.END)
        self.chat_display.config(state='disabled')

    # ------------------------------------------------------------------
    # Shutdown sequence
    # ------------------------------------------------------------------
    def exit_app(self):
        """
        Start the shutdown sequence: play the shutdown GIF (mirrored if needed),
        then slide out and destroy the window.
        """
        if self.current_state == "shutdown":
            return

        def on_shutdown_finished():
            self._slide_out_and_destroy()

        self._stop_current_animation()
        # Choose correct frames based on current orientation
        if self.mirrored:
            frames = self.shutdown_frames_mirrored
            durations = self.shutdown_durations_mirrored
        else:
            frames = self.shutdown_frames
            durations = self.shutdown_durations
        player = GIFPlayer(self.root, self.image_label,
                           frames, durations,
                           loop=False, on_finish=on_shutdown_finished)
        player.start()
        self.current_player = player
        self.current_state = "shutdown"

    def show_menu(self, event):
        """Display the right‑click context menu."""
        self.context_menu.post(event.x_root, event.y_root)

    def run(self):
        """Start the Tkinter main loop."""
        self.root.mainloop()

# ----------------------------------------------------------------------
if __name__ == "__main__":
    app = GLaDOSBuddy()
    app.run()
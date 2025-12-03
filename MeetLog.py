"""
MeetLog - 会議録音・議事録作成支援ツール
Google NotebookLM連携対応版
"""
import os
import time
import soundcard as sc
import soundfile as sf
import tkinter as tk
from tkinter import messagebox, filedialog
import customtkinter as ctk
import threading
import numpy as np
import traceback
import subprocess
import sys
import shutil
import warnings
import webbrowser
from PIL import Image
import glob
from types import SimpleNamespace
from datetime import datetime
from pydub import AudioSegment


warnings.filterwarnings("ignore", message="data discontinuity in recording", category=Warning)
warnings.filterwarnings("ignore", category=UserWarning, module='soundcard')

APP_NAME = "MeetLog"
APP_VERSION = "2.0.0"

# ===== 設定 =====
SETTINGS = SimpleNamespace()
SETTINGS.recording = SimpleNamespace()
SETTINGS.recording.sample_rate = 44100
SETTINGS.recording.buffer_size = SETTINGS.recording.sample_rate // 2
SETTINGS.recording.mic_delay_ms = -50
SETTINGS.recording.max_duration_seconds = 7200
SETTINGS.paths = SimpleNamespace()
SETTINGS.paths.recordings = "./recordings"

# ===== テーマ =====
THEME = SimpleNamespace()
THEME.colors = SimpleNamespace()
THEME.colors.primary = "#4285F4"
THEME.colors.secondary = "#34A853"
THEME.colors.warning = "#FBBC04"
THEME.colors.danger = "#EA4335"
THEME.colors.text = "#ffffff"
THEME.colors.text_muted = "#888888"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ===== 多言語 =====
LANG = SimpleNamespace()
LANG.current = "ja"
LANG.strings = {
    "ja": {
        "recording": "録音開始", "stop": "録音停止", "pause": "一時停止", "resume": "再開",
        "paused": "[一時停止中]", "mic_source": "マイク:", "system_source": "システム音声:",
        "mp3_convert": "MP3変換", "normalize": "正規化", "saving": "保存中...",
        "recording_complete": "録音完了", "error": "エラー", "info": "情報",
        "open_folder": "フォルダを開く", "recent_recordings": "最近の録音",
        "no_recordings": "録音ファイルがありません", "google_integration": "Google連携",
        "settings": "設定", "mic_delay": "マイク遅延:", "delay_help": "負:遅らせる / 正:早める",
    },
    "en": {
        "recording": "Record", "stop": "Stop", "pause": "Pause", "resume": "Resume",
        "paused": "[Paused]", "mic_source": "Mic:", "system_source": "System:",
        "mp3_convert": "MP3", "normalize": "Normalize", "saving": "Saving...",
        "recording_complete": "Complete", "error": "Error", "info": "Info",
        "open_folder": "Open Folder", "recent_recordings": "Recent",
        "no_recordings": "No recordings", "google_integration": "Google",
        "settings": "Settings", "mic_delay": "Mic Delay:", "delay_help": "Neg:delay / Pos:advance",
    }
}

def t(key):
    return LANG.strings.get(LANG.current, LANG.strings["ja"]).get(key, key)

# ===== グローバル変数 =====
recording = False
pause = False
recording_start_time = None
mic_buffer = None
system_buffer = None
input_source_id = None
system_source_id = None
is_mp3 = None
is_normalize = None
last_recording_path = None

def convert_seconds(seconds):
    h, m, s = int(seconds // 3600), int((seconds % 3600) // 60), int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def format_file_size(size_bytes):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} TB"

class RingBuffer:
    def __init__(self, duration_seconds, sample_rate, channels=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.max_samples = int(duration_seconds * sample_rate)
        self.buffer = np.zeros((self.max_samples, channels), dtype=np.float32)
        self.write_pos = 0
        self.total_written = 0
        self.lock = threading.Lock()
    
    def write(self, data):
        with self.lock:
            if len(data) == 0:
                return
            if len(data.shape) == 1:
                data = data.reshape(-1, 1)
            elif data.shape[1] != self.channels:
                data = np.column_stack([data[:, 0]] * self.channels) if data.shape[1] > 0 else data
            
            remaining = len(data)
            src_pos = 0
            while remaining > 0:
                space = self.max_samples - self.write_pos
                to_write = min(remaining, space)
                self.buffer[self.write_pos:self.write_pos + to_write] = data[src_pos:src_pos + to_write]
                self.write_pos = (self.write_pos + to_write) % self.max_samples
                self.total_written += to_write
                remaining -= to_write
                src_pos += to_write
    
    def get_all_data(self):
        with self.lock:
            if self.total_written < self.max_samples:
                return self.buffer[:self.write_pos].copy()
            return np.vstack((self.buffer[self.write_pos:], self.buffer[:self.write_pos])).copy()

def find_ffmpeg():
    exe = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    for path in [os.path.dirname(sys.executable), os.path.dirname(__file__), "."]:
        for sub in ["", "ffmpeg", "bin"]:
            p = os.path.join(path, sub, exe)
            if os.path.isfile(p):
                return p
    return shutil.which(exe)

def record_from_mic(frame):
    global mic_buffer, input_source_id, pause, recording, recording_start_time
    try:
        with sc.get_microphone(id=input_source_id, include_loopback=False).recorder(
            samplerate=SETTINGS.recording.sample_rate, blocksize=SETTINGS.recording.buffer_size
        ) as mic:
            while recording:
                data = mic.record(numframes=SETTINGS.recording.buffer_size)
                if not pause:
                    mic_buffer.write(data)
                    if recording_start_time:
                        elapsed = time.time() - recording_start_time
                        icon = "● " if int(elapsed * 2) % 2 == 0 else "○ "
                        try:
                            frame.label_time.configure(text=icon + convert_seconds(elapsed), text_color=THEME.colors.danger)
                        except: pass
                else:
                    try:
                        frame.label_time.configure(text=t("paused"), text_color=THEME.colors.warning)
                    except: pass
    except Exception as e:
        print(f"Mic error: {e}")
    try:
        frame.label_time.configure(text="00:00:00", text_color=THEME.colors.text)
    except: pass

def record_system_audio(frame):
    global system_buffer, system_source_id, pause, recording
    try:
        with sc.get_microphone(id=system_source_id, include_loopback=True).recorder(
            samplerate=SETTINGS.recording.sample_rate, blocksize=SETTINGS.recording.buffer_size
        ) as rec:
            while recording:
                data = rec.record(numframes=SETTINGS.recording.buffer_size)
                if not pause:
                    system_buffer.write(data)
    except Exception as e:
        print(f"System audio error: {e}")

def mix_audio(mic_audio, system_audio):
    if mic_audio is None and system_audio is None:
        return np.array([])
    if mic_audio is None:
        return system_audio
    if system_audio is None:
        return mic_audio
    
    if len(mic_audio.shape) == 1:
        mic_audio = np.column_stack((mic_audio, mic_audio))
    elif mic_audio.shape[1] == 1:
        mic_audio = np.column_stack((mic_audio.flatten(), mic_audio.flatten()))
    
    delay = int(SETTINGS.recording.sample_rate * abs(SETTINGS.recording.mic_delay_ms) / 1000)
    if SETTINGS.recording.mic_delay_ms < 0:
        mic_audio = np.vstack((np.zeros((delay, 2)), mic_audio))
    elif SETTINGS.recording.mic_delay_ms > 0 and len(mic_audio) > delay:
        mic_audio = mic_audio[delay:]
    
    diff = len(system_audio) - len(mic_audio)
    if diff > 0:
        mic_audio = np.vstack((mic_audio, np.zeros((diff, 2))))
    elif diff < 0:
        system_audio = np.vstack((system_audio, np.zeros((-diff, 2))))
    
    mixed = system_audio * 1.2 + mic_audio
    peak = np.max(np.abs(mixed))
    if peak > 1.0:
        mixed = mixed / peak * 0.95
    return mixed

def get_recent_recordings(limit=8):
    recordings = []
    path = SETTINGS.paths.recordings
    if not os.path.exists(path):
        return recordings
    for folder in sorted(os.listdir(path), reverse=True)[:limit]:
        folder_path = os.path.join(path, folder)
        if os.path.isdir(folder_path):
            for ext in ['*.mp3', '*.wav']:
                for file in glob.glob(os.path.join(folder_path, ext)):
                    try:
                        stat = os.stat(file)
                        recordings.append({'path': file, 'name': os.path.basename(file),
                            'size': stat.st_size, 'date': datetime.fromtimestamp(stat.st_mtime)})
                    except: pass
    return recordings[:limit]

# ===== UI =====
class MeetLogApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"🎙️ {APP_NAME} v{APP_VERSION}")
        self.geometry("800x650")
        self.minsize(700, 550)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=0, padx=15, pady=15, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)
        
        # Header
        header = ctk.CTkFrame(main, fg_color="transparent")
        header.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=f"🎙️ {APP_NAME}", font=ctk.CTkFont(size=28, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="⚙️", width=40, command=self.show_settings).grid(row=0, column=1, sticky="e")
        
        # Source
        self.source_frame = SourceFrame(main)
        self.source_frame.grid(row=1, column=0, pady=5, sticky="ew")
        
        # Recording
        self.recording_frame = RecordingFrame(main)
        self.recording_frame.grid(row=2, column=0, pady=5, sticky="ew")
        
        # Bottom
        bottom = ctk.CTkFrame(main, fg_color="transparent")
        bottom.grid(row=3, column=0, pady=5, sticky="nsew")
        bottom.grid_columnconfigure((0, 1), weight=1)
        bottom.grid_rowconfigure(0, weight=1)
        
        self.google_frame = GoogleFrame(bottom)
        self.google_frame.grid(row=0, column=0, padx=(0, 5), sticky="nsew")
        
        self.history_frame = HistoryFrame(bottom)
        self.history_frame.grid(row=0, column=1, padx=(5, 0), sticky="nsew")
    
    def show_settings(self):
        SettingsWindow(self)

class SourceFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.grid_columnconfigure((1, 3), weight=1)
        
        ctk.CTkLabel(self, text=t("mic_source")).grid(row=0, column=0, padx=10, pady=8, sticky="w")
        self.mics = [m.name for m in sc.all_microphones(include_loopback=False)]
        self.mic_var = ctk.StringVar(value=self.mics[0] if self.mics else "")
        ctk.CTkOptionMenu(self, values=self.mics, variable=self.mic_var, command=self.on_mic, width=250).grid(row=0, column=1, padx=5, pady=8, sticky="ew")
        
        ctk.CTkLabel(self, text=t("system_source")).grid(row=0, column=2, padx=10, pady=8, sticky="w")
        self.systems = [m.name for m in sc.all_microphones(include_loopback=True)]
        self.system_var = ctk.StringVar(value=self.systems[0] if self.systems else "")
        ctk.CTkOptionMenu(self, values=self.systems, variable=self.system_var, command=self.on_system, width=250).grid(row=0, column=3, padx=5, pady=8, sticky="ew")
        
        self.on_mic(self.mic_var.get())
        self.on_system(self.system_var.get())
    
    def on_mic(self, name):
        global input_source_id
        for m in sc.all_microphones(include_loopback=False):
            if m.name == name:
                input_source_id = m.id
                break
    
    def on_system(self, name):
        global system_source_id
        for m in sc.all_microphones(include_loopback=True):
            if m.name == name:
                system_source_id = m.id
                break

class RecordingFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.grid_columnconfigure(0, weight=1)
        
        self.label_time = ctk.CTkLabel(self, text="00:00:00", font=ctk.CTkFont(size=48, weight="bold"))
        self.label_time.grid(row=0, column=0, pady=15)
        
        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=1, column=0, pady=10)
        
        self.rec_btn = ctk.CTkButton(btn, text=f"⏺️ {t('recording')}", command=self.toggle_recording,
            width=160, height=50, font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=THEME.colors.danger, hover_color="#c62828")
        self.rec_btn.pack(side="left", padx=5)
        
        self.pause_btn = ctk.CTkButton(btn, text=f"⏸️ {t('pause')}", command=self.toggle_pause,
            width=120, height=50, fg_color=THEME.colors.warning, hover_color="#f9a825")
        self.pause_btn.pack(side="left", padx=5)
        
        opt = ctk.CTkFrame(self, fg_color="transparent")
        opt.grid(row=2, column=0, pady=10)
        
        global is_mp3, is_normalize
        is_mp3 = ctk.BooleanVar(value=True)
        is_normalize = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(opt, text=t("mp3_convert"), variable=is_mp3).pack(side="left", padx=15)
        ctk.CTkCheckBox(opt, text=t("normalize"), variable=is_normalize).pack(side="left", padx=15)
    
    def toggle_recording(self):
        global recording, mic_buffer, system_buffer, recording_start_time, last_recording_path
        
        if not recording:
            if input_source_id is None or system_source_id is None:
                messagebox.showerror(t("error"), "入力ソースを選択してください")
                return
            
            recording = True
            recording_start_time = time.time()
            mic_buffer = RingBuffer(SETTINGS.recording.max_duration_seconds, SETTINGS.recording.sample_rate, 1)
            system_buffer = RingBuffer(SETTINGS.recording.max_duration_seconds, SETTINGS.recording.sample_rate, 2)
            
            self.rec_btn.configure(text=f"⏹️ {t('stop')}", fg_color=THEME.colors.secondary)
            
            backup_dir = os.path.join(SETTINGS.paths.recordings, datetime.now().strftime('%Y%m%d_%H%M%S'))
            os.makedirs(backup_dir, exist_ok=True)
            self.backup_dir = backup_dir
            
            threading.Thread(target=record_from_mic, args=(self,), daemon=True).start()
            threading.Thread(target=record_system_audio, args=(self,), daemon=True).start()
        else:
            recording = False
            self.rec_btn.configure(state="disabled")
            self.label_time.configure(text=t("saving"), text_color=THEME.colors.warning)
            
            def finalize():
                try:
                    mic_data = mic_buffer.get_all_data()
                    sys_data = system_buffer.get_all_data()
                    mixed = mix_audio(mic_data, sys_data)
                    
                    if len(mixed) > 0:
                        wav_path = os.path.join(self.backup_dir, "output.wav")
                        if is_normalize.get():
                            peak = float(np.max(np.abs(mixed)))
                            if peak > 0:
                                mixed = (mixed / peak) * 0.95
                        sf.write(wav_path, mixed, SETTINGS.recording.sample_rate, subtype='PCM_16')
                        
                        final = wav_path
                        if is_mp3.get():
                            mp3_path = os.path.join(self.backup_dir, "output.mp3")
                            try:
                                ffmpeg = find_ffmpeg()
                                subprocess.run([ffmpeg or 'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                                    '-i', wav_path, '-codec:a', 'libmp3lame', '-b:a', '192k', mp3_path], capture_output=True)
                                if os.path.exists(mp3_path):
                                    os.remove(wav_path)
                                    final = mp3_path
                            except:
                                audio = AudioSegment.from_wav(wav_path)
                                audio.export(mp3_path, format='mp3', bitrate='192k')
                                os.remove(wav_path)
                                final = mp3_path
                        
                        global last_recording_path
                        last_recording_path = final
                        self.after(0, lambda: messagebox.showinfo(t("recording_complete"), f"保存: {os.path.abspath(final)}"))
                        
                        try:
                            self.master.master.history_frame.refresh()
                            self.master.master.google_frame.update_last()
                        except: pass
                except Exception as e:
                    traceback.print_exc()
                    self.after(0, lambda: messagebox.showerror(t("error"), str(e)))
                finally:
                    self.after(0, lambda: self.rec_btn.configure(text=f"⏺️ {t('recording')}", state="normal", fg_color=THEME.colors.danger))
                    self.after(0, lambda: self.label_time.configure(text="00:00:00", text_color=THEME.colors.text))
            
            threading.Thread(target=finalize, daemon=True).start()
    
    def toggle_pause(self):
        global pause, recording
        if not recording:
            return
        pause = not pause
        self.pause_btn.configure(text=f"▶️ {t('resume')}" if pause else f"⏸️ {t('pause')}")

class GoogleFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.grid_columnconfigure(0, weight=1)
        
        ctk.CTkLabel(self, text=f"🔗 {t('google_integration')}", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, padx=15, pady=(15, 5), sticky="w")
        ctk.CTkLabel(self, text="録音→NotebookLMで議事録作成", font=ctk.CTkFont(size=12), text_color=THEME.colors.text_muted).grid(row=1, column=0, padx=15, pady=5, sticky="w")
        
        self.last_label = ctk.CTkLabel(self, text="", font=ctk.CTkFont(size=11), text_color=THEME.colors.primary)
        self.last_label.grid(row=2, column=0, padx=15, pady=5, sticky="w")
        
        btn = ctk.CTkFrame(self, fg_color="transparent")
        btn.grid(row=3, column=0, padx=15, pady=10, sticky="ew")
        btn.grid_columnconfigure((0, 1), weight=1)
        
        ctk.CTkButton(btn, text="📝 NotebookLMで議事録作成", command=self.open_notebooklm, height=45,
            font=ctk.CTkFont(size=13, weight="bold"), fg_color=THEME.colors.primary).grid(row=0, column=0, columnspan=2, pady=5, sticky="ew")
        ctk.CTkButton(btn, text="☁️ Google Drive", command=lambda: webbrowser.open("https://drive.google.com"), height=38,
            fg_color=THEME.colors.secondary).grid(row=1, column=0, pady=5, padx=(0, 3), sticky="ew")
        ctk.CTkButton(btn, text=f"📁 {t('open_folder')}", command=self.open_folder, height=38, fg_color="#6c757d").grid(row=1, column=1, pady=5, padx=(3, 0), sticky="ew")
        
        hint = ctk.CTkFrame(self, fg_color="#2d3748")
        hint.grid(row=4, column=0, padx=15, pady=(5, 15), sticky="ew")
        ctk.CTkLabel(hint, text="💡 NotebookLMにMP3をアップロード\n   →AIが議事録を自動作成", font=ctk.CTkFont(size=11), text_color="#a0aec0", justify="left").pack(padx=10, pady=8)
        
        self.update_last()
    
    def update_last(self):
        recs = get_recent_recordings(1)
        if recs:
            r = recs[0]
            self.last_label.configure(text=f"📎 最新: {r['name']} ({format_file_size(r['size'])})")
    
    def open_notebooklm(self):
        webbrowser.open("https://notebooklm.google.com/")
        messagebox.showinfo("NotebookLM", "1. 新しいノートブック作成\n2. ソース追加→ファイルアップロード\n3. 録音ファイルを選択\n4. AIが議事録を生成")
    
    def open_folder(self):
        path = os.path.abspath(SETTINGS.paths.recordings)
        os.makedirs(path, exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', path])
        else:
            subprocess.run(['xdg-open', path])

class HistoryFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=f"📂 {t('recent_recordings')}", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="🔄", width=30, height=25, command=self.refresh).grid(row=0, column=1, sticky="e")
        
        self.list_frame = ctk.CTkScrollableFrame(self)
        self.list_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        self.list_frame.grid_columnconfigure(0, weight=1)
        self.refresh()
    
    def refresh(self):
        for w in self.list_frame.winfo_children():
            w.destroy()
        recs = get_recent_recordings(8)
        if not recs:
            ctk.CTkLabel(self.list_frame, text=t("no_recordings"), text_color=THEME.colors.text_muted).pack(pady=20)
            return
        for r in recs:
            item = ctk.CTkFrame(self.list_frame)
            item.pack(fill="x", pady=2)
            item.grid_columnconfigure(1, weight=1)
            ctk.CTkLabel(item, text="🎵", font=ctk.CTkFont(size=16)).grid(row=0, column=0, rowspan=2, padx=8, pady=5)
            ctk.CTkLabel(item, text=r['name'], font=ctk.CTkFont(size=12, weight="bold"), anchor="w").grid(row=0, column=1, sticky="w", padx=5)
            ctk.CTkLabel(item, text=f"{r['date'].strftime('%m/%d %H:%M')} • {format_file_size(r['size'])}", font=ctk.CTkFont(size=10), text_color=THEME.colors.text_muted).grid(row=1, column=1, sticky="w", padx=5)
            ctk.CTkButton(item, text="▶️", width=30, height=30, command=lambda p=r['path']: os.startfile(p) if sys.platform=='win32' else subprocess.run(['open', p])).grid(row=0, column=2, rowspan=2, padx=5, pady=5)

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title(t("settings"))
        self.geometry("500x300")
        self.transient(parent)
        self.grab_set()
        self.grid_columnconfigure(0, weight=1)
        
        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, padx=20, pady=20, sticky="ew")
        frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(frame, text="録音設定", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, columnspan=2, pady=10, sticky="w", padx=10)
        
        ctk.CTkLabel(frame, text=t("mic_delay")).grid(row=1, column=0, padx=10, pady=10, sticky="w")
        delay_frame = ctk.CTkFrame(frame, fg_color="transparent")
        delay_frame.grid(row=1, column=1, padx=10, pady=10, sticky="ew")
        delay_frame.grid_columnconfigure(0, weight=1)
        
        self.delay_var = ctk.IntVar(value=SETTINGS.recording.mic_delay_ms)
        ctk.CTkSlider(delay_frame, from_=-200, to=200, number_of_steps=40, variable=self.delay_var, command=self.on_delay).grid(row=0, column=0, sticky="ew")
        self.delay_label = ctk.CTkLabel(delay_frame, text=f"{SETTINGS.recording.mic_delay_ms}ms", width=60)
        self.delay_label.grid(row=0, column=1, padx=(10, 0))
        
        ctk.CTkLabel(frame, text=t("delay_help"), text_color=THEME.colors.text_muted, font=ctk.CTkFont(size=10)).grid(row=2, column=0, columnspan=2, padx=10, sticky="w")
        
        ctk.CTkLabel(frame, text="最大録音時間:").grid(row=3, column=0, padx=10, pady=15, sticky="w")
        dur_frame = ctk.CTkFrame(frame, fg_color="transparent")
        dur_frame.grid(row=3, column=1, padx=10, pady=15, sticky="w")
        self.dur_var = ctk.StringVar(value=str(SETTINGS.recording.max_duration_seconds // 3600))
        ctk.CTkOptionMenu(dur_frame, values=["1", "2", "3", "4"], variable=self.dur_var, command=self.on_dur, width=80).pack(side="left")
        ctk.CTkLabel(dur_frame, text="時間").pack(side="left", padx=10)
        
        ctk.CTkButton(self, text="閉じる", command=self.destroy, width=120).grid(row=1, column=0, pady=20)
    
    def on_delay(self, v):
        SETTINGS.recording.mic_delay_ms = int(v)
        self.delay_label.configure(text=f"{int(v)}ms")
    
    def on_dur(self, v):
        SETTINGS.recording.max_duration_seconds = int(v) * 3600

def main():
    os.makedirs(SETTINGS.paths.recordings, exist_ok=True)
    app = MeetLogApp()
    app.mainloop()

if __name__ == "__main__":
    main()

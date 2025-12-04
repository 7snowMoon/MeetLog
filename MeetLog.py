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
import json
import queue
import base64

# Gemini / 音声認識
try:
    import google.generativeai as genai
    GEMINI_AVAILABLE = True
except ImportError:
    GEMINI_AVAILABLE = False

try:
    import speech_recognition as sr
    SPEECH_RECOGNITION_AVAILABLE = True
except ImportError:
    SPEECH_RECOGNITION_AVAILABLE = False

# WASAPI ループバック用
try:
    import pyaudiowpatch as pyaudio
    WASAPI_AVAILABLE = True
except ImportError:
    try:
        import pyaudio
        WASAPI_AVAILABLE = False
    except ImportError:
        pyaudio = None
        WASAPI_AVAILABLE = False


warnings.filterwarnings("ignore", message="data discontinuity in recording", category=Warning)
warnings.filterwarnings("ignore", category=UserWarning, module='soundcard')

APP_NAME = "MeetLog"
APP_VERSION = "3.0.0"  # Gemini統合版

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
last_recording_path = None
wasapi_device_index = None  # WASAPIループバック用

# Gemini関連
gemini_api_key = ""
gemini_model = None
gemini_enabled = False
transcript_queue = queue.Queue()
current_transcript = []

# ===== 設定ファイル読み込み =====
def load_settings():
    global gemini_api_key, gemini_enabled
    settings_path = os.path.join(os.path.dirname(__file__), "settings.json")
    if os.path.exists(settings_path):
        try:
            with open(settings_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if 'gemini' in data:
                    gemini_api_key = data['gemini'].get('api_key', '')
                    gemini_enabled = data['gemini'].get('enabled', False)
        except: pass

def save_settings():
    settings_path = os.path.join(os.path.dirname(__file__), "settings.json")
    data = {
        "gui": {"lang": LANG.current},
        "recording": {
            "sample_rate": SETTINGS.recording.sample_rate,
            "backup_interval": 60,
            "silence_threshold": 0.05
        },
        "gemini": {
            "api_key": gemini_api_key,
            "model": "gemini-1.5-flash",
            "enabled": gemini_enabled
        }
    }
    with open(settings_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)

# ===== Gemini Assistant =====
class GeminiAssistant:
    def __init__(self):
        self.model = None
        self.chat = None
        self.is_configured = False
        
    def configure(self, api_key):
        global gemini_api_key
        if not GEMINI_AVAILABLE:
            print("Gemini library not available")
            return False
        if not api_key:
            print("API key is empty")
            return False
        try:
            genai.configure(api_key=api_key)
            # 利用可能なモデルをリストアップ
            available_models = []
            for m in genai.list_models():
                if 'generateContent' in m.supported_generation_methods:
                    available_models.append(m.name)
            print(f"Available models: {available_models[:5]}...")
            
            # 優先順位でモデルを選択
            preferred = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-pro']
            selected_model = None
            for pref in preferred:
                for avail in available_models:
                    if pref in avail:
                        selected_model = avail.replace('models/', '')
                        break
                if selected_model:
                    break
            
            if not selected_model and available_models:
                selected_model = available_models[0].replace('models/', '')
            
            print(f"Using model: {selected_model}")
            self.model = genai.GenerativeModel(selected_model)
            
            # テストメッセージを送信して接続確認
            test_response = self.model.generate_content("Hello")
            print(f"Test response: {test_response.text[:50] if test_response.text else 'empty'}")
            self.chat = self.model.start_chat(history=[])
            self.is_configured = True
            gemini_api_key = api_key
            save_settings()
            return True
        except Exception as e:
            print(f"Gemini config error: {e}")
            traceback.print_exc()
            return False
    
    def generate_minutes(self, transcript_text):
        """議事録を生成"""
        if not self.is_configured:
            return "Gemini APIが設定されていません"
        try:
            prompt = f"""以下の会議の文字起こしから、構造化された議事録を作成してください。

【文字起こし】
{transcript_text}

【出力フォーマット】
## 議事録

### 📅 日時
{datetime.now().strftime('%Y年%m月%d日 %H:%M')}

### 📋 議題・話題

### 💡 決定事項

### 📝 議論内容

### ✅ アクションアイテム（担当者・期限）

### 📌 次回への申し送り
"""
            response = self.chat.send_message(prompt)
            return response.text
        except Exception as e:
            return f"議事録生成エラー: {e}"
    
    def suggest_questions(self, transcript_text):
        """疑問点・確認事項を提案"""
        if not self.is_configured:
            return "Gemini APIが設定されていません"
        try:
            prompt = f"""以下の会議内容から、参加者が確認すべき疑問点や懸念事項を抽出してください。
会議の進行をサポートする質問を5つ程度提案してください。

【会議内容】
{transcript_text}

【出力フォーマット】
## 🤔 確認すべき疑問点・懸念事項

1. **質問/懸念事項**
   - 理由: なぜこれを確認すべきか

箇条書きで簡潔に出力してください。"""
            response = self.chat.send_message(prompt)
            return response.text
        except Exception as e:
            return f"疑問点生成エラー: {e}"
    
    def summarize_realtime(self, transcript_text):
        """リアルタイム要約"""
        if not self.is_configured or not transcript_text.strip():
            return ""
        try:
            prompt = f"""以下の会議内容を3行以内で簡潔に要約してください。箇条書きで出力してください。

{transcript_text}"""
            response = self.model.generate_content(prompt)
            return response.text
        except Exception as e:
            return f"要約エラー: {e}"

gemini_assistant = GeminiAssistant()

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

def record_system_audio_wasapi(frame):
    """WASAPIループバックでシステム音声を録音（音が消えない）"""
    global system_buffer, pause, recording, wasapi_device_index
    
    if pyaudio is None or not WASAPI_AVAILABLE:
        print("WASAPI not available, falling back to soundcard")
        record_system_audio_soundcard(frame)
        return
    
    try:
        p = pyaudio.PyAudio()
        
        # WASAPIループバックデバイスを探す
        wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
        
        # ループバックデバイスを検索
        loopback_device = None
        for i in range(p.get_device_count()):
            dev = p.get_device_info_by_index(i)
            if dev.get("isLoopbackDevice", False):
                # 指定デバイスまたはデフォルトスピーカーのループバック
                if wasapi_device_index is None or dev["name"].startswith(default_speakers["name"].split(" (")[0]):
                    loopback_device = dev
                    break
        
        if loopback_device is None:
            print("No loopback device found, using default")
            loopback_device = default_speakers
        
        print(f"Using WASAPI loopback: {loopback_device['name']}")
        
        channels = int(loopback_device["maxInputChannels"])
        rate = int(loopback_device["defaultSampleRate"])
        
        stream = p.open(
            format=pyaudio.paFloat32,
            channels=channels,
            rate=rate,
            input=True,
            input_device_index=loopback_device["index"],
            frames_per_buffer=SETTINGS.recording.buffer_size
        )
        
        while recording:
            try:
                data = stream.read(SETTINGS.recording.buffer_size, exception_on_overflow=False)
                if not pause:
                    audio_data = np.frombuffer(data, dtype=np.float32)
                    # ステレオに変換
                    if channels == 1:
                        audio_data = np.column_stack((audio_data, audio_data))
                    else:
                        audio_data = audio_data.reshape(-1, channels)[:, :2]
                    system_buffer.write(audio_data)
            except Exception as e:
                print(f"Stream read error: {e}")
        
        stream.stop_stream()
        stream.close()
        p.terminate()
        
    except Exception as e:
        print(f"WASAPI error: {e}, falling back to soundcard")
        traceback.print_exc()
        record_system_audio_soundcard(frame)

def record_system_audio_soundcard(frame):
    """soundcardでシステム音声を録音（フォールバック）"""
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

def record_system_audio(frame):
    """システム音声を録音"""
    if WASAPI_AVAILABLE:
        record_system_audio_wasapi(frame)
    else:
        record_system_audio_soundcard(frame)

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
        load_settings()  # 設定読み込み
        
        self.title(f"🎙️ {APP_NAME} v{APP_VERSION}")
        self.geometry("1400x800")
        self.minsize(1200, 700)
        self.grid_columnconfigure(0, weight=1)
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # 左パネル（録音コントロール）
        left_panel = ctk.CTkFrame(self, fg_color="transparent")
        left_panel.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        left_panel.grid_columnconfigure(0, weight=1)
        left_panel.grid_rowconfigure(3, weight=1)
        
        # Header
        header = ctk.CTkFrame(left_panel, fg_color="transparent")
        header.grid(row=0, column=0, pady=(0, 10), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=f"🎙️ {APP_NAME}", font=ctk.CTkFont(size=28, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="⚙️", width=40, command=self.show_settings).grid(row=0, column=1, sticky="e")
        
        # Source
        self.source_frame = SourceFrame(left_panel)
        self.source_frame.grid(row=1, column=0, pady=5, sticky="ew")
        
        # Recording
        self.recording_frame = RecordingFrame(left_panel, self)
        self.recording_frame.grid(row=2, column=0, pady=5, sticky="ew")
        
        # 最近の録音
        self.history_frame = HistoryFrame(left_panel)
        self.history_frame.grid(row=3, column=0, pady=5, sticky="nsew")
        
        # 右パネル（会議補助）
        self.assistant_panel = AssistantPanel(self)
        self.assistant_panel.grid(row=0, column=1, padx=10, pady=10, sticky="nsew")
        
        # Gemini自動設定
        if gemini_api_key:
            gemini_assistant.configure(gemini_api_key)
    
    def show_settings(self):
        SettingsWindow(self)
    
    def update_transcript(self, text):
        """文字起こしを更新"""
        self.assistant_panel.add_transcript(text)

# ===== 会議補助パネル =====
class AssistantPanel(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.grid_rowconfigure(3, weight=1)
        
        # ヘッダー
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=15, pady=10, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text="🤖 AI会議アシスタント", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, sticky="w")
        
        # Gemini状態
        self.status_label = ctk.CTkLabel(header, text="⚪ 未設定", font=ctk.CTkFont(size=12))
        self.status_label.grid(row=0, column=1, sticky="e")
        self.update_status()
        
        # 文字起こしエリア
        transcript_frame = ctk.CTkFrame(self)
        transcript_frame.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        transcript_frame.grid_columnconfigure(0, weight=1)
        transcript_frame.grid_rowconfigure(1, weight=1)
        
        trans_header = ctk.CTkFrame(transcript_frame, fg_color="transparent")
        trans_header.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        trans_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(trans_header, text="📝 リアルタイム文字起こし", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(trans_header, text="🗑️", width=30, height=25, command=self.clear_transcript).grid(row=0, column=1, padx=2)
        
        self.transcript_text = ctk.CTkTextbox(transcript_frame, height=200, font=ctk.CTkFont(size=12))
        self.transcript_text.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
        
        # ボタンエリア
        btn_frame = ctk.CTkFrame(self, fg_color="transparent")
        btn_frame.grid(row=2, column=0, padx=10, pady=5, sticky="ew")
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)
        
        ctk.CTkButton(btn_frame, text="📋 議事録生成", command=self.generate_minutes,
            fg_color=THEME.colors.primary, height=40).grid(row=0, column=0, padx=5, sticky="ew")
        ctk.CTkButton(btn_frame, text="🤔 疑問点を提案", command=self.suggest_questions,
            fg_color=THEME.colors.secondary, height=40).grid(row=0, column=1, padx=5, sticky="ew")
        ctk.CTkButton(btn_frame, text="📄 要約", command=self.summarize,
            fg_color=THEME.colors.warning, height=40).grid(row=0, column=2, padx=5, sticky="ew")
        
        # AI出力エリア
        output_frame = ctk.CTkFrame(self)
        output_frame.grid(row=3, column=0, padx=10, pady=5, sticky="nsew")
        output_frame.grid_columnconfigure(0, weight=1)
        output_frame.grid_rowconfigure(1, weight=1)
        
        out_header = ctk.CTkFrame(output_frame, fg_color="transparent")
        out_header.grid(row=0, column=0, padx=10, pady=5, sticky="ew")
        out_header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(out_header, text="💡 AIアシスタント出力", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(out_header, text="📋", width=30, height=25, command=self.copy_output).grid(row=0, column=1, padx=2)
        ctk.CTkButton(out_header, text="💾", width=30, height=25, command=self.save_output).grid(row=0, column=2, padx=2)
        
        self.output_text = ctk.CTkTextbox(output_frame, height=250, font=ctk.CTkFont(size=12))
        self.output_text.grid(row=1, column=0, padx=10, pady=5, sticky="nsew")
    
    def update_status(self):
        if gemini_assistant.is_configured:
            self.status_label.configure(text="🟢 Gemini接続中", text_color=THEME.colors.secondary)
        else:
            self.status_label.configure(text="⚪ 未設定", text_color=THEME.colors.text_muted)
    
    def add_transcript(self, text):
        """文字起こしを追加"""
        if text.strip():
            timestamp = datetime.now().strftime('%H:%M:%S')
            self.transcript_text.insert("end", f"[{timestamp}] {text}\n")
            self.transcript_text.see("end")
            current_transcript.append(f"[{timestamp}] {text}")
    
    def get_transcript(self):
        return self.transcript_text.get("1.0", "end-1c")
    
    def clear_transcript(self):
        self.transcript_text.delete("1.0", "end")
        current_transcript.clear()
    
    def generate_minutes(self):
        """議事録生成"""
        transcript = self.get_transcript()
        if not transcript.strip():
            messagebox.showwarning("警告", "文字起こしがありません")
            return
        if not gemini_assistant.is_configured:
            messagebox.showerror("エラー", "Gemini APIを設定してください")
            return
        
        self.output_text.delete("1.0", "end")
        self.output_text.insert("end", "⏳ 議事録を生成中...")
        
        def generate():
            result = gemini_assistant.generate_minutes(transcript)
            self.after(0, lambda: self._show_result(result))
        
        threading.Thread(target=generate, daemon=True).start()
    
    def suggest_questions(self):
        """疑問点を提案"""
        transcript = self.get_transcript()
        if not transcript.strip():
            messagebox.showwarning("警告", "文字起こしがありません")
            return
        if not gemini_assistant.is_configured:
            messagebox.showerror("エラー", "Gemini APIを設定してください")
            return
        
        self.output_text.delete("1.0", "end")
        self.output_text.insert("end", "⏳ 疑問点を分析中...")
        
        def suggest():
            result = gemini_assistant.suggest_questions(transcript)
            self.after(0, lambda: self._show_result(result))
        
        threading.Thread(target=suggest, daemon=True).start()
    
    def summarize(self):
        """要約"""
        transcript = self.get_transcript()
        if not transcript.strip():
            messagebox.showwarning("警告", "文字起こしがありません")
            return
        if not gemini_assistant.is_configured:
            messagebox.showerror("エラー", "Gemini APIを設定してください")
            return
        
        self.output_text.delete("1.0", "end")
        self.output_text.insert("end", "⏳ 要約を生成中...")
        
        def do_summarize():
            result = gemini_assistant.summarize_realtime(transcript)
            self.after(0, lambda: self._show_result(result))
        
        threading.Thread(target=do_summarize, daemon=True).start()
    
    def _show_result(self, result):
        self.output_text.delete("1.0", "end")
        self.output_text.insert("end", result)
    
    def copy_output(self):
        """出力をクリップボードにコピー"""
        text = self.output_text.get("1.0", "end-1c")
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)
            messagebox.showinfo("コピー", "クリップボードにコピーしました")
    
    def save_output(self):
        """出力をファイルに保存"""
        text = self.output_text.get("1.0", "end-1c")
        if not text.strip():
            return
        
        file_path = filedialog.asksaveasfilename(
            defaultextension=".md",
            filetypes=[("Markdown", "*.md"), ("Text", "*.txt")],
            initialfile=f"minutes_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        )
        if file_path:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(text)
            messagebox.showinfo("保存完了", f"保存しました: {file_path}")

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
    def __init__(self, parent, app_ref=None):
        super().__init__(parent)
        self.app_ref = app_ref
        self.speech_thread = None
        self.speech_running = False
        self.system_speech_thread = None
        self.system_speech_running = False
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
        
        # 音声認識トグル
        self.speech_var = ctk.BooleanVar(value=False)
        self.speech_btn = ctk.CTkCheckBox(btn, text="🎤 文字起こし", variable=self.speech_var,
            font=ctk.CTkFont(size=12))
        self.speech_btn.pack(side="left", padx=15)
        
        # 音量調整スライダー
        global volume_gain
        volume_gain = ctk.DoubleVar(value=1.5)
        vol_frame = ctk.CTkFrame(self, fg_color="transparent")
        vol_frame.grid(row=2, column=0, pady=10)
        ctk.CTkLabel(vol_frame, text="音量:").pack(side="left", padx=5)
        self.vol_label = ctk.CTkLabel(vol_frame, text="150%", width=50)
        self.vol_label.pack(side="right", padx=5)
        vol_slider = ctk.CTkSlider(vol_frame, from_=0.5, to=3.0, variable=volume_gain, width=200,
            command=lambda v: self.vol_label.configure(text=f"{int(v*100)}%"))
        vol_slider.pack(side="left", padx=5)
    
    def start_speech_recognition(self):
        """リアルタイム音声認識を開始"""
        if not SPEECH_RECOGNITION_AVAILABLE:
            print("SpeechRecognition not available")
            return
        
        print("Starting speech recognition...")
        self.speech_running = True
        recognizer = sr.Recognizer()
        recognizer.energy_threshold = 150  # 感度を上げる
        recognizer.dynamic_energy_threshold = False  # 固定閾値
        recognizer.pause_threshold = 0.5  # 短い沈黙で区切る
        
        def recognize_loop():
            try:
                # 利用可能なマイクを表示
                mic_list = sr.Microphone.list_microphone_names()
                print(f"Available mics for speech recognition: {mic_list[:5]}...")
                
                # 録音用に選択されたマイクを探す
                mic_index = None
                for i, name in enumerate(mic_list):
                    if input_source_id and str(input_source_id) in name:
                        mic_index = i
                        break
                
                # マイクを指定して開く
                with sr.Microphone(device_index=mic_index) as source:
                    print(f"Using mic index {mic_index}: {mic_list[mic_index] if mic_index and mic_index < len(mic_list) else 'default'}")
                    recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    print("Listening for speech...")
                    
                    while self.speech_running and recording:
                        try:
                            audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
                            print(f"Audio captured: {len(audio.frame_data)} bytes")
                            try:
                                text = recognizer.recognize_google(audio, language="ja-JP")
                                print(f"Recognized: {text}")
                                if text and self.app_ref:
                                    self.after(0, lambda t=text: self.app_ref.update_transcript(t))
                            except sr.UnknownValueError:
                                pass  # 無音または認識不可
                            except sr.RequestError as e:
                                print(f"Google API error: {e}")
                        except sr.WaitTimeoutError:
                            pass  # タイムアウトは正常
                        except Exception as e:
                            print(f"Recognition error: {e}")
            except Exception as e:
                print(f"Microphone init error: {e}")
                traceback.print_exc()
        
        self.speech_thread = threading.Thread(target=recognize_loop, daemon=True)
        self.speech_thread.start()
        print("Speech recognition thread started")
    
    def stop_speech_recognition(self):
        """音声認識を停止"""
        self.speech_running = False
        self.system_speech_running = False
    
    def start_system_audio_recognition(self):
        """システム音声（YouTube等）の文字起こし"""
        if not gemini_assistant.is_configured:
            print("Gemini not configured for system audio recognition")
            return
        
        print("Starting system audio recognition with Gemini...")
        self.system_speech_running = True
        
        def recognize_system_loop():
            temp_buffer = []
            last_process_time = time.time()
            
            while self.system_speech_running and recording:
                time.sleep(0.1)
                
                # 10秒ごとにシステム音声を処理
                if time.time() - last_process_time >= 10:
                    if system_buffer and system_buffer.total_written > 0:
                        try:
                            # 最新の10秒分を取得
                            audio_data = system_buffer.get_all_data()
                            if len(audio_data) > SETTINGS.recording.sample_rate * 5:  # 5秒以上あれば処理
                                # 最後の10秒分だけ取得
                                samples_10sec = SETTINGS.recording.sample_rate * 10
                                if len(audio_data) > samples_10sec:
                                    audio_chunk = audio_data[-samples_10sec:]
                                else:
                                    audio_chunk = audio_data
                                
                                # 一時ファイルに保存
                                temp_path = os.path.join(SETTINGS.paths.recordings, "temp_system.wav")
                                sf.write(temp_path, audio_chunk, SETTINGS.recording.sample_rate)
                                
                                # Geminiで文字起こし
                                try:
                                    # 音声ファイルを読み込んでbase64エンコード
                                    import base64
                                    with open(temp_path, 'rb') as f:
                                        audio_bytes = f.read()
                                    
                                    # Geminiに音声を送信
                                    response = gemini_assistant.model.generate_content([
                                        "この音声を日本語で文字起こししてください。会話や発言のみを出力してください。音声がない場合は「なし」と返してください。",
                                        {
                                            "mime_type": "audio/wav",
                                            "data": base64.b64encode(audio_bytes).decode('utf-8')
                                        }
                                    ])
                                    text = response.text.strip()
                                    if text and text != "なし" and text != "空" and len(text) > 2:
                                        print(f"System audio recognized: {text[:50]}...")
                                        if self.app_ref:
                                            self.after(0, lambda t=text: self.app_ref.update_transcript(f"[システム] {t}"))
                                except Exception as e:
                                    print(f"Gemini transcription error: {e}")
                                
                                # 一時ファイル削除
                                try:
                                    os.remove(temp_path)
                                except:
                                    pass
                        except Exception as e:
                            print(f"System audio processing error: {e}")
                    
                    last_process_time = time.time()
        
        self.system_speech_thread = threading.Thread(target=recognize_system_loop, daemon=True)
        self.system_speech_thread.start()
        print("System audio recognition thread started")
    
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
            
            # 音声認識を開始
            if self.speech_var.get():
                self.start_speech_recognition()
                self.start_system_audio_recognition()  # システム音声も認識
        else:
            recording = False
            self.stop_speech_recognition()  # 音声認識を停止
            self.rec_btn.configure(state="disabled")
            self.label_time.configure(text=t("saving"), text_color=THEME.colors.warning)
            
            def finalize():
                try:
                    mic_data = mic_buffer.get_all_data()
                    sys_data = system_buffer.get_all_data()
                    mixed = mix_audio(mic_data, sys_data)
                    
                    if len(mixed) > 0:
                        wav_path = os.path.join(self.backup_dir, "output.wav")
                        # 音量調整（ゲイン適用）
                        gain = volume_gain.get()
                        mixed = mixed * gain
                        # クリッピング防止
                        peak = float(np.max(np.abs(mixed)))
                        if peak > 0.95:
                            mixed = (mixed / peak) * 0.95
                        sf.write(wav_path, mixed, SETTINGS.recording.sample_rate, subtype='PCM_16')
                        
                        final = wav_path
                        # MP3変換
                        mp3_path = os.path.join(self.backup_dir, "output.mp3")
                        try:
                            ffmpeg = find_ffmpeg()
                            startupinfo = None
                            if os.name == 'nt':
                                startupinfo = subprocess.STARTUPINFO()
                                startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                                startupinfo.wShowWindow = subprocess.SW_HIDE
                            subprocess.run([ffmpeg or 'ffmpeg', '-y', '-hide_banner', '-loglevel', 'error',
                                '-i', wav_path, '-codec:a', 'libmp3lame', '-b:a', '192k', mp3_path], 
                                capture_output=True, startupinfo=startupinfo)
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
                        
                        def update_ui():
                            try:
                                self.master.master.history_frame.refresh()
                            except: pass
                        self.after(100, update_ui)
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

class HistoryFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, padx=15, pady=(15, 5), sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(header, text=f"📂 {t('recent_recordings')}", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, sticky="w")
        ctk.CTkButton(header, text="📁", width=30, height=25, command=self.open_folder).grid(row=0, column=1, padx=2, sticky="e")
        ctk.CTkButton(header, text="🔄", width=30, height=25, command=self.refresh).grid(row=0, column=2, sticky="e")
        
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
            ctk.CTkButton(item, text="📁", width=30, height=30, command=lambda p=r['path']: self.open_file_folder(p)).grid(row=0, column=2, rowspan=2, padx=2, pady=5)
            ctk.CTkButton(item, text="▶️", width=30, height=30, command=lambda p=r['path']: os.startfile(p) if sys.platform=='win32' else subprocess.run(['open', p])).grid(row=0, column=3, rowspan=2, padx=5, pady=5)
    
    def open_file_folder(self, file_path):
        if file_path and os.path.exists(file_path):
            path = os.path.abspath(file_path)
            if sys.platform == 'win32':
                subprocess.run(['explorer', '/select,', path])
            elif sys.platform == 'darwin':
                subprocess.run(['open', '-R', path])
            else:
                subprocess.run(['xdg-open', os.path.dirname(path)])
    
    def open_folder(self):
        path = os.path.abspath(SETTINGS.paths.recordings)
        os.makedirs(path, exist_ok=True)
        if sys.platform == 'win32':
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.run(['open', path])
        else:
            subprocess.run(['xdg-open', path])

class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent = parent
        self.title(t("settings"))
        self.geometry("550x500")
        self.transient(parent)
        self.grab_set()
        self.grid_columnconfigure(0, weight=1)
        
        # 録音設定
        frame = ctk.CTkFrame(self)
        frame.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="ew")
        frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(frame, text="🎙️ 録音設定", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, columnspan=2, pady=10, sticky="w", padx=10)
        
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
        
        # Gemini設定
        gemini_frame = ctk.CTkFrame(self)
        gemini_frame.grid(row=1, column=0, padx=20, pady=10, sticky="ew")
        gemini_frame.grid_columnconfigure(1, weight=1)
        
        ctk.CTkLabel(gemini_frame, text="🤖 Gemini API設定", font=ctk.CTkFont(size=14, weight="bold")).grid(row=0, column=0, columnspan=2, pady=10, sticky="w", padx=10)
        
        ctk.CTkLabel(gemini_frame, text="APIキー:").grid(row=1, column=0, padx=10, pady=10, sticky="w")
        self.api_key_entry = ctk.CTkEntry(gemini_frame, placeholder_text="Gemini APIキーを入力", show="*", width=300)
        self.api_key_entry.grid(row=1, column=1, padx=10, pady=10, sticky="ew")
        if gemini_api_key:
            self.api_key_entry.insert(0, gemini_api_key)
        
        # API状態表示
        self.api_status = ctk.CTkLabel(gemini_frame, text="", font=ctk.CTkFont(size=11))
        self.api_status.grid(row=2, column=0, columnspan=2, padx=10, sticky="w")
        self.update_api_status()
        
        # ボタン
        btn_frame = ctk.CTkFrame(gemini_frame, fg_color="transparent")
        btn_frame.grid(row=3, column=0, columnspan=2, pady=10)
        
        ctk.CTkButton(btn_frame, text="🔗 接続テスト", command=self.test_gemini, width=120).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="💾 保存", command=self.save_gemini, width=100).pack(side="left", padx=5)
        
        # ヘルプリンク
        help_frame = ctk.CTkFrame(gemini_frame, fg_color="transparent")
        help_frame.grid(row=4, column=0, columnspan=2, padx=10, pady=5, sticky="w")
        ctk.CTkLabel(help_frame, text="APIキー取得:", font=ctk.CTkFont(size=10), text_color=THEME.colors.text_muted).pack(side="left")
        help_btn = ctk.CTkButton(help_frame, text="Google AI Studio", font=ctk.CTkFont(size=10), 
            fg_color="transparent", text_color=THEME.colors.primary, hover_color=THEME.colors.primary,
            command=lambda: webbrowser.open("https://aistudio.google.com/app/apikey"), width=100, height=20)
        help_btn.pack(side="left")
        
        # 閉じるボタン
        ctk.CTkButton(self, text="閉じる", command=self.destroy, width=120).grid(row=2, column=0, pady=20)
    
    def update_api_status(self):
        if gemini_assistant.is_configured:
            self.api_status.configure(text="✅ Gemini API接続済み", text_color=THEME.colors.secondary)
        else:
            self.api_status.configure(text="⚪ 未接続", text_color=THEME.colors.text_muted)
    
    def test_gemini(self):
        """Gemini接続テスト"""
        api_key = self.api_key_entry.get().strip()
        if not api_key:
            messagebox.showerror("エラー", "APIキーを入力してください")
            return
        
        self.api_status.configure(text="⏳ 接続テスト中...", text_color=THEME.colors.warning)
        self.update()
        
        def do_test():
            success = gemini_assistant.configure(api_key)
            self.after(0, lambda: self._handle_test_result(success))
        
        threading.Thread(target=do_test, daemon=True).start()
    
    def _handle_test_result(self, success):
        if success:
            self.api_status.configure(text="✅ 接続成功！", text_color=THEME.colors.secondary)
            # 親ウィンドウのアシスタントパネルのステータスを更新
            if hasattr(self.parent, 'assistant_panel'):
                self.parent.assistant_panel.update_status()
            messagebox.showinfo("成功", "Gemini APIに正常に接続できました")
        else:
            self.api_status.configure(text="❌ 接続失敗", text_color=THEME.colors.danger)
            messagebox.showerror("エラー", "Gemini APIへの接続に失敗しました。\nAPIキーを確認してください。")
    
    def save_gemini(self):
        """Gemini設定を保存"""
        global gemini_api_key
        api_key = self.api_key_entry.get().strip()
        if api_key:
            gemini_api_key = api_key
            save_settings()
            messagebox.showinfo("保存", "APIキーを保存しました")
    
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

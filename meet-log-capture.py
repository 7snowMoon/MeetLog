import os
import time
import soundcard as sc
import soundfile as sf
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import threading
import numpy as np
import traceback
import asyncio
import json
import base64
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

try:
    import websockets
    WEBSOCKETS_AVAILABLE = True
except ImportError:
    WEBSOCKETS_AVAILABLE = False
warnings.filterwarnings("ignore", message="data discontinuity in recording", category=Warning)
warnings.filterwarnings("ignore", category=UserWarning, module='soundcard')

# ===== Settings =====
def resource_path(relative_path: str) -> str:
    base_path = getattr(sys, '_MEIPASS', os.path.abspath("."))
    return os.path.join(base_path, relative_path)

SETTINGS = SimpleNamespace()
SETTINGS.recording = SimpleNamespace()
SETTINGS.recording.sample_rate = 44100
SETTINGS.recording.buffer_size = SETTINGS.recording.sample_rate // 2  # 0.5秒分のバッファ
SETTINGS.recording.sync_tolerance = 0.01  # 同期許容誤差（秒）
SETTINGS.recording.mic_delay_ms = -50  # マイク音声の遅延調整（ミリ秒）- 負の値はマイクを遅らせる、正の値は早める
SETTINGS.recording.max_duration_seconds = 7200  # 最大録音時間（秒）= 2時間
SETTINGS.recording.ring_buffer_duration = 7200  # リングバッファの保持時間（秒）= 最大時間と同じ
SETTINGS.websocket = SimpleNamespace()
SETTINGS.websocket.port = 8765  # WebSocketサーバーのポート
SETTINGS.ads = SimpleNamespace()
SETTINGS.ads.folder = resource_path("ads")
SETTINGS.ads.interval_seconds = 15

# ===== Language =====
LANG = SimpleNamespace()
LANG.labels = SimpleNamespace()
LANG.labels.RecordingFrame = SimpleNamespace()
LANG.labels.RecordingFrame.label_recording = "録音"
LANG.labels.RecordingFrame.label_stop = "停止"
LANG.labels.RecordingFrame.text_pause = "[一時停止中]"
LANG.labels.RecordingFrame.text_mp3 = "MP3変換"
LANG.labels.RecordingFrame.text_normalize = "正規化"

# ===== Global variables =====
recording = False
pause = False
recording_start_time = None
mic_buffer = None  # リングバッファ
system_buffer = None  # リングバッファ
input_source_id = None
system_source_id = None
backup_dir = None
is_mp3 = True
is_normalize = True
websocket_clients = set()  # WebSocketクライアント接続管理
recording_frame_ref = None  # UIフレームへの参照


def convert_seconds(seconds):
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


class RingBuffer:
    """固定サイズのリングバッファ - メモリ効率的な音声保存"""
    def __init__(self, duration_seconds, sample_rate, channels=1):
        self.sample_rate = sample_rate
        self.channels = channels
        self.max_samples = int(duration_seconds * sample_rate)
        self.buffer = np.zeros((self.max_samples, channels), dtype=np.float32)
        self.write_pos = 0
        self.total_written = 0  # 全体で書き込まれたサンプル数
        self.lock = threading.Lock()
    
    def write(self, data):
        """データをバッファに書き込む"""
        with self.lock:
            if len(data) == 0:
                return
            
            # データの形状を統一
            if len(data.shape) == 1:
                data = data.reshape(-1, 1)
            elif data.shape[1] != self.channels:
                # チャンネル数が異なる場合は調整
                if data.shape[1] == 1:
                    data = np.column_stack([data] * self.channels)
                else:
                    data = data[:, :self.channels]
            
            data_len = len(data)
            remaining = data_len
            src_pos = 0
            
            while remaining > 0:
                # バッファの残り容量
                space_left = self.max_samples - self.write_pos
                to_write = min(remaining, space_left)
                
                # データを書き込み
                self.buffer[self.write_pos:self.write_pos + to_write] = data[src_pos:src_pos + to_write]
                
                self.write_pos += to_write
                self.total_written += to_write
                remaining -= to_write
                src_pos += to_write
                
                # バッファが満杯になったらリセット
                if self.write_pos >= self.max_samples:
                    self.write_pos = 0
    
    def get_all_data(self):
        """バッファ内の全データを取得"""
        with self.lock:
            if self.total_written < self.max_samples:
                # バッファがまだ満杯になっていない場合
                return self.buffer[:self.write_pos].copy()
            else:
                # バッファが満杯の場合、write_posから始まるデータを返す
                data = np.vstack((
                    self.buffer[self.write_pos:],
                    self.buffer[:self.write_pos]
                ))
                return data.copy()


def check_max_duration(recording_frame):
    """最大録音時間をチェック - 超過時は自動停止"""
    global recording, recording_start_time
    
    if recording and recording_start_time:
        elapsed = time.time() - recording_start_time
        if elapsed >= SETTINGS.recording.max_duration_seconds:
            print(f"最大録音時間（{SETTINGS.recording.max_duration_seconds // 3600}時間）に達しました。自動停止します。")
            recording = False
            try:
                recording_frame.recording_button.configure(text=LANG.labels.RecordingFrame.label_recording)
                messagebox.showinfo("通知", f"最大録音時間（{SETTINGS.recording.max_duration_seconds // 3600}時間）に達しました。\n録音を停止しました。")
            except Exception as e:
                print(f"UI更新エラー: {e}")


def find_ffmpeg_executable():
    """同梱/近傍/環境PATHから ffmpeg 実行ファイルを探す（Windows優先）。"""
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    candidates = []
    try:
        # PyInstaller 展開先
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates += [
                os.path.join(meipass, exe_name),
                os.path.join(meipass, "ffmpeg", exe_name),
                os.path.join(meipass, "bin", exe_name),
            ]
        # 実行ファイルと同階層
        if getattr(sys, "frozen", False):
            base = os.path.dirname(sys.executable)
        else:
            base = os.path.dirname(os.path.abspath(__file__))
        candidates += [
            os.path.join(base, exe_name),
            os.path.join(base, "ffmpeg", exe_name),
            os.path.join(base, "bin", exe_name),
        ]
    except Exception:
        pass
    # 直接存在チェック
    for c in candidates:
        if os.path.isfile(c):
            return c
    # PATH から
    which = shutil.which(exe_name)
    return which


def normalize(sound):
    change_in_dBFS = -14.0 - sound.dBFS
    return sound.apply_gain(change_in_dBFS)


def record_from_mic(recording_frame):
    global mic_buffer, input_source_id, pause, recording, recording_start_time
    print(f"マイク録音開始: デバイスID={input_source_id}")
    buffer_size = SETTINGS.recording.buffer_size
    try:
        with sc.get_microphone(id=input_source_id, include_loopback=False).recorder(samplerate=SETTINGS.recording.sample_rate, blocksize=buffer_size) as mic:
            print("マイクレコーダー初期化成功")
            while recording:
                try:
                    _data = mic.record(numframes=buffer_size)
                    if not pause:
                        mic_buffer.write(_data)
                        check_max_duration(recording_frame)
                        
                        if recording_start_time:
                            elapsed = time.time() - recording_start_time
                            sec = elapsed
                            str_l = "[REC " if int(sec * 4) % 2 == 0 else "[    "
                            str_r = "]"
                            t = convert_seconds(sec)
                            try:
                                recording_frame.label_time.configure(text=str_l + t + str_r, text_color="#ff3333")
                            except Exception as ui_err:
                                pass  # UI更新失敗は無視
                    else:
                        try:
                            recording_frame.label_time.configure(text=LANG.labels.RecordingFrame.text_pause, text_color="#888888")
                        except Exception as ui_err:
                            pass
                except Exception as e:
                    print(f"マイク録音エラー: {e}")
                    time.sleep(0.1)
        
    except Exception as e:
        print(f"マイクレコーダー初期化エラー: {e}")
        try:
            messagebox.showerror("エラー", f"マイク録音の初期化に失敗しました。\nデバイスID: {input_source_id}\nエラー: {str(e)}")
        except:
            pass

    print(f"マイク録音終了")
    try:
        recording_frame.label_time.configure(text="00:00:00", text_color="#ffffff")
    except:
        pass


def record_system_audio(recording_frame):
    global system_buffer, system_source_id, pause, recording
    print(f"システム音声録音開始: デバイスID={system_source_id}")
    buffer_size = SETTINGS.recording.buffer_size
    
    try:
        with sc.get_microphone(id=system_source_id, include_loopback=True).recorder(samplerate=SETTINGS.recording.sample_rate, blocksize=buffer_size) as speaker_recorder:
            print("システム音声レコーダー初期化成功")
            while recording:
                try:
                    _data = speaker_recorder.record(numframes=buffer_size)
                    if not pause:
                        system_buffer.write(_data)
                except Exception as e:
                    print(f"システム音声録音エラー: {e}")
                    time.sleep(0.1)
    except Exception as e:
        print(f"システム音声レコーダー初期化エラー: {e}")
        try:
            messagebox.showerror("エラー", f"システム音声録音の初期化に失敗しました。\nデバイスID: {system_source_id}\nエラー: {str(e)}")
        except:
            pass
    
    print(f"システム音声録音終了")


def mix_audio_channels(mic_audio, system_audio):
    """マイク音声とシステム音声を混合する関数"""
    # 両方のデータが存在する場合のみ混合
    if mic_audio is None and system_audio is None:
        print("警告: 両方の音声データがありません")
        return np.array([])  # 空の配列を返す
    
    if mic_audio is None:
        print("マイク音声がないため、システム音声のみを使用")
        return system_audio
    
    if system_audio is None:
        print("システム音声がないため、マイク音声のみを使用")
        return mic_audio
    
    # チャンネル数を合わせる
    if len(mic_audio.shape) == 1:  # モノラルの場合
        mic_stereo = np.column_stack((mic_audio, mic_audio))
    else:
        # 1チャンネルの場合（shape が (n, 1) の場合）
        if mic_audio.shape[1] == 1:
            mic_stereo = np.column_stack((mic_audio.flatten(), mic_audio.flatten()))
        else:
            mic_stereo = mic_audio
    
    # マイク遅延調整（設定値に基づく）
    delay_samples = int(SETTINGS.recording.sample_rate * abs(SETTINGS.recording.mic_delay_ms) / 1000)
    
    if SETTINGS.recording.mic_delay_ms < 0:
        # 負の値の場合、マイク音声を遅らせる（先頭に無音を追加）
        padding = np.zeros((delay_samples, mic_stereo.shape[1]))
        mic_stereo = np.vstack((padding, mic_stereo))
    elif SETTINGS.recording.mic_delay_ms > 0:
        # 正の値の場合、マイク音声を早める（先頭部分を削除）
        if len(mic_stereo) > delay_samples:
            mic_stereo = mic_stereo[delay_samples:]
    
    # 長さを合わせる
    if len(system_audio) > len(mic_stereo):
        # マイク音声が短い場合、足りない部分を0で埋める
        padding = np.zeros((len(system_audio) - len(mic_stereo), 2))
        mic_stereo = np.vstack((mic_stereo, padding))
    elif len(system_audio) < len(mic_stereo):
        # システム音声が短い場合、足りない部分を0で埋める
        padding = np.zeros((len(mic_stereo) - len(system_audio), 2))
        system_audio = np.vstack((system_audio, padding))
    
    # 音声を混合
    mixed_audio = system_audio * 1.2 + mic_stereo * 1.0
    
    # クリッピングを防ぐために正規化
    max_val = np.max(np.abs(mixed_audio))
    if max_val > 1.0:
        mixed_audio = mixed_audio / max_val * 0.95
    
    return mixed_audio


class EzSoundCaptureApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("OtoMemo(音メモ)")
        self.geometry("600x400")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        
        # メインフレーム
        self.main_frame = ctk.CTkFrame(self)
        self.main_frame.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.main_frame.grid_columnconfigure(0, weight=1)
        self.main_frame.grid_rowconfigure(0, weight=0)  # 入力ソース選択フレーム
        self.main_frame.grid_rowconfigure(1, weight=1)  # 録音フレーム
        
        # 入力ソース選択フレーム
        self.source_frame = SourceFrame(self.main_frame)
        self.source_frame.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        
        # 録音フレーム
        self.recording_frame = RecordingFrame(self.main_frame)
        self.recording_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")


class SourceFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.grid_columnconfigure((0, 1), weight=1)
        
        # マイク入力ソース選択
        self.label_input = ctk.CTkLabel(self, text="マイク入力ソース:")
        self.label_input.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        
        self.input_sources = [m.name for m in sc.all_microphones(include_loopback=False)]
        self.input_source_var = ctk.StringVar(value=self.input_sources[0] if self.input_sources else "")
        self.input_source_menu = ctk.CTkOptionMenu(self, values=self.input_sources, variable=self.input_source_var, command=self.on_input_source_change)
        self.input_source_menu.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        
        # システム音声ソース選択
        self.label_system = ctk.CTkLabel(self, text="システム音声ソース:")
        self.label_system.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        
        self.system_sources = [m.name for m in sc.all_microphones(include_loopback=True)]
        self.system_source_var = ctk.StringVar(value=self.system_sources[0] if self.system_sources else "")
        self.system_source_menu = ctk.CTkOptionMenu(self, values=self.system_sources, variable=self.system_source_var, command=self.on_system_source_change)
        self.system_source_menu.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        
        # 初期値設定
        self.on_input_source_change(self.input_source_var.get())
        self.on_system_source_change(self.system_source_var.get())
    
    def on_input_source_change(self, source_name):
        global input_source_id
        for m in sc.all_microphones(include_loopback=False):
            if m.name == source_name:
                input_source_id = m.id
                break
    
    def on_system_source_change(self, source_name):
        global system_source_id
        for m in sc.all_microphones(include_loopback=True):
            if m.name == source_name:
                system_source_id = m.id
                break


class AdsFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.label = ctk.CTkLabel(self, text="")
        self.label.grid(row=0, column=0, sticky="nsew")
        self.label.bind("<Button-1>", self.on_click)
        self.ads = self.load_ads()
        self.index = -1
        self.current_image = None
        self.after(100, self.next_ad)
        self.bind("<Configure>", self.on_resize)

    def load_ads(self):
        folder = SETTINGS.ads.folder
        images = []
        cfg_path = os.path.join(folder, 'ads.json')
        try:
            with open(cfg_path, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
                for b in cfg.get('banners', []):
                    img_path = os.path.join(folder, b.get('image', ''))
                    link = b.get('link')
                    images.append((img_path, link))
        except Exception:
            pass
        if not images:
            for ext in ('*.png','*.jpg','*.jpeg'):
                for p in glob.glob(os.path.join(folder, ext)):
                    images.append((p, None))
        return images

    def next_ad(self):
        if not self.ads:
            self.label.configure(text="広告枠", anchor="center")
            return
        self.index = (self.index + 1) % len(self.ads)
        self.show_current()
        self.after(int(SETTINGS.ads.interval_seconds * 1000), self.next_ad)

    def show_current(self):
        if not self.ads:
            return
        path, _ = self.ads[self.index]
        try:
            w = max(self.winfo_width(), 300)
            h = max(self.winfo_height(), 120)
            img = Image.open(path).convert("RGBA")
            size = (max(10, w-20), max(10, h-20))
            img = img.resize(size, Image.LANCZOS)
            cimg = ctk.CTkImage(light_image=img, size=size)
            self.current_image = cimg
            self.label.configure(image=cimg, text="")
        except Exception:
            self.label.configure(text="広告を表示できません", anchor="center")

    def on_click(self, _event):
        if not self.ads:
            return
        _, link = self.ads[self.index]
        if link:
            try:
                webbrowser.open(link)
            except Exception:
                pass

    def on_resize(self, _event):
        try:
            self.show_current()
        except Exception:
            pass

class RecordingFrame(ctk.CTkFrame):
    def __init__(self, parent):
        super().__init__(parent)
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # 録音時間表示
        self.grid_rowconfigure(1, weight=1)  # 広告枠
        self.grid_rowconfigure(2, weight=0)  # 録音ボタン
        self.grid_rowconfigure(3, weight=0)  # オプション
        self.grid_rowconfigure(4, weight=0)  # 同期調整
        
        # 録音時間表示
        self.label_time = ctk.CTkLabel(self, text="00:00:00", font=("Arial", 24))
        self.label_time.grid(row=0, column=0, padx=10, pady=10)
        
        self.ad_frame = AdsFrame(self)
        self.ad_frame.grid(row=1, column=0, padx=10, pady=10, sticky="nsew")
        
        # 録音ボタン
        self.button_frame = ctk.CTkFrame(self)
        self.button_frame.grid(row=2, column=0, padx=10, pady=10)
        
        self.recording_button = ctk.CTkButton(self.button_frame, text=LANG.labels.RecordingFrame.label_recording, command=self.start_recording, width=100, height=40)
        self.recording_button.grid(row=0, column=0, padx=10, pady=10)
        
        self.pause_button = ctk.CTkButton(self.button_frame, text="一時停止", command=self.pause_recording, width=100, height=40)
        self.pause_button.grid(row=0, column=1, padx=10, pady=10)
        
        # オプション
        self.option_frame = ctk.CTkFrame(self)
        self.option_frame.grid(row=3, column=0, padx=10, pady=10)
        self.option_frame.grid_remove()
        
        global is_mp3, is_normalize
        is_mp3 = ctk.BooleanVar(value=True)
        is_normalize = ctk.BooleanVar(value=True)
        
        self.mp3_checkbox = ctk.CTkCheckBox(self.option_frame, text=LANG.labels.RecordingFrame.text_mp3, variable=is_mp3)
        self.mp3_checkbox.grid(row=0, column=0, padx=10, pady=5)
        
        self.normalize_checkbox = ctk.CTkCheckBox(self.option_frame, text=LANG.labels.RecordingFrame.text_normalize, variable=is_normalize)
        self.normalize_checkbox.grid(row=0, column=1, padx=10, pady=5)
        
        # 同期調整スライダー
        self.sync_frame = ctk.CTkFrame(self)
        self.sync_frame.grid(row=4, column=0, padx=10, pady=10, sticky="ew")
        self.sync_frame.grid_columnconfigure(1, weight=1)
        self.sync_frame.grid_remove()
        
        self.label_sync = ctk.CTkLabel(self.sync_frame, text="マイク遅延調整:")
        self.label_sync.grid(row=0, column=0, padx=10, pady=5, sticky="w")
        
        self.mic_delay_var = ctk.IntVar(value=SETTINGS.recording.mic_delay_ms)
        self.mic_delay_slider = ctk.CTkSlider(self.sync_frame, from_=-200, to=200, number_of_steps=40, variable=self.mic_delay_var, command=self.on_mic_delay_change)
        self.mic_delay_slider.grid(row=0, column=1, padx=10, pady=5, sticky="ew")
        
        self.label_sync_value = ctk.CTkLabel(self.sync_frame, text=f"{SETTINGS.recording.mic_delay_ms}ms")
        self.label_sync_value.grid(row=0, column=2, padx=10, pady=5, sticky="e")
        
        # 説明ラベルを追加
        self.label_sync_help = ctk.CTkLabel(self.sync_frame, text="負の値: マイクを遅らせる / 正の値: マイクを早める", text_color="#888888", font=("Arial", 10))
        self.label_sync_help.grid(row=1, column=0, columnspan=3, padx=10, pady=(0, 5), sticky="w")
    
    def on_mic_delay_change(self, value):
        SETTINGS.recording.mic_delay_ms = int(value)
        self.label_sync_value.configure(text=f"{SETTINGS.recording.mic_delay_ms}ms")
    
    def start_recording(self):
        global input_source_id, system_source_id, recording, mic_buffer, system_buffer, backup_dir, pause, recording_start_time
        if not recording:
            # 入力デバイスの確認
            if input_source_id is None:
                messagebox.showerror("エラー", "マイク入力ソースが選択されていません。")
                return
            
            if system_source_id is None:
                messagebox.showerror("エラー", "システム音声ソースが選択されていません。")
                return
            
            print("録音開始")
            recording = True
            recording_start_time = time.time()
            
            # リングバッファの初期化（最大2時間分）
            mic_buffer = RingBuffer(SETTINGS.recording.max_duration_seconds, SETTINGS.recording.sample_rate, channels=1)
            system_buffer = RingBuffer(SETTINGS.recording.max_duration_seconds, SETTINGS.recording.sample_rate, channels=2)
            
            self.recording_button.configure(text=LANG.labels.RecordingFrame.label_stop)
            backup_dir = f"./recordings/{datetime.now().strftime('%Y%m%d_%H%M%S')}/"
            os.makedirs(backup_dir, exist_ok=True)
            print(f"録音ディレクトリ作成: {backup_dir}")
            
            # マイク録音スレッドの開始
            threading.Thread(target=record_from_mic, args=(self,), daemon=True).start()
            
            # システム音声録音スレッドの開始
            threading.Thread(target=record_system_audio, args=(self,), daemon=True).start()
        
        else:
            if pause:
                pause = False
                self.recording_button.configure(text=LANG.labels.RecordingFrame.label_stop)
                return

            else:
                print("録音停止")
                recording = False
                self.recording_button.configure(state="disabled")
                self.pause_button.configure(state="disabled")
                self.label_time.configure(text="保存中...", text_color="#ffaa00")
                
                def finalize_worker():
                    try:
                        local_backup_dir = backup_dir
                        mic_data_local = mic_buffer.get_all_data()
                        system_data_local = system_buffer.get_all_data()
                        mixed_data = mix_audio_channels(mic_data_local, system_data_local)
                        if len(mixed_data) > 0:
                            wav_path = os.path.join(local_backup_dir, "output.wav")
                            try:
                                global is_mp3, is_normalize
                                if is_normalize.get():
                                    peak = float(np.max(np.abs(mixed_data)))
                                    if peak > 0:
                                        mixed_data = (mixed_data / peak) * 0.95
                                sf.write(file=wav_path, data=mixed_data, samplerate=SETTINGS.recording.sample_rate, subtype='PCM_16')
                                if os.path.exists(wav_path):
                                    file_size = os.path.getsize(wav_path)
                                    if file_size == 0:
                                        self.after(0, lambda: messagebox.showwarning("警告", "保存されたファイルのサイズが0です。録音データが正しく保存されていない可能性があります。"))
                                if is_mp3.get():
                                    mp3_path = os.path.join(local_backup_dir, "output.mp3")
                                    try:
                                        ffmpeg_path = find_ffmpeg_executable()
                                        if ffmpeg_path:
                                            # pydub でも同じ ffmpeg を使えるように設定
                                            try:
                                                AudioSegment.converter = ffmpeg_path
                                            except Exception:
                                                pass
                                        cmd = [
                                            ffmpeg_path or 'ffmpeg',
                                            '-y', '-hide_banner', '-loglevel', 'error',
                                            '-i', wav_path, '-codec:a', 'libmp3lame', '-b:a', '128k', mp3_path
                                        ]
                                        result = subprocess.run(cmd, capture_output=True)
                                        if result.returncode == 0 and os.path.exists(mp3_path):
                                            try:
                                                os.remove(wav_path)
                                            except Exception:
                                                pass
                                        else:
                                            audio = AudioSegment.from_wav(wav_path)
                                            # pydub の ffmpeg パスは上で設定済み（可能なら）
                                            audio.export(mp3_path, format='mp3', bitrate='128k')
                                            try:
                                                os.remove(wav_path)
                                            except Exception:
                                                pass
                                    except Exception:
                                        audio = AudioSegment.from_wav(wav_path)
                                        audio.export(mp3_path, format='mp3', bitrate='128k')
                                        try:
                                            os.remove(wav_path)
                                        except Exception:
                                            pass
                                self.after(0, lambda: messagebox.showinfo("録音完了", f"録音が完了しました。\n保存先: {os.path.abspath(local_backup_dir)}"))
                            except Exception as e:
                                traceback.print_exc()
                                self.after(0, lambda: messagebox.showerror("エラー", f"音声処理中にエラーが発生しました。\n{str(e)}"))
                        else:
                            self.after(0, lambda: messagebox.showwarning("警告", "録音データがありません。マイクとシステム音声の設定を確認してください。"))
                    except Exception as e:
                        traceback.print_exc()
                        self.after(0, lambda: messagebox.showerror("エラー", f"録音データの保存中にエラーが発生しました。\n{str(e)}"))
                    finally:
                        self.after(0, lambda: self.recording_button.configure(text=LANG.labels.RecordingFrame.label_recording, state="normal"))
                        self.after(0, lambda: self.pause_button.configure(state="normal"))
                        self.after(0, lambda: self.label_time.configure(text="00:00:00", text_color="#ffffff"))
                
                threading.Thread(target=finalize_worker, daemon=True).start()
    
    def pause_recording(self):
        global input_source_id, recording, mic_data, system_data, backup_dir, pause
        if not recording:
            pause = False
            return

        if recording:
            if pause:
                pause = False
                self.recording_button.configure(text=LANG.labels.RecordingFrame.label_stop)
            else:
                pause = True
                self.recording_button.configure(text=LANG.labels.RecordingFrame.label_recording)


async def handle_websocket_client(websocket, path):
    """WebSocketクライアントからのスマホマイク音声を処理"""
    global websocket_clients, mic_buffer, recording
    
    if not WEBSOCKETS_AVAILABLE:
        print("WebSocketsライブラリがインストールされていません")
        return
    
    websocket_clients.add(websocket)
    print(f"WebSocketクライアント接続: {websocket.remote_address}")
    
    try:
        async for message in websocket:
            if recording and mic_buffer:
                try:
                    # JSONメッセージをパース
                    data = json.loads(message)
                    if 'audio' in data:
                        # Base64エンコードされた音声データをデコード
                        audio_bytes = base64.b64decode(data['audio'])
                        audio_data = np.frombuffer(audio_bytes, dtype=np.float32)
                        
                        # リングバッファに書き込み
                        mic_buffer.write(audio_data)
                except Exception as e:
                    print(f"WebSocket音声処理エラー: {e}")
    except Exception as e:
        print(f"WebSocketエラー: {e}")
    finally:
        websocket_clients.discard(websocket)
        print(f"WebSocketクライアント切断: {websocket.remote_address}")


def start_websocket_server():
    """WebSocketサーバーを起動（別スレッド）"""
    if not WEBSOCKETS_AVAILABLE:
        print("WebSocketsライブラリがインストールされていません。スマホからの録音は利用できません。")
        return
    
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        async def run_server():
            async with websockets.serve(handle_websocket_client, "0.0.0.0", SETTINGS.websocket.port):
                print(f"WebSocketサーバー起動: ws://0.0.0.0:{SETTINGS.websocket.port}")
                await asyncio.Future()  # 永遠に実行
        
        loop.run_until_complete(run_server())
    except Exception as e:
        print(f"WebSocketサーバー起動エラー: {e}")


def main():
    global monitoring
    global close
    monitoring = True
    
    # WebSocketサーバーをバックグラウンドで起動
    if WEBSOCKETS_AVAILABLE:
        threading.Thread(target=start_websocket_server, daemon=True).start()
    
    app = EzSoundCaptureApp()
    app.mainloop()
    monitoring = False
    exit()

if __name__ == "__main__":
    main()

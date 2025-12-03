# 🎙️ MeetLog - 会議録音・議事録作成支援ツール

<p align="center">
  <img src="https://img.shields.io/badge/version-2.0.0-blue.svg" alt="Version">
  <img src="https://img.shields.io/badge/python-3.8+-green.svg" alt="Python">
  <img src="https://img.shields.io/badge/platform-Windows-lightgrey.svg" alt="Platform">
  <img src="https://img.shields.io/badge/license-MIT-orange.svg" alt="License">
</p>

MeetLogは、会議やミーティングの音声を簡単に録音し、**Google NotebookLM** と連携してAIによる議事録・要約を作成できるツールです。

## ✨ 主な機能

### 🎤 高品質な録音
- **マイク音声 + システム音声** を同時録音
- 最大2時間の連続録音に対応
- MP3変換 & 音量正規化オプション
- 一時停止/再開機能

### 🔗 Google NotebookLM 連携
- 録音ファイルをワンクリックでNotebookLMへ
- AIが自動で**文字起こし・議事録・要約**を生成
- Google Drive連携でファイル管理も簡単

### 📂 録音履歴管理
- 最近の録音を一覧表示
- ワンクリックで再生・フォルダを開く
- ファイルサイズ・日時を確認

## 🚀 クイックスタート

### 方法1: EXE版を使用（おすすめ）

1. [Releases](https://github.com/your-username/MeetLog/releases) から最新版をダウンロード
2. ZIPを解凍
3. `MeetLog.exe` をダブルクリック

### 方法2: Pythonから実行

```bash
# リポジトリをクローン
git clone https://github.com/your-username/MeetLog.git
cd MeetLog

# 仮想環境を作成（推奨）
python -m venv venv
venv\Scripts\activate  # Windows

# 依存パッケージをインストール
pip install -r requirements.txt

# 起動
python MeetLog.py
```

## 📝 NotebookLMで議事録を作成する

1. **録音する**
   - MeetLogで会議を録音
   - 「録音停止」で自動保存

2. **NotebookLMを開く**
   - 「📝 NotebookLMで議事録作成」ボタンをクリック
   - Google アカウントでログイン

3. **ファイルをアップロード**
   - 「新しいノートブック」を作成
   - 「ソースを追加」→「ファイルをアップロード」
   - 録音ファイル（MP3/WAV）を選択

4. **AIが議事録を生成**
   - 自動で文字起こし
   - 要約・アクションアイテムを抽出
   - 質問で詳細を確認

## ⚙️ 設定

### 録音設定
| 設定項目 | デフォルト | 説明 |
|---------|-----------|------|
| 最大録音時間 | 2時間 | 1〜4時間で設定可能 |
| マイク遅延調整 | -50ms | 音声の同期を調整 |
| サンプルレート | 44100Hz | 録音品質 |

### MP3変換
- **ビットレート**: 192kbps
- **コーデック**: LAME MP3
- **要件**: FFmpegがインストールされている必要があります

## 📦 依存パッケージ

```
soundcard>=0.4.2
soundfile>=0.12.1
numpy>=1.24.0
pydub>=0.25.1
customtkinter>=5.2.0
Pillow>=10.0.0
```

## 📤 EXEビルド（開発者向け）

```bash
build_exe.bat
```

→ `dist/MeetLog.exe` が生成されます

配布する場合は `dist` フォルダをZIP圧縮してください。

### FFmpegのインストール

MP3変換機能を使用するには、FFmpegが必要です。

**Windows:**
```bash
# wingetを使用
winget install FFmpeg

# または chocolatey
choco install ffmpeg
```

**ダウンロード:**
https://ffmpeg.org/download.html

## 🗂️ ファイル構成

```
MeetLog/
├── MeetLog.py              # メインアプリケーション
├── MANUAL.md               # 使い方ガイド
├── build_exe.bat           # EXEビルド用
├── requirements.txt        # 依存パッケージ
├── recordings/             # 録音ファイル保存先
└── dist/                   # ビルド出力（生成後）
    └── MeetLog.exe         # ダブルクリックで起動
```

## 🔧 トラブルシューティング

### 録音デバイスが見つからない
- Windows: 「サウンド設定」でデバイスが有効か確認
- 「ステレオミキサー」が無効の場合は有効化

### MP3変換に失敗する
- FFmpegがインストールされているか確認
- `ffmpeg -version` で動作確認

### 音声が同期しない
- 設定画面で「マイク遅延調整」を変更
- 負の値: マイクを遅らせる
- 正の値: マイクを早める

## 📄 ライセンス

MIT License

## 🤝 コントリビューション

Issue・Pull Requestは大歓迎です！

---

<p align="center">
  Made with ❤️ for better meetings
</p>

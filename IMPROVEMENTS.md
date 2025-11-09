# MeetLog 改善内容

## 主な変更点

### 1. ストリーミング方式への変更（WAVファイル蓄積問題の解決）

**問題点:**
- 従来は60秒ごとにバックアップファイルを作成していたため、WAVファイルが大量に蓄積

**解決策:**
- **リングバッファ方式** を導入
  - 固定サイズのメモリバッファを使用
  - 古いデータは自動的に上書きされる
  - メモリ効率が大幅に改善
  - ファイルは最終的に1つだけ保存される

**メリット:**
- ディスク容量を節約
- 管理が簡単
- 処理が高速化

---

### 2. 最大2時間の録音制限

**実装内容:**
- 設定: `SETTINGS.recording.max_duration_seconds = 7200`（2時間）
- 自動停止機能を実装
- 2時間に達すると自動的に録音を停止

**使用方法:**
```python
# 設定ファイルで変更可能
SETTINGS.recording.max_duration_seconds = 3600  # 1時間に変更
```

---

### 3. スマホからの録音対応

#### WebSocketサーバー

PCアプリケーションに **WebSocketサーバー** を統合：
- ポート: `8765`（デフォルト）
- スマホからのマイク音声をリアルタイムで受信
- PCのマイク音声と混合して録音

#### スマホクライアント（HTML）

`smartphone_recorder.html` を提供：
- ブラウザで開くだけで使用可能
- 美しいUIで直感的に操作
- リアルタイム波形表示
- 音量レベル表示

**使用方法:**

1. **PCでアプリを起動**
   ```bash
   python meet-log-capture.py
   ```

2. **スマホでHTMLを開く**
   - `smartphone_recorder.html` をスマホのブラウザで開く
   - または、PCから `file:///path/to/smartphone_recorder.html` でアクセス

3. **接続設定**
   - サーバーアドレスを入力: `ws://PCのIPアドレス:8765`
   - 例: `ws://192.168.1.100:8765`

4. **録音開始**
   - PCで「録音」をクリック
   - スマホで「接続」→「録音開始」をクリック
   - スマホのマイク許可を与える

5. **録音終了**
   - PCで「停止」をクリック
   - スマホで「録音停止」をクリック

---

## 技術仕様

### リングバッファクラス

```python
class RingBuffer:
    """固定サイズのリングバッファ - メモリ効率的な音声保存"""
    def __init__(self, duration_seconds, sample_rate, channels=1):
        # 最大保持時間分のメモリを確保
        self.max_samples = int(duration_seconds * sample_rate)
        self.buffer = np.zeros((self.max_samples, channels), dtype=np.float32)
```

**特徴:**
- スレッドセーフ（ロック機構付き）
- 自動的に古いデータを上書き
- メモリ使用量は固定

### WebSocket通信フォーマット

スマホからPC へ送信されるデータ:

```json
{
    "audio": "Base64エンコードされた音声データ",
    "timestamp": 1234567890
}
```

---

## 設定のカスタマイズ

### 最大録音時間の変更

```python
SETTINGS.recording.max_duration_seconds = 3600  # 1時間
```

### リングバッファの保持時間

```python
SETTINGS.recording.ring_buffer_duration = 300  # 5分
```

### WebSocketサーバーのポート変更

```python
SETTINGS.websocket.port = 9000  # ポート9000に変更
```

---

## 依存パッケージ

新しく追加されたパッケージ:
- `websockets` - WebSocketサーバー機能

インストール:
```bash
pip install -r requirements.txt
```

---

## トラブルシューティング

### スマホから接続できない

1. **ファイアウォール設定を確認**
   - ポート8765がブロックされていないか確認

2. **IPアドレスを確認**
   ```bash
   ipconfig  # Windows
   ifconfig  # Mac/Linux
   ```

3. **同じネットワークに接続**
   - PCとスマホが同じWiFiネットワークに接続していることを確認

### 音声が混合されない

1. **WebSocketクライアントが接続されているか確認**
   - PCのコンソールに「WebSocketクライアント接続」と表示されているか確認

2. **スマホで「録音開始」をクリックしているか確認**
   - スマホのUIで「録音中」と表示されているか確認

3. **マイク許可を与えているか確認**
   - スマホのブラウザ設定でマイクへのアクセスを許可

---

## 今後の拡張予定

- [ ] 複数スマホからの同時録音
- [ ] スマホからのシステム音声キャプチャ
- [ ] リアルタイムレベルメーター
- [ ] クラウド連携

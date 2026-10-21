
import threading
import time
import tkinter as tk
from tkinter import scrolledtext
import speech_recognition as sr
import pyaudio

FORMAT = pyaudio.paInt16
SAMPLE_RATE = 44100        # サンプリングレート
CHANNELS = 1            # モノラル
CHUNK = 1024            # バッファサイズ
INPUT_DEVICE_INDEX = 0  # マイクデバイスインデックス

class VoiceTranscriberApp:
    def __init__(self, root):
        self.root = root
        self.root.title("音声文字起こし (ボタン押下中録音)")
        self.root.geometry("500x400")

        self.recognizer = sr.Recognizer()
        self.audio = pyaudio.PyAudio()
        self.is_recording = False
        self.frames = []
        self.record_thread = None

        self.create_widgets()

    def create_widgets(self):
        # 説明ラベル
        self.label = tk.Label(self.root, text="下のボタンを押している間、音声を入力できます", font=("Helvetica", 12))
        self.label.pack(pady=10)

        # 録音ボタン (押している間録音)
        self.record_btn = tk.Button(
            self.root, 
            text="押しながら話す", 
            font=("Helvetica", 14, "bold"),
            bg="#4CAF50", 
            fg="white",
            activebackground="#45a049",
            activeforeground="white",
            height=2,
            width=20
        )
        self.record_btn.pack(pady=10)

        # マウスイベントのバインド (<ButtonPress-1> で録音開始、<ButtonRelease-1> で録音停止)
        self.record_btn.bind("<ButtonPress-1>", self.start_recording)
        self.record_btn.bind("<ButtonRelease-1>", self.stop_recording)

        # ステータス表示
        self.status_label = tk.Label(self.root, text="待機中", font=("Helvetica", 10), fg="gray")
        self.status_label.pack(pady=5)

        # 結果表示エリア
        self.result_area = scrolledtext.ScrolledText(self.root, wrap=tk.WORD, font=("Helvetica", 11), height=12)
        self.result_area.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)

    def start_recording(self, event=None):
        if self.is_recording:
            return
        
        self.is_recording = True
        self.frames = []
        self.record_btn.config(bg="#f44336", text="録音中...")
        self.status_label.config(text="録音中... ボタンを離すと文字起こしします", fg="red")

        # 録音処理を別スレッドで実行
        self.record_thread = threading.Thread(target=self._record)
        self.record_thread.start()

    def _record(self):
        try:
            stream = self.audio.open(
                format=FORMAT,
                channels=CHANNELS,
                rate=SAMPLE_RATE,
                input=True,
                input_device_index=INPUT_DEVICE_INDEX,
                frames_per_buffer=CHUNK
            )
            while self.is_recording:
                data = stream.read(CHUNK, exception_on_overflow=False)
                self.frames.append(data)
            
            stream.stop_stream()
            stream.close()
        except Exception as e:
            print(f"録音エラー: {e}")

    def stop_recording(self, event=None):
        if not self.is_recording:
            return
        
        self.is_recording = False
        self.record_btn.config(bg="#4CAF50", text="押しながら話す")
        self.status_label.config(text="文字起こし中...", fg="blue")

        # 文字起こし処理を別スレッドで実行
        threading.Thread(target=self._transcribe).start()

    def _transcribe(self):
        if not self.frames:
            self.status_label.config(text="録音データがありません", fg="gray")
            return

        audio_data_bytes = b"".join(self.frames)
        sample_width = self.audio.get_sample_size(FORMAT)
        audio_data = sr.AudioData(audio_data_bytes, SAMPLE_RATE, sample_width)

        try:
            text = self.recognizer.recognize_google(audio_data, language="ja-JP")
            print(f"認識結果: {text}")
            self.result_area.insert(tk.END, text + "\n")
            self.result_area.see(tk.END)
            self.status_label.config(text="文字起こし完了", fg="green")
        except sr.UnknownValueError:
            self.status_label.config(text="声を認識できませんでした", fg="orange")
        except sr.RequestError as e:
            self.status_label.config(text=f"APIエラー: {e}", fg="red")
        except Exception as e:
            self.status_label.config(text=f"エラーが発生しました: {e}", fg="red")

    def __del__(self):
        if hasattr(self, 'audio'):
            self.audio.terminate()

if __name__ == "__main__":
    root = tk.Tk()
    app = VoiceTranscriberApp(root)
    root.mainloop()

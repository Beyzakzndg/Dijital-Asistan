import tkinter as tk
from tkinter import messagebox
import threading
import datetime
from pathlib import Path
import time
import os
import tempfile
import asyncio

import speech_recognition as sr
import edge_tts
import pygame

# ---------------- Config ----------------
NOTES_FILE = Path("notes.txt")

WAKE_WORDS = ["lee", "li", "ley", "hey lee", "ok lee", "selam lee", "hey li", "ok li"]

COMMAND_KEYWORDS = [
    "saat", "tarih", "bugün", "günlerden", "not al", "notlar", "yardım",
    "kapat", "çık", "bitir", "exit", "quit"
]

# Neural voices
VOICE_MALE = "tr-TR-AhmetNeural"
VOICE_FEMALE = "tr-TR-EmelNeural"


# ---------------- Helpers ----------------
def normalize(text: str) -> str:
    return (text or "").lower().strip()


def tr_day_name(dt: datetime.datetime) -> str:
    gunler = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]
    return gunler[dt.weekday()]


def save_note(note: str):
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    old = NOTES_FILE.read_text(encoding="utf-8") if NOTES_FILE.exists() else ""
    NOTES_FILE.write_text(old + f"[{ts}] {note}\n", encoding="utf-8")


def read_notes_last(n=12):
    if not NOTES_FILE.exists():
        return []
    content = NOTES_FILE.read_text(encoding="utf-8").strip()
    if not content:
        return []
    return content.splitlines()[-n:]


def contains_command(text: str) -> bool:
    t = normalize(text)
    return any(k in t for k in COMMAND_KEYWORDS)


def strip_wake(text: str) -> str:
    t = normalize(text)
    for w in WAKE_WORDS:
        if w in t:
            t = t.replace(w, "").strip(" ,.!?:;")
    return t


def wake_missing(text: str, wake_enabled: bool) -> bool:
    if not wake_enabled:
        return False
    t = normalize(text)
    return not any(w in t for w in WAKE_WORDS)


# ---------------- STT ----------------
def stt_listen(recognizer: sr.Recognizer, mic: sr.Microphone, phrase_time_limit=8) -> str | None:
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.3)
        audio = recognizer.listen(source, phrase_time_limit=phrase_time_limit)
    try:
        return recognizer.recognize_google(audio, language="tr-TR")
    except sr.UnknownValueError:
        return None
    except sr.RequestError:
        return None


# ---------------- Intent ----------------
def parse_intent(user_text: str):
    t = normalize(user_text)

    if t in ["çık", "kapat", "bitir", "exit", "quit"]:
        return "__EXIT__", "Tamam, görüşürüz!"

    if "yardım" in t or "ne yapabilirsin" in t:
        return "OK", (
            "Şunları yapabilirim:\n"
            "• saat kaç\n"
            "• tarih ne / bugün günlerden ne\n"
            "• not al: ...\n"
            "• notlarımı oku\n"
            "• kapat"
        )

    if "saat kaç" in t or "saati söyle" in t or t == "saat":
        now = datetime.datetime.now()
        return "OK", f"Şu an saat {now.strftime('%H:%M:%S')}."

    if "tarih" in t or "bugün günlerden ne" in t or "bugün gün" in t:
        now = datetime.datetime.now()
        return "OK", f"Bugün {tr_day_name(now)}, {now.strftime('%d.%m.%Y')}."

    if t.startswith("not al") or "not al" in t:
        original = user_text.strip()
        note = ""
        if ":" in original:
            note = original.split(":", 1)[1].strip()
        else:
            idx = normalize(original).find("not al")
            note = original[idx + len("not al"):].strip(" :")

        if not note:
            return "OK", "Not için 'Not al: ...' şeklinde söyleyebilirsin."

        save_note(note)
        return "OK", f"Not aldım: {note}"

    if "notlarımı oku" in t or "notları oku" in t or t == "notlar":
        lines = read_notes_last(5)
        if not lines:
            return "OK", "Henüz not yok."
        return "OK", "Son notların:\n" + "\n".join(lines)

    if t.startswith("merhaba") or "selam" in t:
        return "OK", "Merhaba! Hazırım. 'saat kaç' ya da 'not al: ...' diyebilirsin."

    return "OK", f"Bunu duydum: {user_text}. 'Yardım' dersen komutları göstereyim."


# ---------------- UI ----------------
class AssistantUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Lee • Dijital Asistan (Neural)")
        self.root.geometry("920x580")
        self.root.minsize(880, 540)

        # STT (tek sefer)
        self.recognizer = sr.Recognizer()
        self.mic = sr.Microphone()

        # UI state
        self.wake_enabled = tk.BooleanVar(value=True)
        self.is_listening = False

        # TTS settings
        self.voice = VOICE_MALE  # istersen VOICE_FEMALE yap
        self._tts_lock = threading.Lock()

        # Init audio player once
        self._init_player()

        # ---------- LIGHT THEME ----------
        self.bg = "#f5f7fb"
        self.panel = "#ffffff"
        self.card = "#eef2ff"
        self.text = "#0f172a"
        self.muted = "#475569"
        self.accent = "#2563eb"
        self.border = "#dbeafe"

        self.root.configure(bg=self.bg)

        # ---------- Header ----------
        header = tk.Frame(root, bg=self.bg)
        header.pack(fill="x", padx=16, pady=(14, 10))

        tk.Label(header, text="Lee", fg=self.text, bg=self.bg, font=("Segoe UI", 22, "bold")).pack(side="left")
        tk.Label(header, text="Dijital Asistan • Neural Türkçe", fg=self.muted, bg=self.bg, font=("Segoe UI", 10)).pack(side="left", padx=(10, 0))

        clock_frame = tk.Frame(header, bg=self.bg)
        clock_frame.pack(side="right")
        self.time_lbl = tk.Label(clock_frame, text="--:--:--", fg=self.text, bg=self.bg, font=("Consolas", 18, "bold"))
        self.time_lbl.pack(anchor="e")
        self.date_lbl = tk.Label(clock_frame, text="--", fg=self.muted, bg=self.bg, font=("Segoe UI", 10))
        self.date_lbl.pack(anchor="e")

        # ---------- Main ----------
        main = tk.Frame(root, bg=self.bg)
        main.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        left = tk.Frame(main, bg=self.panel, highlightbackground=self.border, highlightthickness=1)
        left.pack(side="left", fill="both", expand=True)

        right = tk.Frame(main, bg=self.panel, width=300, highlightbackground=self.border, highlightthickness=1)
        right.pack(side="right", fill="y", padx=(12, 0))
        right.pack_propagate(False)

        # ---------- Chat ----------
        self.chat = tk.Text(left, bg=self.panel, fg=self.text, insertbackground=self.text,
                            relief="flat", wrap="word", font=("Segoe UI", 11))
        self.chat.pack(fill="both", expand=True, padx=12, pady=12)
        self.chat.configure(state="disabled")
        self.chat.tag_configure("hdr", foreground=self.accent, font=("Segoe UI", 10, "bold"))

        self.status = tk.Label(left, text="Hazır.", fg=self.muted, bg=self.panel, font=("Segoe UI", 10))
        self.status.pack(fill="x", padx=12, pady=(0, 10))

        # ---------- Controls ----------
        controls = tk.Frame(right, bg=self.panel)
        controls.pack(fill="x", padx=12, pady=12)

        self.listen_btn = tk.Button(
            controls, text="🎤 Dinle", bg=self.accent, fg="#ffffff",
            activebackground=self.accent, activeforeground="#ffffff",
            font=("Segoe UI", 11, "bold"), relief="flat",
            command=self.on_listen_click
        )
        self.listen_btn.pack(fill="x", pady=(0, 8))

        tk.Checkbutton(
            controls, text="Uyandırma kelimesi: Lee",
            variable=self.wake_enabled,
            bg=self.panel, fg=self.text,
            selectcolor=self.panel,
            activebackground=self.panel, activeforeground=self.text,
            font=("Segoe UI", 10)
        ).pack(anchor="w", pady=(0, 8))

        tk.Button(
            controls, text="📌 Komutlar", bg=self.card, fg=self.text,
            activebackground=self.card, activeforeground=self.text,
            font=("Segoe UI", 10), relief="flat", command=self.show_help
        ).pack(fill="x", pady=(0, 8))

        tk.Button(
            controls, text="🎙️ Ses Değiştir (Ahmet/Emel)", bg=self.card, fg=self.text,
            activebackground=self.card, activeforeground=self.text,
            font=("Segoe UI", 10), relief="flat", command=self.toggle_voice
        ).pack(fill="x")

        # ---------- Notes ----------
        notes_box = tk.Frame(right, bg=self.panel)
        notes_box.pack(fill="both", expand=True, padx=12, pady=(12, 12))

        tk.Label(notes_box, text="🗒️ Notlar", fg=self.text, bg=self.panel, font=("Segoe UI", 11, "bold")).pack(anchor="w")
        self.notes_list = tk.Listbox(notes_box, bg=self.panel, fg=self.text, relief="flat", font=("Segoe UI", 10),
                                     highlightbackground=self.border, highlightthickness=1)
        self.notes_list.pack(fill="both", expand=True, pady=(8, 8))

        tk.Button(
            notes_box, text="↻ Notları Yenile", bg=self.card, fg=self.text,
            activebackground=self.card, activeforeground=self.text,
            font=("Segoe UI", 10), relief="flat", command=self.refresh_notes
        ).pack(fill="x")

        # ---------- Greet ----------
        self.add_chat("Lee", "Merhaba Beyza! Ben Lee. 'saat kaç' ya da 'not al: ...' diyebilirsin.")
        self.add_chat("Sistem", f"Neural ses aktif ✅ ({self.voice})")

        self.refresh_notes()
        self.tick_clock()

    # ----- Audio / TTS -----
    def _init_player(self):
        try:
            pygame.mixer.init()
        except Exception:
            pass

    def speak(self, text: str):
        # UI kilitlenmesin
        threading.Thread(target=self._speak_neural_thread, args=(text,), daemon=True).start()

    def _speak_neural_thread(self, text: str):
        # aynı anda iki ses binmesin
        with self._tts_lock:
            async def _run():
                fd, filename = tempfile.mkstemp(suffix=".mp3")
                os.close(fd)
                try:
                    communicate = edge_tts.Communicate(text, self.voice)
                    await communicate.save(filename)

                    pygame.mixer.music.load(filename)
                    pygame.mixer.music.play()
                    while pygame.mixer.music.get_busy():
                        time.sleep(0.05)
                finally:
                    try:
                        pygame.mixer.music.stop()
                    except Exception:
                        pass
                    try:
                        os.remove(filename)
                    except Exception:
                        pass

            try:
                asyncio.run(_run())
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(_run())
                loop.close()

    # ----- UI helpers -----
    def add_chat(self, who, msg):
        self.chat.configure(state="normal")
        ts = datetime.datetime.now().strftime("%H:%M")
        self.chat.insert("end", f"[{ts}] {who}: ", ("hdr",))
        self.chat.insert("end", msg + "\n\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def set_status(self, text):
        self.status.config(text=text)

    def tick_clock(self):
        now = datetime.datetime.now()
        self.time_lbl.config(text=now.strftime("%H:%M:%S"))
        self.date_lbl.config(text=f"{tr_day_name(now)} • {now.strftime('%d.%m.%Y')}")
        self.root.after(250, self.tick_clock)

    def refresh_notes(self):
        self.notes_list.delete(0, "end")
        for line in read_notes_last(12):
            self.notes_list.insert("end", line)

    # ----- Buttons -----
    def show_help(self):
        cmds = (
            "Örnek komutlar:\n"
            "• saat kaç\n"
            "• tarih ne\n"
            "• not al: yarın 10'da toplantı\n"
            "• notlarımı oku\n"
            "• kapat\n\n"
            "Not: Uyandırma açıksa 'Lee' demen iyi olur.\n"
            "Ama 'saat kaç' gibi net komutları Lee olmadan da çalıştırırım 🙂"
        )
        messagebox.showinfo("Komutlar", cmds)

    def toggle_voice(self):
        self.voice = VOICE_FEMALE if self.voice == VOICE_MALE else VOICE_MALE
        self.add_chat("Sistem", f"Ses değişti ✅ ({self.voice})")
        self.speak("Ses değiştirildi.")

    # ----- Listen flow -----
    def on_listen_click(self):
        if self.is_listening:
            return
        self.is_listening = True
        self.set_status("🎧 Dinliyorum... konuş, sonra dur.")
        self.listen_btn.config(text="🎧 Dinliyorum...", state="disabled")
        threading.Thread(target=self.listen_flow, daemon=True).start()

    def listen_flow(self):
        heard = stt_listen(self.recognizer, self.mic, phrase_time_limit=8)
        self.root.after(0, self.after_listen, heard)

    def after_listen(self, heard):
        self.is_listening = False
        self.listen_btn.config(text="🎤 Dinle", state="normal")

        if not heard:
            self.set_status("Anlayamadım. Tekrar dene.")
            self.add_chat("Lee", "Anlayamadım. Tekrar söyler misin?")
            self.speak("Anlayamadım. Tekrar söyler misin?")
            return

        self.set_status("Hazır.")
        self.add_chat("Sen", heard)

        if wake_missing(heard, self.wake_enabled.get()) and not contains_command(heard):
            self.add_chat("Lee", "Uyandırma kelimesi yok. Örn: 'Lee saat kaç' de.")
            self.speak("Uyandırma kelimesi yok. Lee saat kaç gibi söyleyebilirsin.")
            return

        cleaned = strip_wake(heard)
        status, reply = parse_intent(cleaned)

        self.add_chat("Lee", reply)
        self.speak(reply)

        if status == "__EXIT__":
            self.root.after(300, self.root.destroy)
        else:
            self.refresh_notes()


if __name__ == "__main__":
    root = tk.Tk()
    app = AssistantUI(root)
    root.mainloop()

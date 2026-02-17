import tkinter as tk
from tkinter import ttk, messagebox
import threading
import datetime
from pathlib import Path
import time
import os
import tempfile
import asyncio
import math
import random
import re

import speech_recognition as sr
import edge_tts
import pygame
import requests

# =========================
# Config
# =========================
NOTES_FILE = Path("notes.txt")

VOICE_MALE = "tr-TR-AhmetNeural"
VOICE_FEMALE = "tr-TR-EmelNeural"

TURKEY_CITIES = [
    "Adana","Adıyaman","Afyonkarahisar","Ağrı","Amasya","Ankara","Antalya","Artvin","Aydın",
    "Balıkesir","Bilecik","Bingöl","Bitlis","Bolu","Burdur","Bursa","Çanakkale","Çankırı",
    "Çorum","Denizli","Diyarbakır","Edirne","Elazığ","Erzincan","Erzurum","Eskişehir","Gaziantep",
    "Giresun","Gümüşhane","Hakkari","Hatay","Isparta","Mersin","İstanbul","İzmir","Kars","Kastamonu",
    "Kayseri","Kırklareli","Kırşehir","Kocaeli","Konya","Kütahya","Malatya","Manisa","Kahramanmaraş",
    "Mardin","Muğla","Muş","Nevşehir","Niğde","Ordu","Rize","Sakarya","Samsun","Siirt","Sinop",
    "Sivas","Tekirdağ","Tokat","Trabzon","Tunceli","Şanlıurfa","Uşak","Van","Yozgat","Zonguldak",
    "Aksaray","Bayburt","Karaman","Kırıkkale","Batman","Şırnak","Bartın","Ardahan","Iğdır","Yalova",
    "Karabük","Kilis","Osmaniye","Düzce"
]

# =========================
# Helpers
# =========================
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

def turkish_fold(s: str) -> str:
    s = normalize(s)
    return (
        s.replace("ı", "i")
         .replace("ğ", "g")
         .replace("ş", "s")
         .replace("ö", "o")
         .replace("ü", "u")
         .replace("ç", "c")
    )

def find_city_in_text(text: str) -> str | None:
    t = turkish_fold(text)
    cities_sorted = sorted(TURKEY_CITIES, key=len, reverse=True)
    for city in cities_sorted:
        if turkish_fold(city) in t:
            return city
    return None

def fetch_weather(city: str) -> str:
    city = (city or "").strip()
    if not city:
        return "Şehir bulamadım. 'İstanbul hava durumu' gibi söyleyebilirsin."

    try:
        geo = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "tr", "format": "json"},
            timeout=10
        ).json()

        results = geo.get("results") or []
        if not results:
            return f"'{city}' için konum bulamadım. Başka bir şehir dener misin?"

        lat = results[0]["latitude"]
        lon = results[0]["longitude"]
        resolved = results[0].get("name", city)

        fc = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
                "timezone": "auto"
            },
            timeout=10
        ).json()

        daily = fc.get("daily") or {}
        tmax = daily.get("temperature_2m_max") or []
        tmin = daily.get("temperature_2m_min") or []
        pop = daily.get("precipitation_probability_max") or []

        if not tmax or not tmin:
            return "Hava tahminini şu an alamadım."

        p = f"%{int(pop[0])}" if pop and pop[0] is not None else "?"
        # yüzde okunuşu daha doğal:
        p_say = p.replace("%", "yüzde ")
        return f"{resolved} için bugün: en düşük {tmin[0]} derece, en yüksek {tmax[0]} derece. Yağış olasılığı {p_say}."

    except Exception:
        return "Hava tahminini alamadım. İnternet bağlantın açık mı?"

def stt_listen(recognizer: sr.Recognizer, mic: sr.Microphone, phrase_time_limit=7) -> str | None:
    with mic as source:
        recognizer.adjust_for_ambient_noise(source, duration=0.25)
        audio = recognizer.listen(source, phrase_time_limit=phrase_time_limit)
    try:
        return recognizer.recognize_google(audio, language="tr-TR")
    except Exception:
        return None

# =========================
# TTS Clean (emoji okumasın)
# =========================
def tts_clean(text: str) -> str:
    if not text:
        return ""
    emoji_re = re.compile(
        "["
        "\U0001F300-\U0001F5FF"
        "\U0001F600-\U0001F64F"
        "\U0001F680-\U0001F6FF"
        "\U0001F700-\U0001F77F"
        "\U0001F780-\U0001F7FF"
        "\U0001F800-\U0001F8FF"
        "\U0001F900-\U0001F9FF"
        "\U0001FA00-\U0001FA6F"
        "\U0001FA70-\U0001FAFF"
        "\U00002700-\U000027BF"
        "\U00002600-\U000026FF"
        "]+",
        flags=re.UNICODE
    )
    text = emoji_re.sub("", text)

    # süs/ikon karakterleri
    for ch in ["•", "✅", "✨", "🤖", "☕", "💜", "😄", "😊", "😅"]:
        text = text.replace(ch, "")

    # fazla boşluk
    text = re.sub(r"\s+", " ", text).strip()
    return text

# =========================
# Robot Avatar (big, dark, siri-ish)
# =========================
class RobotAvatar(tk.Canvas):
    """
    Big robot in center.
    - eyes follow mouse
    - listening glow
    - speaking halo pulse + mouth animation
    """
    def __init__(self, parent, size=280,
                 bg="#070B14",
                 head="#0B1224",
                 head_border="#1F2A44",
                 eye_white="#E6F0FF",
                 pupil="#0B1224",
                 glow_listen="#22C55E",
                 glow_speak="#60A5FA",
                 neon="#7C3AED"):
        super().__init__(parent, width=size, height=size, bg=bg, highlightthickness=0)
        self.size = size
        self.bg = bg
        self.head = head
        self.head_border = head_border
        self.eye_white = eye_white
        self.pupil = pupil
        self.glow_listen = glow_listen
        self.glow_speak = glow_speak
        self.neon = neon

        self.is_listening = False
        self.is_speaking = False

        self._mouth_phase = 0.0
        self._halo_phase = 0.0
        self._anim_job = None
        self._blink_job = None

        self._draw()
        self._center_pupils()
        self._schedule_blink()
        self._start_anim_loop()

    def _draw(self):
        s = self.size
        cx, cy = s/2, s/2

        pad = 14
        self.halo = self.create_oval(pad, pad, s-pad, s-pad, outline="", width=7)

        head_pad = 34
        self.head_oval = self.create_oval(
            head_pad, head_pad, s-head_pad, s-head_pad,
            fill=self.head, outline=self.head_border, width=3
        )

        # antenna
        self.create_line(cx, head_pad-4, cx, head_pad-24, fill="#94A3B8", width=4)
        self.create_oval(cx-7, head_pad-38, cx+7, head_pad-22, fill=self.neon, outline="")

        # face plate
        plate_pad = 60
        self.create_oval(
            plate_pad, plate_pad, s-plate_pad, s-plate_pad,
            fill="#0F1B36", outline="#1F2A44", width=2
        )

        self.eye_r = 28
        self.pupil_r = 10

        self.left_eye_center = (cx - 52, cy - 18)
        self.right_eye_center = (cx + 52, cy - 18)

        self.left_eye = self.create_oval(*self._bbox(self.left_eye_center, self.eye_r), fill=self.eye_white, outline="")
        self.right_eye = self.create_oval(*self._bbox(self.right_eye_center, self.eye_r), fill=self.eye_white, outline="")

        self.left_pupil = self.create_oval(*self._bbox(self.left_eye_center, self.pupil_r), fill=self.pupil, outline="")
        self.right_pupil = self.create_oval(*self._bbox(self.right_eye_center, self.pupil_r), fill=self.pupil, outline="")

        # mouth
        self.mouth_y = cy + 64
        self.mouth = self.create_line(cx-42, self.mouth_y, cx+42, self.mouth_y,
                                      fill="#E2E8F0", width=7, capstyle="round")

        # side lights
        self.create_oval(cx-98, cy+38, cx-80, cy+56, fill="#22C55E", outline="")
        self.create_oval(cx+80, cy+38, cx+98, cy+56, fill="#60A5FA", outline="")

    def _bbox(self, center, r):
        x, y = center
        return (x-r, y-r, x+r, y+r)

    def set_listening(self, v: bool):
        self.is_listening = v

    def set_speaking(self, v: bool):
        self.is_speaking = v

    def follow_target(self, tx: float, ty: float):
        self._move_pupil(self.left_pupil, self.left_eye_center, (tx, ty))
        self._move_pupil(self.right_pupil, self.right_eye_center, (tx, ty))

    def _center_pupils(self):
        self.follow_target(*self.left_eye_center)

    def _move_pupil(self, pupil_id, eye_center, target):
        ex, ey = eye_center
        tx, ty = target
        dx = tx - ex
        dy = ty - ey
        dist = math.hypot(dx, dy) + 1e-6

        max_move = self.eye_r - self.pupil_r - 6
        scale = min(max_move / dist, 1.0)

        px = ex + dx * scale
        py = ey + dy * scale
        self.coords(pupil_id, *self._bbox((px, py), self.pupil_r))

    # blink
    def _schedule_blink(self):
        delay = random.randint(2400, 6200)
        self._blink_job = self.after(delay, self._blink)

    def _blink(self):
        def squish(step):
            k = 1 - (step/6)
            if step <= 6:
                self._set_eye_squish(max(0.15, k))
                self.after(22, lambda: squish(step+1))
            else:
                def back(step2):
                    k2 = (step2/6)
                    self._set_eye_squish(max(0.15, k2))
                    if step2 < 6:
                        self.after(22, lambda: back(step2+1))
                    else:
                        self._set_eye_squish(1.0)
                        self._schedule_blink()
                back(0)
        squish(0)

    def _set_eye_squish(self, k):
        def squish_one(eye_id, pupil_id, center):
            x, y = center
            r = self.eye_r
            h = max(6, int(2*r*k))
            self.coords(eye_id, x-r, y-h/2, x+r, y+h/2)

            pr = self.pupil_r
            ph = max(4, int(2*pr*k))
            self.coords(pupil_id, x-pr, y-ph/2, x+pr, y+ph/2)

        squish_one(self.left_eye, self.left_pupil, self.left_eye_center)
        squish_one(self.right_eye, self.right_pupil, self.right_eye_center)

    # animation
    def _start_anim_loop(self):
        if self._anim_job is not None:
            return
        self._anim_job = self.after(33, self._anim_tick)

    def _anim_tick(self):
        self._anim_job = None

        self._halo_phase += 0.12
        pulse = (math.sin(self._halo_phase) + 1) / 2  # 0..1

        if self.is_speaking:
            self.itemconfig(self.halo, outline=self.glow_speak)
            self.itemconfig(self.halo, width=int(6 + 3*pulse))
        elif self.is_listening:
            self.itemconfig(self.halo, outline=self.glow_listen)
            self.itemconfig(self.halo, width=7)
        else:
            self.itemconfig(self.halo, outline="")
            self.itemconfig(self.halo, width=7)

        if self.is_speaking:
            self._mouth_phase += 0.35
            m = (math.sin(self._mouth_phase) + 1) / 2
            cx = self.size/2
            y = self.mouth_y
            amp = 10 + 12*m
            self.coords(self.mouth, cx-42, y-amp/2, cx+42, y+amp/2)
        else:
            cx = self.size/2
            y = self.mouth_y
            self.coords(self.mouth, cx-42, y, cx+42, y)

        self._start_anim_loop()

# =========================
# Main App
# =========================
class LeeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Lee • Dark Robot Assistant")
        self.root.geometry("1120x760")
        self.root.minsize(980, 660)

        # Theme
        self.bg = "#070B14"
        self.panel = "#0B1224"
        self.panel2 = "#0F1B36"
        self.border = "#1F2A44"
        self.text = "#E5E7EB"
        self.muted = "#94A3B8"
        self.accent = "#60A5FA"
        self.bubble_lee = "#0F1B36"
        self.bubble_user = "#2563EB"
        self.bubble_user_text = "#FFFFFF"

        self.root.configure(bg=self.bg)
        self._setup_ttk()

        # STT
        self.recognizer = sr.Recognizer()
        self.mic = sr.Microphone()

        # TTS
        self.voice = VOICE_MALE
        self._tts_lock = threading.Lock()
        self._init_player()

        self.is_listening = False
        self.waiting_tea_answer = False
        self.typing_widget = None

        # Top
        top = tk.Frame(root, bg=self.bg)
        top.pack(fill="x", padx=18, pady=(14, 10))

        self.time_box = tk.Frame(top, bg=self.bg)
        self.time_box.pack(side="right", anchor="e")

        self.time_lbl = tk.Label(self.time_box, text="--:--:--", fg=self.text, bg=self.bg,
                                 font=("Consolas", 18, "bold"))
        self.time_lbl.pack(anchor="e")
        self.date_lbl = tk.Label(self.time_box, text="--", fg=self.muted, bg=self.bg,
                                 font=("Segoe UI", 10))
        self.date_lbl.pack(anchor="e")

        center = tk.Frame(top, bg=self.bg)
        center.pack(side="top", fill="x")

        self.status_lbl = tk.Label(center, text="Lee aktif • Hazırım", fg=self.muted, bg=self.bg,
                                   font=("Segoe UI", 11))
        self.status_lbl.pack(anchor="center", pady=(0, 8))

        self.robot = RobotAvatar(center, size=280, bg=self.bg)
        self.robot.pack(anchor="center")

        # Middle
        mid = tk.Frame(root, bg=self.bg)
        mid.pack(fill="both", expand=True, padx=18, pady=(10, 12))

        self.chat_panel = tk.Frame(mid, bg=self.panel, highlightbackground=self.border, highlightthickness=1)
        self.chat_panel.pack(side="left", fill="both", expand=True)

        self.side_panel = tk.Frame(mid, bg=self.panel, width=320, highlightbackground=self.border, highlightthickness=1)
        self.side_panel.pack(side="right", fill="y", padx=(12, 0))
        self.side_panel.pack_propagate(False)

        self.chat_canvas = tk.Canvas(self.chat_panel, bg=self.panel, highlightthickness=0)
        self.chat_canvas.pack(side="left", fill="both", expand=True)

        self.scroll = ttk.Scrollbar(self.chat_panel, orient="vertical", command=self.chat_canvas.yview)
        self.scroll.pack(side="right", fill="y")
        self.chat_canvas.configure(yscrollcommand=self.scroll.set)

        self.chat_frame = tk.Frame(self.chat_canvas, bg=self.panel)
        self.chat_window = self.chat_canvas.create_window((0, 0), window=self.chat_frame, anchor="nw")
        self.chat_frame.bind("<Configure>", self._on_frame_configure)
        self.chat_canvas.bind("<Configure>", self._on_canvas_configure)

        # Bottom
        bottom = tk.Frame(root, bg=self.bg)
        bottom.pack(fill="x", padx=18, pady=(0, 16))

        self.entry = tk.Entry(bottom, font=("Segoe UI", 11), relief="flat",
                              bg=self.panel2, fg=self.text, insertbackground=self.text)
        self.entry.pack(side="left", fill="x", expand=True, ipady=12, padx=(0, 10))
        self.entry.bind("<Return>", lambda e: self.send_text())

        self.mic_btn = tk.Button(
            bottom, text="🎤 Dinle", bg=self.accent, fg="#081018",
            relief="flat", font=("Segoe UI", 11, "bold"),
            padx=16, pady=10,
            command=self.on_listen_click
        )
        self.mic_btn.pack(side="right")

        # Side panel
        self._build_side_panel()

        # Mouse follow
        self.root.bind("<Motion>", self._global_mouse_follow)

        # boot
        self.city_var.set("Kahramanmaraş")
        self.refresh_notes()
        self.tick_clock()

        self.add_bubble("Lee", "Merhaba Beyza! Ben Lee. İstersen 'İstanbul hava durumu' de.")
        self.add_bubble("Sistem", f"Neural ses aktif ({self.voice})")

        self.ask_tea_checkin(initial=True)

    def _setup_ttk(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TCombobox", padding=8)
        style.map("TCombobox", fieldbackground=[("readonly", "#0F1B36")])
        style.configure("TCombobox", foreground="#E5E7EB")

    def _build_side_panel(self):
        box = tk.Frame(self.side_panel, bg=self.panel)
        box.pack(fill="both", expand=True, padx=12, pady=12)

        tk.Label(box, text="Kontroller", bg=self.panel, fg=self.text,
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")

        tk.Label(box, text="Şehir", bg=self.panel, fg=self.muted, font=("Segoe UI", 9)).pack(anchor="w", pady=(12, 4))
        self.city_var = tk.StringVar(value="Kahramanmaraş")
        self.city_combo = ttk.Combobox(box, textvariable=self.city_var, values=TURKEY_CITIES, state="readonly")
        self.city_combo.pack(fill="x")

        tk.Button(box, text="Hava Tahmini", bg=self.panel2, fg=self.text, relief="flat",
                  font=("Segoe UI", 10), command=self.say_weather).pack(fill="x", pady=(10, 0))

        tk.Button(box, text="Çay Sor", bg=self.panel2, fg=self.text, relief="flat",
                  font=("Segoe UI", 10), command=lambda: self.ask_tea_checkin(initial=False)).pack(fill="x", pady=(8, 0))

        tk.Button(box, text="Ses Değiştir (Ahmet/Emel)", bg=self.panel2, fg=self.text, relief="flat",
                  font=("Segoe UI", 10), command=self.toggle_voice).pack(fill="x", pady=(8, 0))

        tk.Button(box, text="Komutlar", bg=self.panel2, fg=self.text, relief="flat",
                  font=("Segoe UI", 10), command=self.show_help).pack(fill="x", pady=(8, 0))

        tk.Label(box, text="Notlar", bg=self.panel, fg=self.muted, font=("Segoe UI", 9)).pack(anchor="w", pady=(14, 4))
        self.notes_list = tk.Listbox(
            box, bg=self.panel2, fg=self.text, relief="flat",
            highlightbackground=self.border, highlightthickness=1,
            font=("Segoe UI", 10), height=10
        )
        self.notes_list.pack(fill="x")

        tk.Button(box, text="Notları Yenile", bg=self.panel2, fg=self.text, relief="flat",
                  font=("Segoe UI", 10), command=self.refresh_notes).pack(fill="x", pady=(10, 0))

    def _global_mouse_follow(self, event):
        try:
            rx = event.x_root - self.robot.winfo_rootx()
            ry = event.y_root - self.robot.winfo_rooty()
            self.robot.follow_target(rx, ry)
        except Exception:
            pass

    # chat
    def add_bubble(self, who: str, msg: str):
        outer = tk.Frame(self.chat_frame, bg=self.panel)
        outer.pack(fill="x", pady=6, padx=12)

        is_user = (who.lower() == "sen")
        anchor = "e" if is_user else "w"

        bubble_bg = self.bubble_user if is_user else self.bubble_lee
        bubble_fg = self.bubble_user_text if is_user else self.text

        wrap = 640
        b = tk.Frame(outer, bg=self.panel)
        b.pack(anchor=anchor)

        lbl = tk.Label(
            b, text=msg, bg=bubble_bg, fg=bubble_fg,
            font=("Segoe UI", 11), justify="left", wraplength=wrap,
            padx=14, pady=12
        )
        lbl.pack(anchor=anchor)

        self.root.after(50, lambda: self.chat_canvas.yview_moveto(1.0))

    def show_typing(self):
        if self.typing_widget is not None:
            return
        self.typing_widget = tk.Label(self.chat_frame, text="Lee düşünüyor...", bg=self.panel, fg=self.muted,
                                      font=("Segoe UI", 10, "italic"))
        self.typing_widget.pack(anchor="w", padx=16, pady=(0, 8))
        self.root.after(50, lambda: self.chat_canvas.yview_moveto(1.0))

    def hide_typing(self):
        if self.typing_widget is None:
            return
        self.typing_widget.destroy()
        self.typing_widget = None

    def _on_frame_configure(self, _):
        self.chat_canvas.configure(scrollregion=self.chat_canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.chat_canvas.itemconfig(self.chat_window, width=event.width)

    # audio
    def _init_player(self):
        try:
            pygame.mixer.init()
        except Exception:
            pass

    def speak(self, text: str):
        clean = tts_clean(text)
        if not clean:
            return

        self.robot.set_speaking(True)

        def done_off():
            self.robot.set_speaking(False)

        threading.Thread(target=self._speak_neural_thread, args=(clean, done_off), daemon=True).start()

    def _speak_neural_thread(self, text: str, on_done):
        with self._tts_lock:
            async def _run():
                fd, filename = tempfile.mkstemp(suffix=".mp3")
                os.close(fd)
                try:
                    await edge_tts.Communicate(text, self.voice).save(filename)
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

        try:
            self.root.after(0, on_done)
        except Exception:
            pass

    # clock / notes
    def tick_clock(self):
        now = datetime.datetime.now()
        self.time_lbl.config(text=now.strftime("%H:%M:%S"))
        self.date_lbl.config(text=f"{tr_day_name(now)} • {now.strftime('%d.%m.%Y')}")
        self.root.after(250, self.tick_clock)

    def refresh_notes(self):
        self.notes_list.delete(0, "end")
        for line in read_notes_last(10):
            self.notes_list.insert("end", line)

    # actions
    def show_help(self):
        messagebox.showinfo(
            "Komutlar",
            "• saat kaç\n"
            "• tarih ne\n"
            "• İstanbul hava durumu / Ankara hava tahmini\n"
            "• not al: ...\n"
            "• notlar\n"
            "• kapat"
        )

    def toggle_voice(self):
        self.voice = VOICE_FEMALE if self.voice == VOICE_MALE else VOICE_MALE
        self.add_bubble("Sistem", f"Ses değişti ({self.voice})")
        self.speak("Ses değiştirildi.")

    def say_weather(self):
        city = self.city_var.get()
        self.add_bubble("Sen", f"{city} hava durumu")
        self.show_typing()

        def run():
            msg = fetch_weather(city)
            self.root.after(0, lambda: (self.hide_typing(), self.add_bubble("Lee", msg), self.speak(msg)))

        threading.Thread(target=run, daemon=True).start()

    def ask_tea_checkin(self, initial=False):
        self.waiting_tea_answer = True
        msg = "Beyza, çay içtin mi?" if initial else "Çay molası verdin mi Beyza?"
        self.add_bubble("Lee", msg + " ☕")
        self.speak(msg)
        self.root.after(2 * 60 * 60 * 1000, self.ask_tea_checkin)

    # input / mic
    def send_text(self):
        txt = self.entry.get().strip()
        if not txt:
            return
        self.entry.delete(0, "end")
        self.handle_text(txt)

    def on_listen_click(self):
        if self.is_listening:
            return
        self.is_listening = True
        self.robot.set_listening(True)
        self.status_lbl.config(text="Dinliyorum...")
        self.mic_btn.config(text="Dinliyorum...", state="disabled")

        threading.Thread(target=self._listen_flow, daemon=True).start()

    def _listen_flow(self):
        heard = stt_listen(self.recognizer, self.mic, phrase_time_limit=7)
        self.root.after(0, self._after_listen, heard)

    def _after_listen(self, heard):
        self.is_listening = False
        self.robot.set_listening(False)
        self.status_lbl.config(text="Lee aktif • Hazırım")
        self.mic_btn.config(text="🎤 Dinle", state="normal")

        if not heard:
            self.add_bubble("Lee", "Anlayamadım. Tekrar söyler misin? 😅")
            self.speak("Anlayamadım. Tekrar söyler misin?")
            return

        self.handle_text(heard)

    # core logic
    def handle_text(self, text: str):
        self.add_bubble("Sen", text)
        t = normalize(text)

        # tea answer mode
        if self.waiting_tea_answer:
            yes_words = ["evet", "ictim", "içtim", "içiyorum", "iciyorum", "içmişim", "icmisim"]
            no_words = ["hayir", "hayır", "icmedim", "içmedim", "icmiyorum", "içmiyorum", "yok", "daha icmedim", "daha içmedim"]

            if any(w in t for w in yes_words):
                self.waiting_tea_answer = False
                msg = "Afiyet olsun Beyza!"
                self.add_bubble("Lee", msg + " ☕😊")
                self.speak(msg)
                return

            if any(w in t for w in no_words):
                self.waiting_tea_answer = False
                msg = "Ben sana çay getireyim. Şaka! Ama bir mola iyi gelir."
                self.add_bubble("Lee", msg + " ☕😄")
                self.speak(msg)
                return

            msg = "Tam anlayamadım. 'Evet içtim' ya da 'Hayır içmedim' diyebilirsin."
            self.add_bubble("Lee", msg + " 😅")
            self.speak(msg)
            return

        # weather (auto city detect)
        if "hava" in t:
            found = find_city_in_text(text)
            if found:
                self.city_var.set(found)

            self.show_typing()

            def run():
                msg = fetch_weather(self.city_var.get())
                self.root.after(0, lambda: (self.hide_typing(), self.add_bubble("Lee", msg), self.speak(msg)))

            threading.Thread(target=run, daemon=True).start()
            return

        # time
        if "saat" in t:
            now = datetime.datetime.now()
            msg = f"Şu an saat {now.strftime('%H:%M:%S')}."
            self.add_bubble("Lee", msg)
            self.speak(msg)
            return

        # date
        if "tarih" in t or "bugün günlerden" in t or t == "bugün":
            now = datetime.datetime.now()
            msg = f"Bugün {tr_day_name(now)}, {now.strftime('%d.%m.%Y')}."
            self.add_bubble("Lee", msg)
            self.speak(msg)
            return

        # notes
        if "not al" in t:
            note = text
            if ":" in text:
                note = text.split(":", 1)[1].strip()
            else:
                note = text.lower().split("not al", 1)[-1].strip(" :")

            if not note:
                msg = "Not için 'Not al: ...' şeklinde yazabilirsin."
            else:
                save_note(note)
                self.refresh_notes()
                msg = f"Not aldım: {note}"

            self.add_bubble("Lee", msg)
            self.speak(msg)
            return

        if "notlar" in t:
            lines = read_notes_last(6)
            msg = "Son notların:\n" + ("\n".join(lines) if lines else "Henüz not yok.")
            self.add_bubble("Lee", msg)
            self.speak("Notlarını okudum.")
            return

        # exit
        if t in ["kapat", "çık", "bitir", "exit", "quit"]:
            msg = "Tamam, görüşürüz!"
            self.add_bubble("Lee", msg + " 🤖💜")
            self.speak(msg)
            self.root.after(450, self.root.destroy)
            return

        # help
        if "yardım" in t:
            self.show_help()
            self.speak("Komutları ekrana getirdim.")
            return

        # fallback
        msg = "Bunu tam anlayamadım. İstersen 'yardım' yaz."
        self.add_bubble("Lee", msg + " 😅")
        self.speak(msg)

if __name__ == "__main__":
    root = tk.Tk()
    app = LeeApp(root)
    root.mainloop()

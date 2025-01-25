import os
import ctypes
from ctypes import wintypes, Structure, byref, c_int, c_float, c_char, c_byte
import pymem
import threading
import math
import time
import keyboard
import customtkinter as ctk
from pymem.exception import MemoryReadError
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
from PyQt5.QtCore import Qt, QTimer
import sys
import struct
from dataclasses import dataclass

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("green")

OFFSETS = {
    'player_object': 0x18AC00,
    'entity_list': 0x18AC04,
    'player_count': 0x18AC0C,
    'health': 0xEC,
    'armor': 0xF0,
    'name': 0x205,
    'coords': [0x4, 0x8, 0xC],
    'view_angle_x': 0x34,
    'view_angle_y': 0x38,
    'team': 0x30C,
    'gamemode': 0x18ABF8,
}
TEAM_GAMEMODES = {7, 20, 21}

@dataclass(slots=True)
class Vec3:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0
    def __post_init__(self):
        self.x = round(self.x, 3)
        self.y = round(self.y, 3)
        self.z = round(self.z, 3)

class Vec3C(Structure):
    _fields_ = [("x", c_float), ("y", c_float), ("z", c_float)]

class Entity(Structure):
    _fields_ = [
        ("pad1", c_byte * 4),
        ("pos", Vec3C),
        ("pad2", c_byte * 220),
        ("health", c_int),
        ("pad3", c_byte * 277),
        ("name", c_char * 80),
        ("pad4", c_byte * 183),
        ("team", c_int)
    ]

def qBase(pm):
    for module in pm.list_modules():
        if "ac_client.exe" in module.name.lower():
            return module.lpBaseOfDll
    raise RuntimeError("Module ac_client.exe not found")

def qLocal(pm, base):
    try:
        return pm.read_uint(base + OFFSETS['player_object'])
    except MemoryReadError:
        return None

def qCount(pm, base):
    try:
        return pm.read_int(base + OFFSETS['player_count'])
    except MemoryReadError:
        return 0

def qEntList(pm, base, count):
    try:
        la = pm.read_uint(base + OFFSETS['entity_list'])
        raw = pm.read_bytes(la, count * 4)
        return list(struct.unpack(f"{count}I", raw))
    except MemoryReadError:
        return []

def qReadVec(pm, address):
    try:
        x = pm.read_float(address + OFFSETS['coords'][0])
        y = pm.read_float(address + OFFSETS['coords'][1])
        z = pm.read_float(address + OFFSETS['coords'][2])
        return Vec3(x, y, z)
    except MemoryReadError:
        return Vec3()

def qDist(a: Vec3, b: Vec3):
    return math.sqrt((b.x - a.x)**2 + (b.y - a.y)**2 + (b.z - a.z)**2)

def qW2S(matrix, pos: Vec3, w, h):
    cx = pos.x * matrix[0] + pos.y * matrix[4] + pos.z * matrix[8] + matrix[12]
    cy = pos.x * matrix[1] + pos.y * matrix[5] + pos.z * matrix[9] + matrix[13]
    cw = pos.x * matrix[3] + pos.y * matrix[7] + pos.z * matrix[11] + matrix[15]
    if cw < 0.2:
        raise ValueError("Entity behind camera or too close.")
    nx = cx / cw
    ny = cy / cw
    return (int((nx+1.0)*0.5*w), int((1.0-ny)*0.5*h))

fov_value = 15
fov_color = "red"
smoothing_value = 1
aim_key = "ctrl"
aimbot_enabled = False
esp_enabled = False
key_held = False
aiming_height = "Head"
last_toggle_time = 0

def aT1():
    global key_held
    while True:
        if aimbot_enabled and keyboard.is_pressed(aim_key):
            key_held = True
        else:
            key_held = False
        time.sleep(0.02)

def aT2():
    pm = None
    base = None
    while True:
        if not aimbot_enabled:
            time.sleep(0.05)
            continue
        if pm is None or base is None:
            try:
                pm = pymem.Pymem("ac_client.exe")
                base = qBase(pm)
                print("[Aimbot] Attached or re-attached to ac_client.exe.")
            except Exception as ex:
                print(f"[Aimbot] Could not attach: {ex}")
                pm = None
                base = None
                time.sleep(1)
                continue
        if key_held:
            try:
                pl = qLocal(pm, base)
                if not pl:
                    time.sleep(0.05)
                    continue
                c = qReadVec(pm, pl)
                lNb(pm, base, pl, c)
            except Exception as e:
                print(f"[Aimbot] Error: {e}")
                pm = None
                base = None
                time.sleep(1)
        time.sleep(0.01)

def lNb(pm, base, po, pc: Vec3):
    try:
        gm = pm.read_int(base + OFFSETS['gamemode'])
        mt = pm.read_int(po + OFFSETS['team'])
        co = qCount(pm, base)
        if co < 2:
            return
        ents = qEntList(pm, base, co)
        if not ents:
            return
        oy = pm.read_float(po + OFFSETS['view_angle_x'])
        op = pm.read_float(po + OFFSETS['view_angle_y'])
        cands = []
        for i in range(1, co):
            ad = ents[i]
            if ad == 0:
                continue
            hp = pm.read_int(ad + OFFSETS['health'])
            if hp <= 0:
                continue
            et = pm.read_int(ad + OFFSETS['team'])
            if gm in TEAM_GAMEMODES and et == mt:
                continue
            cc = qReadVec(pm, ad)
            dx = cc.x - pc.x
            dy = cc.y - pc.y
            yw = math.degrees(math.atan2(dy, dx)) + 90.0
            yw = yw % 360
            df = nYd(yw - oy)
            if abs(df) <= fov_value:
                dist = qDist(pc, cc)
                cands.append((dist, yw, cc))
        if not cands:
            return
        cands.sort(key=lambda x: x[0])
        _, by, bc = cands[0]
        dz = bc.z - pc.z
        if aiming_height == "Torso":
            dz -= 1.0
        hp = math.sqrt((bc.x - pc.x)**2 + (bc.y - pc.y)**2)
        bp = math.degrees(math.atan2(dz+0.15, hp))
        f = (100.0 - smoothing_value)/100.0
        ny = oy + (by - oy)*f
        np = op + (bp - op)*f
        pm.write_float(po + OFFSETS['view_angle_x'], ny)
        pm.write_float(po + OFFSETS['view_angle_y'], np)
    except Exception as e:
        print(f"[Aimbot] lock_on_to_nearest_enemy error: {e}")

def nYd(d):
    return (d+180)%360 - 180

class LQA(QWidget):
    def __init__(self, rect):
        super().__init__()
        f = (Qt.FramelessWindowHint|Qt.WindowStaysOnTopHint|Qt.Tool)
        if hasattr(Qt, "WindowTransparentForInput"):
            f |= Qt.WindowTransparentForInput
        self.setWindowFlags(f)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setGeometry(*rect)
        self.pm = None
        self.base = None
        try:
            self.pm = pymem.Pymem("ac_client.exe")
            self.base = qBase(self.pm)
            print("[Overlay] Attached to ac_client.exe.")
        except Exception as e:
            print(f"[Overlay] Could not attach: {e}")
        self.timer = QTimer()
        self.timer.timeout.connect(self.lUp)
        self.timer.start(16)

    def closeEvent(self, event):
        self.timer.stop()
        if self.pm:
            try:
                self.pm.close()
            except:
                pass
            self.pm = None
            self.base = None
        event.accept()

    def lUp(self):
        self.update()

    def paintEvent(self, event):
        if not self.pm or not self.base:
            return
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing)
            if aimbot_enabled and fov_value <= 30:
                self.tFo(p)
            if esp_enabled:
                self.eSp(p)
        except Exception as ex:
            print(f"[Overlay] paintEvent error: {ex}")

    def tFo(self, painter):
        r = int(fov_value*16)
        cx = self.width()//2
        cy = self.height()//2
        pen = QPen(QColor(fov_color), 2)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(cx-r, cy-r, r*2, r*2)

    def eSp(self, painter):
        try:
            c = qCount(self.pm, self.base)
            if c <= 1:
                painter.setPen(QColor("white"))
                painter.setFont(QFont("Arial", 14))
                painter.drawText(10, 30, "No other players.")
                return
            la = qLocal(self.pm, self.base)
            if not la:
                return
            mt = self.pm.read_int(la + OFFSETS['team'])
            gm = self.pm.read_int(self.base + OFFSETS['gamemode'])
            mr = self.pm.read_bytes(self.base + 0x17DFD0, 64)
            ma = struct.unpack("16f", mr)
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Arial", 14))
            painter.drawText(210, 20, "IrohBot")
            painter.drawText(210, 40, f"Players: {c-1}")
            eL = qEntList(self.pm, self.base, c)
            if len(eL) > 1:
                eL = eL[1:]
            sw = self.width()
            sh = self.height()
            pd = sh//16
            for ad in eL:
                if ad == 0:
                    continue
                buf = self.pm.read_bytes(ad, ctypes.sizeof(Entity))
                en = Entity.from_buffer_copy(buf)
                if en.health <= 0:
                    continue
                if gm in TEAM_GAMEMODES:
                    color = QColor("blue") if en.team == mt else QColor("red")
                else:
                    color = QColor("red")
                try:
                    h2 = qW2S(ma, Vec3(en.pos.x, en.pos.y, en.pos.z+0.5), sw, sh)
                    f2 = qW2S(ma, Vec3(en.pos.x, en.pos.y, en.pos.z-4.5), sw, sh)
                except ValueError:
                    continue
                hh = f2[1] - h2[1]
                ww = max(int(hh//3), 2)
                xx = h2[0] - (ww//2)
                yy = h2[1]
                painter.setBrush(QColor(128,128,128,128))
                painter.setPen(Qt.NoPen)
                painter.drawRect(xx, yy, ww, hh)
                pe = QPen(color)
                pe.setWidth(2)
                painter.setPen(pe)
                painter.setBrush(Qt.NoBrush)
                painter.drawRect(xx, yy, ww, hh)
                rt = max(en.health/100.0, 0.0)
                hhh = int(hh*rt)
                painter.setBrush(QColor("green"))
                painter.setPen(Qt.NoPen)
                painter.drawRect(xx-6, yy+(hh-hhh), 4, hhh)
                try:
                    ns = en.name.decode("utf-8").strip("\x00")
                except:
                    ns = "??"
                painter.setPen(QColor("white"))
                painter.setFont(QFont("Arial",12))
                painter.drawText(xx, yy-10, ns)
                painter.drawText(xx+ww+5, yy+hh//2, f"HP: {en.health}")
                painter.setPen(QPen(QColor("orange"),1))
                painter.drawLine(sw//2, sh-pd, f2[0], f2[1])
        except Exception as ex:
            print(f"[Overlay] draw_esp error: {ex}")

overlay_app = None
overlay_instance = None
overlay_running = False

def gWin():
    hwnd = ctypes.windll.user32.FindWindowW(None, "AssaultCube")
    if not hwnd:
        raise ValueError("Window 'AssaultCube' not found.")
    re = wintypes.RECT()
    ctypes.windll.user32.GetClientRect(hwnd, byref(re))
    w = re.right - re.left
    h = re.bottom - re.top
    tl = wintypes.POINT(0,0)
    ctypes.windll.user32.ClientToScreen(hwnd, byref(tl))
    return (tl.x, tl.y, w, h)

def tOg():
    global overlay_running, last_toggle_time
    n = time.time()
    if (n - last_toggle_time) < 0.3:
        print("[Toggle] Ignoring rapid toggle to prevent crash.")
        return
    last_toggle_time = n
    if aimbot_enabled or esp_enabled:
        RnC()
    else:
        sTOp()

def SpnT():
    global overlay_app, overlay_instance, overlay_running
    overlay_app = QApplication(sys.argv)
    try:
        rect = gWin()
    except ValueError as e:
        print(f"[Overlay] {e}, using full screen fallback.")
        sw = ctypes.windll.user32.GetSystemMetrics(0)
        sh = ctypes.windll.user32.GetSystemMetrics(1)
        rect = (0, 0, sw, sh)
    overlay_instance = LQA(rect)
    overlay_instance.show()
    overlay_app.exec_()
    overlay_running = False
    overlay_instance = None
    overlay_app = None

def RnC():
    global overlay_running
    if not overlay_running:
        overlay_running = True
        threading.Thread(target=SpnT, daemon=True).start()

def sTOp():
    global overlay_running, overlay_instance, overlay_app
    if overlay_running and overlay_instance:
        overlay_instance.close()
    if overlay_app:
        overlay_app.quit()
    overlay_running = False

try:
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("IrohBotAssaultCube")
except Exception as e:
    print(f"Could not set AppUserModelID: {e}")

root = ctk.CTk()
root.title("IrohBot: AssaultCube")
root.geometry("300x400")
root.configure(bg="#5b8c56")
root.attributes("-topmost", True)

icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icon.ico")
try:
    root.iconbitmap(icon_path)
except Exception as e:
    print(f"Could not set icon: {e}")

root.withdraw()

font_style = ("Helvetica", 12, "bold")

def aTg():
    global aimbot_enabled
    aimbot_enabled = bool(aimbot_var.get())
    tOg()

aimbot_var = ctk.BooleanVar(value=False)
aimbot_checkbox = ctk.CTkCheckBox(root, text="Enable Aimbot", variable=aimbot_var, font=font_style, command=aTg)
aimbot_checkbox.pack(pady=10)

def eTg():
    global esp_enabled
    esp_enabled = bool(esp_var.get())
    tOg()

esp_var = ctk.BooleanVar(value=False)
esp_checkbox = ctk.CTkCheckBox(root, text="Enable ESP", variable=esp_var, font=font_style, command=eTg)
esp_checkbox.pack(pady=10)

h_var = ctk.StringVar(value="Head")
def hCh(c):
    global aiming_height
    aiming_height = c

height_dropdown = ctk.CTkOptionMenu(root, values=["Head","Torso"], variable=h_var, command=hCh)
height_dropdown.pack(pady=10)

ak_var = ctk.StringVar(value=aim_key)
def akCh(n):
    global aim_key
    aim_key = n

aimkey_dropdown = ctk.CTkOptionMenu(root, values=["ctrl","alt","shift","`","z","x","c","v","b"], variable=ak_var, command=akCh)
aimkey_dropdown.pack(pady=10)

def fvCh(v):
    global fov_value
    fov_value = float(v)
    fov_label.configure(text=f"FOV: {int(fov_value)}")

fov_slider = ctk.CTkSlider(root, from_=1, to=180, number_of_steps=179, command=fvCh)
fov_slider.set(fov_value)
fov_slider.pack(pady=10)

fov_label = ctk.CTkLabel(root, text=f"FOV: {fov_value}", font=font_style)
fov_label.pack(pady=5)

def colCh(nc):
    global fov_color
    fov_color = nc

c_var = ctk.StringVar(value=fov_color)
color_dropdown = ctk.CTkOptionMenu(root, values=["red","orange","yellow","green","blue","purple"], variable=c_var, command=colCh)
color_dropdown.pack(pady=10)

def smCh(v):
    global smoothing_value
    smoothing_value = float(v)
    smoothing_label.configure(text=f"Smoothing: {int(smoothing_value)}")

smoothing_slider = ctk.CTkSlider(root, from_=1, to=100, number_of_steps=99, command=smCh)
smoothing_slider.set(smoothing_value)
smoothing_slider.pack(pady=10)

smoothing_label = ctk.CTkLabel(root, text=f"Smoothing: {smoothing_value}", font=font_style)
smoothing_label.pack(pady=5)

threading.Thread(target=aT1, daemon=True).start()
threading.Thread(target=aT2, daemon=True).start()

def cC():
    sTOp()
    root.quit()
    root.destroy()

root.protocol("WM_DELETE_WINDOW", cC)

ui_visible = False
def tUI():
    global ui_visible
    ui_visible = not ui_visible
    if ui_visible:
        root.deiconify()
        root.lift()
        root.focus_force()
    else:
        root.withdraw()

keyboard.add_hotkey("insert", tUI)
root.mainloop()

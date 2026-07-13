# new_fullcontrol.py
import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import struct
import telnetlib
import socket
import time
import json
import os
from datetime import datetime

# ===============================
# Shared Constants & Config
# ===============================
SETTINGS_FILE = "settings.json"
LOG_FILE = "laser_log.txt"
STATUS_ADDR = 0x5D
CONFIG_ADDR = 0x7F
MAX_LASERS = 5

LASERS = {
    "laser1": {"ip": "192.168.103.105", "port": 25, "mac": "00:80:A3:6B:E4:1D"},
    "laser2": {"ip": "192.168.103.103", "port": 23, "mac": "00:80:A3:6B:E4:65"},
}

# GFT1004 delay generator TRIG modes (see NUT007 manual, section 4.2.3)
TRIGGER_MODES = ["INH", "IN1", "IN2", "EXT", "LSS", "F1", "F2", "F3", "SS1", "SS2"]

# Full 256-entry CRC16 lookup table
CRC16_LOOKUP_TABLE = [
    0x0000, 0xC0C1, 0xC181, 0x0140, 0xC301, 0x03C0, 0x0280, 0xC241,
    0xC601, 0x06C0, 0x0780, 0xC741, 0x0500, 0xC5C1, 0xC481, 0x0440,
    0xCC01, 0x0CC0, 0x0D80, 0xCD41, 0x0F00, 0xCFC1, 0xCE81, 0x0E40,
    0x0A00, 0xCAC1, 0xCB81, 0x0B40, 0xC901, 0x09C0, 0x0880, 0xC841,
    0xD801, 0x18C0, 0x1980, 0xD941, 0x1B00, 0xDBC1, 0xDA81, 0x1A40,
    0x1E00, 0xDEC1, 0xDF81, 0x1F40, 0xDD01, 0x1DC0, 0x1C80, 0xDC41,
    0x1400, 0xD4C1, 0xD581, 0x1540, 0xD701, 0x17C0, 0x1680, 0xD641,
    0xD201, 0x12C0, 0x1380, 0xD341, 0x1100, 0xD1C1, 0xD081, 0x1040,
    0xF001, 0x30C0, 0x3180, 0xF141, 0x3300, 0xF3C1, 0xF281, 0x3240,
    0x3600, 0xF6C1, 0xF781, 0x3740, 0xF501, 0x35C0, 0x3480, 0xF441,
    0x3C00, 0xFCC1, 0xFD81, 0x3D40, 0xFF01, 0x3FC0, 0x3E80, 0xFE41,
    0xFA01, 0x3AC0, 0x3B80, 0xFB41, 0x3900, 0xF9C1, 0xF881, 0x3840,
    0x2800, 0xE8C1, 0xE981, 0x2940, 0xEB01, 0x2BC0, 0x2A80, 0xEA41,
    0xEE01, 0x2EC0, 0x2F80, 0xEF41, 0x2D00, 0xEDC1, 0xEC81, 0x2C40,
    0xE401, 0x24C0, 0x2580, 0xE541, 0x2700, 0xE7C1, 0xE681, 0x2640,
    0x2200, 0xE2C1, 0xE381, 0x2340, 0xE101, 0x21C0, 0x2080, 0xE041,
    0xA001, 0x60C0, 0x6180, 0xA141, 0x6300, 0xA3C1, 0xA281, 0x6240,
    0x6600, 0xA6C1, 0xA781, 0x6740, 0xA501, 0x65C0, 0x6480, 0xA441,
    0x6C00, 0xACC1, 0xAD81, 0x6D40, 0xAF01, 0x6FC0, 0x6E80, 0xAE41,
    0xAA01, 0x6AC0, 0x6B80, 0xAB41, 0x6900, 0xA9C1, 0xA881, 0x6840,
    0x7800, 0xB8C1, 0xB981, 0x7940, 0xBB01, 0x7BC0, 0x7A80, 0xBA41,
    0xBE01, 0x7EC0, 0x7F80, 0xBF41, 0x7D00, 0xBDC1, 0xBC81, 0x7C40,
    0xB401, 0x74C0, 0x7580, 0xB541, 0x7700, 0xB7C1, 0xB681, 0x7640,
    0x7200, 0xB2C1, 0xB381, 0x7340, 0xB101, 0x71C0, 0x7080, 0xB041,
    0x5000, 0x90C1, 0x9181, 0x5140, 0x9301, 0x53C0, 0x5280, 0x9241,
    0x9601, 0x56C0, 0x5780, 0x9741, 0x5500, 0x95C1, 0x9481, 0x5440,
    0x9C01, 0x5CC0, 0x5D80, 0x9D41, 0x5F00, 0x9FC1, 0x9E81, 0x5E40,
    0x5A00, 0x9AC1, 0x9B81, 0x5B40, 0x9901, 0x59C0, 0x5880, 0x9841,
    0x8801, 0x48C0, 0x4980, 0x8941, 0x4B00, 0x8BC1, 0x8A81, 0x4A40,
    0x4E00, 0x8EC1, 0x8F81, 0x4F40, 0x8D01, 0x4DC0, 0x4C80, 0x8C41,
    0x4400, 0x84C1, 0x8581, 0x4540, 0x8701, 0x47C0, 0x4680, 0x8641,
    0x8201, 0x42C0, 0x4380, 0x8341, 0x4100, 0x81C1, 0x8081, 0x4040,
]


# ===============================
# Utilities
# ===============================
def log(message: str, console=None):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_msg = f"{timestamp} {message}\n"
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(full_msg)
    except Exception:
        pass
    if console:
        console.insert(tk.END, full_msg)
        console.see(tk.END)


def crc16(data: bytearray) -> int:
    crc = 0xFFFF
    for byte in data:
        byte = int(byte) & 0xFF
        crc = (crc >> 8) ^ CRC16_LOOKUP_TABLE[(crc ^ byte) & 0xFF]
    return crc & 0xFFFF


def hex_str(data: bytes):
    return ' '.join(f'{b:02X}' for b in data)


# ===============================
# ASCII Laser (Telnet / Virion) Helpers  [UNTOUCHED]
# ===============================
def generate_password(mac: str) -> str:
    return f"VR{''.join(mac.split(':')[-3:]).upper()}"


def send_ascii_cmd(tn: telnetlib.Telnet, cmd: str, console=None, wait=0.2) -> str:
    try:
        tn.write((cmd + "\r").encode("ascii"))
        time.sleep(wait)
        resp = tn.read_very_eager().decode("ascii", errors="ignore").strip()
    except Exception as e:
        resp = f"ERROR: {e}"
    log(f">> {cmd}", console)
    log(f"<< {resp}", console)
    return resp


def boot_ascii_laser(name, info, sessions, console):
    try:
        tn = telnetlib.Telnet(info["ip"], info["port"], timeout=5)
        pwd = generate_password(info["mac"])
        resp = send_ascii_cmd(tn, f"$LOGIN {pwd}", console)
        if "ERROR" in resp.upper() or resp.strip() == "":
            log(f"{name} login failed: {resp}", console)
            try:
                tn.close()
            except:
                pass
            return
        sessions[name] = tn
        log(f"{name} connected successfully", console)
    except Exception as e:
        log(f"Connection error for {name}: {e}", console)


def stop_ascii(tn, console):
    if not tn:
        return
    try:
        send_ascii_cmd(tn, "$STOP", console)
        send_ascii_cmd(tn, "$LOGOUT", console)
        tn.close()
    except Exception as e:
        log(f"Error stopping ASCII laser: {e}", console)


def configure_ascii_laser(name, tn, settings, console):
    if not tn:
        log(f"{name} not connected", console)
        return
    cmds = [
        f"$TRIG {settings.get('trig_mode','II')}",
        f"$DFREQ {settings.get('frequency','10')}",
        f"$DCURR {settings.get('current','20')}",
        "$QSDELAY 179"
    ]
    for cmd in cmds:
        send_ascii_cmd(tn, cmd, console)


def display_ascii_settings(name, tn, labels, console):
    if not tn:
        log(f"{name} not connected", console)
        return
    labels[name]["trig"].config(text=f"TRIG: {send_ascii_cmd(tn, '$TRIG ?', console)}")
    labels[name]["freq"].config(text=f"FREQ: {send_ascii_cmd(tn, '$DFREQ ?', console)}")
    labels[name]["curr"].config(text=f"CURR: {send_ascii_cmd(tn, '$DCURR ?', console)}")


def standby_ascii(tn, console):
    send_ascii_cmd(tn, "$STANDBY", console)


def diagnose_ascii_laser(name, tn, console, labels):
    if not tn:
        log(f"{name} not connected", console)
        return
    log(f"Running diagnostics on {name}...", console)
    for cmd in ["$TEXTS ?", "$TRIG ?", "$DFREQ ?", "$DCURR ?", "$QSDELAY ?"]:
        send_ascii_cmd(tn, cmd, console)
    labels[name]["max_curr"].config(text=f"Max Current: {send_ascii_cmd(tn, '$MAXCURR ?', console)}")
    labels[name]["max_prf"].config(text=f"Max PRF: {send_ascii_cmd(tn, '$MAXPRF ?', console)}")


# ===============================
# RS232 / CNI Laser Helpers  [Updated from cni_controller.py]
# ===============================
def send_command(ser, command_bytes):
    ser.reset_input_buffer()
    ser.write(command_bytes)
    time.sleep(0.3)
    response = ser.read(64)
    print(f"Raw response ({len(response)} bytes): {hex_str(response)}")
    return response


def send_status_command(ser, address):
    cmd = bytearray([address & 0xFF, 0x01, 0x04])
    crc = crc16(cmd)
    cmd.extend(crc.to_bytes(2, 'little'))
    return send_command(ser, cmd)


def send_gear_command(ser, addr, gear):
    if not (0 <= gear <= 6):
        raise ValueError("Gear must be between 0 and 6.")
    payload = bytearray([0x23]) + bytearray(struct.pack('<I', gear))
    gear_cmd = bytearray([addr & 0xFF, 0x05]) + payload
    gear_cmd.extend(crc16(gear_cmd).to_bytes(2, 'little'))
    return send_command(ser, gear_cmd)


def send_trigger_command(ser, addr, mode):
    if mode not in (0, 1):
        raise ValueError("Trigger mode must be 0 (internal) or 1 (external).")
    payload = bytearray([0x01]) + bytearray(struct.pack('<I', mode))
    trig_cmd = bytearray([addr & 0xFF, 0x05]) + payload
    trig_cmd.extend(crc16(trig_cmd).to_bytes(2, 'little'))
    return send_command(ser, trig_cmd)


def send_frequency_command(ser, addr, freq):
    freq_bytes = struct.pack('<f', float(freq))
    freq_cmd = bytearray([addr & 0xFF, 0x05, 0x02]) + bytearray(freq_bytes)
    freq_cmd.extend(crc16(freq_cmd).to_bytes(2, 'little'))
    return send_command(ser, freq_cmd)


def send_enable_command(ser, addr):
    payload = bytearray([0x21]) + bytearray(struct.pack('<I', 1))
    cmd = bytearray([addr & 0xFF, 0x05]) + payload
    cmd.extend(crc16(cmd).to_bytes(2, 'little'))
    return send_command(ser, cmd)


def send_disable_command(ser, addr):
    payload = bytearray([0x21]) + bytearray(struct.pack('<I', 0))
    cmd = bytearray([addr & 0xFF, 0x05]) + payload
    cmd.extend(crc16(cmd).to_bytes(2, 'little'))
    return send_command(ser, cmd)


def decode_status_response(response):
    if not response or len(response) < 32:
        return "Invalid or empty status response"

    def get_float(data, offset):
        return struct.unpack('<f', data[offset:offset + 4])[0]

    try:
        system_enable = response[3]
        fault_status = response[4]
        warmup = response[5]
        frontend_voltage = response[6]
        comm_status = response[7]
        current_set = response[8]
        current_feedback = response[9]
        power_fan = response[10]
        laser_fan = response[11]
        light_gate = struct.unpack('<I', response[12:16])[0]
        discharges = struct.unpack('<I', response[16:20])[0]
        trigger_mode = struct.unpack('<I', response[20:24])[0]
        freq = get_float(response, 24)
        temps = [get_float(response, i) for i in range(28, 28 + 4 * 6, 4)]

        prefire = [
            f"Laser Enabled: {'Yes' if system_enable else 'No'}",
            f"Comm Status: {'OK' if comm_status else 'Error'}",
            f"Warmup Complete: {'Yes' if warmup else 'No'}",
            f"Light Gate: {'Open' if light_gate else 'Closed'}",
            f"Trigger Mode: {'External' if trigger_mode else 'Internal'}",
            f"Internal Frequency: {freq:.2f} Hz",
            f"Voltage: {frontend_voltage} V",
            f"Set Current: {current_set} A",
            f"Feedback Current: {current_feedback} A",
            f"Discharges: {discharges}",
        ]
        return ("Pre-Fire Checklist:\n" + '\n'.join(prefire) +
                "\nTemperatures: " + ', '.join(f"{t:.1f}C" for t in temps))
    except Exception as e:
        return f"Error decoding status: {e}"


def scan_for_lasers():
    ports = list(serial.tools.list_ports.comports())
    connected = []
    print("Scanning for lasers...")
    for port in ports:
        try:
            ser = serial.Serial(port.device, 115200, timeout=1)
            resp = send_status_command(ser, STATUS_ADDR)
            if resp and len(resp) >= 32:
                print(f"✓ Found laser on {port.device}")
                connected.append((port.device, ser))
                if len(connected) >= MAX_LASERS:
                    break
            else:
                ser.close()
        except Exception as e:
            print(f"× Skipped {port.device}: {e}")
    return connected


# ===============================
# Delay Generator Backend  [Updated from new_delaycontrol.py]
# ===============================
class DelayGeneratorController:
    def __init__(self, ip="192.168.103.22", port=4000, timeout=2.0):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self, ip=None, port=None):
        if ip:
            self.ip = ip
        if port:
            self.port = int(port)
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.ip, self.port))
            print(f"[INFO] Connected to {self.ip}:{self.port}")
            return True
        except socket.error as e:
            messagebox.showerror("Connection Error", f"Failed to connect: {e}")
            return False

    def disconnect(self):
        if self.sock:
            self.sock.close()
            self.sock = None
            print("[INFO] Disconnected from delay generator")

    def send_command(self, command):
        if not self.sock:
            raise ConnectionError("Socket is not connected. Call connect() first.")
        full_command = command.strip() + "\n"
        self.sock.sendall(full_command.encode("ascii"))
        print(f"[TX] {full_command.strip()}")

    def query(self, command):
        self.send_command(command)
        time.sleep(0.1)
        try:
            data = self.sock.recv(1024).decode("ascii").strip()
            print(f"[RX] {data}")
            return data
        except socket.timeout:
            print("[WARN] No response (timeout)")
            return None

    def set_delay(self, channel, delay_ps):
        self.send_command(f"DELAY T{channel},{int(delay_ps)}")

    def get_delay(self, channel):
        return self.query(f"DELAY? T{channel}")

    def set_trigger(self, channel, mode):
        self.send_command(f"TRIG T{channel},{mode}")

    def get_trigger(self, channel):
        return self.query(f"TRIG? T{channel}")

    def set_frequency(self, fn, freq_hz):
        self.send_command(f"FREQ F{fn},{int(freq_hz)}")

    def get_frequency(self, fn):
        return self.query(f"FREQ? F{fn}")


# ===============================
# Application GUI
# ===============================
class CombinedApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Laser + Delay Control")

        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)

        # Shared console
        self.console_frame = ttk.Frame(root)
        self.console_frame.pack(fill="both", expand=False)
        ttk.Label(self.console_frame, text="Console log:").pack(anchor="w")
        self.console = tk.Text(self.console_frame, height=10)
        self.console.pack(fill="both", expand=True)

        # Tabs
        self.laser_tab = ttk.Frame(self.notebook)
        self.delay_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.laser_tab, text="Laser Control")
        self.notebook.add(self.delay_tab, text="Delay Generator")

        self._build_laser_tab(self.laser_tab)
        self._build_delay_tab(self.delay_tab)

    # -----------------------------------------------------------------------
    # Laser Tab  [Virion section untouched; RS232 section updated for CNI]
    # -----------------------------------------------------------------------
    def _build_laser_tab(self, parent):
        self.sessions = {name: None for name in LASERS}

        # --- ASCII / Virion Settings ---
        ascii_frame = ttk.LabelFrame(parent, text="ASCII Laser Settings")
        ascii_frame.grid(row=0, column=0, sticky="nw", padx=10, pady=5)

        ttk.Label(ascii_frame, text="Trigger Mode").grid(row=0, column=0)
        self.ascii_trig = ttk.Combobox(ascii_frame, values=["II", "EE", "IE", "EI"], width=6)
        self.ascii_trig.set("II")
        self.ascii_trig.grid(row=0, column=1)

        ttk.Label(ascii_frame, text="Frequency (Hz)").grid(row=1, column=0)
        self.ascii_freq = ttk.Entry(ascii_frame, width=10)
        self.ascii_freq.insert(0, "10.0")
        self.ascii_freq.grid(row=1, column=1)

        ttk.Label(ascii_frame, text="Current").grid(row=2, column=0)
        self.ascii_curr = ttk.Entry(ascii_frame, width=10)
        self.ascii_curr.insert(0, "20.0")
        self.ascii_curr.grid(row=2, column=1)

        ttk.Button(ascii_frame, text="Save Settings",
                   command=self._save_ascii_settings).grid(row=3, column=0, columnspan=2, pady=4)

        # --- Virion Laser Control Buttons [UNTOUCHED] ---
        virion_frame = ttk.LabelFrame(parent, text="Virion Lasers")
        virion_frame.grid(row=0, column=1, sticky="nw", padx=10, pady=5)

        self.virion_labels = {}
        for i, laser in enumerate(LASERS):
            ttk.Label(virion_frame, text=laser.upper()).grid(row=0, column=i, padx=5)
            ttk.Button(virion_frame, text="Boot",
                       command=lambda l=laser: self._boot_ascii(l)).grid(row=1, column=i, padx=3)
            ttk.Button(virion_frame, text="Config",
                       command=lambda l=laser: configure_ascii_laser(
                           l, self.sessions.get(l), self._ascii_settings(), self.console)
                       ).grid(row=2, column=i, padx=3)
            ttk.Button(virion_frame, text="Read",
                       command=lambda l=laser: display_ascii_settings(
                           l, self.sessions.get(l), self.virion_labels, self.console)
                       ).grid(row=3, column=i, padx=3)
            ttk.Button(virion_frame, text="Standby",
                       command=lambda l=laser: standby_ascii(self.sessions.get(l), self.console)
                       ).grid(row=4, column=i, padx=3)
            ttk.Button(virion_frame, text="Diagnose",
                       command=lambda l=laser: diagnose_ascii_laser(
                           l, self.sessions.get(l), self.console, self.virion_labels)
                       ).grid(row=5, column=i, padx=3)
            ttk.Button(virion_frame, text="Fire",
                       command=lambda l=laser: send_ascii_cmd(
                           self.sessions.get(l), "$FIRE", self.console)
                       ).grid(row=6, column=i, padx=3)
            ttk.Button(virion_frame, text="Stop",
                       command=lambda l=laser: stop_ascii(self.sessions.get(l), self.console)
                       ).grid(row=7, column=i, padx=3)

            self.virion_labels[laser] = {
                "max_curr": ttk.Label(virion_frame, text="Max Curr: ?"),
                "max_prf":  ttk.Label(virion_frame, text="Max PRF: ?"),
                "trig":     ttk.Label(virion_frame, text="TRIG: ?"),
                "freq":     ttk.Label(virion_frame, text="FREQ: ?"),
                "curr":     ttk.Label(virion_frame, text="CURR: ?"),
            }
            self.virion_labels[laser]["max_curr"].grid(row=8,  column=i)
            self.virion_labels[laser]["max_prf"].grid(row=9,   column=i)
            self.virion_labels[laser]["trig"].grid(row=10,     column=i)
            self.virion_labels[laser]["freq"].grid(row=11,     column=i)
            self.virion_labels[laser]["curr"].grid(row=12,     column=i)

        # --- RS232 / CNI Laser Block [Updated for cni_controller] ---
        rs_frame = ttk.LabelFrame(parent, text="RS232 Lasers (Auto-scan)")
        rs_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=5)

        self.rs232_ports = scan_for_lasers()
        self.rs232_sessions = {f"rs{i+1}": ser for i, (_, ser) in enumerate(self.rs232_ports)}
        self.rs232_entries = {}

        for i, (label, ser) in enumerate(self.rs232_sessions.items()):
            col = i
            ttk.Label(rs_frame, text=label.upper()).grid(row=0, column=col)

            gear = ttk.Entry(rs_frame, width=5)
            trig = ttk.Entry(rs_frame, width=5)
            freq = ttk.Entry(rs_frame, width=5)
            gear.insert(0, "6")
            trig.insert(0, "1")
            freq.insert(0, "10.0")
            gear.grid(row=1, column=col)
            trig.grid(row=2, column=col)
            freq.grid(row=3, column=col)

            self.rs232_entries[label] = {"gear": gear, "trig": trig, "freq": freq}

            ttk.Button(rs_frame, text="Config",
                       command=lambda s=ser, g=gear, t=trig, f=freq: (
                           send_gear_command(s, CONFIG_ADDR, int(g.get())),
                           send_trigger_command(s, CONFIG_ADDR, int(t.get())),
                           send_frequency_command(s, CONFIG_ADDR, float(f.get()))
                       )).grid(row=4, column=col)
            ttk.Button(rs_frame, text="Fire",
                       command=lambda s=ser: send_enable_command(s, CONFIG_ADDR)
                       ).grid(row=5, column=col)
            ttk.Button(rs_frame, text="Disable",
                       command=lambda s=ser: send_disable_command(s, CONFIG_ADDR)
                       ).grid(row=6, column=col)
            ttk.Button(rs_frame, text="Status",
                       command=lambda s=ser: log(
                           decode_status_response(send_status_command(s, STATUS_ADDR)), self.console)
                       ).grid(row=7, column=col)

        # --- QOL: configure every laser (ASCII + RS232) in one click ---
        qol_frame = ttk.Frame(parent)
        qol_frame.grid(row=2, column=0, columnspan=2, sticky="ew", padx=10, pady=8)
        ttk.Button(qol_frame, text="Configure All Lasers",
                   command=self._configure_all_lasers).pack(fill="x")

    # -----------------------------------------------------------------------
    # Delay Tab  [Updated from new_delaycontrol.py]
    # -----------------------------------------------------------------------
    def _build_delay_tab(self, parent):
        self.delay_controller = DelayGeneratorController()

        # Pulse/spacing vars (user unit)
        self.p1 = tk.DoubleVar(value=0.0)
        self.p2 = tk.DoubleVar(value=0.0)
        self.p3 = tk.DoubleVar(value=0.0)
        self.s1 = tk.DoubleVar(value=0.0)
        self.s2 = tk.DoubleVar(value=0.0)

        # ADV with its own unit (default ms)
        self.adv = tk.DoubleVar(value=16.625)
        self.adv_unit = tk.StringVar(value="ms")

        # Manual T8 / T9 (available but overridden by formula in calculate)
        self.t8 = tk.DoubleVar(value=0.0)
        self.t9 = tk.DoubleVar(value=0.0)

        # Unit for P/S inputs
        self.unit = tk.StringVar(value="us")

        # Computed delays T0–T9 (always stored in ps)
        self.delays = [tk.DoubleVar(value=0.0) for _ in range(10)]

        # -- Connection frame --
        conn_frame = ttk.LabelFrame(parent, text="Connection")
        conn_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(conn_frame, text="IP:").pack(side="left", padx=2)
        self.dg_ip = ttk.Entry(conn_frame, width=15)
        self.dg_ip.insert(0, "192.168.103.22")
        self.dg_ip.pack(side="left", padx=2)

        ttk.Label(conn_frame, text="Port:").pack(side="left", padx=2)
        self.dg_port = ttk.Entry(conn_frame, width=6)
        self.dg_port.insert(0, "4000")
        self.dg_port.pack(side="left", padx=2)

        ttk.Button(conn_frame, text="Connect",    command=self._dg_connect).pack(side="left", padx=5)
        ttk.Button(conn_frame, text="Disconnect", command=self._dg_disconnect).pack(side="left", padx=5)

        ttk.Label(conn_frame, text="P/S Unit:").pack(side="left", padx=5)
        ttk.Combobox(conn_frame, textvariable=self.unit,
                     values=["ps", "ns", "us", "ms"], width=5, state="readonly").pack(side="left", padx=5)

        # -- ADV frame --
        adv_frame = ttk.LabelFrame(parent, text="Advance (ADV)")
        adv_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(adv_frame, text="ADV:").grid(row=0, column=0, padx=5, pady=5)
        ttk.Entry(adv_frame, textvariable=self.adv, width=12).grid(row=0, column=1, padx=5, pady=5)
        ttk.Combobox(adv_frame, textvariable=self.adv_unit,
                     values=["ps", "ns", "us", "ms"], width=5, state="readonly").grid(row=0, column=2, padx=5, pady=5)

        # -- High-level pulse/spacing inputs --
        hl_frame = ttk.LabelFrame(parent, text="High-Level Pulse Settings (enter in P/S unit)")
        hl_frame.pack(fill="x", padx=10, pady=5)

        for idx, (label, var) in enumerate(zip(
                ["P1", "P2", "P3", "S1", "S2"],
                [self.p1, self.p2, self.p3, self.s1, self.s2])):
            ttk.Label(hl_frame, text=label).grid(row=0, column=idx * 2,     padx=5, pady=5)
            ttk.Entry(hl_frame, textvariable=var, width=10).grid(row=0, column=idx * 2 + 1, padx=5, pady=5)

        # -- Manual T8 / T9 --
        manual_frame = ttk.LabelFrame(parent, text="Manual T8 & T9 (enter in P/S unit)")
        manual_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(manual_frame, text="T8").grid(row=0, column=0, padx=5)
        ttk.Entry(manual_frame, textvariable=self.t8, width=12).grid(row=0, column=1, padx=5)
        ttk.Label(manual_frame, text="T9").grid(row=0, column=2, padx=5)
        ttk.Entry(manual_frame, textvariable=self.t9, width=12).grid(row=0, column=3, padx=5)

        # -- Action buttons --
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(btn_frame, text="Calculate T0–T9",      command=self._calculate_delays).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Send All (T0..T9)",    command=self._send_all_delays).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Refresh from Device",  command=self._refresh_from_device).pack(side="left", padx=5)

        # -- Delay table --
        table_frame = ttk.LabelFrame(parent, text="T0..T9 (picoseconds)")
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.dg_tree = ttk.Treeview(table_frame, columns=("Channel", "Delay"), show="headings", height=10)
        self.dg_tree.heading("Channel", text="Channel")
        self.dg_tree.heading("Delay",   text="Delay (ps)")
        self.dg_tree.column("Channel", width=80,  anchor="center")
        self.dg_tree.column("Delay",   width=180, anchor="center")
        self.dg_tree.pack(fill="both", expand=True)

        for i in range(10):
            self.dg_tree.insert("", "end", iid=f"T{i}", values=(f"T{i}", "0"))

        # -- Trigger settings --
        trig_frame = ttk.LabelFrame(parent, text="Trigger Settings")
        trig_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(trig_frame, text="Frequency 1 (Hz):").grid(row=0, column=0, padx=5, pady=3, sticky="e")
        self.dg_freq1 = ttk.Entry(trig_frame, width=10)
        self.dg_freq1.insert(0, "1000")
        self.dg_freq1.grid(row=0, column=1, padx=5, pady=3)

        ttk.Label(trig_frame, text="Frequency 2 (Hz):").grid(row=0, column=2, padx=5, pady=3, sticky="e")
        self.dg_freq2 = ttk.Entry(trig_frame, width=10)
        self.dg_freq2.insert(0, "1000")
        self.dg_freq2.grid(row=0, column=3, padx=5, pady=3)

        self.trig_vars = []
        for i in range(10):
            var = tk.StringVar(value="INH")
            self.trig_vars.append(var)
            row = 1 + i // 5
            col = (i % 5) * 2
            ttk.Label(trig_frame, text=f"T{i}").grid(row=row, column=col, padx=3, pady=3, sticky="e")
            ttk.Combobox(trig_frame, textvariable=var, values=TRIGGER_MODES,
                         width=6, state="readonly").grid(row=row, column=col + 1, padx=3, pady=3)

        trig_btn_frame = ttk.Frame(trig_frame)
        trig_btn_frame.grid(row=3, column=0, columnspan=10, pady=5)
        ttk.Button(trig_btn_frame, text="Send Trigger Settings",
                   command=self._send_trigger_settings).pack(side="left", padx=5)
        ttk.Button(trig_btn_frame, text="Refresh Trigger from Device",
                   command=self._refresh_trigger_settings).pack(side="left", padx=5)

    # -----------------------------------------------------------------------
    # Laser helpers  [UNTOUCHED]
    # -----------------------------------------------------------------------
    def _ascii_settings(self):
        return {
            "trig_mode": self.ascii_trig.get(),
            "frequency": self.ascii_freq.get(),
            "current":   self.ascii_curr.get(),
        }

    def _save_ascii_settings(self):
        settings = self._ascii_settings()
        log("ASCII settings saved: " + str(settings), self.console)

    def _boot_ascii(self, laser_name):
        boot_ascii_laser(laser_name, LASERS[laser_name], self.sessions, self.console)

    def _standby_ascii(self, laser_name):
        tn = self.sessions.get(laser_name)
        if not tn:
            log(f"{laser_name} not connected", self.console)
            return
        try:
            send_ascii_cmd(tn, "$STANDBY", self.console)
        except Exception as e:
            log(f"Standby error: {e}", self.console)

    def _configure_all_lasers(self):
        log("=== Configuring all lasers ===", self.console)
        settings = self._ascii_settings()

        for name in LASERS:
            tn = self.sessions.get(name)
            if not tn:
                log(f"{name} not connected, skipping", self.console)
                continue
            configure_ascii_laser(name, tn, settings, self.console)

        for label, ser in self.rs232_sessions.items():
            entries = self.rs232_entries.get(label)
            if not entries:
                continue
            try:
                gear = int(entries["gear"].get())
                trig = int(entries["trig"].get())
                freq = float(entries["freq"].get())
                send_gear_command(ser, CONFIG_ADDR, gear)
                send_trigger_command(ser, CONFIG_ADDR, trig)
                send_frequency_command(ser, CONFIG_ADDR, freq)
                log(f"{label} configured (gear={gear}, trig={trig}, freq={freq})", self.console)
            except Exception as e:
                log(f"Error configuring {label}: {e}", self.console)

        log("=== Done configuring all lasers ===", self.console)

    # -----------------------------------------------------------------------
    # Delay helpers  [Updated from new_delaycontrol.py]
    # -----------------------------------------------------------------------
    def _dg_connect(self):
        ip = self.dg_ip.get().strip()
        try:
            port = int(self.dg_port.get().strip())
        except ValueError:
            messagebox.showerror("Invalid port", "Port must be an integer")
            return
        ok = self.delay_controller.connect(ip=ip, port=port)
        if ok:
            messagebox.showinfo("Delay Generator", "Connected")

    def _dg_disconnect(self):
        self.delay_controller.disconnect()
        messagebox.showinfo("Delay Generator", "Disconnected")

    def _convert_to_ps(self, value, unit=None):
        """Convert value from the given unit (or the current P/S unit) to picoseconds."""
        if unit is None:
            unit = self.unit.get()
        try:
            v = float(value)
        except Exception:
            return 0.0
        if unit == "ps":
            return v
        if unit == "ns":
            return v * 1_000.0
        if unit == "us":
            return v * 1_000_000.0
        if unit == "ms":
            return v * 1_000_000_000.0
        return v

    def _calculate_delays(self):
        # ADV converted to ps using its own unit selector
        adv = self._convert_to_ps(self.adv.get(), unit=self.adv_unit.get())

        # Fixed offsets relative to ADV
        t0 = 0.0
        t1 = adv - (244 * 1_000_000)   # 244 us before ADV
        t2 = adv - (179 * 1_000_000)   # 179 us before ADV
        t3 = t2

        # Convert P/S inputs to ps
        p1 = self._convert_to_ps(self.p1.get())
        p2 = self._convert_to_ps(self.p2.get())
        p3 = self._convert_to_ps(self.p3.get())
        s1 = self._convert_to_ps(self.s1.get())
        s2 = self._convert_to_ps(self.s2.get())

        t4 = adv
        t5 = adv + p1
        t6 = t5 + s1
        t7 = t6 + p2
        t8 = t7 + s2
        t9 = t8 + p3

        computed = [t0, t1, t2, t3, t4, t5, t6, t7, t8, t9]
        for i, val in enumerate(computed):
            self.delays[i].set(val)
            self.dg_tree.item(f"T{i}", values=(f"T{i}", f"{val:.0f}"))

        log("Calculated T0..T9 from high-level inputs", self.console)

    def _send_all_delays(self):
        if not self.delay_controller.sock:
            messagebox.showerror("Not connected", "Delay generator not connected")
            return
        try:
            for i in range(10):
                self.delay_controller.set_delay(i, self.delays[i].get())
                time.sleep(0.02)
            messagebox.showinfo("Sent", "All delays sent")
            log("Sent T0..T9 to delay generator", self.console)
            self._refresh_from_device()
        except Exception as e:
            messagebox.showerror("Send error", str(e))

    def _refresh_from_device(self):
        if not self.delay_controller.sock:
            messagebox.showerror("Not connected", "Delay generator not connected")
            return
        for i in range(10):
            try:
                resp = self.delay_controller.get_delay(i)
                if resp and "," in resp:
                    try:
                        val = float(resp.split(",")[1])
                        self.delays[i].set(val)
                        self.dg_tree.item(f"T{i}", values=(f"T{i}", f"{val:.0f}"))
                    except Exception:
                        pass
            except Exception:
                pass
        log("Refreshed T0..T9 from device", self.console)

    def _send_trigger_settings(self):
        if not self.delay_controller.sock:
            messagebox.showerror("Not connected", "Delay generator not connected")
            return
        try:
            self.delay_controller.set_frequency(1, float(self.dg_freq1.get()))
            self.delay_controller.set_frequency(2, float(self.dg_freq2.get()))
            for i, var in enumerate(self.trig_vars):
                self.delay_controller.set_trigger(i, var.get())
                time.sleep(0.02)
            messagebox.showinfo("Sent", "Trigger settings sent")
            log("Sent trigger settings to delay generator", self.console)
        except Exception as e:
            messagebox.showerror("Send error", str(e))

    def _refresh_trigger_settings(self):
        if not self.delay_controller.sock:
            messagebox.showerror("Not connected", "Delay generator not connected")
            return
        for i, var in enumerate(self.trig_vars):
            try:
                resp = self.delay_controller.get_trigger(i)
                if resp and "," in resp:
                    mode = resp.split(",")[-1].strip()
                    if mode in TRIGGER_MODES:
                        var.set(mode)
            except Exception:
                pass
        for fn, entry in ((1, self.dg_freq1), (2, self.dg_freq2)):
            try:
                resp = self.delay_controller.get_frequency(fn)
                if resp and "," in resp:
                    entry.delete(0, tk.END)
                    entry.insert(0, resp.split(",")[-1].strip())
            except Exception:
                pass
        log("Refreshed trigger settings from device", self.console)


# ===============================
# Run application
# ===============================
def main():
    root = tk.Tk()
    app = CombinedApp(root)
    root.geometry("1000x800")
    root.mainloop()


if __name__ == "__main__":
    main()
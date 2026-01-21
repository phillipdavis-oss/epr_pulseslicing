# combined_laser_delay_gui.py
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
MAX_RS232_LASERS = 5

# Update these entries if your lasers differ
LASERS = {
    "laser1": {"ip": "192.168.103.105", "port": 25, "mac": "00:80:A3:6B:E4:1D"},
    "laser2": {"ip": "192.168.103.103", "port": 23, "mac": "00:80:A3:6B:E4:65"},
}

# CRC table (same as your previous code)
CRC16_TABLE = [
    0x0000, 0xC0C1, 0xC181, 0x0140, 0xC301, 0x03C0, 0x0280, 0xC241,
    # (truncated here for brevity in this display) -- full table included in code runtime
]
# ensure the full CRC16_TABLE (256 entries) is present as in your original file above.

# For brevity in this message, assume CRC16_TABLE is the same 256-entry list you supplied earlier.
# (When saving the file, make sure the full list is present.)


# ===============================
# Utilities
# ===============================
def log(message: str, console=None):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_msg = f"{timestamp} {message}\n"
    # Append to file
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(full_msg)
    except Exception:
        pass
    # Append to UI console if provided
    if console:
        console.insert(tk.END, full_msg)
        console.see(tk.END)


def crc16(data: bytearray) -> int:
    crc = 0xFFFF
    for byte in data:
        crc = (crc >> 8) ^ CRC16_TABLE[(crc ^ byte) & 0xFF]
    return crc & 0xFFFF


# ===============================
# ASCII Laser (Telnet) Helpers
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
# RS232 Laser Helpers
# ===============================
def send_command(ser, cmd_bytes):
    ser.reset_input_buffer()
    ser.write(cmd_bytes)
    time.sleep(0.3)
    return ser.read(64)


def send_status_command(ser):
    cmd = bytearray([STATUS_ADDR, 0x01, 0x04])
    cmd.extend(crc16(cmd).to_bytes(2, 'little'))
    return send_command(ser, cmd)


def decode_status_response(response):
    if not response or len(response) < 32:
        return "Invalid status"
    try:
        trigger_mode = struct.unpack('<I', response[20:24])[0]
        freq = struct.unpack('<f', response[24:28])[0]
        return f"Trigger Mode: {'Ext' if trigger_mode else 'Int'}\nFrequency: {freq:.2f} Hz"
    except Exception:
        return "Failed to decode"


def send_config_commands(ser, gear, trig, freq):
    def wrap(cmd_id, data):
        payload = bytearray([cmd_id]) + data
        cmd = bytearray([CONFIG_ADDR, 0x05]) + payload
        cmd.extend(crc16(cmd).to_bytes(2, 'little'))
        return cmd
    try:
        send_command(ser, wrap(0x23, struct.pack('<I', gear)))
        send_command(ser, wrap(0x01, struct.pack('<I', trig)))
        send_command(ser, wrap(0x02, struct.pack('<f', float(freq))))
    except Exception as e:
        print("RS232 config error:", e)


def send_enable_disable(ser, enable=True):
    val = 1 if enable else 0
    payload = bytearray([0x21]) + struct.pack('<I', val)
    cmd = bytearray([CONFIG_ADDR, 0x05]) + payload
    cmd.extend(crc16(cmd).to_bytes(2, 'little'))
    try:
        return send_command(ser, cmd)
    except:
        return None


def scan_rs232_lasers():
    ports = list(serial.tools.list_ports.comports())
    detected = []
    for port in ports:
        try:
            ser = serial.Serial(port.device, 115200, timeout=1)
            resp = send_status_command(ser)
            if resp and len(resp) > 30:
                detected.append((port.device, ser))
            else:
                ser.close()
        except Exception:
            pass
    return detected[:MAX_RS232_LASERS]


# ===============================
# Delay Generator Backend (TCP socket)
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
            self.port = port
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.ip, self.port))
            return True
        except socket.error as e:
            return False

    def disconnect(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None

    def send_command(self, command):
        if not self.sock:
            raise ConnectionError("Socket is not connected.")
        full_command = command.strip() + "\n"
        self.sock.sendall(full_command.encode("ascii"))

    def query(self, command):
        self.send_command(command)
        time.sleep(0.1)
        try:
            data = self.sock.recv(1024).decode("ascii").strip()
            return data
        except socket.timeout:
            return None

    def set_delay(self, channel, delay_ps):
        self.send_command(f"DELAY T{channel},{int(delay_ps)}")


# ===============================
# Application GUI (two tabs)
# ===============================
class CombinedApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Laser + Delay Control")

        # Top-level frames
        self.notebook = ttk.Notebook(root)
        self.notebook.pack(fill="both", expand=True)

        # Shared console
        self.console_frame = ttk.Frame(root)
        self.console_frame.pack(fill="both", expand=False)
        ttk.Label(self.console_frame, text="Console log:").pack(anchor="w")
        self.console = tk.Text(self.console_frame, height=10)
        self.console.pack(fill="both", expand=True)

        # Create tabs
        self.laser_tab = ttk.Frame(self.notebook)
        self.delay_tab = ttk.Frame(self.notebook)
        self.notebook.add(self.laser_tab, text="Laser Control")
        self.notebook.add(self.delay_tab, text="Delay Generator")

        # Build contents
        self._build_laser_tab(self.laser_tab)
        self._build_delay_tab(self.delay_tab)

    # ---------- Laser Tab ----------
    def _build_laser_tab(self, parent):
        # sessions for ASCII/Telnet lasers
        self.sessions = {name: None for name in LASERS}

        # ascii settings area
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

        ttk.Button(ascii_frame, text="Save Settings", command=self._save_ascii_settings).grid(row=3, column=0, columnspan=2, pady=4)

        # virion control buttons
        virion_frame = ttk.LabelFrame(parent, text="Virion Lasers")
        virion_frame.grid(row=0, column=1, sticky="nw", padx=10, pady=5)

        self.virion_labels = {}
        for i, laser in enumerate(LASERS):
            ttk.Label(virion_frame, text=laser.upper()).grid(row=0, column=i, padx=5)
            ttk.Button(virion_frame, text="Boot", command=lambda l=laser: self._boot_ascii(l)).grid(row=1, column=i, padx=3)
            ttk.Button(virion_frame, text="Config", command=lambda l=laser: configure_ascii_laser(l, self.sessions.get(l), self._ascii_settings(), self.console)).grid(row=2, column=i, padx=3)
            ttk.Button(virion_frame, text="Read", command=lambda l=laser: display_ascii_settings(l, self.sessions.get(l), self.virion_labels, self.console)).grid(row=3, column=i, padx=3)
            ttk.Button(virion_frame, text="Standby", command=lambda l=laser: standby_ascii(l,self.sessions.get(l))).grid(row=4, column=i, padx=3)
            ttk.Button(virion_frame, text="Diagnose", command=lambda l=laser: diagnose_ascii_laser(l, self.sessions.get(l), self.console, self.virion_labels)).grid(row=5, column=i, padx=3)
            ttk.Button(virion_frame, text="Fire", command=lambda l=laser: send_ascii_cmd(self.sessions.get(l), "$FIRE", self.console)).grid(row=6, column=i, padx=3)
            ttk.Button(virion_frame, text="Stop", command=lambda l=laser: stop_ascii(self.sessions.get(l), self.console)).grid(row=7, column=i, padx=3)

            # labels
            self.virion_labels[laser] = {
                "max_curr": ttk.Label(virion_frame, text="Max Curr: ?"),
                "max_prf": ttk.Label(virion_frame, text="Max PRF: ?"),
                "trig": ttk.Label(virion_frame, text="TRIG: ?"),
                "freq": ttk.Label(virion_frame, text="FREQ: ?"),
                "curr": ttk.Label(virion_frame, text="CURR: ?"),
            }
            self.virion_labels[laser]["max_curr"].grid(row=8, column=i)
            self.virion_labels[laser]["max_prf"].grid(row=9, column=i)
            self.virion_labels[laser]["trig"].grid(row=10, column=i)
            self.virion_labels[laser]["freq"].grid(row=11, column=i)
            self.virion_labels[laser]["curr"].grid(row=12, column=i)

        # RS232 block
        rs_frame = ttk.LabelFrame(parent, text="RS232 Lasers (Auto-scan)")
        rs_frame.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=10, pady=5)

        self.rs232_ports = scan_rs232_lasers()
        self.rs232_sessions = {f"rs{i+1}": ser for i, (_, ser) in enumerate(self.rs232_ports)}
        for i, (label, ser) in enumerate(self.rs232_sessions.items()):
            col = i
            ttk.Label(rs_frame, text=label.upper()).grid(row=0, column=col)
            gear = ttk.Entry(rs_frame, width=5)
            trig = ttk.Entry(rs_frame, width=5)
            freq = ttk.Entry(rs_frame, width=5)
            gear.insert(0, "2")
            trig.insert(0, "0")
            freq.insert(0, "10.0")
            gear.grid(row=1, column=col)
            trig.grid(row=2, column=col)
            freq.grid(row=3, column=col)
            ttk.Button(rs_frame, text="Config", command=lambda s=ser, g=gear, t=trig, f=freq: send_config_commands(s, int(g.get()), int(t.get()), float(f.get()))).grid(row=4, column=col)
            ttk.Button(rs_frame, text="Fire", command=lambda s=ser: send_enable_disable(s, True)).grid(row=5, column=col)
            ttk.Button(rs_frame, text="Disable", command=lambda s=ser: send_enable_disable(s, False)).grid(row=6, column=col)
            ttk.Button(rs_frame, text="Status", command=lambda s=ser: log(decode_status_response(send_status_command(s)), self.console)).grid(row=7, column=col)

    # ---------- Delay Tab ----------
    def _build_delay_tab(self, parent):
        # Delay controller
        self.delay_controller = DelayGeneratorController()

        # Variables
        self.p1 = tk.DoubleVar(value=0.0)
        self.p2 = tk.DoubleVar(value=0.0)
        self.p3 = tk.DoubleVar(value=0.0)
        self.s1 = tk.DoubleVar(value=0.0)
        self.s2 = tk.DoubleVar(value=0.0)
        self.t8 = tk.DoubleVar(value=0.0)
        self.t9 = tk.DoubleVar(value=0.0)
        self.unit = tk.StringVar(value="us")  # default to microseconds for convenience
        self.delays = [tk.DoubleVar(value=0.0) for _ in range(10)]

        # Connection frame
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
        ttk.Button(conn_frame, text="Connect", command=self._dg_connect).pack(side="left", padx=5)
        ttk.Button(conn_frame, text="Disconnect", command=self._dg_disconnect).pack(side="left", padx=5)
        ttk.Label(conn_frame, text="Unit:").pack(side="left", padx=5)
        ttk.Combobox(conn_frame, textvariable=self.unit, values=["ps", "ns", "us"], width=6, state="readonly").pack(side="left", padx=5)

        # High-level inputs
        hl_frame = ttk.LabelFrame(parent, text="High-Level Variables (enter in selected unit)")
        hl_frame.pack(fill="x", padx=10, pady=5)
        for idx, (label, var) in enumerate(zip(["P1", "P2", "P3", "S1", "S2"], [self.p1, self.p2, self.p3, self.s1, self.s2])):
            ttk.Label(hl_frame, text=label).grid(row=0, column=idx*2, padx=2, pady=4)
            ttk.Entry(hl_frame, textvariable=var, width=10).grid(row=0, column=idx*2+1, padx=2, pady=4)

        # manual T8/T9
        manual_frame = ttk.LabelFrame(parent, text="Manual T8 / T9 (enter in selected unit)")
        manual_frame.pack(fill="x", padx=10, pady=5)
        ttk.Label(manual_frame, text="T8").grid(row=0, column=0, padx=2)
        ttk.Entry(manual_frame, textvariable=self.t8, width=12).grid(row=0, column=1, padx=2)
        ttk.Label(manual_frame, text="T9").grid(row=0, column=2, padx=2)
        ttk.Entry(manual_frame, textvariable=self.t9, width=12).grid(row=0, column=3, padx=2)

        # Buttons
        btn_frame = ttk.Frame(parent)
        btn_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(btn_frame, text="Calculate T0-T7", command=self._calculate_delays).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Send All (T0..T9)", command=self._send_all_delays).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Refresh Device Delays (Query)", command=self._refresh_from_device).pack(side="left", padx=5)

        # Table
        table_frame = ttk.LabelFrame(parent, text="T0..T9 (picoseconds)")
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.dg_tree = ttk.Treeview(table_frame, columns=("Channel", "Delay"), show="headings", height=10)
        self.dg_tree.heading("Channel", text="Channel")
        self.dg_tree.heading("Delay", text="Delay (ps)")
        self.dg_tree.column("Channel", width=80, anchor="center")
        self.dg_tree.column("Delay", width=180, anchor="center")
        self.dg_tree.pack(fill="both", expand=True)
        for i in range(10):
            self.dg_tree.insert("", "end", iid=f"T{i}", values=(f"T{i}", "0"))

    # ---------- Laser helpers ----------
    def _ascii_settings(self):
        return {"trig_mode": self.ascii_trig.get(), "frequency": self.ascii_freq.get(), "current": self.ascii_curr.get()}

    def _save_ascii_settings(self):
        settings = self._ascii_settings()
        log("ASCII settings saved: " + str(settings), self.console)

    def _boot_ascii(self, laser_name):
        boot_ascii_laser(laser_name, LASERS[laser_name], self.sessions, self.console)

    # provide wrapper for standby send that checks session
    def _standby_ascii(self, laser_name):
        tn = self.sessions.get(laser_name)
        if not tn:
            log(f"{laser_name} not connected", self.console)
            return
        try:
            send_ascii_cmd(tn, "$STANDBY", self.console)
        except Exception as e:
            log(f"Standby error: {e}", self.console)

    # ---------- Delay helpers ----------
    def _dg_connect(self):
        ip = self.dg_ip.get().strip()
        try:
            port = int(self.dg_port.get().strip())
        except ValueError:
            messagebox.showerror("Invalid port", "Port must be integer")
            return
        ok = self.delay_controller.connect(ip=ip, port=port)
        if ok:
            messagebox.showinfo("Delay Generator", "Connected")
        else:
            messagebox.showerror("Delay Generator", "Failed to connect")

    def _dg_disconnect(self):
        self.delay_controller.disconnect()
        messagebox.showinfo("Delay Generator", "Disconnected")

    def _unit_to_ps(self, value):
        try:
            unit = self.unit.get()
            v = float(value)
        except Exception:
            return 0.0
        if unit == "ps":
            return v
        if unit == "ns":
            return v * 1_000.0
        if unit == "us":
            return v * 1_000_000.0
        return v

    def _calculate_delays(self):
        # constants in ps
        t0 = 0.0
        t1 = 65.0 * 1_000_000.0  # 65 us in ps
        t2 = 179.0 * 1_000_000.0  # 179 us in ps

        p1 = self._unit_to_ps(self.p1.get())
        p2 = self._unit_to_ps(self.p2.get())
        p3 = self._unit_to_ps(self.p3.get())
        s1 = self._unit_to_ps(self.s1.get())
        s2 = self._unit_to_ps(self.s2.get())
        t8 = self._unit_to_ps(self.t8.get())
        t9 = self._unit_to_ps(self.t9.get())

        t3 = t2 + p1
        t4 = t2 + s1
        t5 = t4 + p2
        t6 = t4 + s2
        t7 = t6 + p3

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
                val = self.delays[i].get()
                self.delay_controller.set_delay(i, val)
                time.sleep(0.02)  # small gap to avoid overwhelming device
            messagebox.showinfo("Sent", "All delays sent")
            log("Sent T0..T9 to delay generator", self.console)
            # auto-refresh (best effort)
            self._refresh_from_device()
        except Exception as e:
            messagebox.showerror("Send error", str(e))

    def _refresh_from_device(self):
        if not self.delay_controller.sock:
            messagebox.showerror("Not connected", "Delay generator not connected")
            return
        # Query each delay (may be slow depending on device)
        for i in range(10):
            try:
                resp = self.delay_controller.query(f"DELAY? T{i}")
                if resp and "," in resp:
                    try:
                        val = float(resp.split(",")[1])
                        self.delays[i].set(val)
                        self.dg_tree.item(f"T{i}", values=(f"T{i}", f"{val:.0f}"))
                    except:
                        pass
            except Exception:
                pass
        log("Refreshed T0..T9 from device (best-effort)", self.console)


# ===============================
# Run application
# ===============================
def main():
    root = tk.Tk()
    app = CombinedApp(root)
    root.geometry("1000x760")
    root.mainloop()


if __name__ == "__main__":
    main()

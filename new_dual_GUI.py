import tkinter as tk
from tkinter import ttk, messagebox
import serial
import serial.tools.list_ports
import struct
import telnetlib
import time
import json
import os
from datetime import datetime

# === Shared Setup ===
SETTINGS_FILE = "settings.json"
LOG_FILE = "laser_log.txt"
STATUS_ADDR = 0x5D
CONFIG_ADDR = 0x7F
MAX_RS232_LASERS = 5

LASERS = {
    "laser1": {"ip": "192.168.103.105", "port": 25, "mac": "00:80:A3:6B:E4:1D"},
    "laser2": {"ip": "192.168.103.103", "port": 23, "mac": "00:80:A3:6B:E4:65"},
}

CRC16_TABLE =  [
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
    0x8201, 0x42C0, 0x4380, 0x8341, 0x4100, 0x81C1, 0x8081, 0x4040
]
  # shortened here — paste your full CRC table

def crc16(data: bytearray) -> int:
    crc = 0xFFFF
    for byte in data:
        crc = (crc >> 8) ^ CRC16_TABLE[(crc ^ byte) & 0xFF]
    return crc & 0xFFFF

def log(message: str, console=None):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_msg = f"{timestamp} {message}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(full_msg)
    if console:
        console.insert(tk.END, full_msg)
        console.see(tk.END)

# === ASCII/Virion Laser Logic ===

def generate_password(mac: str) -> str:
    last6 = ''.join(mac.split(":")[-3:]).upper()
    return f"VR{last6}"

def send_ascii_cmd(tn: telnetlib.Telnet, cmd: str, console=None, wait=0.2) -> str:
    tn.write((cmd + "\r").encode("ascii"))
    time.sleep(wait)
    resp = tn.read_very_eager().decode("ascii", errors="ignore").strip()
    log(f">> {cmd}", console)
    log(f"<< {resp}", console)
    return resp

def boot_ascii_laser(name, info, sessions, labels, console):
    try:
        tn = telnetlib.Telnet(info["ip"], info["port"], timeout=5)
        pwd = generate_password(info["mac"])
        if "ERROR" in send_ascii_cmd(tn, f"$LOGIN {pwd}", console).upper():
            log(f"{name} login failed", console)
            return
        send_ascii_cmd(tn, "$STANDBY", console)
        labels[name]["max_curr"].config(text=f"Max Current: {send_ascii_cmd(tn, '$MAXCURR ?', console)}")
        labels[name]["max_prf"].config(text=f"Max PRF: {send_ascii_cmd(tn, '$MAXPRF ?', console)}")
        sessions[name] = tn
    except Exception as e:
        log(f"Connection error for {name}: {e}", console)

def configure_ascii_laser(name, tn, settings, console):
    for cmd in [
        f"$TRIG {settings['trig_mode']}",
        f"$DFREQ {settings['frequency']}",
        f"$DCURR {settings['current']}",
        "$QSDELAY 179"
    ]:
        send_ascii_cmd(tn, cmd, console)

def display_ascii_settings(name, tn, labels, console):
    labels[name]["trig"].config(text=f"TRIG: {send_ascii_cmd(tn, '$TRIG ?', console)}")
    labels[name]["freq"].config(text=f"FREQ: {send_ascii_cmd(tn, '$DFREQ ?', console)}")
    labels[name]["curr"].config(text=f"CURR: {send_ascii_cmd(tn, '$DCURR ?', console)}")

def stop_ascii(tn, console):
    send_ascii_cmd(tn, "$STOP", console)

# === RS232 Laser Logic ===
def hex_str(data: bytes):
    return ' '.join(f'{b:02X}' for b in data)

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
    except:
        return "Failed to decode"

def send_config_commands(ser, gear, trig, freq):
    def wrap_cmd(cmd_id, data):
        payload = bytearray([cmd_id]) + data
        cmd = bytearray([CONFIG_ADDR, 0x05]) + payload
        cmd.extend(crc16(cmd).to_bytes(2, 'little'))
        return cmd

    send_command(ser, wrap_cmd(0x23, struct.pack('<I', gear)))
    send_command(ser, wrap_cmd(0x01, struct.pack('<I', trig)))
    send_command(ser, wrap_cmd(0x02, struct.pack('<f', float(freq))))

def send_enable_disable(ser, enable=True):
    val = 1 if enable else 0
    payload = bytearray([0x21]) + struct.pack('<I', val)
    cmd = bytearray([CONFIG_ADDR, 0x05]) + payload
    cmd.extend(crc16(cmd).to_bytes(2, 'little'))
    return send_command(ser, cmd)

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
        except:
            pass
    return detected[:MAX_RS232_LASERS]

# === GUI ===
def gui_app():
    root = tk.Tk()
    root.title("Dual Laser Controller")

    sessions = {"laser1": None, "laser2": None}
    rs232_list = scan_rs232_lasers()
    rs232_sessions = {f"rs{i+1}": ser for i, (_, ser) in enumerate(rs232_list)}
    settings = {"trig_mode": "II", "frequency": "10.0", "current": "20.0"}

    frame = ttk.Frame(root)
    frame.pack(fill='both', expand=True)
    console = tk.Text(frame, height=15)
    console.grid(row=0, column=0, columnspan=4)

    # Virion laser GUI blocks
    virion_labels = {
        "laser1": {"max_curr": None, "max_prf": None, "trig": None, "freq": None, "curr": None},
        "laser2": {"max_curr": None, "max_prf": None, "trig": None, "freq": None, "curr": None}
    }

    for idx, laser in enumerate(["laser1", "laser2"]):
        col = idx
        ttk.Label(frame, text=laser.upper()).grid(row=1, column=col)
        ttk.Button(frame, text="Boot", command=lambda l=laser: boot_ascii_laser(l, LASERS[l], sessions, virion_labels, console)).grid(row=2, column=col)
        ttk.Button(frame, text="Config", command=lambda l=laser: configure_ascii_laser(l, sessions[l], settings, console)).grid(row=3, column=col)
        ttk.Button(frame, text="Read", command=lambda l=laser: display_ascii_settings(l, sessions[l], virion_labels, console)).grid(row=4, column=col)
        ttk.Button(frame, text="Stop", command=lambda l=laser: stop_ascii(sessions[l], console)).grid(row=5, column=col)

        virion_labels[laser]["max_curr"] = ttk.Label(frame, text="Max Curr: ?")
        virion_labels[laser]["max_curr"].grid(row=6, column=col)
        virion_labels[laser]["max_prf"] = ttk.Label(frame, text="Max PRF: ?")
        virion_labels[laser]["max_prf"].grid(row=7, column=col)
        virion_labels[laser]["trig"] = ttk.Label(frame, text="TRIG: ?")
        virion_labels[laser]["trig"].grid(row=8, column=col)
        virion_labels[laser]["freq"] = ttk.Label(frame, text="FREQ: ?")
        virion_labels[laser]["freq"].grid(row=9, column=col)
        virion_labels[laser]["curr"] = ttk.Label(frame, text="CURR: ?")
        virion_labels[laser]["curr"].grid(row=10, column=col)

    # RS232 laser GUI blocks
    for idx, (label, ser) in enumerate(rs232_sessions.items()):
        col = 2 + idx
        ttk.Label(frame, text=f"{label.upper()}").grid(row=1, column=col)
        gear_entry = ttk.Entry(frame, width=5)
        trig_entry = ttk.Entry(frame, width=5)
        freq_entry = ttk.Entry(frame, width=5)
        gear_entry.insert(0, "2")
        trig_entry.insert(0, "0")
        freq_entry.insert(0, "10.0")
        gear_entry.grid(row=2, column=col)
        trig_entry.grid(row=3, column=col)
        freq_entry.grid(row=4, column=col)
        ttk.Button(frame, text="Configure", command=lambda s=ser: send_config_commands(s, int(gear_entry.get()), int(trig_entry.get()), float(freq_entry.get()))).grid(row=5, column=col)
        ttk.Button(frame, text="Fire", command=lambda s=ser: send_enable_disable(s, True)).grid(row=6, column=col)
        ttk.Button(frame, text="Disable", command=lambda s=ser: send_enable_disable(s, False)).grid(row=7, column=col)
        ttk.Button(frame, text="Status", command=lambda s=ser: log(decode_status_response(send_status_command(s)), console)).grid(row=8, column=col)

    root.mainloop()

if __name__ == "__main__":
    gui_app()


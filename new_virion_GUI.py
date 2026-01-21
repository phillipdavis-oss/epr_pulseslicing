import telnetlib
import tkinter as tk
from tkinter import ttk, messagebox
import json
import os
import time
from datetime import datetime

# File paths
SETTINGS_FILE = "settings.json"
LOG_FILE = "laser_log.txt"

# Laser device definitions
LASERS = {
    "laser1": {"ip": "192.168.103.105", "port": 25, "mac": "00:80:A3:6B:E4:1D"},
    "laser2": {"ip": "192.168.103.103", "port": 23, "mac": "00:80:A3:6B:E4:65"},
}

def generate_password(mac: str) -> str:
    """Generate login password from MAC address."""
    last6 = ''.join(mac.split(":")[-3:]).upper()
    return f"VR{last6}"

def log(message: str, console=None):
    """Log messages with timestamp to file and optionally to GUI console."""
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    full_msg = f"{timestamp} {message}\n"
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(full_msg)
    if console:
        console.insert(tk.END, full_msg)
        console.see(tk.END)

def send_ascii_cmd(tn: telnetlib.Telnet, cmd: str, console=None, wait=0.2) -> str:
    """Send ASCII command to laser and return response."""
    full_cmd = cmd + "\r"
    tn.write(full_cmd.encode("ascii"))
    time.sleep(wait)
    resp = tn.read_very_eager().decode("ascii", errors="ignore").strip()
    log(f">> {cmd}", console)
    log(f"<< {resp}", console)
    return resp

def load_settings() -> dict:
    """Load persistent configuration settings from file."""
    defaults = {
        "trig_mode": "II",
        "frequency": "10.0",
        "current": "20.0"
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, "r") as f:
                data = json.load(f)
                defaults.update(data)
        except Exception:
            pass
    return defaults

def save_settings(settings: dict):
    """Save settings to JSON file."""
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)

def standby_laser(tn, console):
    """Send standby command to laser."""
    send_ascii_cmd(tn, "$STANDBY", console)

def display_settings(name, tn, labels, console):
    """Read and display current laser configuration settings."""
    trig = send_ascii_cmd(tn, "$TRIG ?", console)
    freq = send_ascii_cmd(tn, "$DFREQ ?", console)
    curr = send_ascii_cmd(tn, "$DCURR ?", console)
    labels[name]["trig"].config(text=f"TRIG: {trig}")
    labels[name]["freq"].config(text=f"FREQ: {freq}")
    labels[name]["curr"].config(text=f"CURR: {curr}")

def diagnose_laser(name, tn, console):
    """Send diagnostic commands to the laser and log the responses."""
    log(f"Running diagnostics on {name}...", console)
    cmds = ["$TEXTS ?", "$TRIG ?", "$DFREQ ?", "$DCURR ?", "$QSDELAY ?"]
    for cmd in cmds:
        send_ascii_cmd(tn, cmd, console)

def boot_laser(name: str, info: dict, sessions, console, max_labels):
    """Boot the laser by logging in and setting to standby, then probe max values."""
    log(f"Connecting to {name} ({info['ip']}:{info['port']})...", console)
    try:
        tn = telnetlib.Telnet(info["ip"], info["port"], timeout=5)
        pwd = generate_password(info["mac"])

        login_resp = send_ascii_cmd(tn, f"$LOGIN {pwd}", console)
        if "ERROR" in login_resp.upper():
            log("Login failed.", console)
            return

        standby_resp = send_ascii_cmd(tn, "$STANDBY", console)
        if "STANDBY" in standby_resp.upper():
            log(f"{name} is in standby mode.", console)
            max_curr = send_ascii_cmd(tn, "$MAXCURR ?", console)
            max_freq = send_ascii_cmd(tn, "$MAXPRF ?", console)
            log(f"{name} Max Current: {max_curr}", console)
            log(f"{name} Max PRF: {max_freq}", console)
            max_labels[name]["current"].config(text=f"Max Current: {max_curr}")
            max_labels[name]["prf"].config(text=f"Max PRF: {max_freq}")
            sessions[name] = tn
        else:
            log("Unexpected standby response.", console)
            tn.close()
    except Exception as e:
        log(f"Connection error for {name}: {e}", console)

def configure_laser(name, tn, settings, console):
    """Send configuration commands to laser based on user input."""
    cmds = [
        f"$TRIG {settings['trig_mode']}",
        f"$DFREQ {settings['frequency']}",
        f"$DCURR {settings['current']}",
        f"$QSDELAY 179"
    ]
    for cmd in cmds:
        send_ascii_cmd(tn, cmd, console)

def check_ready(tn, console) -> bool:
    """Check if laser is ready to fire based on status queries."""
    resp1 = send_ascii_cmd(tn, "$TEXTS ?", console)
    resp2 = send_ascii_cmd(tn, "$QSON ?", console)
    return all(k in resp1.upper() or k in resp2.upper() for k in ["OK", "NO TEXTS", "ON"])

def fire_laser(name, tn, console):
    """Prompt user and send fire command."""
    if messagebox.askyesno("Confirm Fire", f"Are you sure you want to fire {name}?"):
        send_ascii_cmd(tn, "$FIRE", console)
    else:
        log("Fire command canceled.", console)

def stop_laser(tn, console):
    """Send stop command to laser."""
    send_ascii_cmd(tn, "$STOP", console)

def gui_app():
    root = tk.Tk()
    root.title("ASCII Laser Control GUI")

    settings = load_settings()
    sessions = {"laser1": None, "laser2": None}
    max_labels = {
        "laser1": {"current": None, "prf": None},
        "laser2": {"current": None, "prf": None}
    }
    setting_labels = {
        "laser1": {"trig": None, "freq": None, "curr": None},
        "laser2": {"trig": None, "freq": None, "curr": None}
    }

    entries = {}
    frame = ttk.Frame(root, padding=10)
    frame.grid(row=0, column=0, sticky="nsew")

    # Configuration input fields
    ttk.Label(frame, text="Trigger Mode ($TRIG)").grid(row=0, column=0, sticky="e")
    entries['trig_mode'] = ttk.Combobox(frame, values=["II", "EE", "IE", "EI"])
    entries['trig_mode'].set(settings['trig_mode'])
    entries['trig_mode'].grid(row=0, column=1)

    ttk.Label(frame, text="Frequency (Hz)").grid(row=1, column=0, sticky="e")
    entries['frequency'] = ttk.Entry(frame)
    entries['frequency'].insert(0, settings['frequency'])
    entries['frequency'].grid(row=1, column=1)

    ttk.Label(frame, text="Diode Current").grid(row=2, column=0, sticky="e")
    entries['current'] = ttk.Entry(frame)
    entries['current'].insert(0, settings['current'])
    entries['current'].grid(row=2, column=1)

    # Display labels for each laser
    for i, laser in enumerate(["laser1", "laser2"]):
        offset = 3 + i * 6
        mac = LASERS[laser]["mac"]
        ttk.Label(frame, text=f"{laser.capitalize()} MAC: {mac}").grid(row=offset, column=0, columnspan=2, sticky="w")
        max_labels[laser]["current"] = ttk.Label(frame, text="Max Current: ?")
        max_labels[laser]["current"].grid(row=offset+1, column=0, columnspan=2, sticky="w")
        max_labels[laser]["prf"] = ttk.Label(frame, text="Max PRF: ?")
        max_labels[laser]["prf"].grid(row=offset+2, column=0, columnspan=2, sticky="w")
        setting_labels[laser]["trig"] = ttk.Label(frame, text="TRIG: ?")
        setting_labels[laser]["trig"].grid(row=offset+3, column=0, columnspan=2, sticky="w")
        setting_labels[laser]["freq"] = ttk.Label(frame, text="FREQ: ?")
        setting_labels[laser]["freq"].grid(row=offset+4, column=0, columnspan=2, sticky="w")
        setting_labels[laser]["curr"] = ttk.Label(frame, text="CURR: ?")
        setting_labels[laser]["curr"].grid(row=offset+5, column=0, columnspan=2, sticky="w")

    # Console output
    console = tk.Text(root, height=15, width=80)
    console.grid(row=1, column=0, padx=10, pady=10)

    def update_settings():
        settings['trig_mode'] = entries['trig_mode'].get().strip().upper()
        settings['frequency'] = entries['frequency'].get().strip()
        settings['current'] = entries['current'].get().strip()
        save_settings(settings)

    # Action button functions
    def boot(name): boot_laser(name, LASERS[name], sessions, console, max_labels)
    def config(name):
        tn = sessions.get(name)
        if tn:
            update_settings()
            configure_laser(name, tn, settings, console)
            if check_ready(tn, console):
                log(f"{name} ready to fire.", console)
    def fire(name): tn = sessions.get(name); fire_laser(name, tn, console) if tn else None
    def stop(name): tn = sessions.get(name); stop_laser(tn, console) if tn else None
    def standby(name): tn = sessions.get(name); standby_laser(tn, console) if tn else None
    def display(name): tn = sessions.get(name); display_settings(name, tn, setting_labels, console) if tn else None
    def diagnose(name): tn = sessions.get(name); diagnose_laser(name, tn, console) if tn else None
    def boot_both():
        """Boot both lasers."""
        for name in LASERS:
            boot(name)

    # Button definitions
    buttons = [
        ("Boot Laser 1", lambda: boot("laser1")),
        ("Boot Laser 2", lambda: boot("laser2")),
        ("Boot Both Lasers", boot_both),
        ("Configure Laser 1", lambda: config("laser1")),
        ("Configure Laser 2", lambda: config("laser2")),
        ("Fire Laser 1", lambda: fire("laser1")),
        ("Fire Laser 2", lambda: fire("laser2")),
        ("Stop Laser 1", lambda: stop("laser1")),
        ("Stop Laser 2", lambda: stop("laser2")),
        ("Standby Laser 1", lambda: standby("laser1")),
        ("Standby Laser 2", lambda: standby("laser2")),
        ("Read Settings Laser 1", lambda: display("laser1")),
        ("Read Settings Laser 2", lambda: display("laser2")),
        ("Diagnose Laser 1", lambda: diagnose("laser1")),
        ("Diagnose Laser 2", lambda: diagnose("laser2"))
    ]

    # Layout buttons
    button_frame = ttk.Frame(root)
    button_frame.grid(row=2, column=0, pady=5)
    for idx, (label, cmd) in enumerate(buttons):
        ttk.Button(button_frame, text=label, command=cmd).grid(row=idx // 2, column=idx % 2, padx=5, pady=5)

    root.mainloop()

if __name__ == "__main__":
    gui_app()

import telnetlib
import time
import json
import os
from datetime import datetime

SETTINGS_FILE = "settings.json"
LOG_FILE = "laser_log.txt"

LASERS = {
    "laser1": {"ip": "192.168.103.105", "port": 25, "mac": "00:80:A3:6B:E4:1D"},
    "laser2": {"ip": "192.168.103.103", "port": 23, "mac": "00:80:A3:6B:E4:65"},
}


def generate_password(mac: str) -> str:
    last6 = ''.join(mac.split(":")[-3:]).upper()
    return f"VR{last6}"


def log(message: str):
    timestamp = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} {message}\n")
    print(f"{timestamp} {message}")


def send_ascii_cmd(tn: telnetlib.Telnet, cmd: str, wait=0.2) -> str:
    full_cmd = cmd + "\r"
    tn.write(full_cmd.encode("ascii"))
    time.sleep(wait)
    resp = tn.read_very_eager().decode("ascii", errors="ignore").strip()
    log(f">> {cmd}")
    log(f"<< {resp}")
    return resp


def boot_laser(name: str, info: dict) -> telnetlib.Telnet | None:
    log(f"Connecting to {name} ({info['ip']}:{info['port']})...")
    try:
        tn = telnetlib.Telnet(info["ip"], info["port"], timeout=5)
        pwd = generate_password(info["mac"])

        login_resp = send_ascii_cmd(tn, f"$LOGIN {pwd}")
        if "ERROR" in login_resp.upper():
            log("Login failed.")
            tn.close()
            return None

        standby_resp = send_ascii_cmd(tn, "$STANDBY")
        if "STANDBY" in standby_resp.upper():
            log(f"{name} is in standby mode.")
            return tn
        else:
            log("Unexpected standby response.")
            tn.close()
            return None
    except Exception as e:
        log(f"Connection error for {name}: {e}")
        return None


def load_settings() -> dict:
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, "r") as f:
            return json.load(f)
    return {
        "trigger_source": "$DTRIG",
        "frequency": "10.0",
        "current": "20.0"
    }


def save_settings(settings: dict):
    with open(SETTINGS_FILE, "w") as f:
        json.dump(settings, f, indent=2)
    log("Settings saved.")


def configure_laser(tn: telnetlib.Telnet, name: str, settings: dict):
    log(f"Configuring {name}...")
    source = input(f"Trigger source [{settings['trigger_source']}]: ").strip().upper() or settings['trigger_source']
    freq = input(f"Frequency [{settings['frequency']} Hz]: ").strip() or settings['frequency']
    curr = input(f"Diode current [{settings['current']}]: ").strip() or settings['current']

    settings.update({
        "trigger_source": source,
        "frequency": freq,
        "current": curr
    })
    save_settings(settings)

    cmds = [
        source,
        f"$DFREQ {freq}",
        f"$DCURR {curr}",
        "$QSON"
    ]

    for cmd in cmds:
        send_ascii_cmd(tn, cmd)


def check_texts(tn: telnetlib.Telnet) -> bool:
    resp = send_ascii_cmd(tn, "$TEXTS ?")
    if "NO TEXTS" in resp.upper() or "OK" in resp.upper():
        log("No system issues.")
        return True
    else:
        log("Issues reported.")
        return False


def fire_laser(tn: telnetlib.Telnet, name: str):
    confirm = input(f"Are you sure you want to fire {name}? (yes/no): ").strip().lower()
    if confirm == "yes":
        send_ascii_cmd(tn, "$FIRE")
    else:
        log("Fire command canceled.")


def stop_laser(tn: telnetlib.Telnet):
    send_ascii_cmd(tn, "$STOP")


def menu():
    print("""\n=== ASCII Laser Control ===
1. Boot laser1
2. Boot laser2
3. Boot both lasers
4. Configure laser1
5. Configure laser2
6. FIRE laser1
7. FIRE laser2
8. STOP laser1
9. STOP laser2
r. Reload saved settings
q. Quit
""")


def main():
    telnet_sessions = {"laser1": None, "laser2": None}
    settings = load_settings()

    while True:
        menu()
        choice = input("Select option: ").strip().lower()

        if choice == "1":
            telnet_sessions["laser1"] = boot_laser("laser1", LASERS["laser1"])
        elif choice == "2":
            telnet_sessions["laser2"] = boot_laser("laser2", LASERS["laser2"])
        elif choice == "3":
            telnet_sessions["laser1"] = boot_laser("laser1", LASERS["laser1"])
            telnet_sessions["laser2"] = boot_laser("laser2", LASERS["laser2"])
        elif choice == "4" and telnet_sessions["laser1"]:
            configure_laser(telnet_sessions["laser1"], "laser1", settings)
            if check_texts(telnet_sessions["laser1"]):
                log("Ready to fire laser1.")
        elif choice == "5" and telnet_sessions["laser2"]:
            configure_laser(telnet_sessions["laser2"], "laser2", settings)
            if check_texts(telnet_sessions["laser2"]):
                log("Ready to fire laser2.")
        elif choice == "6" and telnet_sessions["laser1"]:
            fire_laser(telnet_sessions["laser1"], "laser1")
        elif choice == "7" and telnet_sessions["laser2"]:
            fire_laser(telnet_sessions["laser2"], "laser2")
        elif choice == "8" and telnet_sessions["laser1"]:
            stop_laser(telnet_sessions["laser1"])
        elif choice == "9" and telnet_sessions["laser2"]:
            stop_laser(telnet_sessions["laser2"])
        elif choice == "r":
            settings = load_settings()
            log("Settings reloaded.")
        elif choice == "q":
            for tn in telnet_sessions.values():
                if tn: tn.close()
            log("Exiting.")
            break
        else:
            print("Invalid option or laser not initialized.")


if __name__ == "__main__":
    main()

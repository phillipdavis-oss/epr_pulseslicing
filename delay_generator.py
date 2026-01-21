import socket
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox


# ===================================
# Delay Generator Controller (from working test code)
# ===================================
class DelayGeneratorController:
    def __init__(self, ip="192.168.103.22", port=4000, timeout=2.0):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
        """Connect to the delay generator using raw TCP socket."""
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(self.timeout)
            self.sock.connect((self.ip, self.port))
            print(f"[INFO] Connected to {self.ip}:{self.port}")
            return True
        except socket.error as e:
            print(f"[ERROR] Failed to connect: {e}")
            return False

    def disconnect(self):
        """Close the TCP connection."""
        if self.sock:
            self.sock.close()
            self.sock = None
            print("[INFO] Disconnected from delay generator")

    def send_command(self, command):
        """Send a command string terminated with LF."""
        if not self.sock:
            raise ConnectionError("Socket is not connected. Call connect() first.")
        full_command = command.strip() + "\n"
        try:
            self.sock.sendall(full_command.encode("ascii"))
            print(f"[TX] {full_command.strip()}")
        except socket.error as e:
            print(f"[ERROR] Send failed: {e}")

    def read_response(self):
        """Read up to 1024 bytes from the delay generator."""
        if not self.sock:
            raise ConnectionError("Socket is not connected. Call connect() first.")
        try:
            data = self.sock.recv(1024).decode("ascii").strip()
            if data:
                print(f"[RX] {data}")
            return data
        except socket.timeout:
            print("[WARN] No response (timeout)")
            return None
        except socket.error as e:
            print(f"[ERROR] Receive failed: {e}")
            return None

    def query(self, command):
        """Send a query command and return the response."""
        self.send_command(command)
        time.sleep(0.1)  # small delay for device response
        return self.read_response()

    # ====== Specific Command Wrappers ======
    def set_delay(self, channel, delay_ps):
        self.send_command(f"DELAY T{channel},{delay_ps}")

    def get_delay(self, channel):
        return self.query(f"DELAY? T{channel}")

    def set_trigger(self, channel, mode):
        self.send_command(f"TRIG T{channel},{mode}")

    def get_trigger(self, channel):
        return self.query(f"TRIG? T{channel}")

    def set_frequency(self, channel, freq_hz):
        self.send_command(f"FREQ F{channel},{freq_hz}")

    def get_frequency(self, channel):
        return self.query(f"FREQ? F{channel}")


# ===================================
# Tkinter GUI
# ===================================
class DelayGeneratorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Delay Generator Controller")

        # Controller instance
        self.dg = DelayGeneratorController()

        # Track connection state
        self.connected = False

        # Build GUI
        self.build_connection_frame()
        self.build_delay_frame()
        self.build_trigger_frame()
        self.build_frequency_frame()

    # -----------------------------------
    # GUI Building
    # -----------------------------------
    def build_connection_frame(self):
        frame = ttk.LabelFrame(self.root, text="Connection", padding=10)
        frame.grid(row=0, column=0, sticky="ew", padx=10, pady=5)

        ttk.Label(frame, text="IP Address:").grid(row=0, column=0, sticky="w")
        self.ip_entry = ttk.Entry(frame, width=15)
        self.ip_entry.insert(0, "192.168.103.22")
        self.ip_entry.grid(row=0, column=1, padx=5)

        ttk.Label(frame, text="Port:").grid(row=0, column=2, sticky="w")
        self.port_entry = ttk.Entry(frame, width=6)
        self.port_entry.insert(0, "4000")
        self.port_entry.grid(row=0, column=3, padx=5)

        self.connect_btn = ttk.Button(frame, text="Connect", command=self.connect_device)
        self.connect_btn.grid(row=0, column=4, padx=5)

        self.disconnect_btn = ttk.Button(frame, text="Disconnect", command=self.disconnect_device, state="disabled")
        self.disconnect_btn.grid(row=0, column=5, padx=5)

        self.status_label = ttk.Label(frame, text="Disconnected", foreground="red")
        self.status_label.grid(row=0, column=6, padx=10)

    def build_delay_frame(self):
        frame = ttk.LabelFrame(self.root, text="Channel Delays (ps)", padding=10)
        frame.grid(row=1, column=0, sticky="ew", padx=10, pady=5)

        self.delay_entries = {}
        self.delay_labels = {}

        # Headers
        ttk.Label(frame, text="Channel").grid(row=0, column=0)
        ttk.Label(frame, text="Current").grid(row=0, column=1)
        ttk.Label(frame, text="New Value").grid(row=0, column=2)

        for i in range(10):
            ttk.Label(frame, text=f"T{i}").grid(row=i+1, column=0, sticky="w")
            current_val = ttk.Label(frame, text="---")
            current_val.grid(row=i+1, column=1)
            self.delay_labels[i] = current_val

            entry = ttk.Entry(frame, width=10)
            entry.grid(row=i+1, column=2)
            self.delay_entries[i] = entry

            set_btn = ttk.Button(frame, text="Set", command=lambda ch=i: self.set_delay(ch))
            set_btn.grid(row=i+1, column=3, padx=5)

    def build_trigger_frame(self):
        frame = ttk.LabelFrame(self.root, text="Trigger Settings", padding=10)
        frame.grid(row=2, column=0, sticky="ew", padx=10, pady=5)

        self.trigger_mode_var = tk.StringVar()
        self.trigger_mode_var.set("EXT")

        ttk.Label(frame, text="Trigger Mode:").grid(row=0, column=0, sticky="w")
        trigger_menu = ttk.OptionMenu(frame, self.trigger_mode_var, "EXT", "EXT", "IN1", "IN2")
        trigger_menu.grid(row=0, column=1, padx=5)

        ttk.Label(frame, text="Channel:").grid(row=0, column=2, sticky="w")
        self.trigger_channel_entry = ttk.Entry(frame, width=5)
        self.trigger_channel_entry.insert(0, "0")
        self.trigger_channel_entry.grid(row=0, column=3, padx=5)

        set_trigger_btn = ttk.Button(frame, text="Set Trigger", command=self.set_trigger)
        set_trigger_btn.grid(row=0, column=4, padx=5)

        self.trigger_status_label = ttk.Label(frame, text="---")
        self.trigger_status_label.grid(row=0, column=5, padx=10)

    def build_frequency_frame(self):
        frame = ttk.LabelFrame(self.root, text="Frequency Settings", padding=10)
        frame.grid(row=3, column=0, sticky="ew", padx=10, pady=5)

        self.freq_labels = {}
        self.freq_entries = {}

        for idx, label in enumerate(["F1", "F2"]):
            ttk.Label(frame, text=f"{label} Current:").grid(row=idx, column=0, sticky="w")
            current_label = ttk.Label(frame, text="---")
            current_label.grid(row=idx, column=1)
            self.freq_labels[label] = current_label

            ttk.Label(frame, text="New Value (Hz):").grid(row=idx, column=2, sticky="w")
            entry = ttk.Entry(frame, width=10)
            entry.grid(row=idx, column=3, padx=5)
            self.freq_entries[label] = entry

            set_btn = ttk.Button(frame, text="Set", command=lambda f=label: self.set_frequency(f))
            set_btn.grid(row=idx, column=4, padx=5)

        refresh_btn = ttk.Button(frame, text="Refresh", command=self.refresh_all)
        refresh_btn.grid(row=2, column=0, columnspan=2, pady=5)

    # -----------------------------------
    # Actions
    # -----------------------------------
    def connect_device(self):
        ip = self.ip_entry.get().strip()
        port = int(self.port_entry.get().strip())

        self.dg.ip = ip
        self.dg.port = port

        if self.dg.connect():
            self.connected = True
            self.status_label.config(text="Connected", foreground="green")
            self.connect_btn.config(state="disabled")
            self.disconnect_btn.config(state="normal")
            self.refresh_all()
        else:
            messagebox.showerror("Connection Error", "Failed to connect to delay generator.")

    def disconnect_device(self):
        self.dg.disconnect()
        self.connected = False
        self.status_label.config(text="Disconnected", foreground="red")
        self.connect_btn.config(state="normal")
        self.disconnect_btn.config(state="disabled")

    def set_delay(self, channel):
        if not self.connected:
            messagebox.showerror("Error", "Not connected to device")
            return
        try:
            delay_val = int(self.delay_entries[channel].get())
            self.dg.set_delay(channel, delay_val)
            self.refresh_all()
        except ValueError:
            messagebox.showerror("Invalid Input", f"Delay for T{channel} must be an integer.")

    def set_trigger(self):
        if not self.connected:
            messagebox.showerror("Error", "Not connected to device")
            return
        try:
            channel = int(self.trigger_channel_entry.get())
            mode = self.trigger_mode_var.get()
            self.dg.set_trigger(channel, mode)
            self.refresh_all()
        except ValueError:
            messagebox.showerror("Invalid Input", "Trigger channel must be an integer.")

    def set_frequency(self, freq_label):
        if not self.connected:
            messagebox.showerror("Error", "Not connected to device")
            return
        try:
            freq_val = int(self.freq_entries[freq_label].get())
            channel_num = 1 if freq_label == "F1" else 2
            self.dg.set_frequency(channel_num, freq_val)
            self.refresh_all()
        except ValueError:
            messagebox.showerror("Invalid Input", f"Frequency for {freq_label} must be an integer.")

    def refresh_all(self):
        """Query all current settings and update GUI."""
        if not self.connected:
            return

        def worker():
            for i in range(10):
                resp = self.dg.get_delay(i)
                if resp and "," in resp:
                    self.delay_labels[i].config(text=resp.split(",")[1])

            for f_label, f_num in [("F1", 1), ("F2", 2)]:
                resp = self.dg.get_frequency(f_num)
                if resp and "," in resp:
                    self.freq_labels[f_label].config(text=resp.split(",")[1])

        threading.Thread(target=worker, daemon=True).start()


# ===================================
# Run the GUI
# ===================================
if __name__ == "__main__":
    root = tk.Tk()
    app = DelayGeneratorGUI(root)
    root.mainloop()



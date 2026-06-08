import socket
import time
import tkinter as tk
from tkinter import ttk, messagebox

# ===============================
# Backend Controller
# ===============================
class DelayGeneratorController:
    def __init__(self, ip="192.168.103.22", port=4000, timeout=2.0):
        self.ip = ip
        self.port = port
        self.timeout = timeout
        self.sock = None

    def connect(self):
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

    # ===== Specific Command Wrappers =====
    def set_delay(self, channel, delay_ps):
        self.send_command(f"DELAY T{channel},{int(delay_ps)}")

    def get_delay(self, channel):
        return self.query(f"DELAY? T{channel}")

# ===============================
# GUI Application
# ===============================
class DelayGeneratorGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Delay Generator Controller")

        # Backend
        self.controller = DelayGeneratorController()

        # High-level variables (user input)
        self.p1 = tk.DoubleVar()
        self.p2 = tk.DoubleVar()
        self.p3 = tk.DoubleVar()
        self.s1 = tk.DoubleVar()
        self.s2 = tk.DoubleVar()

        # ADV variable with its own unit
        self.adv = tk.DoubleVar(value=16.625)
        self.adv_unit = tk.StringVar(value="ms")

        # Manual t8 and t9
        self.t8 = tk.DoubleVar()
        self.t9 = tk.DoubleVar()

        # Selected time unit for P/S inputs (ps, ns, us)
        self.unit = tk.StringVar(value="ps")

        # Computed delays for T0-T9
        self.delays = [tk.DoubleVar() for _ in range(10)]

        # Build GUI
        self.build_gui()

    def build_gui(self):
        # Connection frame
        conn_frame = ttk.LabelFrame(self.root, text="Connection")
        conn_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(conn_frame, text="Connect", command=self.connect_device).pack(side="left", padx=5, pady=5)
        ttk.Button(conn_frame, text="Disconnect", command=self.controller.disconnect).pack(side="left", padx=5, pady=5)

        # Unit selection (for P/S inputs)
        ttk.Label(conn_frame, text="P/S Time Unit:").pack(side="left", padx=5)
        ttk.Combobox(conn_frame, textvariable=self.unit, values=["ps", "ns", "us", "ms"], width=5, state="readonly").pack(side="left", padx=5)

        # High-level variable frame
        hl_frame = ttk.LabelFrame(self.root, text="High-Level Pulse Settings")
        hl_frame.pack(fill="x", padx=10, pady=5)

        for idx, (label, var) in enumerate(zip(["P1", "P2", "P3", "S1", "S2"], [self.p1, self.p2, self.p3, self.s1, self.s2])):
            ttk.Label(hl_frame, text=label).grid(row=0, column=idx*2, padx=5, pady=5)
            ttk.Entry(hl_frame, textvariable=var, width=8).grid(row=0, column=idx*2+1, padx=5, pady=5)

        # ADV input with its own unit selector
        adv_frame = ttk.LabelFrame(self.root, text="Advance (ADV)")
        adv_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(adv_frame, text="ADV:").grid(row=0, column=0, padx=5, pady=5)
        ttk.Entry(adv_frame, textvariable=self.adv, width=12).grid(row=0, column=1, padx=5, pady=5)
        ttk.Combobox(adv_frame, textvariable=self.adv_unit, values=["ps", "ns", "us", "ms"], width=5, state="readonly").grid(row=0, column=2, padx=5, pady=5)

        # Manual T8 and T9 frame
        manual_frame = ttk.LabelFrame(self.root, text="Manual T8 & T9")
        manual_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(manual_frame, text="T8").grid(row=0, column=0, padx=5, pady=5)
        ttk.Entry(manual_frame, textvariable=self.t8, width=8).grid(row=0, column=1, padx=5, pady=5)
        ttk.Label(manual_frame, text="T9").grid(row=0, column=2, padx=5, pady=5)
        ttk.Entry(manual_frame, textvariable=self.t9, width=8).grid(row=0, column=3, padx=5, pady=5)

        # Computation & Send buttons
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=10, pady=5)
        ttk.Button(btn_frame, text="Calculate T0-T7", command=self.calculate_delays).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Send All", command=self.send_all).pack(side="left", padx=5)

        # Table for displaying T0-T9
        table_frame = ttk.LabelFrame(self.root, text="Current Delay Settings (ps)")
        table_frame.pack(fill="both", expand=True, padx=10, pady=5)

        self.tree = ttk.Treeview(table_frame, columns=("Channel", "Delay"), show="headings")
        self.tree.heading("Channel", text="Channel")
        self.tree.heading("Delay", text="Delay (ps)")
        self.tree.column("Channel", width=80, anchor="center")
        self.tree.column("Delay", width=150, anchor="center")
        self.tree.pack(fill="both", expand=True)

        for i in range(10):
            self.tree.insert("", "end", iid=f"T{i}", values=(f"T{i}", "-"))

    # ===============================
    # Helper Functions
    # ===============================
    def connect_device(self):
        if self.controller.connect():
            messagebox.showinfo("Connected", "Successfully connected to delay generator")

    def convert_to_ps(self, value, unit=None):
        if unit is None:
            unit = self.unit.get()
        if unit == "ps":
            return value
        elif unit == "ns":
            return value * 1_000
        elif unit == "us":
            return value * 1_000_000
        elif unit == "ms":
            return value * 1_000_000_000

    def calculate_delays(self):
        # Convert ADV from its selected unit to ps
        adv = self.convert_to_ps(self.adv.get(), unit=self.adv_unit.get())

        t0 = 0
        t1 = adv - (244 * 1_000_000)  # 244 us in ps
        t2 = adv - (179 * 1_000_000)  # 179 us in ps
        t3 = t2

        # Convert P/S inputs to ps
        p1 = self.convert_to_ps(self.p1.get())
        p2 = self.convert_to_ps(self.p2.get())
        p3 = self.convert_to_ps(self.p3.get())
        s1 = self.convert_to_ps(self.s1.get())
        s2 = self.convert_to_ps(self.s2.get())

        # Compute t4-t9
        t4 = adv
        t5 = adv + p1
        t6 = t5 + s1
        t7 = t6 + p2
        t8 = t7 + s2
        t9 = t8 + p3
        computed = [t0, t1, t2, t3, t4, t5, t6, t7, t8, t9]

        # Update GUI table and internal vars
        for i, val in enumerate(computed):
            self.delays[i].set(val)
            self.tree.item(f"T{i}", values=(f"T{i}", f"{val:.0f}"))

    def send_all(self):
        if not self.controller.sock:
            messagebox.showerror("Error", "Not connected to device.")
            return

        for i, val in enumerate(self.delays):
            self.controller.set_delay(i, val.get())

        messagebox.showinfo("Success", "All delays sent to device!")

# ===============================
# Run App
# ===============================
if __name__ == "__main__":
    root = tk.Tk()
    app = DelayGeneratorGUI(root)
    root.mainloop()


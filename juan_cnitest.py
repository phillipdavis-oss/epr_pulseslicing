import serial
import serial.tools.list_ports
import time
import struct

MAX_LASERS = 5
STATUS_ADDR = 0x5D
CONFIG_ADDR = 0x7F

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
    0x8201, 0x42C0, 0x4380, 0x8341, 0x4100, 0x81C1, 0x8081, 0x4040
]


def hex_str(data: bytes):
    return ' '.join(f'{b:02X}' for b in data)

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

def crc16(data: bytearray) -> int:
    crc = 0xFFFF
    for byte in data:
        byte = int(byte) & 0xFF
        crc = (crc >> 8) ^ CRC16_LOOKUP_TABLE[(crc ^ byte) & 0xFF]
    return crc & 0xFFFF

def decode_status_response(response):
    if not response or len(response) < 32:
        return "Invalid or empty status response"

    def get_float(data, offset):
        return struct.unpack('<f', data[offset:offset+4])[0]

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
        temps = [get_float(response, i) for i in range(28, 28 + 4*6, 4)]

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
            f"Discharges: {discharges}"
        ]

        return "Pre-Fire Checklist:\n" + '\n'.join(prefire) + "\nTemperatures: " + ', '.join(f"{t:.1f}C" for t in temps)
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

def configure_laser(ser):
    gear = int(input("Enter gear (0–6): "))
    trig = int(input("Trigger mode (0=int, 1=ext): "))
    freq = float(input("Enter frequency in Hz: "))
    send_gear_command(ser, CONFIG_ADDR, gear)
    send_trigger_command(ser, CONFIG_ADDR, trig)
    send_frequency_command(ser, CONFIG_ADDR, freq)

def interactive_loop(lasers):
    while True:
        print("\nConnected lasers:")
        for idx, (port, _) in enumerate(lasers):
            print(f"[{idx+1}] {port}")
        choice = input("Select laser (1–5) or 'q' to quit: ").strip().lower()
        if choice == 'q':
            break
        try:
            index = int(choice) - 1
            if 0 <= index < len(lasers):
                _, ser = lasers[index]
                while True:
                    cmd = input("Command [status, fire, disable, config, back]: ").strip().lower()
                    if cmd == 'status':
                        resp = send_status_command(ser, STATUS_ADDR)
                        print(decode_status_response(resp))
                    elif cmd == 'fire':
                        send_enable_command(ser, CONFIG_ADDR)
                    elif cmd == 'disable':
                        send_disable_command(ser, CONFIG_ADDR)
                    elif cmd == 'config':
                        configure_laser(ser)
                    elif cmd == 'back':
                        break
                    else:
                        print("Unknown command.")
            else:
                print("Invalid selection.")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == "__main__":
    lasers = scan_for_lasers()
    if not lasers:
        print("No RS232 lasers detected.")
    else:
        interactive_loop(lasers)
        for _, ser in lasers:
            send_disable_command(ser, CONFIG_ADDR)
            ser.close()

















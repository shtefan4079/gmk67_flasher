import hid
import time
import sys
import os
import struct

# Configuration
PKG_FILE = "recovery.pkg"

def find_and_connect(vid, pid, timeout=1, quiet=True):
    if not quiet: print(f"[*] Searching for {vid:04x}:{pid:04x}...")
    start = time.time()
    devices = []
    while time.time() - start < timeout:
        # Try to find a device matching VID/PID
        devices = [d for d in hid.enumerate() if d['vendor_id'] == vid and d['product_id'] == pid]
        if devices:
            # Sort to prefer higher interface numbers (usually 1 is the control interface)
            # but keep 0/ -1 as fallbacks.
            sorted_devs = sorted(devices, key=lambda x: x.get('interface_number', -1), reverse=True)
            for d in sorted_devs:
                if d.get('interface_number', -1) in [1, 0, -1, 2]:
                    try:
                        dev = hid.device()
                        dev.open_path(d['path'])
                        if not quiet: print(f"[+] Connected to {vid:04x}:{pid:04x} via {d['path']} (IF: {d.get('interface_number')})")
                        return dev
                    except:
                        continue
        time.sleep(0.5)
    return None

def load_pkg(filename):
    if not os.path.exists(filename):
        return None
    
    commands = []
    with open(filename, "rb") as f:
        magic = f.read(4)
        if magic != b"PKG1":
            print("[!] Invalid package format.")
            return None
        
        count = struct.unpack("<I", f.read(4))[0]
        for _ in range(count):
            vid, pid, ctype, dlen = struct.unpack("<HHBB", f.read(6))
            data = f.read(dlen)
            commands.append({
                'vid_pid': (vid, pid),
                'type': "0x02" if ctype == 2 else "0x03",
                'data': data
            })
    return commands

def main():
    print("=== GMK67 Universal Flasher (Standalone PKG) ===")
    
    commands = load_pkg(PKG_FILE)
    if not commands:
        print(f"[!] Could not load {PKG_FILE}. Run compile_recovery.py first.")
        return
    
    print(f"[*] Loaded {len(commands)} commands from {PKG_FILE}.")

    # 1. Detect Current State
    print("[*] Detecting keyboard state...")
    # Gather all unique VID/PIDs from the package
    known_vpt = list(set([cmd['vid_pid'] for cmd in commands]))
    
    connected_vid_pid = None
    for vid, pid in known_vpt:
        dev = find_and_connect(vid, pid, timeout=0.1)
        if dev:
            connected_vid_pid = (vid, pid)
            dev.close()
            print(f"[+] Found keyboard: {vid:04x}:{pid:04x}")
            break
    
    if not connected_vid_pid:
        print("[!] Keyboard not found. Is it plugged in?"); return

    # 2. Find Start Index
    start_index = 0
    for i, cmd in enumerate(commands):
        if cmd['vid_pid'] == connected_vid_pid:
            start_index = i
            print(f"[*] Starting at sequence index {i} (matching state {connected_vid_pid[0]:04x}:{connected_vid_pid[1]:04x})")
            break

    # 3. Replay
    current_dev = None
    current_vid_pid = (0, 0)
    
    # Progress Bar simulation
    total = len(commands) - start_index
    
    for i in range(start_index, len(commands)):
        cmd = commands[i]
        target_vid, target_pid = cmd['vid_pid']
        
        # Connection management
        if (target_vid, target_pid) != current_vid_pid:
            if current_dev: current_dev.close()
            print(f"\n[*] Sequence {i} targets {target_vid:04x}:{target_pid:04x}. Connecting...")
            current_dev = find_and_connect(target_vid, target_pid, timeout=1, quiet=False)
            if not current_dev:
                # Retry for transitions (up to 15s)
                current_dev = find_and_connect(target_vid, target_pid, timeout=15, quiet=False)
            
            if not current_dev:
                print(f"[!] Device {target_vid:04x}:{target_pid:04x} not found."); break
            current_vid_pid = (target_vid, target_pid)

        # Send data directly
        report = cmd['data']
        try:
            # Prepend 0x00 Report ID for Linux hidapi compatibility
            payload = b'\x00' + report
            if cmd['type'] == "0x02": 
                res = current_dev.send_feature_report(payload)
                if res < 0: raise IOError(f"Feature Report failed: {res}")
            else: 
                res = current_dev.write(payload)
                if res < 0: raise IOError(f"Write failed: {res}")
            
            if i % 10 == 0:
                percent = int((i - start_index) / total * 100)
                sys.stdout.write(f"\rFlash Progress: [{('#' * (percent // 2)).ljust(50)}] {percent}% ({i}/{len(commands)})")
                sys.stdout.flush()
            
            # Increased delay to 20ms for FLASH memory stability
            time.sleep(0.02)
        except Exception as e:
            print(f"\n[!] Error at index {i}: {e}")
            # IO errors are expected during reboots, try to reconnect in next iteration
            current_dev = None; current_vid_pid = (0, 0)
            time.sleep(1) # Extra wait on error

    if current_dev: current_dev.close()
    print("\n[+] Done! Keyboard successfully flashed/recovered.")

if __name__ == "__main__":
    main()

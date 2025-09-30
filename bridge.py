#!/usr/bin/env python3
"""
bridge.py - ExynosBridge implementation (safe defaults)

This file exposes:
 - ExynosBridge class with connect/disconnect
 - partition discovery via PIT (heimdall preferred)
 - read_partition, write_partition, erase_partition (heimdall preferred)
"""

import os
import sys
import time
import struct
import shutil
import subprocess
import tempfile
import re
from typing import Optional, Dict, List

try:
    import usb.core
    import usb.util
except Exception:
    usb = None

SAMSUNG_VID = 0x04E8
EXYNOS_ODIN_PIDS = [0x685D, 0x6860, 0x6861, 0x6863, 0x6864, 0x6866, 0x7000]
ODIN_MAGIC = b"ODIN"
LOKE_MAGIC = b"LOKE"

DEFAULT_TIMEOUT_MS = 30000

class XynError(Exception):
    pass

# -------------------- Small Partition types --------------------
class Partition:
    def __init__(self, name: str, start: Optional[int] = None, length: Optional[int] = None, id: Optional[int] = None):
        self.name = name.lower()
        self.start = start
        self.length = length
        self.id = id

    def to_dict(self):
        return {'name': self.name, 'start': self.start, 'length': self.length, 'id': self.id}

# -------------------- PIT Parser (heuristic + heimdall) --------------------
class PitParser:
    def __init__(self, heimdall_path: Optional[str] = None):
        self.heimdall = heimdall_path or shutil.which("heimdall")

    def parse_with_heimdall_file(self, pit_path: str) -> List[Partition]:
        if not self.heimdall:
            raise FileNotFoundError("heimdall not found")
        cmds = [
            [self.heimdall, "print-pit", "--pit", pit_path],
            [self.heimdall, "print-pit", pit_path]
        ]
        for cmd in cmds:
            try:
                p = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
                if p.returncode == 0 and p.stdout:
                    return self._parse_text(p.stdout)
            except Exception:
                continue
        raise RuntimeError("heimdall print-pit failed")

    def parse_heuristic(self, pit_bytes: bytes) -> List[Partition]:
        # Find ascii tokens terminated by zero bytes (likely partition names)
        tokens = re.findall(rb"([A-Za-z0-9_\-]{3,24})\x00", pit_bytes)
        seen = set()
        parts: List[Partition] = []
        for t in tokens:
            s = t.decode('ascii', errors='ignore').lower()
            if s in seen:
                continue
            seen.add(s)
            if s in ("pit", "samsung", "odinfw", "android", "bootloader"):
                continue
            parts.append(Partition(name=s))
        return parts

    def parse_via_heimdall_device(self, heimdall_bin: str) -> List[Partition]:
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pit")
        tmp_path = tmp.name
        tmp.close()
        try:
            cmd = [heimdall_bin, "download-pit", "--output", tmp_path]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if r.returncode != 0:
                raise RuntimeError("heimdall download-pit failed")
            return self.parse_with_heimdall_file(tmp_path)
        finally:
            try:
                os.remove(tmp_path)
            except Exception:
                pass

    def _parse_text(self, text: str) -> List[Partition]:
        parts: List[Partition] = []
        # parse lines containing Name: and Size:
        for line in text.splitlines():
            if "Name" in line or "Partition" in line:
                m = re.search(r"Name:\s*'([^']+)'|Name:\s*([A-Za-z0-9_\-]+)", line)
                if not m:
                    continue
                name = m.group(1) or m.group(2)
                size = None
                msize = re.search(r"Size:\s*0x([0-9A-Fa-f]+)", line)
                if msize:
                    size = int(msize.group(1), 16)
                pid = None
                mid = re.search(r"Identifier:\s*([0-9]+)|Id:\s*([0-9]+)", line)
                if mid:
                    pid = int(mid.group(1) or mid.group(2))
                parts.append(Partition(name=name.lower(), length=size, id=pid))
        return parts

    def parse(self, pit_bytes: Optional[bytes] = None, pit_path: Optional[str] = None, heimdall_bin: Optional[str] = None, bridge=None) -> List[Partition]:
        # prefer heimdall if available and path given
        hb = heimdall_bin or self.heimdall
        if hb and pit_path:
            try:
                return self.parse_with_heimdall_file(pit_path)
            except Exception:
                pass
        if hb and bridge:
            try:
                return self.parse_via_heimdall_device(hb)
            except Exception:
                pass
        if pit_bytes:
            return self.parse_heuristic(pit_bytes)
        if bridge:
            # try to download PIT file via bridge.download_pit and then parse heuristically
            tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pit")
            tmp_path = tmp.name
            tmp.close()
            try:
                ok = bridge.download_pit(tmp_path)
                if not ok:
                    raise RuntimeError("bridge.download_pit failed")
                with open(tmp_path, "rb") as fh:
                    data = fh.read()
                # try heimdall parsing if available
                if hb:
                    try:
                        return self.parse_with_heimdall_file(tmp_path)
                    except Exception:
                        pass
                return self.parse_heuristic(data)
            finally:
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
        return []

# -------------------- PartitionManager --------------------
class PartitionManager:
    def __init__(self, bridge):
        self.bridge = bridge
        self.parser = PitParser(heimdall_path=self._find_heimdall())
        self.partitions: Dict[str, Partition] = {}

    def _find_heimdall(self) -> Optional[str]:
        return shutil.which("heimdall")

    def detect_partition_layout(self) -> Dict[str, Dict]:
        parts: List[Partition] = []
        hb = self._find_heimdall()
        if hb:
            try:
                parts = self.parser.parse(heimdall_bin=hb, bridge=self.bridge)
            except Exception:
                parts = []
        if not parts:
            parts = self.parser.parse(bridge=self.bridge)
        self.partitions = {p.name: p for p in parts}
        # Return a mapping name->dict for CLI printing
        return {name: p.to_dict() for name, p in self.partitions.items()}

    def get_partition_by_name(self, name: str) -> Optional[Partition]:
        if not self.partitions:
            self.detect_partition_layout()
        return self.partitions.get(name.lower())

    def guess_partition_identifier(self, name: str) -> int:
        p = self.get_partition_by_name(name)
        if p and p.id is not None:
            return p.id
        common_map = {
            'boot': 1, 'recovery': 2, 'system': 3, 'userdata': 4, 'cache': 5, 'modem': 6
        }
        return common_map.get(name.lower(), 0xFFFFFFFF)

# -------------------- ExynosBridge core --------------------
class ExynosBridge:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.dev = None
        self.interface = None
        self.in_ep = None
        self.out_ep = None
        self.detached_kernel = False
        self.session_established = False
        self.partition_manager = PartitionManager(self)

    def _log(self, *a):
        if self.verbose:
            print("[DEBUG]", *a)

    def _find_heimdall(self) -> Optional[str]:
        return shutil.which("heimdall")

    # Connect / disconnect
    def connect(self) -> bool:
        if not self.find_device():
            raise XynError("No Exynos device found in ODIN mode")
        self.open_and_claim()
        return True

    def disconnect(self) -> None:
        if self.dev and self.interface is not None:
            try:
                usb.util.release_interface(self.dev, self.interface)
            except Exception:
                pass
            if self.detached_kernel:
                try:
                    self.dev.attach_kernel_driver(self.interface)
                except Exception:
                    pass
        self.dev = None
        self.interface = None
        self.in_ep = None
        self.out_ep = None
        self.detached_kernel = False
        self.session_established = False

    # Device detection and claiming
    def find_device(self) -> bool:
        if usb is None:
            raise XynError("pyusb not available")
        for pid in EXYNOS_ODIN_PIDS:
            dev = usb.core.find(idVendor=SAMSUNG_VID, idProduct=pid)
            if dev:
                self.dev = dev
                self._log("Found device with PID 0x%04X" % pid)
                return True
        dev = usb.core.find(idVendor=SAMSUNG_VID)
        if dev:
            self.dev = dev
            self._log("Found Samsung device (fallback), PID=0x%04X" % dev.idProduct)
            return True
        return False

    def open_and_claim(self) -> None:
        if self.dev is None:
            raise XynError("No device to open")
        try:
            try:
                self.dev.set_configuration()
            except Exception:
                pass
            cfg = self.dev.get_active_configuration()
            chosen = None
            for intf in cfg:
                for alt in intf:
                    ep_in = ep_out = None
                    for ep in alt:
                        if usb.util.endpoint_direction(ep.bEndpointAddress) == usb.util.ENDPOINT_IN:
                            ep_in = ep
                        else:
                            ep_out = ep
                    if ep_in and ep_out:
                        chosen = (alt, ep_in.bEndpointAddress, ep_out.bEndpointAddress)
                        break
                if chosen:
                    break
            if not chosen:
                raise XynError("No suitable interface (requires bulk IN and OUT)")
            alt, in_ep, out_ep = chosen
            self.interface = alt.bInterfaceNumber
            self.in_ep = in_ep
            self.out_ep = out_ep
            try:
                if self.dev.is_kernel_driver_active(self.interface):
                    self._log("Detaching kernel driver")
                    self.dev.detach_kernel_driver(self.interface)
                    self.detached_kernel = True
            except Exception:
                pass
            usb.util.claim_interface(self.dev, self.interface)
            self._log("Interface claimed")
        except Exception as e:
            raise XynError(f"open_and_claim failed: {e}")

    # Basic handshake (ODIN -> expect LOKE)
    def establish_session(self, attempts: int = 3) -> bool:
        if self.dev is None:
            raise XynError("Device not connected")
        for attempt in range(attempts):
            try:
                self.dev.write(self.out_ep, ODIN_MAGIC, timeout=1000)
                resp = self.dev.read(self.in_ep, 8, timeout=2000)
                resp_b = resp.tobytes() if hasattr(resp, 'tobytes') else bytes(resp)
                self._log("Handshake resp:", resp_b)
                if resp_b.startswith(LOKE_MAGIC):
                    self.session_established = True
                    return True
            except Exception as e:
                self._log("Handshake attempt failed:", e)
                time.sleep(0.5)
        raise XynError("Handshake failed (device may not be in Download/Odin mode)")

    # download PIT: prefer heimdall; otherwise attempt conservative fallback
    def download_pit(self, out_path: str) -> bool:
        hb = self._find_heimdall()
        if hb:
            cmd = [hb, "download-pit", "--output", out_path]
            if self.verbose:
                cmd.append("--verbose")
            self._log("Running Heimdall:", " ".join(cmd))
            r = subprocess.run(cmd, capture_output=True)
            return r.returncode == 0
        # fallback: must have session
        if not self.session_established:
            self.establish_session()
        # Heuristic: attempt a short read (non-destructive) and save whatever comes
        try:
            chunk = None
            try:
                chunk = self.dev.read(self.in_ep, 4096, timeout=2000)
            except Exception:
                chunk = None
            if not chunk:
                raise XynError("No PIT data received (install heimdall for reliable PIT download)")
            data = chunk.tobytes() if hasattr(chunk, 'tobytes') else bytes(chunk)
            with open(out_path, "wb") as fh:
                fh.write(data)
            return True
        except Exception as e:
            raise XynError(f"PIT download fallback failed: {e}")

    # Low-level helper: call heimdall and return bool on success
    def _call_heimdall(self, args: List[str]) -> bool:
        hb = self._find_heimdall()
        if not hb:
            return False
        cmd = [hb] + args
        if self.verbose:
            cmd.append("--verbose")
        self._log("Calling heimdall:", " ".join(cmd))
        r = subprocess.run(cmd, capture_output=True)
        return r.returncode == 0

    # ------------------ Public partition operations ------------------
    def read_partition(self, partition_name: str, out_file: str) -> bool:
        # Prefer heimdall dump (read)
        if self._call_heimdall(["dump", partition_name, "--output", out_file]):
            self._log("Read via heimdall succeeded")
            return True
        # fallback: require partition table information (safe behavior)
        part = self.partition_manager.get_partition_by_name(partition_name)
        if not part:
            raise XynError(f"Partition '{partition_name}' not found (run partitions to detect PIT first)")
        # Without heimdall, we do not implement a generic, raw-flash read here.
        raise XynError("Reading partition without heimdall is not implemented (unsafe). Install heimdall or use a tested Python implementation.")

    def write_partition(self, partition_name: str, input_file: str, force: bool = False) -> bool:
        # If heimdall available, use it (recommended)
        if self._call_heimdall(["flash", partition_name, input_file]):
            self._log("Write via heimdall succeeded")
            return True
        # Otherwise, if user explicitly forces Python fallback, refuse until fully implemented
        if force:
            # placeholder: user asked to force; not implemented
            raise XynError("Python write fallback not implemented. To avoid accidental bricking, writing without heimdall is disabled.")
        raise XynError("Write requires heimdall or a completed Python flash implementation. Install heimdall or use --force (unsafe) after implementing the packet-level writer.")

    def erase_partition(self, partition_name: str, force: bool = False) -> bool:
        # Prefer heimdall 'erase' if available
        if self._call_heimdall(["erase", partition_name]):
            self._log("Erase via heimdall succeeded")
            return True
        # Only allow custom erase if forced and implemented
        if force:
            raise XynError("Python erase fallback not implemented. Avoid attempting erase without a proven implementation.")
        raise XynError("Erase requires heimdall or a completed Python eraser. Use --force to override (not implemented).")

from __future__ import annotations

import ctypes
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

GIB = 1024**3


@dataclass(frozen=True)
class HostMemory:
    total: int | None
    available: int | None
    swap_used: int | None


def _sysctl(name: str) -> str | None:
    binary = shutil.which("sysctl") or "/usr/sbin/sysctl"
    result = subprocess.run([binary, "-n", name], capture_output=True, text=True, check=False)  # noqa: S603
    return result.stdout.strip() if result.returncode == 0 else None


def _mac() -> HostMemory:
    total_text = _sysctl("hw.memsize")
    swap_text = _sysctl("vm.swapusage") or ""
    swap = re.search(r"used = ([0-9.]+)M", swap_text)
    available = None
    vm_stat = shutil.which("vm_stat") or "/usr/bin/vm_stat"
    vm = subprocess.run([vm_stat], capture_output=True, text=True, check=False).stdout  # noqa: S603
    page = re.search(r"page size of (\d+) bytes", vm)
    if page:
        pages = 0
        for key in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"):
            found = re.search(rf"{key}:\s+(\d+)", vm)
            pages += int(found.group(1)) if found else 0
        available = pages * int(page.group(1))
    return HostMemory(
        int(total_text) if total_text else None,
        available,
        int(float(swap.group(1)) * 1024**2) if swap else None,
    )


def _linux() -> HostMemory:
    info: dict[str, int] = {}
    meminfo = Path("/proc/meminfo")
    if meminfo.exists():
        for line in meminfo.read_text().splitlines():
            key, _, rest = line.partition(":")
            number = rest.strip().split(" ")[0]
            if number.isdigit():
                info[key] = int(number) * 1024
    swap_used = info["SwapTotal"] - info["SwapFree"] if "SwapTotal" in info and "SwapFree" in info else None
    return HostMemory(info.get("MemTotal"), info.get("MemAvailable"), swap_used)


def _windows() -> HostMemory:
    class MemoryStatus(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):  # type: ignore[attr-defined]
        return HostMemory(None, None, None)
    return HostMemory(status.ullTotalPhys, status.ullAvailPhys, None)


def host_memory() -> HostMemory:
    try:
        if sys.platform == "darwin":
            return _mac()
        if sys.platform == "win32":
            return _windows()
        return _linux()
    except (OSError, ValueError):
        return HostMemory(None, None, None)


def _gib(value: int | None) -> str:
    return "n/a" if value is None else f"{value / GIB:.1f} GiB"


def memory_summary() -> str:
    mem = host_memory()
    return f"total {_gib(mem.total)}, available {_gib(mem.available)}, swap used {_gib(mem.swap_used)}"

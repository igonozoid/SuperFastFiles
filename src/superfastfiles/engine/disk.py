"""Que tipo de disco está em cada ponta, e se origem e destino são o mesmo disco físico.

É isso que define a estratégia (como no FastCopy):
- mesmo disco giratório (HDD): uma coisa de cada vez, blocos grandes — evitar o vai-e-vem da cabeça de leitura;
- algum HDD: poucas threads;
- SSD/NVMe: muitas threads (o SSD rende mais com várias requisições em paralelo);
- rede: muitas threads (esconde a latência de cada arquivo).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from superfastfiles.i18n import tr

WIN = sys.platform == "win32"


@dataclass
class DiskInfo:
    ids: frozenset          # discos físicos que guardam o volume (vazio = não deu para saber)
    rotational: bool | None
    network: bool = False
    usb: bool = False

    @property
    def kind(self) -> str:
        if self.network:
            return tr("rede")
        if self.rotational is None:
            return "?"
        return "HDD" if self.rotational else "SSD"


@dataclass
class Strategy:
    name: str               # texto para o usuário
    small_threads: int      # threads para arquivos pequenos
    large_threads: int      # arquivos grandes copiados ao mesmo tempo
    chunk: int              # tamanho do bloco do pipeline
    depth: int              # blocos em voo por arquivo grande
    scan_threads: int
    mode: str = "ssd"


def _existing_parent(path: str) -> str:
    p = os.path.abspath(path)
    while not os.path.exists(p):
        parent = os.path.dirname(p)
        if parent == p:
            break
        p = parent
    return p


# Windows -----------------------------------------------------------------------
if WIN:
    import ctypes
    from ctypes import wintypes as wt

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.GetVolumePathNameW.argtypes = [wt.LPCWSTR, wt.LPWSTR, wt.DWORD]
    _k32.GetDriveTypeW.argtypes = [wt.LPCWSTR]
    _k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, wt.LPVOID, wt.DWORD, wt.DWORD, wt.HANDLE]
    _k32.CreateFileW.restype = wt.HANDLE
    _k32.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, wt.LPVOID, wt.DWORD, wt.LPVOID, wt.DWORD,
                                     ctypes.POINTER(wt.DWORD), wt.LPVOID]
    _k32.CloseHandle.argtypes = [wt.HANDLE]
    IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000
    IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400
    DRIVE_REMOTE = 4

    class _DISK_EXTENT(ctypes.Structure):
        _fields_ = [("DiskNumber", wt.DWORD), ("StartingOffset", ctypes.c_int64), ("ExtentLength", ctypes.c_int64)]

    class _VOLUME_DISK_EXTENTS(ctypes.Structure):
        _fields_ = [("NumberOfDiskExtents", wt.DWORD), ("Extents", _DISK_EXTENT * 16)]

    class _STORAGE_PROPERTY_QUERY(ctypes.Structure):
        _fields_ = [("PropertyId", ctypes.c_int), ("QueryType", ctypes.c_int), ("Extra", ctypes.c_ubyte * 1)]

    class _DEVICE_SEEK_PENALTY_DESCRIPTOR(ctypes.Structure):
        _fields_ = [("Version", wt.DWORD), ("Size", wt.DWORD), ("IncursSeekPenalty", wt.BOOLEAN)]

    class _DEVICE_TRIM_DESCRIPTOR(ctypes.Structure):
        _fields_ = [("Version", wt.DWORD), ("Size", wt.DWORD), ("TrimEnabled", wt.BOOLEAN)]

    class _STORAGE_DEVICE_DESCRIPTOR(ctypes.Structure):
        _fields_ = [("Version", wt.DWORD), ("Size", wt.DWORD), ("DeviceType", ctypes.c_ubyte),
                    ("DeviceTypeModifier", ctypes.c_ubyte), ("RemovableMedia", wt.BOOLEAN),
                    ("CommandQueueing", wt.BOOLEAN), ("VendorIdOffset", wt.DWORD), ("ProductIdOffset", wt.DWORD),
                    ("ProductRevisionOffset", wt.DWORD), ("SerialNumberOffset", wt.DWORD), ("BusType", ctypes.c_int),
                    ("RawPropertiesLength", wt.DWORD), ("Raw", ctypes.c_ubyte * 512)]

    BUS_USB = 7
    PROP_DEVICE, PROP_SEEK_PENALTY, PROP_TRIM = 0, 7, 8

    def _rotational(h) -> tuple[bool | None, bool]:
        """(giratório?, é USB?). Muitas pontes USB não respondem à pergunta direta ("tem atraso de busca?").
        Aí: TRIM ligado = SSD; USB sem TRIM = tratar como HD (escolha segura: com poucas threads um SSD perde
        pouco, mas com 64 threads um HD fica muito lento, a cabeça de leitura pulando de arquivo em arquivo)."""
        dev = _STORAGE_DEVICE_DESCRIPTOR()
        usb = _ioctl(h, IOCTL_STORAGE_QUERY_PROPERTY, _STORAGE_PROPERTY_QUERY(PROP_DEVICE, 0), dev) and \
            dev.BusType == BUS_USB
        seek = _DEVICE_SEEK_PENALTY_DESCRIPTOR()
        if _ioctl(h, IOCTL_STORAGE_QUERY_PROPERTY, _STORAGE_PROPERTY_QUERY(PROP_SEEK_PENALTY, 0), seek):
            return bool(seek.IncursSeekPenalty), usb
        trim = _DEVICE_TRIM_DESCRIPTOR()
        if _ioctl(h, IOCTL_STORAGE_QUERY_PROPERTY, _STORAGE_PROPERTY_QUERY(PROP_TRIM, 0), trim) and trim.TrimEnabled:
            return False, usb
        return (True if usb else None), usb

    def _ioctl(h, code, inbuf, outbuf) -> bool:
        ret = wt.DWORD(0)
        return bool(_k32.DeviceIoControl(h, code, ctypes.byref(inbuf) if inbuf is not None else None,
                                         ctypes.sizeof(inbuf) if inbuf is not None else 0,
                                         ctypes.byref(outbuf), ctypes.sizeof(outbuf), ctypes.byref(ret), None))

    def _open_dev(path: str):
        h = _k32.CreateFileW(path, 0, 3, None, 3, 0, None)        # sem acesso a dados: não precisa de admin
        return None if h in (None, wt.HANDLE(-1).value) else h

    def disk_info(path: str) -> DiskInfo:
        p = _existing_parent(path.removeprefix("\\\\?\\"))
        if p.startswith("\\\\") and not p.startswith("\\\\.\\"):
            return DiskInfo(frozenset({"net:" + p.split("\\")[2].lower()}), None, True)
        buf = ctypes.create_unicode_buffer(1024)
        if not _k32.GetVolumePathNameW(p, buf, 1024):
            return DiskInfo(frozenset(), None)
        vol = buf.value
        if _k32.GetDriveTypeW(vol) == DRIVE_REMOTE:
            return DiskInfo(frozenset({"net:" + vol.lower()}), None, True)
        h = _open_dev("\\\\.\\" + vol.rstrip("\\"))
        if h is None:
            return DiskInfo(frozenset({vol.lower()}), None)
        disks = set()
        try:
            ext = _VOLUME_DISK_EXTENTS()
            if _ioctl(h, IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS, None, ext):
                for i in range(min(ext.NumberOfDiskExtents, 16)):
                    disks.add(ext.Extents[i].DiskNumber)
            rot, usb = _rotational(h)
        finally:
            _k32.CloseHandle(h)
        return DiskInfo(frozenset(f"disk{n}" for n in disks) or frozenset({vol.lower()}), rot, usb=usb)

# Linux / macOS -------------------------------------------------------------------
else:
    def _linux_disk(dev: int) -> tuple[set, bool | None]:
        major, minor = os.major(dev), os.minor(dev)
        base = f"/sys/dev/block/{major}:{minor}"
        try:
            real = os.path.realpath(base)
        except OSError:
            return set(), None
        if not os.path.exists(real):
            return set(), None
        # partição -> disco pai; dm/md -> discos de baixo (slaves)
        disk = real if os.path.exists(os.path.join(real, "queue")) else os.path.dirname(real)
        names = {os.path.basename(disk)}
        slaves = os.path.join(disk, "slaves")
        rots = []
        if os.path.isdir(slaves) and os.listdir(slaves):
            names = set()
            for s in os.listdir(slaves):
                sub = os.path.realpath(os.path.join(slaves, s))
                sd = sub if os.path.exists(os.path.join(sub, "queue")) else os.path.dirname(sub)
                names.add(os.path.basename(sd))
                rots.append(_rot(sd))
        else:
            rots.append(_rot(disk))
        known = [r for r in rots if r is not None]
        return names, (any(known) if known else None)

    def _rot(disk: str) -> bool | None:
        try:
            with open(os.path.join(disk, "queue", "rotational")) as f:
                return f.read().strip() == "1"
        except OSError:
            return None

    def _is_network(path: str) -> bool:
        if sys.platform.startswith("linux"):
            try:
                best, fstype = "", ""
                with open("/proc/mounts") as f:
                    for line in f:
                        parts = line.split()
                        mnt = parts[1].replace("\\040", " ")
                        if path.startswith(mnt) and len(mnt) > len(best):
                            best, fstype = mnt, parts[2]
                return fstype in {"nfs", "nfs4", "cifs", "smb3", "smbfs", "sshfs", "fuse.sshfs", "9p", "afs"}
            except OSError:
                return False
        return False

    def disk_info(path: str) -> DiskInfo:
        p = _existing_parent(path)
        try:
            dev = os.stat(p).st_dev
        except OSError:
            return DiskInfo(frozenset(), None)
        if _is_network(p):
            return DiskInfo(frozenset({f"net:{dev}"}), None, True)
        if sys.platform.startswith("linux"):
            names, rot = _linux_disk(dev)
            return DiskInfo(frozenset(names) or frozenset({f"dev:{dev}"}), rot)
        return DiskInfo(frozenset({f"dev:{dev}"}), False)        # macOS: praticamente só SSD hoje


def choose_strategy(src: DiskInfo, dst: DiskInfo, forced: str = "auto", threads: int = 0,
                    buffer_mb: int = 0) -> Strategy:
    cpu = os.cpu_count() or 4
    same = bool(src.ids & dst.ids)
    mode = forced
    if mode == "auto":
        if same and (src.rotational or dst.rotational):
            mode = "same"
        elif src.rotational or dst.rotational:
            mode = "hdd"
        elif src.network or dst.network:
            mode = "net"
        else:
            mode = "ssd"
    if mode == "same":
        s = Strategy(tr("Mesmo disco (HDD): sequencial, blocos grandes"), 1, 1, 32 << 20, 3, 2)
    elif mode == "hdd":
        s = Strategy(tr("Disco rígido (HDD): poucas threads"), 4, 1, 16 << 20, 4, 4)
    elif mode == "net":
        s = Strategy(tr("Rede: muitas threads"), min(32, cpu * 4), 2, 8 << 20, 4, 16)
    else:
        # Arquivos pequenos: o custo é abrir/criar/fechar (e o antivírus olhando cada um); muitas threads
        # escondem essa latência. Medido: 64 threads ~40% mais rápido que 16 num NVMe com 16 núcleos.
        s = Strategy(tr("SSD/NVMe: leitura e escrita em paralelo"), min(64, max(8, cpu * 4)), 2, 8 << 20, 4, 8)
    s.mode = mode
    if same and mode == "ssd":
        s.name = tr("Mesmo SSD: paralelo")
    if threads:
        s.small_threads = threads
    if buffer_mb:
        s.chunk = buffer_mb << 20
    return s

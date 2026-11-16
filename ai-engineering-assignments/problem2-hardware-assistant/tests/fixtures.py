"""Realistic command outputs captured from the formats of lscpu/lsblk/free/lspci/dmidecode on a laptop."""
import json

LSCPU_JSON = json.dumps({"lscpu": [
    {"field": "Architecture:", "data": "x86_64", "children": [
        {"field": "CPU op-mode(s):", "data": "32-bit, 64-bit"}]},
    {"field": "CPU(s):", "data": "8", "children": [{"field": "On-line CPU(s) list:", "data": "0-7"}]},
    {"field": "Vendor ID:", "data": "GenuineIntel", "children": [
        {"field": "Model name:", "data": "11th Gen Intel(R) Core(TM) i7-1165G7 @ 2.80GHz",
         "children": [{"field": "Thread(s) per core:", "data": "2"}, {"field": "Core(s) per socket:", "data": "4"},
                      {"field": "Socket(s):", "data": "1"}, {"field": "CPU max MHz:", "data": "4700.0000"},
                      {"field": "CPU min MHz:", "data": "400.0000"}]}]},
    {"field": "Virtualization:", "data": "VT-x"},
    {"field": "Caches (sum of all):", "data": "", "children": [
        {"field": "L1d:", "data": "192 KiB (4 instances)"}, {"field": "L2:", "data": "5 MiB (4 instances)"}]},
    {"field": "L1d cache:", "data": "192 KiB (4 instances)"}, {"field": "L1i cache:", "data": "128 KiB (4 instances)"},
    {"field": "L2 cache:", "data": "5 MiB (4 instances)"}, {"field": "L3 cache:", "data": "12 MiB (1 instance)"},
]})

PROC_CPUINFO = """processor\t: 0
vendor_id\t: AuthenticAMD
model name\t: AMD Ryzen 7 5800U with Radeon Graphics
cpu MHz\t\t: 1900.000

processor\t: 1
vendor_id\t: AuthenticAMD
model name\t: AMD Ryzen 7 5800U with Radeon Graphics
cpu MHz\t\t: 4400.123
"""

FREE_B = """               total        used        free      shared  buff/cache   available
Mem:     16611606528  4123456789  8000000000   312000000  4488149739 12000000000
Swap:     8589930496           0  8589930496
"""

MEMINFO = """MemTotal:       16222272 kB
MemFree:         8000000 kB
MemAvailable:   11718750 kB
SwapTotal:       8388604 kB
SwapFree:        8388604 kB
"""

LSBLK_JSON = json.dumps({"blockdevices": [
    {"name": "nvme0n1", "type": "disk", "size": 512110190592, "rota": False, "model": "Samsung SSD 970 EVO Plus 512GB",
     "tran": "nvme", "fstype": None, "mountpoints": [None], "rm": False, "ro": False, "pkname": None, "children": [
         {"name": "nvme0n1p1", "type": "part", "size": 536870912, "fstype": "vfat", "mountpoints": ["/boot/efi"]},
         {"name": "nvme0n1p2", "type": "part", "size": 511000000000, "fstype": "ext4", "mountpoints": ["/"]}]},
    {"name": "sda", "type": "disk", "size": 1000204886016, "rota": True, "model": "WDC WD10SPZX-24Z", "tran": "sata",
     "rm": False, "ro": False, "children": []},
    {"name": "zram0", "type": "disk", "size": 8589934592, "rota": False, "model": None, "tran": None},
    {"name": "loop0", "type": "loop", "size": 4096, "rota": False},
]})

DMI_BASEBOARD = """# dmidecode 3.5
Getting SMBIOS data from sysfs.
SMBIOS 3.3.0 present.

Handle 0x0002, DMI type 2, 15 bytes
Base Board Information
\tManufacturer: LENOVO
\tProduct Name: 20XWCTO1WW
\tVersion: SDK0J40697 WIN
\tSerial Number: PF2ABCDE
\tAsset Tag: Not Available
"""
DMI_BIOS = """Handle 0x0000, DMI type 0, 26 bytes
BIOS Information
\tVendor: LENOVO
\tVersion: N32ET85W (1.60 )
\tRelease Date: 03/05/2022
\tCharacteristics:
\t\tPCI is supported
"""
DMI_SYSTEM = """Handle 0x0001, DMI type 1, 27 bytes
System Information
\tManufacturer: LENOVO
\tProduct Name: 20XWCTO1WW
\tVersion: ThinkPad X1 Carbon Gen 9
\tSerial Number: PF2ABCDE
\tUUID: 6bf7a0b6-1111-2222-3333-444455556666
"""
DMI_MEMORY = """Handle 0x0007, DMI type 16, 23 bytes
Physical Memory Array
\tLocation: System Board Or Motherboard
\tMaximum Capacity: 64 GB
\tNumber Of Devices: 4

Handle 0x0008, DMI type 17, 40 bytes
Memory Device
\tSize: 8 GB
\tForm Factor: SODIMM
\tLocator: ChannelA-DIMM0
\tType: DDR4
\tSpeed: 3200 MT/s
\tManufacturer: Samsung
\tSerial Number: 12345678
\tPart Number: M471A1K43DB1-CWE
\tConfigured Memory Speed: 3200 MT/s

Handle 0x0009, DMI type 17, 40 bytes
Memory Device
\tSize: 8 GB
\tForm Factor: SODIMM
\tLocator: ChannelB-DIMM0
\tType: DDR4
\tSpeed: 3200 MT/s
\tManufacturer: Samsung

Handle 0x000A, DMI type 17, 40 bytes
Memory Device
\tSize: No Module Installed
\tLocator: ChannelA-DIMM1
"""

LSPCI = """Slot:\t00:02.0
Class:\tVGA compatible controller [0300]
Vendor:\tIntel Corporation [8086]
Device:\tTigerLake-LP GT2 [Iris Xe Graphics] [9a49]
Driver:\ti915

Slot:\t01:00.0
Class:\t3D controller [0302]
Vendor:\tNVIDIA Corporation [10de]
Device:\tGA107M [GeForce RTX 3050 Mobile] [25a2]
Driver:\tnvidia

Slot:\t00:1f.3
Class:\tAudio device [0403]
Vendor:\tIntel Corporation [8086]
Device:\tTigerLake-LP Smart Sound Technology Audio Controller [a0c8]
"""

LSPCI_UNKNOWN_GPU = """Slot:\t00:02.0
Class:\tVGA compatible controller [0300]
Vendor:\tRed Hat, Inc. [1af4]
Device:\tDevice [1111]
"""

NVIDIA_SMI = "NVIDIA GeForce RTX 3050 Laptop GPU, 4096, 535.154.05\n"

# XynClient

**XynClient** is a low-level tool for accessing Samsung Exynos devices in ODIN/Download mode. It supports safe partition discovery, reading, writing, and erasing operations—preferably via the [heimdall](https://github.com/Benjamin-Dobell/Heimdall) utility for maximum safety.

## Features

- **Device Detection:** Connects to Exynos devices in ODIN mode using USB.
- **Partition Management:** Discovers partitions via PIT files using Heimdall or heuristic parsing.
- **Read/Write/Erase:** Safely reads, writes, and erases partitions (Heimdall recommended).
- **CLI Interface:** Easy command-line interface for all operations.

## Requirements

- Python 3.6+
- [pyusb](https://github.com/pyusb/pyusb) (`pip install pyusb`)
- [heimdall](https://github.com/Benjamin-Dobell/Heimdall) (for reliable PIT and partition operations)
- Samsung Exynos device in ODIN/Download mode

## Usage

```
python xyn_cli.py detect
python xyn_cli.py partitions
python xyn_cli.py read BOOT boot.img
python xyn_cli.py write BOOT boot.img
python xyn_cli.py erase userdata --force
```

### CLI Commands

- `detect`: Detect and connect to a device.
- `partitions`: List all partitions discovered from the PIT file.
- `read <partition> <output_file>`: Read the specified partition to a file.
- `write <partition> <input_file>`: Write a file to the specified partition.
- `erase <partition> --force`: Erase the specified partition (requires `--force`).

## File Structure

- `bridge.py`: ExynosBridge implementation. Core logic for device connection, partition operations, and PIT parsing.
- `xyn_cli.py`: Main command-line interface for using XynClient.

## Safety Notice

- **Partition writing/erasing is potentially destructive.** Heimdall is recommended for these operations. Python fallback implementations are disabled or marked unsafe to avoid accidental device bricking.

## License

This project currently does not specify a license. Please add one if you intend to distribute or share the tool.

---

**Author:** [ABDO10DZ](https://github.com/ABDO10DZ)
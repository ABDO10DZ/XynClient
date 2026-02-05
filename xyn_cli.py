#!/usr/bin/env python3
"""
xyn_cli.py - Main launcher for XynClient (FIXED)

Usage examples:
  python xyn_cli.py detect
  python xyn_cli.py partitions
  python xyn_cli.py read BOOT boot.img
  python xyn_cli.py write BOOT boot.img
  python xyn_cli.py erase userdata
"""
import argparse
import sys
import os
from bridge import ExynosBridge, XynError

def validate_file_exists(path, operation):
    """Validate file exists for read/write operations"""
    if operation == 'read':
        # Output file directory must exist
        dir_path = os.path.dirname(path)
        if dir_path and not os.path.exists(dir_path):
            raise XynError(f"Output directory does not exist: {dir_path}")
    elif operation == 'write':
        # Input file must exist
        if not os.path.exists(path):
            raise XynError(f"Input file does not exist: {path}")
        if not os.path.isfile(path):
            raise XynError(f"Input path is not a file: {path}")

def main():
    parser = argparse.ArgumentParser(description='XynClient - Exynos Tool (Complete Implementation)')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')
    parser.add_argument('--timeout', '-t', type=int, default=30, help='USB timeout in seconds (default: 30)')

    subparsers = parser.add_subparsers(dest='command', help='Command to execute', required=True)

    subparsers.add_parser('detect', help='Detect a connected device in ODIN mode')
    subparsers.add_parser('partitions', help='List all partitions from PIT')

    read_parser = subparsers.add_parser('read', help='Read a partition to a file')
    read_parser.add_argument('partition_name', help='Name of the partition to read')
    read_parser.add_argument('output_file', help='Path to the output file')

    erase_parser = subparsers.add_parser('erase', help='Erase a partition')
    erase_parser.add_argument('partition_name', help='Name of the partition to erase')
    erase_parser.add_argument('--force', action='store_true', required=True, 
                             help='Force erase (DANGEROUS - requires explicit confirmation)')

    write_parser = subparsers.add_parser('write', help='Write a file to a partition')    write_parser.add_argument('partition_name', help='Name of the partition to write to')
    write_parser.add_argument('input_file', help='Path to the file to flash')
    write_parser.add_argument('--force', action='store_true', 
                             help='Force write using Python implementation (requires heimdall unavailable)')

    args = parser.parse_args()

    bridge = ExynosBridge(verbose=args.verbose, timeout=args.timeout)

    try:
        # connect() now properly establishes session and returns True on success
        if not bridge.connect():
            print("ERROR: Failed to connect to a device in ODIN mode.")
            print("Make sure device is in Download/ODIN mode and USB debugging is enabled.")
            return 1

        if args.command == 'detect':
            print("✓ Device found and connected successfully.")
            print(f"  Device: VID={hex(bridge.dev.idVendor)} PID={hex(bridge.dev.idProduct)}")
            print(f"  Interface: {bridge.interface}")
            print(f"  Endpoints: IN={hex(bridge.in_ep)} OUT={hex(bridge.out_ep)}")
            return 0

        elif args.command == 'partitions':
            print("Detecting partition layout...")
            partitions = bridge.partition_manager.detect_partition_layout()
            if not partitions:
                print("ERROR: No partitions detected.")
                print("Try: Install heimdall for better partition detection")
                return 1
            
            print(f"\n{'Partition Name':<20} {'Size (MB)':<12} {'ID':<6} {'Status':<10}")
            print("-" * 55)
            for name, info in sorted(partitions.items()):
                size = info.get('length', 0)
                size_mb = f"{size / (1024*1024):.1f}" if size else "Unknown"
                pid = info.get('id', 'N/A')
                status = "OK" if size else "Partial"
                print(f"{name:<20} {size_mb:<12} {pid:<6} {status:<10}")
            print(f"\nTotal partitions: {len(partitions)}")
            return 0

        elif args.command == 'read':
            validate_file_exists(args.output_file, 'read')
            
            print(f"Reading partition '{args.partition_name}' to '{args.output_file}'...")
            success = bridge.read_partition(args.partition_name, args.output_file)
            if success:
                file_size = os.path.getsize(args.output_file)
                print(f"✓ Read operation succeeded. ({file_size:,} bytes)")                return 0
            else:
                print("✗ Read operation failed.")
                return 1

        elif args.command == 'erase':
            print(f"WARNING: This will ERASE partition '{args.partition_name}'")
            print("This operation is DESTRUCTIVE and cannot be undone!")
            confirm = input("Type 'YES' to confirm: ")
            if confirm.strip() != 'YES':
                print("Operation cancelled.")
                return 2
            
            print(f"Erasing partition '{args.partition_name}'...")
            success = bridge.erase_partition(args.partition_name, force=True)
            if success:
                print(f"✓ Erase operation succeeded.")
                return 0
            else:
                print("✗ Erase operation failed.")
                return 1

        elif args.command == 'write':
            validate_file_exists(args.input_file, 'write')
            file_size = os.path.getsize(args.input_file)
            
            print(f"Writing to partition '{args.partition_name}' from '{args.input_file}'")
            print(f"File size: {file_size:,} bytes ({file_size / (1024*1024):.2f} MB)")
            
            if not args.force:
                print("\nNote: Using heimdall if available (recommended)")
            
            success = bridge.write_partition(args.partition_name, args.input_file, force=args.force)
            if success:
                print(f"✓ Write operation succeeded.")
                return 0
            else:
                print("✗ Write operation failed.")
                return 1

    except XynError as e:
        print(f"ERROR: {e}")
        return 1
    except KeyboardInterrupt:
        print("\nOperation cancelled by user.")
        return 2
    except Exception as e:
        print(f"UNEXPECTED ERROR: {e}")
        if args.verbose:
            import traceback            traceback.print_exc()
        return 1
    finally:
        try:
            if bridge.dev:
                bridge.disconnect()
                if args.verbose:
                    print("[DEBUG] Device disconnected cleanly")
        except Exception as e:
            if args.verbose:
                print(f"[DEBUG] Error during cleanup: {e}")

if __name__ == '__main__':
    sys.exit(main())
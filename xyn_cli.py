#!/usr/bin/env python3
"""
xyn_cli.py - Main launcher for XynClient

Usage examples:
  python xyn_cli.py detect
  python xyn_cli.py partitions
  python xyn_cli.py read BOOT boot.img
  python xyn_cli.py write BOOT boot.img
  python xyn_cli.py erase userdata
"""
import argparse
import sys
from bridge import ExynosBridge, XynError

def main():
    parser = argparse.ArgumentParser(description='XynClient - Exynos Tool')
    parser.add_argument('--verbose', '-v', action='store_true', help='Enable verbose output')

    subparsers = parser.add_subparsers(dest='command', help='Command to execute', required=True)

    subparsers.add_parser('detect', help='Detect a connected device')
    subparsers.add_parser('partitions', help='List all partitions from PIT')

    read_parser = subparsers.add_parser('read', help='Read a partition to a file')
    read_parser.add_argument('partition_name', help='Name of the partition to read')
    read_parser.add_argument('output_file', help='Path to the output file')

    erase_parser = subparsers.add_parser('erase', help='Erase a partition')
    erase_parser.add_argument('partition_name', help='Name of the partition to erase')
    # destructive operation: require explicit flag
    erase_parser.add_argument('--force', action='store_true', help='Force erase (dangerous)')

    write_parser = subparsers.add_parser('write', help='Write a file to a partition')
    write_parser.add_argument('partition_name', help='Name of the partition to write to')
    write_parser.add_argument('input_file', help='Path to the file to flash')
    write_parser.add_argument('--force', action='store_true', help='Force write using Python fallback (unsafe)')

    args = parser.parse_args()

    bridge = ExynosBridge(verbose=args.verbose)

    try:
        # connect() returns True on success
        if not bridge.connect():
            print("Failed to connect to a device.")
            return 1

        if args.command == 'detect':
            print("Device found and connected successfully.")
            return 0

        elif args.command == 'partitions':
            partitions = bridge.partition_manager.detect_partition_layout()
            if not partitions:
                print("No partitions detected.")
                return 1
            for name, info in partitions.items():
                size = info.get('length', 'Unknown')
                pid = info.get('id', 'Unknown')
                print(f"{name:20} size={size:12} id={pid}")
            return 0

        elif args.command == 'read':
            success = bridge.read_partition(args.partition_name, args.output_file)
            print(f"Read operation {'succeeded' if success else 'failed'}.")
            return 0 if success else 1

        elif args.command == 'erase':
            if not args.force:
                print("Erase is destructive. Re-run with --force to proceed.")
                return 2
            success = bridge.erase_partition(args.partition_name, force=args.force)
            print(f"Erase operation {'succeeded' if success else 'failed'}.")
            return 0 if success else 1

        elif args.command == 'write':
            success = bridge.write_partition(args.partition_name, args.input_file, force=args.force)
            print(f"Write operation {'succeeded' if success else 'failed'}.")
            return 0 if success else 1

    except XynError as e:
        print(f"An error occurred: {e}")
        return 1
    finally:
        try:
            bridge.disconnect()
        except Exception:
            pass

if __name__ == '__main__':
    sys.exit(main())

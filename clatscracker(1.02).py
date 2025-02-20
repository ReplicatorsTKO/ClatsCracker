import hashlib
import sys
import os
import time
import bcrypt
import itertools
import string
import threading
import signal
import zlib
from concurrent.futures import ThreadPoolExecutor
from argon2 import PasswordHasher, Type
import psutil  # <-- Ensure this is installed: pip install psutil

passwords_tried = 0
total_passwords = 0
found_password = None
threads_count = 1
progress_lock = threading.Lock()
found_lock = threading.Lock()

# For ETA and APS
start_time_global = None

# For graceful interruption
abort_requested = False

# For logging
log_file = "cracking.log"

# CPU usage threshold (percentage). If system load is higher than this, we pause briefly.
CPU_USAGE_THRESHOLD = 90.0

def write_log(message):
    try:
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(f"{time.ctime()} - {message}\n")
    except Exception:
        pass

def signal_handler(sig, frame):
    global abort_requested
    abort_requested = True
    print("\n\nCaught interruption signal. Attempting to stop gracefully...")

signal.signal(signal.SIGINT, signal_handler)

def print_header():
    title = r"""
   ██████╗██╗        █████╗ ████████╗███████╗
   ██╔════╝██║       ██╔══██╗╚══██╔══╝██╔════╝
   ██║     ██║       ███████║   ██║   ███████╗
   ██║     ██║       ██╔══██║   ██║   ╚════██║
   ██████╗ ███████╗  ██║  ██║   ██║   ███████║
   ╚═════╝ ╚══════╝  ╚═╝  ╚═╝   ╚═╝   ╚══════╝

        C       L      A       T       S
    """
    print("\033[1;31m" + title + "\033[0m")

    author = "🛡️ By Josh Clatney - Ethical Pentesting Enthusiast 🛡️"
    print("\033[1;36m" + author + "\033[0m")

    quote = """
    --------------------------------------------------------------------------------------------------------------------
    A top-tier hash cracking tool that supports numerous algorithms and has unique capabilities and functionality. 
    --------------------------------------------------------------------------------------------------------------------
    """
    print("\033[1;37m" + quote + "\033[0m")

def print_menu():
    print("\nMenu:")
    print("1.Crack Password")
    print("2.Exit")

# Extended supported algorithms including sha1_v2
hash_lengths = {
    'crc32': 8,
    'md4': 32,
    'md5': 32,
    'ripemd160': 40,
    'sha1': 40,
    'sha1_v2': 40,
    'sha224': 56,
    'sha256': 64,
    'sha3_224': 56,
    'sha3_256': 64,
    'sha3_384': 96,
    'sha3_512': 128,
    'sha512': 128,
    'blake2_224': 56
}

def guess_hash_algorithm(hash_value):
    if hash_value.startswith("$2"):
        return ['bcrypt']
    if hash_value.startswith("$argon2id$"):
        return ['argon2id']

    length = len(hash_value)
    candidates = []

    for algo, algo_len in hash_lengths.items():
        if length == algo_len:
            candidates.append(algo)

    # If length=128 and purely hex, add scrypt as a candidate
    if length == 128 and all(c in '0123456789abcdef' for c in hash_value.lower()):
        candidates.append('scrypt')

    candidates = list(set(candidates))
    if len(candidates) == 0:
        return None
    return candidates

def hash_password(password, hash_algorithm):
    password_bytes = password.encode('utf-8')

    if hash_algorithm == 'crc32':
        return format(zlib.crc32(password_bytes) & 0xffffffff, '08x')
    elif hash_algorithm == 'md4':
        return hashlib.new('md4', password_bytes).hexdigest()
    elif hash_algorithm == 'ripemd160':
        return hashlib.new('ripemd160', password_bytes).hexdigest()
    elif hash_algorithm == 'blake2_224':
        return hashlib.blake2b(password_bytes, digest_size=28).hexdigest()
    elif hash_algorithm == 'sha224':
        return hashlib.sha224(password_bytes).hexdigest()
    elif hash_algorithm == 'sha3_224':
        return hashlib.sha3_224(password_bytes).hexdigest()
    elif hash_algorithm == 'sha3_256':
        return hashlib.sha3_256(password_bytes).hexdigest()
    elif hash_algorithm == 'sha3_384':
        return hashlib.sha3_384(password_bytes).hexdigest()
    elif hash_algorithm == 'sha3_512':
        return hashlib.sha3_512(password_bytes).hexdigest()
    elif hash_algorithm == 'md5':
        return hashlib.md5(password_bytes).hexdigest()
    elif hash_algorithm == 'sha1':
        return hashlib.sha1(password_bytes).hexdigest()
    elif hash_algorithm == 'sha1_v2':
        first_pass = hashlib.sha1(password_bytes).digest()
        return hashlib.sha1(first_pass).hexdigest()
    elif hash_algorithm == 'sha256':
        return hashlib.sha256(password_bytes).hexdigest()
    elif hash_algorithm == 'sha512':
        return hashlib.sha512(password_bytes).hexdigest()
    elif hash_algorithm == 'scrypt':
        return hashlib.scrypt(password_bytes, salt=b'', n=16384, r=8, p=1, dklen=64).hex()
    else:
        return None

def validate_hash_length(hash_algorithm, hash_value):
    if hash_algorithm in ['bcrypt', 'argon2id', 'scrypt']:
        return True
    expected_length = hash_lengths.get(hash_algorithm)
    if expected_length and len(hash_value) != expected_length:
        print(f"🚫 The provided hash does not match the expected length for {hash_algorithm}.")
        return False
    return True

def print_stats():
    global passwords_tried, total_passwords, start_time_global
    elapsed = time.time() - start_time_global
    if elapsed > 0 and passwords_tried > 0:
        aps = passwords_tried / elapsed
        remaining = total_passwords - passwords_tried
        eta = remaining / aps if aps > 0 else 99999
        print(f" APS: {aps:.2f}/s ETA: {eta:.1f}s", end='', flush=True)

def throttle_cpu_usage():
    """Check CPU usage and sleep if usage is too high."""
    cpu_usage = psutil.cpu_percent(interval=0.0)
    if cpu_usage > CPU_USAGE_THRESHOLD:
        # Sleep briefly to reduce load
        time.sleep(0.5)

def check_password(password, hash_to_decrypt, hash_algorithm):
    global passwords_tried, found_password, abort_requested
    with found_lock:
        if found_password is not None or abort_requested:
            return

    if hash_algorithm == 'bcrypt':
        try:
            if bcrypt.checkpw(password.encode('utf-8'), hash_to_decrypt.encode('utf-8')):
                with found_lock:
                    found_password = password
                return
        except Exception:
            pass
    elif hash_algorithm == 'argon2id':
        ph = PasswordHasher(type=Type.ID)
        try:
            ph.verify(hash_to_decrypt, password)
            with found_lock:
                found_password = password
            return
        except Exception:
            pass
    else:
        hashed_word = hash_password(password, hash_algorithm)
        if hashed_word == hash_to_decrypt:
            with found_lock:
                found_password = password
            return

    with progress_lock:
        passwords_tried += 1
        if not abort_requested:
            progress = (passwords_tried / total_passwords) * 100
            print(f"\rProgress: {progress:.2f}%", end='', flush=True)
            print_stats()

    # After incrementing passwords_tried, throttle if CPU is too high
    throttle_cpu_usage()

def chunk_list(lst, n):
    k, m = divmod(len(lst), n)
    return (lst[i*k+min(i,m):(i+1)*k+min(i+1,m)] for i in range(n))

def dictionary_crack_worker(passwords_chunk, hash_to_decrypt, hash_algorithm):
    for pwd in passwords_chunk:
        with found_lock:
            if found_password is not None or abort_requested:
                return
        check_password(pwd, hash_to_decrypt, hash_algorithm)
        with found_lock:
            if found_password is not None or abort_requested:
                return

def concurrent_hash_cracker(dictionary, hash_to_decrypt, hash_algorithm):
    global total_passwords, passwords_tried, found_password, start_time_global, abort_requested
    found_password = None
    passwords_tried = 0
    abort_requested = False

    write_log(f"Starting dictionary cracking. Hash: {hash_to_decrypt}, Algo: {hash_algorithm}, Dicts: {dictionary}")
    start_time_global = time.time()

    all_passwords = []

    for dictionary_path in dictionary:
        if os.path.exists(dictionary_path):
            with open(dictionary_path, 'r', encoding='utf-8') as f:
                for line in f:
                    p = line.strip()
                    if p:
                        all_passwords.append(p)
        else:
            print(f"\n🔍 Dictionary file '{dictionary_path}' not found.\n")

    all_passwords = list(set(all_passwords))
    total_passwords = len(all_passwords)

    if total_passwords == 0:
        print("Sorry, no password was found in the dictionary.")
        write_log("No passwords found in dictionary.")
        return None

    chunks = list(chunk_list(all_passwords, threads_count))

    with ThreadPoolExecutor(max_workers=threads_count) as executor:
        futures = [executor.submit(dictionary_crack_worker, chunk, hash_to_decrypt, hash_algorithm) for chunk in chunks]
        for future in futures:
            future.result()

    if abort_requested:
        write_log("Cracking aborted by user.")
    elif found_password:
        write_log(f"Password found: {found_password}")
    else:
        write_log("Cracking completed, password not found.")

    return found_password

def brute_force_crack(hash_to_decrypt, hash_algorithm, charset, length):
    global found_password, total_passwords, passwords_tried, start_time_global, abort_requested
    found_password = None
    passwords_tried = 0
    abort_requested = False

    write_log(f"Starting brute force. Hash: {hash_to_decrypt}, Algo: {hash_algorithm}, Length: {length}")
    start_time_global = time.time()

    attempts = [''.join(p) for p in itertools.product(charset, repeat=length)]
    total_passwords = len(attempts)

    def brute_force_worker(pwd_chunk, htd, algo):
        for pwd in pwd_chunk:
            with found_lock:
                if found_password is not None or abort_requested:
                    return
            check_password(pwd, htd, algo)
            with found_lock:
                if found_password is not None or abort_requested:
                    return

    start_time = time.time()
    chunks = list(chunk_list(attempts, threads_count))
    with ThreadPoolExecutor(max_workers=threads_count) as executor:
        futures = [executor.submit(brute_force_worker, chunk, hash_to_decrypt, hash_algorithm) for chunk in chunks]
        for future in futures:
            future.result()

    if found_password:
        print(f"\n\n\033[1;32m🔓 Found Password: {found_password}\033[0m\n")
        print(f"⏱️ Amount of time it took to crack the password: {time.time() - start_time:.2f} seconds")
        write_log(f"Brute force success. Password: {found_password}")
        return True
    else:
        if abort_requested:
            write_log("Brute force aborted by user.")
        else:
            write_log("Brute force completed, no password found.")

        print("\n\033[1;31m🛑 Sorry, no password was found.\033[0m\n")
        print(f"⏱️ Amount of time it took: {time.time() - start_time:.2f} seconds")
        return False

def choose_resource_usage():
    global threads_count
    print("\nChoose the resource usage level (number of threads):")
    print("1. Low (1 thread)")
    print("2. Medium (4 threads)")
    print("3. High (8 threads)")
    print("4. Custom")
    choice = input("\nEnter your choice: ").strip()

    if choice == '1':
        threads_count = 1
    elif choice == '2':
        threads_count = 4
    elif choice == '3':
        threads_count = 8
    elif choice == '4':
        custom_threads = input("Enter the number of threads (1-1000): ").strip()
        if custom_threads.isdigit():
            custom_threads = int(custom_threads)
            if 1 <= custom_threads <= 1000:
                threads_count = custom_threads
            else:
                print("⛔ Invalid number. Defaulting to Medium usage.")
                threads_count = 4
        else:
            print("⛔ Invalid input. Defaulting to Medium usage.")
            threads_count = 4
    else:
        print("⛔ Invalid choice. Defaulting to Medium usage.")
        threads_count = 4

def main():
    attention_message = "⚠️ This tool is for ethical use or pentesting only. Do not misuse it or break the law with it. ⚠️"
    print("\033[1;33m" + attention_message + "\033[0m")

    print_header()
    choose_resource_usage()

    valid_algorithms = [
        'md5', 'sha1', 'sha1_v2', 'sha256', 'sha512', 'sha3_256', 'bcrypt', 'argon2id', 'scrypt', 'auto',
        'crc32', 'md4', 'ripemd160', 'blake2_224', 'sha224', 'sha3_224', 'sha3_384', 'sha3_512'
    ]

    brute_force_supported = [
        'md5', 'sha1', 'sha1_v2', 'sha256', 'sha3_256', 'sha224', 'sha3_224', 'sha3_384', 'sha3_512',
        'md4', 'ripemd160', 'crc32', 'blake2_224'
    ]

    while True:
        print_menu()
        choice = input("\nEnter your choice: ").strip()

        if choice == '1':
            print("\n🔐  Password Cracker  🔐\n")
            print("Supported algorithms:", ", ".join(valid_algorithms))
            hash_algorithm = input("Which hashing algorithm do you want to crack? (or 'auto' to guess): ").lower()

            hash_to_decrypt = input("Enter the unsalted hash value: ").strip()

            if not hash_to_decrypt:
                print("🚫 No hash provided.")
                continue

            if hash_algorithm == 'auto':
                candidates = guess_hash_algorithm(hash_to_decrypt)
                if candidates is None:
                    print("🚫 Could not auto-detect hash algorithm.")
                    continue
                if len(candidates) == 1:
                    hash_algorithm = candidates[0]
                    print(f"Guessed algorithm: {hash_algorithm}")
                else:
                    # Multiple candidates found
                    print("Multiple possible algorithms found:")
                    for i, c in enumerate(candidates, 1):
                        print(f"{i}. {c}")
                    sel = input("Select the algorithm number: ").strip()
                    if sel.isdigit() and 1 <= int(sel) <= len(candidates):
                        hash_algorithm = candidates[int(sel) - 1]
                        print(f"Selected algorithm: {hash_algorithm}")
                    else:
                        print("⛔ Invalid choice.")
                        continue
            else:
                if hash_algorithm not in valid_algorithms:
                    print("🚫 Invalid hash algorithm.")
                    continue

            if hash_algorithm == 'bcrypt':
                if not hash_to_decrypt.startswith("$2"):
                    print("🚫 This does not look like a bcrypt hash.")
                    continue
            elif hash_algorithm == 'argon2id':
                if not hash_to_decrypt.startswith("$argon2id$"):
                    print("🚫 This does not look like a valid Argon2id hash.")
                    continue

            if hash_algorithm not in ['bcrypt', 'argon2id', 'scrypt']:
                if not validate_hash_length(hash_algorithm, hash_to_decrypt):
                    continue

            print("\nChoose your cracking method:")
            print("1. Dictionary-Based Cracking")
            print("2. Automatic Brute Force Cracking")
            method_choice = input("\nEnter your choice: ").strip()

            if method_choice == '1':
                num_dictionary = input("Enter how many dictionaries you want to use: ").strip()
                if not num_dictionary.isdigit() or int(num_dictionary) <= 0:
                    print("❌ Invalid number of dictionaries.")
                    continue
                num_dictionary = int(num_dictionary)

                dictionary = []
                for i in range(num_dictionary):
                    dictionary_path = input(f"Enter path for the dictionary file {i+1}: ").strip()
                    dictionary.append(dictionary_path)

                start_time = time.time()
                cracked_password = concurrent_hash_cracker(dictionary, hash_to_decrypt, hash_algorithm)
                end_time = time.time()

                if cracked_password:
                    print(f"\n\n\033[1;32m🔓 Password Successfully Cracked!: {cracked_password}\033[0m\n")
                else:
                    if not abort_requested:
                        print("\n\033[1;31m🛑 Cracking unsuccessful. Password not found.\033[0m\n")

                print(f"⏱️ Amount of time to crack the password: {end_time - start_time:.2f} seconds")

            elif method_choice == '2':
                if hash_algorithm not in brute_force_supported:
                    print("🚫 Automatic brute force is not supported for this algorithm.")
                    continue
                charset = string.ascii_letters + string.digits
                length_input = input("Enter password length: ").strip()
                if not length_input.isdigit() or int(length_input) <= 0:
                    print("❌ Invalid length.")
                    continue
                length = int(length_input)
                brute_force_crack(hash_to_decrypt, hash_algorithm, charset, length)
            else:
                print("\n⛔ Invalid choice. Please select a valid option.")

        elif choice == '2':
            print("\n🚪 Exiting...")
            sys.exit()
        else:
            print("\n⛔ Invalid choice. Please select a valid option.")

if __name__ == "__main__":
    main()
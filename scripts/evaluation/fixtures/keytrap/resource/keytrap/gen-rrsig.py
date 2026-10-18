import time
import argparse
from datetime import datetime, timezone
import base64
import os

def create_dummy_signature():
    # Generate a dummy digital signature
    dummy_signature = os.urandom(96)  # Match the signature size for ECDSAP384SHA384
    return base64.b64encode(dummy_signature).decode('utf-8')

def create_dummy_rrsig(signer_name, type_covered, algorithm, labels, original_ttl,
                       expiration, inception, key_tag):
    dummy_signature = create_dummy_signature()  # Generate a dummy digital signature

    # Format the signature start and end times
    inception_date = datetime.fromtimestamp(inception, timezone.utc).strftime('%Y%m%d%H%M%S')
    expiration_date = datetime.fromtimestamp(expiration, timezone.utc).strftime('%Y%m%d%H%M%S')

    # Create the RRSIG record
    rrsig_record = f"{type_covered} {algorithm} {labels} {original_ttl} {expiration_date} " \
                   f"{inception_date} {key_tag} {signer_name} {dummy_signature}"

    return rrsig_record

# Default parameters
DEFAULT_SIGNER_NAME = "a.test."
DEFAULT_TYPE_COVERED = "A"
DEFAULT_ALGORITHM = 14
DEFAULT_LABELS = 3
DEFAULT_ORIGINAL_TTL = 86400
DEFAULT_KEY_TAG = 18503
DEFAULT_COUNT = 400
DEFAULT_OUTPUT = None  # None means output to stdout

def parse_args():
    parser = argparse.ArgumentParser(description='Generate fake RRSIG records')
    parser.add_argument('-s', '--signer-name', type=str, default=DEFAULT_SIGNER_NAME,
                        help=f'Signer domain name (default: {DEFAULT_SIGNER_NAME})')
    parser.add_argument('-t', '--type-covered', type=str, default=DEFAULT_TYPE_COVERED,
                        help=f'Type covered (default: {DEFAULT_TYPE_COVERED})')
    parser.add_argument('-a', '--algorithm', type=int, default=DEFAULT_ALGORITHM,
                        help=f'Algorithm (default: {DEFAULT_ALGORITHM})')
    parser.add_argument('-l', '--labels', type=int, default=DEFAULT_LABELS,
                        help=f'Number of labels (default: {DEFAULT_LABELS})')
    parser.add_argument('--original-ttl', type=int, default=DEFAULT_ORIGINAL_TTL,
                        help=f'Original TTL (default: {DEFAULT_ORIGINAL_TTL})')
    parser.add_argument('-k', '--key-tag', type=int, default=DEFAULT_KEY_TAG,
                        help=f'Key Tag (default: {DEFAULT_KEY_TAG})')
    parser.add_argument('-n', '--count', type=int, default=DEFAULT_COUNT,
                        help=f'Number of records to generate (default: {DEFAULT_COUNT})')
    parser.add_argument('-o', '--output', type=str, default=DEFAULT_OUTPUT,
                        help=f'Output file name (default: output to stdout)')
    parser.add_argument('--expiration-days', type=int, default=7,
                        help='Expiration days from today (default: 7)')
    parser.add_argument('--inception-days-ago', type=int, default=1,
                        help='Inception days ago from today (default: 1)')
    return parser.parse_args()

if __name__ == "__main__":
    args = parse_args()

    current_time = int(time.time())
    expiration = current_time + args.expiration_days * 24 * 3600
    inception = current_time - args.inception_days_ago * 24 * 3600

    # Determine output target
    if args.output:
        fout = open(args.output, 'w')
    else:
        fout = None  # Use stdout

    try:
        # Generate the dummy RRSIG records
        for i in range(args.count):
            dummy_rrsig = create_dummy_rrsig(args.signer_name, args.type_covered, args.algorithm,
                                             args.labels, args.original_ttl, expiration, inception,
                                             args.key_tag)
            line = f"\t\t\t86400\tRRSIG\t{dummy_rrsig}"
            if fout:
                fout.write(line + '\n')
            else:
                print(line)
    finally:
        if fout:
            fout.close()


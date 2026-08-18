#!/usr/bin/env python3
"""Final investigation: the 'unknown' devices have uniformly-distributed
first bytes — that's the signature of RANDOM MACs, not stable OUI-assigned
MACs. The is_random_mac() function checks bit 1 (0x02), but the IEEE
locally-administered bit is bit 1 of the FIRST byte in MSB order, which
translates to 0x02 in the value. But many BLE random addresses use bit 0
(0x01) for the 'type' (static vs non-resolvable). Let's check which bit
these MACs actually have set, and whether is_random_mac is checking the
right bit."""
import os
import sys
import sqlite3

DB_PATH = os.path.expanduser("~/neighborhood-rhythm/rhythm.db")
APP_DIR = os.path.expanduser("~/neighborhood-rhythm")
sys.path.insert(0, APP_DIR)

def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def main():
    conn = connect()
    all_unknowns = conn.execute("""
        SELECT mac FROM devices WHERE last_type='unknown' OR last_type IS NULL
    """).fetchall()

    # Check ALL bits of the first byte
    print("=== FIRST BYTE BIT ANALYSIS (unknowns) ===")
    bit_counts = [0] * 8
    for u in all_unknowns:
        mac = u["mac"]
        hexpart = mac.replace(":", "").replace("-", "")
        if len(hexpart) != 12:
            continue
        first = int(hexpart[0:2], 16)
        for bit in range(8):
            if first & (1 << bit):
                bit_counts[bit] += 1

    n = len(all_unknowns)
    print(f"  Total unknowns: {n}")
    print(f"  Bit counts (how many have each bit set in first byte):")
    for bit in range(8):
        mask = 1 << bit
        print(f"    bit {bit} (0x{mask:02X}): {bit_counts[bit]} ({bit_counts[bit]/n*100:.1f}%)")

    # If these were truly random MACs with the locally-administered bit set,
    # bit 1 (0x02) would be set in ~50% (random) + the LA bit. But we see
    # bit 1 set in 0%. That means NONE of them have the LA bit set.
    # But the distribution is uniform across first bytes — that's the
    # signature of random addresses where the LA bit is NOT being checked
    # correctly, OR the devices are using a different randomization scheme.

    # Actually: BLE has two random address types:
    # - Static: bit 1 (0x02) set, bit 0 (0x01) = 0
    # - Non-resolvable private: bit 1 (0x02) = 0, bit 0 (0x01) = 1
    # The is_random_mac function only checks bit 1 (0x02), so it MISSES
    # non-resolvable private addresses (where bit 0 is set instead).

    # Let's check: how many unknowns have bit 0 (0x01) set but NOT bit 1?
    n_bit0_only = 0
    n_bit1_only = 0
    n_both = 0
    n_neither = 0
    for u in all_unknowns:
        mac = u["mac"]
        hexpart = mac.replace(":", "").replace("-", "")
        if len(hexpart) != 12:
            continue
        first = int(hexpart[0:2], 16)
        b0 = bool(first & 0x01)
        b1 = bool(first & 0x02)
        if b0 and not b1:
            n_bit0_only += 1
        elif b1 and not b0:
            n_bit1_only += 1
        elif b0 and b1:
            n_both += 1
        else:
            n_neither += 1
    print(f"\n  bit0(0x01) only (non-resolvable private): {n_bit0_only} ({n_bit0_only/n*100:.1f}%)")
    print(f"  bit1(0x02) only (static random): {n_bit1_only} ({n_bit1_only/n*100:.1f}%)")
    print(f"  both bits set: {n_both} ({n_both/n*100:.1f}%)")
    print(f"  neither bit set (stable/OUI): {n_neither} ({n_neither/n*100:.1f}%)")

    # Now compare with the phone-anon devices (which ARE caught as random)
    print("\n=== COMPARISON: phone-anon devices ===")
    phone_anon = conn.execute("""
        SELECT mac FROM devices WHERE last_type='phone-anon' LIMIT 500
    """).fetchall()
    n = len(phone_anon)
    if n:
        bit0_only = 0
        bit1_only = 0
        both = 0
        neither = 0
        for u in phone_anon:
            mac = u["mac"]
            hexpart = mac.replace(":", "").replace("-", "")
            if len(hexpart) != 12:
                continue
            first = int(hexpart[0:2], 16)
            b0 = bool(first & 0x01)
            b1 = bool(first & 0x02)
            if b0 and not b1:
                bit0_only += 1
            elif b1 and not b0:
                bit1_only += 1
            elif b0 and b1:
                both += 1
            else:
                neither += 1
        print(f"  phone-anon sample: {n}")
        print(f"  bit0(0x01) only: {bit0_only} ({bit0_only/n*100:.1f}%)")
        print(f"  bit1(0x02) only: {bit1_only} ({bit1_only/n*100:.1f}%)")
        print(f"  both: {both} ({both/n*100:.1f}%)")
        print(f"  neither: {neither} ({neither/n*100:.1f}%)")

    # The key question: are the unknowns' first bytes uniformly distributed
    # (random) or do they cluster (real OUI assignments)?
    print("\n=== UNIFORMITY TEST ===")
    # If random, each first byte value should appear ~n/256 times.
    # Real OUI assignments cluster heavily.
    byte_counts = {}
    for u in all_unknowns:
        mac = u["mac"]
        hexpart = mac.replace(":", "").replace("-", "")
        if len(hexpart) != 12:
            continue
        fb = hexpart[0:2].upper()
        byte_counts[fb] = byte_counts.get(fb, 0) + 1

    counts = list(byte_counts.values())
    import statistics
    mean = statistics.mean(counts)
    stdev = statistics.stdev(counts) if len(counts) > 1 else 0
    print(f"  Distinct first bytes: {len(byte_counts)} / 256")
    print(f"  Mean count per byte: {mean:.1f}")
    print(f"  Stdev: {stdev:.1f}")
    print(f"  CV (stdev/mean): {stdev/mean:.3f}")
    print(f"  (Random data: CV ~0.06 with 256 buckets; real OUI data: CV >> 1)")

    # Also check: are these MACs seen only once (drive-bys) or repeatedly?
    print("\n=== SIGHTING COUNT FOR UNKNOWNS ===")
    cnt_dist = conn.execute("""
        SELECT sighting_count, COUNT(*) c FROM devices
        WHERE last_type='unknown' OR last_type IS NULL
        GROUP BY sighting_count ORDER BY sighting_count
    """).fetchall()
    for r in cnt_dist[:10]:
        print(f"  sighting_count={r['sighting_count']}: {r['c']} devices")
    total_unknown = sum(r["c"] for r in cnt_dist)
    single = sum(r["c"] for r in cnt_dist if r["sighting_count"] == 1)
    print(f"  Single-sighting unknowns: {single} / {total_unknown} ({single/total_unknown*100:.1f}%)")

    conn.close()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Investigate the unknown-device mystery: are they random MACs that
is_random_mac misses, or stable MACs with no OUI? Also check the OUI file
coverage and the actual CPU breakdown of a collector run."""
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
    from rules import is_random_mac
    conn = connect()

    print("=== UNKNOWN DEVICE MAC ANALYSIS ===")
    unknowns = conn.execute("""
        SELECT d.mac, d.oui_name, d.last_type
        FROM devices d
        WHERE d.last_type='unknown' OR d.last_type IS NULL
        LIMIT 20
    """).fetchall()

    for u in unknowns:
        mac = u["mac"]
        # Check the locally-administered bit manually
        hexpart = mac.replace(":", "").replace("-", "")
        first = int(hexpart[0:2], 16)
        is_random_bit = bool(first & 0b10)
        is_random_fn = is_random_mac(mac)
        print(f"  mac={mac} first_byte=0x{first:02x} random_bit={is_random_bit} is_random_mac()={is_random_fn} oui={u['oui_name']}")

    # Count: how many unknowns have the random bit set but is_random_mac returns False?
    all_unknowns = conn.execute("""
        SELECT mac FROM devices WHERE last_type='unknown' OR last_type IS NULL
    """).fetchall()
    n_random_bit_set = 0
    n_random_fn = 0
    n_stable_no_oui = 0
    for u in all_unknowns:
        mac = u["mac"]
        hexpart = mac.replace(":", "").replace("-", "")
        if len(hexpart) != 12:
            continue
        first = int(hexpart[0:2], 16)
        if first & 0b10:
            n_random_bit_set += 1
        if is_random_mac(mac):
            n_random_fn += 1
        elif not u or True:
            # stable MAC, no OUI
            pass
    print(f"\n  Total unknowns: {len(all_unknowns)}")
    print(f"  With random bit set (locally-administered): {n_random_bit_set}")
    print(f"  is_random_mac() returns True: {n_random_fn}")

    # The mystery: is_random_mac returned 0 randoms among unknowns in the
    # previous script. But the MACs look random (29:97, 5C:CA, E1:39).
    # Let's check: 0x29 = 0b00101001 — bit 1 (0b10) is SET. So it IS random.
    # But is_random_mac checks `first & 0b10` which is bit 1 (value 2).
    # 0x29 = 41 = 0b101001. bit 1 (0b10) = 0. NOT set!
    # Wait: 0b10 = 2. 41 & 2 = 0. So is_random_mac returns False for 0x29.
    # But the locally-administered bit is bit 1 (0b10), which is the SECOND
    # bit (value 2). 0x29 = 0b00101001. bit 1 (value 2) = 0. So it's NOT random.
    # Let me check the actual IEEE spec: locally-administered bit is bit 1
    # of the first octet, which is the 0x02 bit. 0x29 & 0x02 = 0. NOT random.
    # So these are actually STABLE (globally-unique) MACs that just have no
    # OUI in our oui.txt. They're real devices we can't name.
    print(f"\n  NOTE: 0x29 & 0x02 = {0x29 & 0x02} — these are STABLE MACs, not random.")
    print(f"  They're real devices with OUIs not in our oui.txt cache.")

    # Check oui.txt coverage
    oui_path = os.path.join(APP_DIR, "oui.txt")
    if os.path.exists(oui_path):
        sz = os.path.getsize(oui_path)
        with open(oui_path) as f:
            n_lines = sum(1 for _ in f)
        print(f"\n  oui.txt: {sz/1024:.0f} KB, {n_lines} lines")
    else:
        print(f"  oui.txt not found at {oui_path}")

    # How many distinct OUIs are we missing? Look up a few unknown MACs
    # manually in the OUI file.
    import oui
    test_macs = ["29:97:7A:65:73:77", "5C:CA:FE:A0:F6:2E", "E1:39:60:24:96:0A"]
    for mac in test_macs:
        result = oui.lookup(mac)
        print(f"  oui.lookup({mac}) = {result}")

    # The OUI lookup uses the first 3 octets. 29:97:7A — is that in oui.txt?
    oui_prefix = test_macs[0][:8].upper().replace(":", "-")
    print(f"  Looking for OUI prefix {oui_prefix} in oui.txt...")
    with open(oui_path) as f:
        found = [line for line in f if oui_prefix in line]
    print(f"  Found: {found}")

    # Check: how many of the 4979 unknowns have OUIs that ARE in oui.txt
    # but oui.lookup missed them? vs how many have OUIs not in the file at all?
    print("\n=== OUI COVERAGE FOR UNKNOWNS ===")
    # Sample 100 unknowns, check OUI prefix against oui.txt
    sample = conn.execute("""
        SELECT mac FROM devices WHERE last_type='unknown' OR last_type IS NULL
        LIMIT 200
    """).fetchall()
    in_oui = 0
    not_in_oui = 0
    missing_prefixes = set()
    for u in sample:
        mac = u["mac"]
        hexpart = mac.replace(":", "").replace("-", "")
        if len(hexpart) != 12:
            continue
        prefix = mac[:8].upper().replace(":", "-")
        with open(oui_path) as f:
            if prefix in f.read():
                in_oui += 1
            else:
                not_in_oui += 1
                missing_prefixes.add(prefix)
    print(f"  Sampled {len(sample)} unknowns:")
    print(f"  OUI in oui.txt: {in_oui}")
    print(f"  OUI NOT in oui.txt: {not_in_oui}")
    print(f"  Missing prefixes (first 10): {list(missing_prefixes)[:10]}")

    # The real question: are these random MACs that the phone-anon rule
    # should catch, or stable MACs with unknown OUI?
    # Check the first byte distribution of unknowns
    print("\n=== FIRST-BYTE DISTRIBUTION OF UNKNOWNS ===")
    first_bytes = {}
    for u in all_unknowns:
        mac = u["mac"]
        hexpart = mac.replace(":", "").replace("-", "")
        if len(hexpart) != 12:
            continue
        fb = hexpart[0:2].upper()
        first_bytes[fb] = first_bytes.get(fb, 0) + 1
    print(f"  Top first bytes among {len(all_unknowns)} unknowns:")
    for fb, cnt in sorted(first_bytes.items(), key=lambda x: -x[1])[:15]:
        val = int(fb, 16)
        random_bit = "RANDOM" if val & 0x02 else "STABLE"
        print(f"    0x{fb} ({random_bit}): {cnt}")

    conn.close()

if __name__ == "__main__":
    main()

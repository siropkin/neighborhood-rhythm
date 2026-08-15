"""Recompute all device fingerprints from scratch. Run after changing
fingerprint.py or after a fresh Apple-decoder fix. Idempotent."""
import db
from fingerprint import fingerprint_all


def main():
    db.init_db()
    with db.get_db() as conn:
        before = conn.execute("SELECT COUNT(*) c FROM devices").fetchone()["c"]
        n = fingerprint_all(conn)
        after = conn.execute("SELECT COUNT(*) c FROM device_fingerprints").fetchone()["c"]
    print(f"devices: {before} → fingerprints: {after} ({n} created)")
    print(f"dedup: {before - after} MACs merged")


if __name__ == "__main__":
    main()

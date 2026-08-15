"""Reclassify all existing devices with the current rules. Run after changing
rules.py to refresh device types/labels without waiting for a new scan."""
import db
import oui
from classify import classify
from rules import is_random_mac


def main():
    db.init_db()
    n = 0
    with db.get_db() as conn:
        for row in conn.execute("SELECT mac, oui_name FROM devices").fetchall():
            mac = row["mac"]
            raw = {
                "mac": mac,
                "name": "",  # name comes from latest sighting
                "oui_name": row["oui_name"],
                "services": [],
                "is_random": is_random_mac(mac),
            }
            # pull the latest name + services for this device
            s = conn.execute(
                "SELECT name, services FROM sightings WHERE mac=? ORDER BY ts DESC LIMIT 1",
                (mac,),
            ).fetchone()
            if s:
                raw["name"] = s["name"] or ""
                raw["services"] = [s["services"]] if s["services"] else []
            result = classify(raw)
            conn.execute(
                "UPDATE devices SET last_type=?, last_label=? WHERE mac=?",
                (result["type"], result["label"], mac),
            )
            n += 1
    print(f"reclassified {n} devices")


if __name__ == "__main__":
    main()

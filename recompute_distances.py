"""One-shot fixup: recompute distance from rssi for all existing sightings,
after the _distance_from_rssi sign bug was fixed. Run once."""
import sqlite3
from position import _distance_from_rssi

DB = "/home/siropkin/neighborhood-rhythm/rhythm.db"


def main():
    c = sqlite3.connect(DB)
    rows = c.execute("SELECT id, rssi FROM sightings WHERE rssi IS NOT NULL").fetchall()
    n = 0
    for sid, rssi in rows:
        d = _distance_from_rssi(rssi)
        c.execute("UPDATE sightings SET distance=? WHERE id=?", (d, sid))
        n += 1
    c.commit()
    print(f"recomputed distance for {n} sightings")
    # show the new distribution
    for r in c.execute("""SELECT CASE
      WHEN distance < 1 THEN "<1m"
      WHEN distance < 2 THEN "1-2m"
      WHEN distance < 5 THEN "2-5m"
      WHEN distance < 10 THEN "5-10m"
      WHEN distance < 20 THEN "10-20m"
      ELSE "20m+"
      END as band, COUNT(*) FROM sightings WHERE distance IS NOT NULL GROUP BY band ORDER BY MIN(distance)"""):
        print(f"  {r[1]:4}  {r[0]}")


if __name__ == "__main__":
    main()

import sqlite3
from pathlib import Path

DB_PATH = "data.db"
ITEMS_COUNT = 1000

def main():
    if Path(DB_PATH).exists():
        Path(DB_PATH).unlink()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    rows = [(i, f"value_{i}") for i in range(1, ITEMS_COUNT + 1)]
    cur.executemany("INSERT INTO items (id, value) VALUES (?, ?)", rows)

    conn.commit()
    conn.close()

    print(f"DB initialized: {DB_PATH}, items: {ITEMS_COUNT}")

if __name__ == "__main__":
    main()

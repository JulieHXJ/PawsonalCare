# init_db.py
from schema import connect, migrate, DB_DEFAULT


def main():
    with connect(DB_DEFAULT) as conn:
        migrate(conn)
    print(f"✅ Database migrated/initialized safely: {DB_DEFAULT}")


if __name__ == "__main__":
    main()
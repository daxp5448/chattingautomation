import asyncio
import os
from sqlalchemy import create_engine, MetaData, text
from sqlalchemy.orm import sessionmaker

def migrate_data():
    sqlite_url = "sqlite:///dev.db"
    # Read Postgres URL from environment or use default
    pg_url = os.getenv("DATABASE_URL")
    if not pg_url:
        print("DATABASE_URL environment variable is not set.")
        return

    # Convert asyncpg to psycopg2 if needed for synchronous migration script
    if "postgresql+asyncpg" in pg_url:
        pg_url = pg_url.replace("postgresql+asyncpg", "postgresql")

    print(f"Source: {sqlite_url}")
    print(f"Target: {pg_url}")

    sqlite_engine = create_engine(sqlite_url)
    pg_engine = create_engine(pg_url)

    sqlite_meta = MetaData()
    sqlite_meta.reflect(bind=sqlite_engine)

    pg_meta = MetaData()
    pg_meta.reflect(bind=pg_engine)

    with sqlite_engine.connect() as sqlite_conn:
        with pg_engine.connect() as pg_conn:
            with pg_conn.begin():
                # Disable triggers (including foreign keys) to allow bulk insert
                pg_conn.execute(text("SET session_replication_role = 'replica';"))
                
                for table in sqlite_meta.sorted_tables:
                    if table.name == "alembic_version":
                        continue
                    
                    print(f"Migrating table: {table.name}...")
                    
                    # Read all rows from sqlite
                    rows = sqlite_conn.execute(table.select()).fetchall()
                    if not rows:
                        continue
                        
                    # Clear target table (optional, assuming we want an exact mirror)
                    pg_conn.execute(text(f'TRUNCATE TABLE "{table.name}" CASCADE;'))
                    
                    # Convert rows to list of dicts for insertion
                    # fetchall returns tuples, we need to map them to columns
                    keys = table.columns.keys()
                    dicts = [dict(zip(keys, row)) for row in rows]
                    
                    # Insert into PG
                    pg_target_table = pg_meta.tables[table.name]
                    pg_conn.execute(pg_target_table.insert(), dicts)
                    
                    print(f"  -> Migrated {len(rows)} rows.")

                # Re-enable triggers
                pg_conn.execute(text("SET session_replication_role = 'origin';"))
                
    print("Migration completed successfully!")

if __name__ == "__main__":
    migrate_data()

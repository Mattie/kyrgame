import os
from pathlib import Path

from kyrgame import database, loader


def main():
    database_url = os.getenv("DATABASE_URL", "sqlite:///kyrgame.db")
    fixture_dir = Path(os.getenv("KYRGAME_FIXTURES", "")) if os.getenv("KYRGAME_FIXTURES") else None

    engine = database.get_engine(database_url)
    database.init_db_schema(engine)
    session = database.create_session(engine)
    loader.load_all_from_fixtures(session, fixture_dir)


if __name__ == "__main__":
    main()

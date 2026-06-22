from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

from core.settings import settings

# Base class every model inherits from (same as your usual `declarative_base()`).
Base = declarative_base()


class Database:
    """One shared database connection for the whole app (singleton).

    How the singleton works:
    - `_instance` is a class attribute that starts as None.
    - The first time someone writes `Database()`, `__new__` sees `_instance is
      None`, builds the engine + session factory once, and stores that object
      in `_instance`.
    - Every later `Database()` call finds `_instance` already set and returns the
      SAME object instead of building a new engine. So there is only ever one
      engine/connection pool in the process.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._setup()
        return cls._instance

    def _setup(self):
        # check_same_thread is a SQLite-only option; skip it for other databases.
        connect_args = (
            {"check_same_thread": False}
            if settings.DATABASE_URL.startswith("sqlite")
            else {}
        )
        self.engine = create_engine(settings.DATABASE_URL, connect_args=connect_args)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def get_db(self):
        """FastAPI dependency: yield a session and always close it afterwards."""
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()


# The single shared instance — import `database` anywhere you need the DB.
database = Database()



import time

from alembic import op
from sqlalchemy import text

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SCHEMA = (
    """CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, user TEXT NOT NULL, created_at INT,
                last_seen INT, expires_at INT, ua TEXT)""",
    """CREATE TABLE IF NOT EXISTS plays(user TEXT, track_id INT, started_at INT, listened_ms INT,
                completed INT, skipped INT, source TEXT, PRIMARY KEY(user, track_id, started_at))""",
    """CREATE INDEX IF NOT EXISTS ix_plays_user_time ON plays(user, started_at)""",
    """CREATE TABLE IF NOT EXISTS likes(user TEXT, track_id INT, created_at INT, PRIMARY KEY(user, track_id))""",
    """CREATE TABLE IF NOT EXISTS letters(id INTEGER PRIMARY KEY AUTOINCREMENT, sender TEXT NOT NULL,
                recipient TEXT NOT NULL, track_id INT NOT NULL, text TEXT NOT NULL, created_at INT NOT NULL, read_at INT)""",
    """CREATE INDEX IF NOT EXISTS ix_letters_recipient ON letters(recipient, created_at)""",
    """CREATE TABLE IF NOT EXISTS ours(track_id INT PRIMARY KEY, added_by TEXT NOT NULL, added_at INT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS together(day TEXT PRIMARY KEY, seconds REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS pet(id INTEGER PRIMARY KEY CHECK(id=1), name TEXT, born_at INT NOT NULL,
                food REAL NOT NULL, joy REAL NOT NULL, energy REAL NOT NULL, clean REAL NOT NULL,
                sick INT NOT NULL DEFAULT 0, asleep_until INT, updated_at INT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS pet_log(id INTEGER PRIMARY KEY AUTOINCREMENT, at INT NOT NULL, user TEXT,
                action TEXT NOT NULL, detail TEXT)""",
    """CREATE INDEX IF NOT EXISTS ix_pet_log_at ON pet_log(at)""",
    """CREATE TABLE IF NOT EXISTS push_subs(endpoint TEXT PRIMARY KEY, user TEXT NOT NULL, p256dh TEXT NOT NULL,
                auth TEXT NOT NULL, created_at INT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS quest_day(day TEXT PRIMARY KEY, kind TEXT NOT NULL, album_id INT,
                set_by TEXT NOT NULL, set_at INT NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS daily(id INTEGER PRIMARY KEY AUTOINCREMENT, day TEXT NOT NULL, slot INT NOT NULL,
                for_user TEXT NOT NULL, title TEXT NOT NULL, blurb TEXT NOT NULL, tracks TEXT NOT NULL,
                model TEXT NOT NULL, created_at INT NOT NULL, UNIQUE(day, slot))""",
)
PET_SEED = (
    "INSERT OR IGNORE INTO pet(id,born_at,food,joy,energy,clean,updated_at) "
    "VALUES (1,:now,80,80,80,80,:now)"
)


def upgrade() -> None:
    for statement in SCHEMA:
        op.execute(statement)
    op.execute(text(PET_SEED).bindparams(now=int(time.time() * 1000)))

CREATE TABLE artists(name TEXT PRIMARY KEY, mbid TEXT, count INT, genre TEXT, tier INT, canonical TEXT);
CREATE TABLE albums(id INTEGER PRIMARY KEY AUTOINCREMENT, artist TEXT, mbid TEXT UNIQUE, name TEXT, year TEXT,
        genre TEXT, tier INT, ntracks INT DEFAULT 0, canonical TEXT);
CREATE TABLE tracks(id INTEGER PRIMARY KEY AUTOINCREMENT, album_id INT, num INT, artist TEXT, album TEXT,
        title TEXT, dur INT, tier INT, status TEXT DEFAULT 'pending', path TEXT, err TEXT);
CREATE INDEX ix_tracks_status ON tracks(status);
CREATE INDEX ix_tracks_album ON tracks(album_id);

CREATE TABLE records (
 id TEXT PRIMARY KEY, category TEXT NOT NULL, title TEXT NOT NULL,
 content TEXT NOT NULL, effective_date TEXT, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
 source_ref TEXT, payload TEXT NOT NULL CHECK(json_valid(payload)), deleted INTEGER NOT NULL DEFAULT 0);
CREATE INDEX records_date ON records(effective_date,category,deleted);
CREATE UNIQUE INDEX records_source ON records(category,source_ref) WHERE source_ref IS NOT NULL;
CREATE TABLE versions(record_id TEXT NOT NULL REFERENCES records(id),version INTEGER NOT NULL,
 timestamp TEXT NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(record_id,version));
CREATE TABLE audit(sequence INTEGER PRIMARY KEY AUTOINCREMENT,record_id TEXT NOT NULL,
 action TEXT NOT NULL,timestamp TEXT NOT NULL,actor TEXT NOT NULL,authorization TEXT NOT NULL,
 version INTEGER NOT NULL);
CREATE TABLE idempotency(key TEXT PRIMARY KEY,digest TEXT NOT NULL,result TEXT NOT NULL,timestamp TEXT NOT NULL);
CREATE TABLE links(record_id TEXT NOT NULL REFERENCES records(id),related_id TEXT NOT NULL REFERENCES records(id),
 PRIMARY KEY(record_id,related_id));
CREATE VIRTUAL TABLE records_fts USING fts5(id UNINDEXED,title,content,tokenize='unicode61 remove_diacritics 2');
CREATE TRIGGER record_insert AFTER INSERT ON records WHEN new.deleted=0 BEGIN
 INSERT INTO records_fts VALUES(new.id,new.title,new.content); END;
CREATE TRIGGER record_update AFTER UPDATE ON records BEGIN
 DELETE FROM records_fts WHERE id=old.id;
 INSERT INTO records_fts SELECT new.id,new.title,new.content WHERE new.deleted=0; END;

-- Data for the end-to-end comparison (tools/golden/e2e.sh and tests/test_e2e.py).
-- Loaded after the CREATE TABLE statements of install.sql.
INSERT INTO global_query_review (checksum, fingerprint, sample, first_seen, last_seen, reviewed_by, reviewed_on, reviewed_status, comments) VALUES
  ('A1', 'select * from global_query_review where checksum = ?', 'select * from global_query_review where checksum = 1', '2024-03-01 00:00:00', '2024-03-31 10:00:00', 'dba1', '2024-03-31 11:00:00', 'needs-fix', 'add an index'),
  ('B2', 'select ?', 'select 2', '2024-03-02 00:00:00', '2024-03-30 11:00:00', NULL, NULL, NULL, NULL);
INSERT INTO global_query_review_history (hostname_max, db_max, user_max, checksum, sample, ts_min, ts_max, ts_cnt, Query_time_sum, Query_time_max, Lock_time_sum, Rows_sent_sum, Rows_examined_sum) VALUES
  ('db1.example.com', 'app', 'web', 'A1', 'select * from global_query_review where checksum = ''x''', '2024-03-30 10:00:00', '2024-03-30 10:05:00', 2, 0.5, 0.3, 0.01, 2, 200),
  ('db2.example.com', 'app', 'web', 'A1', 'select * from global_query_review where checksum = ''y''', '2024-03-31 10:00:00', '2024-03-31 10:05:00', 1, 1.5, 1.5, 0.02, 1, 100),
  ('db1.example.com', 'app', 'batch', 'B2', 'select 2', '2024-03-31 11:00:00', '2024-03-31 11:05:00', 4, 2, 0.75, 0, 4, 4);

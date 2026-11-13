-- Local dev/test only. Production users and passwords are created by the operator (see deploy/README.md).
-- msp_migrator: DDL + grants; msp_ingest: plan tables RW; msp_api: plan tables RO, user tables RW.
-- Table-level grants are applied after migrations by `selector db-grants`.
CREATE DATABASE IF NOT EXISTS msp CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE USER IF NOT EXISTS 'msp_migrator'@'%' IDENTIFIED WITH caching_sha2_password BY 'dev-migrator-pw';
CREATE USER IF NOT EXISTS 'msp_ingest'@'%' IDENTIFIED WITH caching_sha2_password BY 'dev-ingest-pw';
CREATE USER IF NOT EXISTS 'msp_api'@'%' IDENTIFIED WITH caching_sha2_password BY 'dev-api-pw';
GRANT ALL PRIVILEGES ON msp.* TO 'msp_migrator'@'%' WITH GRANT OPTION;
-- Throwaway databases for migration tests (msp_test_*).
GRANT ALL PRIVILEGES ON `msp\_test\_%`.* TO 'msp_migrator'@'%' WITH GRANT OPTION;
FLUSH PRIVILEGES;

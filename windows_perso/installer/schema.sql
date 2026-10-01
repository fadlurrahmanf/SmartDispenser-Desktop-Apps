CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    created_at VARCHAR(40) NOT NULL,
    event_type VARCHAR(32) NOT NULL,
    status VARCHAR(96) NOT NULL,
    operation VARCHAR(48),
    card_session BIGINT UNSIGNED
);

CREATE TABLE IF NOT EXISTS customers (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    customer_number VARCHAR(32) NOT NULL UNIQUE,
    nik VARCHAR(16) NOT NULL UNIQUE,
    family_card_number VARCHAR(16) NOT NULL,
    full_name VARCHAR(160) NOT NULL,
    phone VARCHAR(32),
    address VARCHAR(500),
    status VARCHAR(16) NOT NULL DEFAULT 'active',
    created_at VARCHAR(40) NOT NULL,
    updated_at VARCHAR(40) NOT NULL
);

CREATE TABLE IF NOT EXISTS personalization_runs (
    run_id VARCHAR(36) NOT NULL PRIMARY KEY,
    customer_id BIGINT UNSIGNED NOT NULL,
    device_port VARCHAR(32),
    card_session BIGINT UNSIGNED,
    started_at VARCHAR(40) NOT NULL,
    completed_at VARCHAR(40),
    result VARCHAR(32) NOT NULL,
    failure_stage VARCHAR(48),
    failure_code VARCHAR(96),
    precheck_result VARCHAR(32),
    sectors_checked SMALLINT UNSIGNED DEFAULT 0,
    readable_blocks SMALLINT UNSIGNED DEFAULT 0,
    restricted_blocks SMALLINT UNSIGNED DEFAULT 0,
    quality_success SMALLINT UNSIGNED,
    quality_attempts SMALLINT UNSIGNED,
    wallet_sector SMALLINT UNSIGNED NOT NULL DEFAULT 2,
    wallet_block SMALLINT UNSIGNED NOT NULL DEFAULT 8,
    wallet_version SMALLINT UNSIGNED NOT NULL DEFAULT 2,
    protection_written BOOLEAN NOT NULL DEFAULT FALSE,
    wallet_written BOOLEAN NOT NULL DEFAULT FALSE,
    verification_passed BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT fk_runs_customer FOREIGN KEY (customer_id) REFERENCES customers(id)
);

CREATE TABLE IF NOT EXISTS customer_cards (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    customer_id BIGINT UNSIGNED NOT NULL,
    personalization_run_id VARCHAR(36) NOT NULL UNIQUE,
    card_reference VARCHAR(96),
    card_session BIGINT UNSIGNED,
    status VARCHAR(24) NOT NULL DEFAULT 'active',
    wallet_version SMALLINT UNSIGNED NOT NULL DEFAULT 2,
    wallet_sector SMALLINT UNSIGNED NOT NULL DEFAULT 2,
    wallet_block SMALLINT UNSIGNED NOT NULL DEFAULT 8,
    activated_at VARCHAR(40) NOT NULL,
    CONSTRAINT fk_cards_customer FOREIGN KEY (customer_id) REFERENCES customers(id),
    CONSTRAINT fk_cards_run FOREIGN KEY (personalization_run_id) REFERENCES personalization_runs(run_id),
    INDEX idx_cards_customer_status (customer_id, status)
);

CREATE TABLE IF NOT EXISTS card_reference_allocations (
    card_reference INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
    personalization_run_id VARCHAR(36) NOT NULL UNIQUE,
    allocated_at VARCHAR(40) NOT NULL,
    CONSTRAINT fk_reference_run FOREIGN KEY (personalization_run_id) REFERENCES personalization_runs(run_id)
);

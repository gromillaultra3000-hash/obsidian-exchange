CREATE TABLE workers(user_id BIGINT PRIMARY KEY,username TEXT,added_by BIGINT,
 added_at TIMESTAMPTZ NOT NULL DEFAULT now(),is_active BOOLEAN NOT NULL DEFAULT true);
CREATE TABLE operators(user_id BIGINT PRIMARY KEY,username TEXT,added_by BIGINT,
 added_at TIMESTAMPTZ NOT NULL DEFAULT now(),is_active BOOLEAN NOT NULL DEFAULT true);
CREATE TABLE blocked_users(user_id BIGINT PRIMARY KEY,reason TEXT,
 blocked_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE blocked_addresses(address TEXT PRIMARY KEY,reason TEXT,blocked_by BIGINT,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE TABLE reserves(currency TEXT PRIMARY KEY,amount NUMERIC(30,12) NOT NULL CHECK(amount>=0),
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now());

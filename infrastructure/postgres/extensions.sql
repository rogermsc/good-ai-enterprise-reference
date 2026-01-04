-- PostgreSQL Extensions Setup
-- Run during database initialization

-- UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Vector operations for embeddings (pgvector)
CREATE EXTENSION IF NOT EXISTS "vector";

-- Cryptographic functions (for future token encryption)
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

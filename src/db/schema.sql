-- Good AI Enterprise Reference - Database Schema
-- PostgreSQL 15+ with pgvector extension

-- Enable required extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- Audit logs table
-- Stores immutable records of all AI operations
CREATE TABLE IF NOT EXISTS audit_logs (
    audit_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    ticket_id VARCHAR(100) NOT NULL,
    user_id VARCHAR(100) NOT NULL,
    tenant_id VARCHAR(100) NOT NULL,
    redacted_input TEXT NOT NULL,
    token_map JSONB,
    model_name VARCHAR(50),
    provider VARCHAR(50),
    severity VARCHAR(10),
    actions JSONB,
    policy_decision JSONB NOT NULL,
    final_response TEXT,
    latency_ms INTEGER,
    cost_estimate DECIMAL(10, 6),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_audit_logs_ticket_id ON audit_logs(ticket_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id ON audit_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_severity ON audit_logs(severity);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_created ON audit_logs(tenant_id, created_at DESC);

-- Tickets table (optional - for full ticket storage)
CREATE TABLE IF NOT EXISTS tickets (
    ticket_id VARCHAR(100) PRIMARY KEY,
    tenant_id VARCHAR(100) NOT NULL,
    subject VARCHAR(500) NOT NULL,
    body TEXT NOT NULL,
    customer_email VARCHAR(255),
    source VARCHAR(50),
    severity VARCHAR(10),
    status VARCHAR(50) DEFAULT 'open',
    assigned_to VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tickets_tenant_id ON tickets(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_severity ON tickets(severity);
CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets(created_at DESC);

-- Embeddings table (for RAG - future use)
CREATE TABLE IF NOT EXISTS embeddings (
    embedding_id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id VARCHAR(100) NOT NULL,
    content_type VARCHAR(50) NOT NULL,
    content_id VARCHAR(100) NOT NULL,
    chunk_index INTEGER DEFAULT 0,
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_tenant_id ON embeddings(tenant_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_content_id ON embeddings(content_id);

-- Vector similarity search index (IVFFlat for large datasets)
-- Note: Create after initial data load for better performance
-- CREATE INDEX IF NOT EXISTS idx_embeddings_vector ON embeddings
--     USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- Comments for documentation
COMMENT ON TABLE audit_logs IS 'Immutable audit trail of all AI operations';
COMMENT ON COLUMN audit_logs.redacted_input IS 'Ticket content with PII tokenized';
COMMENT ON COLUMN audit_logs.token_map IS 'Mapping of tokens to original PII values (encrypt in production)';
COMMENT ON COLUMN audit_logs.policy_decision IS 'Full policy engine response';

COMMENT ON TABLE tickets IS 'Support tickets (optional storage)';
COMMENT ON TABLE embeddings IS 'Vector embeddings for RAG (future use)';

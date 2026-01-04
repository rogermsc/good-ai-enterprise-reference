-- Good AI Enterprise Reference - Database Initialization
-- This script runs when the PostgreSQL container starts

-- Create extensions
\i /docker-entrypoint-initdb.d/extensions.sql

-- Create audit_logs table
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

-- Create indexes
CREATE INDEX IF NOT EXISTS idx_audit_logs_ticket_id ON audit_logs(ticket_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_id ON audit_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_severity ON audit_logs(severity);
CREATE INDEX IF NOT EXISTS idx_audit_logs_tenant_created ON audit_logs(tenant_id, created_at DESC);

-- Create tickets table
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

-- Create embeddings table for future RAG use
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

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO postgres;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO postgres;

-- Log completion
DO $$
BEGIN
    RAISE NOTICE 'Good AI Enterprise Reference database initialized successfully';
END $$;

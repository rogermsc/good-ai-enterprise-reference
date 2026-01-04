# Data Sovereignty Patterns

> **Disclaimer:** This document describes architectural patterns for data sovereignty compliance.
> It is not legal advice. Consult legal counsel and data protection officers for specific
> regulatory requirements in your jurisdiction.

## Overview

Enterprise AI systems processing personal data must comply with data residency requirements. This document outlines patterns for Brazil (LGPD), Ecuador, and general cross-border processing scenarios.

## Regulatory Context

### Brazil — LGPD

Lei Geral de Proteção de Dados (LGPD) establishes:
- Personal data of Brazilian citizens protected
- Cross-border transfer requires adequacy decisions or contractual safeguards
- Data subjects have rights to access, correction, deletion
- DPO appointment required for certain processing activities

### Ecuador

Ecuador's Organic Law on Personal Data Protection establishes:
- Cédula de Identidad is sensitive identification data
- Processing requires consent or legitimate basis
- International transfers require equivalent protection
- Sector-specific regulations may apply

## Pattern 1: Sovereign Gateway (Redaction/Tokenization)

**Use Case:** Process data with external LLMs while maintaining data residency

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SOVEREIGN BOUNDARY (Brazil)                           │
│                                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │   Client    │───▶│  Sovereign  │───▶│   Token     │                 │
│  │   Request   │    │   Gateway   │    │   Store     │                 │
│  │  (Raw PII)  │    │ (Redaction) │    │  (Brazil)   │                 │
│  └─────────────┘    └──────┬──────┘    └─────────────┘                 │
│                            │                                             │
└────────────────────────────┼─────────────────────────────────────────────┘
                             │ Tokenized data only
                             ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    EXTERNAL (Any Region)                                 │
│                                                                          │
│  ┌─────────────┐                                                        │
│  │  LLM API    │  Receives: "[PII_CPF_1] reported an issue..."         │
│  │  (OpenAI)   │  Never sees: "123.456.789-00"                          │
│  └─────────────┘                                                        │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Implementation:**

```python
# 1. All PII redacted before leaving sovereign boundary
redacted_text, token_map = pii_redactor.redact(raw_text)

# 2. Token map stored in sovereign region
await token_store.save(ticket_id, token_map)  # Brazil datacenter

# 3. Only tokenized data sent to LLM
response = await llm_gateway.complete(redacted_text)

# 4. Restoration happens within sovereign boundary
final_response = pii_redactor.restore(response, token_map)
```

**Benefits:**
- LLM never processes raw PII
- Token map remains in sovereign region
- Compliant with cross-border transfer restrictions

**Limitations:**
- Token format may leak data types
- Response quality may suffer from missing context
- Token map storage adds complexity

## Pattern 2: Hybrid RAG with Residency

**Use Case:** Enterprise knowledge base with mixed residency requirements

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    SOVEREIGN REGION (Ecuador)                            │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    LOCAL VECTOR STORE                                ││
│  │  • Employee records (Cédula, personal data)                         ││
│  │  • Customer PII                                                      ││
│  │  • Regulated documents                                               ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    LOCAL EMBEDDING MODEL                             ││
│  │  • Runs within sovereign boundary                                    ││
│  │  • Generates embeddings without external calls                       ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────────┐
│                    GLOBAL REGION                                         │
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────────┐│
│  │                    GLOBAL VECTOR STORE                               ││
│  │  • Public documentation                                              ││
│  │  • Product manuals                                                   ││
│  │  • Non-sensitive knowledge                                           ││
│  └─────────────────────────────────────────────────────────────────────┘│
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Query Flow:**

1. Query classified for data sensitivity
2. Sensitive queries → local vector store only
3. Non-sensitive queries → can use global store
4. Results merged within sovereign boundary
5. LLM call uses redacted context only

**Implementation Considerations:**

- Embedding models can run locally (sentence-transformers)
- pgvector enables sovereign vector storage
- Query routing based on sensitivity classification
- Fallback to local-only for uncertain cases

## Pattern 3: Full Air-Gapped Sovereign AI

**Use Case:** Maximum data protection, no external LLM calls

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    FULLY SOVEREIGN DEPLOYMENT                            │
│                                                                          │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                 │
│  │   Client    │───▶│    API      │───▶│   LOCAL     │                 │
│  │   Request   │    │   Gateway   │    │    LLM      │                 │
│  └─────────────┘    └─────────────┘    │  (Llama,    │                 │
│                                         │   Mistral)  │                 │
│  ┌─────────────┐    ┌─────────────┐    └─────────────┘                 │
│  │   Vector    │    │  PostgreSQL │                                     │
│  │   Store     │    │  (pgvector) │                                     │
│  └─────────────┘    └─────────────┘                                     │
│                                                                          │
│  ALL COMPONENTS WITHIN SOVEREIGN BOUNDARY                                │
│  NO EXTERNAL API CALLS                                                   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

**Components:**

| Component | Sovereign Alternative |
|-----------|----------------------|
| LLM | Llama 3, Mistral, locally deployed |
| Embeddings | sentence-transformers, local |
| Vector DB | pgvector (PostgreSQL) |
| API | FastAPI (this reference) |

**Trade-offs:**

- (+) Complete data control
- (+) No external dependencies
- (-) Lower model capability
- (-) Higher infrastructure cost
- (-) Operational complexity

## Implementation in This Reference

This reference implementation uses **Pattern 1: Sovereign Gateway**:

```python
# src/core/pii_redaction.py
class PIIRedactor:
    """Tokenizes PII before external processing."""

    def redact(self, text: str) -> tuple[str, dict]:
        """
        Returns (redacted_text, token_map).
        Token map stored in sovereign region.
        """
        # CPF, CNPJ, Cédula, email, phone patterns
        ...

    def restore(self, text: str, token_map: dict) -> str:
        """Restores PII from tokens within sovereign boundary."""
        ...
```

## Audit Trail for Sovereignty

All data processing is logged with:
- Timestamp of processing
- Data classification (PII type)
- Processing location (region)
- External services called (if any)
- Token map reference (not content)

## Production Recommendations

1. **Data Classification**
   - Implement automated PII detection
   - Tag data with residency requirements
   - Audit classification accuracy

2. **Infrastructure**
   - Deploy in sovereign cloud regions (AWS São Paulo, Azure Brazil)
   - Use cloud-native encryption (KMS in-region)
   - Implement network segmentation

3. **Monitoring**
   - Alert on cross-border data flow attempts
   - Log all external API calls
   - Regular compliance audits

4. **Legal**
   - Document processing activities
   - Maintain data processing agreements
   - Appoint DPO where required

## References

- LGPD Full Text (Portuguese)
- Ecuador Organic Law on Personal Data Protection
- GDPR Cross-Border Transfer Guidance
- Cloud Provider Compliance Documentation

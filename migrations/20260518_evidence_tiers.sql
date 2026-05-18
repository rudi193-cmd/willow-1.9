-- Evidence tiers v0 — Soul mechanics Part 3, 2026-05-18
-- Adds tier + confidence to knowledge atoms.
-- tier:       hypothesis | observed | validated  (NULL = legacy, treat as observed)
-- confidence: 0.0–1.0 float (NULL = unscored)

ALTER TABLE knowledge
    ADD COLUMN IF NOT EXISTS tier       TEXT CHECK (tier IN ('hypothesis','observed','validated')),
    ADD COLUMN IF NOT EXISTS confidence FLOAT CHECK (confidence >= 0.0 AND confidence <= 1.0);

CREATE INDEX IF NOT EXISTS knowledge_tier_idx ON knowledge(tier) WHERE tier IS NOT NULL;

-- Backfill existing atoms as 'observed' with full confidence
UPDATE knowledge SET tier = 'observed', confidence = 1.0 WHERE tier IS NULL;

COMMENT ON COLUMN knowledge.tier IS
    'Evidence tier: hypothesis (unverified), observed (seen in practice), validated (confirmed by multiple sources)';
COMMENT ON COLUMN knowledge.confidence IS
    '0.0–1.0 confidence score. 1.0 = fully confident, 0.0 = speculative.';

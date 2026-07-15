-- Schema iniziale, caricato automaticamente da PostgreSQL al primo avvio.

CREATE TABLE IF NOT EXISTS reviews (
    id           UUID PRIMARY KEY,
    bank         TEXT,
    text         TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'pending',  -- pending|processing|done|error
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS aspects (
    id         BIGSERIAL PRIMARY KEY,
    review_id  UUID NOT NULL REFERENCES reviews(id) ON DELETE CASCADE,
    aspect     TEXT NOT NULL,
    sentiment  TEXT NOT NULL,    -- Positive|Negative|Neutral
    confidence REAL
);

CREATE INDEX IF NOT EXISTS idx_aspects_review ON aspects(review_id);
CREATE INDEX IF NOT EXISTS idx_reviews_status ON reviews(status);

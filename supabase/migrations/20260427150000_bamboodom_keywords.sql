-- Bamboodom keywords storage for auto-publishing pipeline (Session 4Y, 2026-04-27)
-- Storing collected keywords from DataForSEO Yandex per material with AI clustering.
-- Phase 1: manual publish trigger. Phase 2 will add cron-based auto-publish.

CREATE TABLE bamboodom_keywords (
    id              SERIAL PRIMARY KEY,
    keyword         TEXT NOT NULL,
    material        VARCHAR(20) NOT NULL,  -- wpc / flex / reiki / profiles
    search_volume   INTEGER NOT NULL DEFAULT 0,
    competition     REAL,                  -- 0..1 from DataForSEO, nullable
    cluster_id      INTEGER,
    cluster_label   VARCHAR(80),           -- e.g. "выбор", "монтаж", "сравнение", "use-case"
    status          VARCHAR(20) NOT NULL DEFAULT 'new',
    -- new: ready to publish
    -- queued: picked by auto-publisher, in flight
    -- used: published successfully
    -- failed: publication attempt failed
    -- skipped: admin marked as not for publishing
    published_slug  VARCHAR(255),
    published_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at    TIMESTAMPTZ,
    UNIQUE(keyword, material)
);

CREATE INDEX idx_bbk_material_status ON bamboodom_keywords(material, status);
CREATE INDEX idx_bbk_cluster ON bamboodom_keywords(material, cluster_id);
CREATE INDEX idx_bbk_volume ON bamboodom_keywords(search_volume DESC);

-- Phase 2 (next session): autopost settings table will be added separately.

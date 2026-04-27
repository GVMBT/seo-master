-- Geo-expansion for bamboodom_keywords (Session 5E, 2026-04-27)
-- Adds city column for geo-targeted articles. Crimean cities by default.

ALTER TABLE bamboodom_keywords
    ADD COLUMN IF NOT EXISTS city VARCHAR(64);

-- Drop old UNIQUE on (keyword, material) — replace with composite that includes city.
-- NULL city = generic keyword (no geo). Same keyword+material can have multiple
-- city-tagged variants.
ALTER TABLE bamboodom_keywords
    DROP CONSTRAINT IF EXISTS bamboodom_keywords_keyword_material_key;

-- Use a partial unique index to treat NULL city as "no duplicate" per
-- (keyword, material). Postgres NULLs are not equal by default — so the
-- old UNIQUE worked for generics. Now we need:
--   * (keyword, material) unique when city IS NULL
--   * (keyword, material, city) unique when city IS NOT NULL
CREATE UNIQUE INDEX IF NOT EXISTS uniq_bbk_keyword_material_no_city
    ON bamboodom_keywords (keyword, material)
    WHERE city IS NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uniq_bbk_keyword_material_city
    ON bamboodom_keywords (keyword, material, city)
    WHERE city IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_bbk_material_city
    ON bamboodom_keywords (material, city)
    WHERE city IS NOT NULL;

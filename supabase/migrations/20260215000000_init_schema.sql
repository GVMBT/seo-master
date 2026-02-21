-- SEO Master Bot v2 — Initial Schema
-- Source of truth: docs/ARCHITECTURE.md section 3.2
-- Apply via: Supabase SQL Editor or `supabase db push`

-- ============================================================================
-- 1. users
-- ============================================================================
CREATE TABLE users (
    id              BIGINT PRIMARY KEY,
    username        VARCHAR(255),
    first_name      VARCHAR(255),
    last_name       VARCHAR(255),
    balance         INTEGER NOT NULL DEFAULT 1500,
    language        VARCHAR(10) DEFAULT 'ru',
    role            VARCHAR(20) DEFAULT 'user',
    referrer_id     BIGINT REFERENCES users(id) ON DELETE SET NULL,
    notify_publications BOOLEAN DEFAULT TRUE,
    notify_balance  BOOLEAN DEFAULT TRUE,
    notify_news     BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT now(),
    last_activity   TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_users_referrer ON users(referrer_id);
CREATE INDEX idx_users_activity ON users(last_activity);

-- ============================================================================
-- 2. projects
-- ============================================================================
CREATE TABLE projects (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    company_name    VARCHAR(255) NOT NULL,
    specialization  TEXT NOT NULL,
    website_url     VARCHAR(500),
    company_city    VARCHAR(255),
    company_address TEXT,
    company_phone   VARCHAR(50),
    company_email   VARCHAR(255),
    company_instagram VARCHAR(255),
    company_vk      VARCHAR(255),
    company_pinterest VARCHAR(255),
    company_telegram VARCHAR(255),
    experience      TEXT,
    advantages      TEXT,
    description     TEXT,
    timezone        VARCHAR(50) DEFAULT 'Europe/Moscow',
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_projects_user ON projects(user_id);

-- ============================================================================
-- 3. platform_connections
-- ============================================================================
CREATE TABLE platform_connections (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    platform_type   VARCHAR(20) NOT NULL,
    status          VARCHAR(20) DEFAULT 'active',
    credentials     TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    identifier      VARCHAR(500) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(project_id, platform_type, identifier)
);
CREATE INDEX idx_connections_project ON platform_connections(project_id);

-- ============================================================================
-- 4. categories
-- ============================================================================
CREATE TABLE categories (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name            VARCHAR(255) NOT NULL,
    description     TEXT,
    keywords        JSONB DEFAULT '[]',
    media           JSONB DEFAULT '[]',
    prices          TEXT,
    reviews         JSONB DEFAULT '[]',
    image_settings  JSONB DEFAULT '{}',
    text_settings   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_categories_project ON categories(project_id);

-- ============================================================================
-- 5. platform_content_overrides
-- ============================================================================
CREATE TABLE platform_content_overrides (
    id              SERIAL PRIMARY KEY,
    category_id     INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    platform_type   VARCHAR(20) NOT NULL,
    image_settings  JSONB,
    text_settings   JSONB,
    UNIQUE(category_id, platform_type)
);

-- ============================================================================
-- 6. platform_schedules
-- ============================================================================
CREATE TABLE platform_schedules (
    id              SERIAL PRIMARY KEY,
    category_id     INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    platform_type   VARCHAR(20) NOT NULL,
    connection_id   INTEGER NOT NULL REFERENCES platform_connections(id) ON DELETE CASCADE,
    schedule_days   TEXT[] DEFAULT '{}',
    schedule_times  TEXT[] DEFAULT '{}',
    posts_per_day   INTEGER DEFAULT 1 CHECK (posts_per_day BETWEEN 1 AND 5),
    enabled         BOOLEAN DEFAULT FALSE,
    status          VARCHAR(20) DEFAULT 'active',
    qstash_schedule_ids TEXT[] DEFAULT '{}',
    cross_post_connection_ids INTEGER[] DEFAULT '{}',
    last_post_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(category_id, platform_type, connection_id),
    CHECK (schedule_times = '{}' OR array_length(schedule_times, 1) = posts_per_day)
);
CREATE INDEX idx_schedules_enabled ON platform_schedules(enabled) WHERE enabled = TRUE;

-- ============================================================================
-- 7. publication_logs
-- ============================================================================
CREATE TABLE publication_logs (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category_id     INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    platform_type   VARCHAR(20) NOT NULL,
    connection_id   INTEGER REFERENCES platform_connections(id) ON DELETE SET NULL,
    keyword         VARCHAR(500),
    content_type    VARCHAR(20) NOT NULL DEFAULT 'article',
    images_count    INTEGER DEFAULT 0,
    post_url        TEXT,
    word_count      INTEGER DEFAULT 0,
    tokens_spent    INTEGER DEFAULT 0,
    ai_model        VARCHAR(100),
    generation_time_ms INTEGER,
    prompt_version  VARCHAR(20),
    content_hash    BIGINT,
    status          VARCHAR(20) DEFAULT 'success',
    error_message   TEXT,
    rank_position   INTEGER,
    rank_checked_at TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_pub_logs_user ON publication_logs(user_id, created_at DESC);
CREATE INDEX idx_pub_logs_project ON publication_logs(project_id);
CREATE INDEX idx_pub_logs_category ON publication_logs(category_id, created_at DESC);
CREATE INDEX idx_pub_logs_rotation ON publication_logs(category_id, created_at DESC) INCLUDE (keyword);

-- ============================================================================
-- 8. token_expenses
-- ============================================================================
CREATE TABLE token_expenses (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    amount          INTEGER NOT NULL,
    operation_type  VARCHAR(50) NOT NULL,
    description     TEXT,
    ai_model        VARCHAR(100),
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    cost_usd        DECIMAL(10,6),
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_expenses_user ON token_expenses(user_id, created_at DESC);

-- ============================================================================
-- 9. payments
-- ============================================================================
CREATE TABLE payments (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    provider        VARCHAR(20) NOT NULL,
    status          VARCHAR(20) NOT NULL DEFAULT 'pending',
    telegram_payment_charge_id VARCHAR(255),
    provider_payment_charge_id VARCHAR(255),
    stars_amount    INTEGER,
    yookassa_payment_id VARCHAR(255),
    yookassa_payment_method_id VARCHAR(255),
    package_name    VARCHAR(50),
    tokens_amount   INTEGER NOT NULL,
    amount_rub      DECIMAL(10,2),
    is_subscription BOOLEAN DEFAULT FALSE,
    subscription_id VARCHAR(255),
    subscription_status VARCHAR(20),
    subscription_expires_at TIMESTAMPTZ,
    referral_bonus_credited BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX idx_payments_user ON payments(user_id);
CREATE INDEX idx_payments_status ON payments(status) WHERE status = 'pending';

-- ============================================================================
-- 10. site_audits
-- ============================================================================
CREATE TABLE site_audits (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url             VARCHAR(500) NOT NULL,
    performance     INTEGER,
    accessibility   INTEGER,
    best_practices  INTEGER,
    seo_score       INTEGER,
    lcp_ms          INTEGER,
    inp_ms          INTEGER,
    cls             DECIMAL(5,3),
    ttfb_ms         INTEGER,
    full_report     JSONB,
    recommendations JSONB DEFAULT '[]',
    audited_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(project_id)
);
CREATE INDEX idx_audits_project ON site_audits(project_id);

-- ============================================================================
-- 11. site_brandings
-- ============================================================================
CREATE TABLE site_brandings (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    url             VARCHAR(500) NOT NULL,
    colors          JSONB DEFAULT '{}',
    fonts           JSONB DEFAULT '{}',
    logo_url        TEXT,
    extracted_at    TIMESTAMPTZ DEFAULT now(),
    UNIQUE(project_id)
);
CREATE INDEX idx_brandings_project ON site_brandings(project_id);

-- ============================================================================
-- 12. article_previews
-- ============================================================================
CREATE TABLE article_previews (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(id),
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category_id     INTEGER NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    connection_id   INTEGER REFERENCES platform_connections(id) ON DELETE SET NULL,
    telegraph_url   VARCHAR(500),
    telegraph_path  VARCHAR(255),
    title           TEXT,
    keyword         VARCHAR(500),
    word_count      INTEGER,
    images_count    INTEGER,
    tokens_charged  INTEGER,
    regeneration_count INTEGER DEFAULT 0,
    status          VARCHAR(20) DEFAULT 'draft',
    content_html    TEXT,
    images          JSONB DEFAULT '[]',
    created_at      TIMESTAMPTZ DEFAULT now(),
    expires_at      TIMESTAMPTZ DEFAULT (now() + INTERVAL '24 hours')
);
CREATE INDEX idx_previews_user ON article_previews(user_id);
CREATE INDEX idx_previews_expires ON article_previews(expires_at) WHERE status = 'draft';

-- ============================================================================
-- 13. prompt_versions
-- ============================================================================
CREATE TABLE prompt_versions (
    id              SERIAL PRIMARY KEY,
    task_type       VARCHAR(50) NOT NULL,
    version         VARCHAR(20) NOT NULL,
    prompt_yaml     TEXT NOT NULL,
    is_active       BOOLEAN DEFAULT FALSE,
    success_rate    DECIMAL(5,2),
    avg_quality     DECIMAL(3,1),
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(task_type, version)
);

-- ============================================================================
-- RPC Functions: Atomic Balance Operations (ARCHITECTURE.md section 5.5)
-- ============================================================================

-- charge_balance: atomic deduction with balance check
CREATE OR REPLACE FUNCTION charge_balance(p_user_id BIGINT, p_amount INTEGER)
RETURNS INTEGER AS $$
DECLARE
    new_balance INTEGER;
BEGIN
    UPDATE users SET balance = balance - p_amount
    WHERE id = p_user_id AND balance >= p_amount
    RETURNING balance INTO new_balance;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'insufficient_balance';
    END IF;
    RETURN new_balance;
END;
$$ LANGUAGE plpgsql;

-- refund_balance: atomic refund (error/expiry)
CREATE OR REPLACE FUNCTION refund_balance(p_user_id BIGINT, p_amount INTEGER)
RETURNS INTEGER AS $$
DECLARE
    new_balance INTEGER;
BEGIN
    UPDATE users SET balance = balance + p_amount
    WHERE id = p_user_id
    RETURNING balance INTO new_balance;
    RETURN new_balance;
END;
$$ LANGUAGE plpgsql;

-- credit_balance: top-up (purchase, referral bonus)
CREATE OR REPLACE FUNCTION credit_balance(p_user_id BIGINT, p_amount INTEGER)
RETURNS INTEGER AS $$
DECLARE
    new_balance INTEGER;
BEGIN
    UPDATE users SET balance = balance + p_amount
    WHERE id = p_user_id
    RETURNING balance INTO new_balance;
    RETURN new_balance;
END;
$$ LANGUAGE plpgsql;

-- ============================================================================
-- Storage: Create bucket for content images
-- Run in Supabase Dashboard > Storage > Create Bucket:
--   Name: content-images
--   Public: true (for signed URL access)
--   File size limit: 10MB
--   Allowed MIME types: image/webp, image/png, image/jpeg
-- ============================================================================

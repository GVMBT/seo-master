-- Replace category-level platform_content_overrides with project-level project_platform_settings.
-- platform_content_overrides was never used by any service; dead code cleanup.

DROP TABLE IF EXISTS platform_content_overrides;

CREATE TABLE project_platform_settings (
    id              SERIAL PRIMARY KEY,
    project_id      INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    platform_type   VARCHAR(20) NOT NULL,
    text_settings   JSONB NOT NULL DEFAULT '{}',
    image_settings  JSONB NOT NULL DEFAULT '{}',
    UNIQUE(project_id, platform_type)
);

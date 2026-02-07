-- Миграция 004: Добавление поля connected_platforms в таблицу bots
-- Дата: 2026-01-24
-- Описание: Хранит список подключенных к боту площадок (сайты, соцсети)

DO $$ 
BEGIN
    -- Добавляем поле connected_platforms если его нет
    IF NOT EXISTS (
        SELECT 1 
        FROM information_schema.columns 
        WHERE table_name = 'bots' 
        AND column_name = 'connected_platforms'
    ) THEN
        ALTER TABLE bots ADD COLUMN connected_platforms JSONB DEFAULT '{}';
        
        COMMENT ON COLUMN bots.connected_platforms IS 
            'Подключенные к боту площадки: {websites: [], pinterests: [], telegrams: []}';
        
        RAISE NOTICE 'Поле bots.connected_platforms добавлено';
    ELSE
        RAISE NOTICE 'Поле bots.connected_platforms уже существует';
    END IF;
END $$;

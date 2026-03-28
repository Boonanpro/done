-- iconのみの変更ではupdated_atを更新しないようにトリガー関数を修正
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    -- icon以外のカラムが変更された場合のみupdated_atを更新
    -- (icon変更だけではソート順を変えたくない)
    IF TG_TABLE_NAME = 'projects' THEN
        IF (OLD.title IS NOT DISTINCT FROM NEW.title
            AND OLD.description IS NOT DISTINCT FROM NEW.description
            AND OLD.status IS NOT DISTINCT FROM NEW.status
            AND OLD.summary IS NOT DISTINCT FROM NEW.summary
            AND OLD.metadata IS NOT DISTINCT FROM NEW.metadata
            AND OLD.room_id IS NOT DISTINCT FROM NEW.room_id
            AND OLD.icon IS DISTINCT FROM NEW.icon) THEN
            NEW.updated_at = OLD.updated_at;
            RETURN NEW;
        END IF;
    END IF;
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

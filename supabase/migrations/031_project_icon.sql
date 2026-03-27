-- プロジェクトにアイコン（絵文字）カラムを追加
ALTER TABLE projects ADD COLUMN IF NOT EXISTS icon TEXT;

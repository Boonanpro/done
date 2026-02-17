-- execution_events: プロジェクト実行の内部イベントを記録
-- tool_use, reasoning, phase, error を分類して格納する

CREATE TABLE execution_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
  room_id UUID NOT NULL,
  event_type TEXT NOT NULL,   -- 'tool_use', 'reasoning', 'phase', 'error'
  tool_name TEXT,             -- 'Read', 'Bash', 'mcp__dan-tools__browser_open'
  tool_label TEXT,            -- 'ファイル読み取り: main.py'
  content TEXT,               -- 思考テキスト or ツール入力の要約
  metadata JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_exec_events_project ON execution_events(project_id, created_at);

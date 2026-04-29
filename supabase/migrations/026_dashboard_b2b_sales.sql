-- AI B2B Sales Dashboard Schema
-- Business slug: ai-b2b-sales
-- Prefix: b2b_

-- updated_at trigger function (shared, create if not exists)
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 1. dashboard_businesses (hub table)
CREATE TABLE IF NOT EXISTS dashboard_businesses (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  name TEXT NOT NULL,
  slug TEXT NOT NULL UNIQUE,
  description TEXT,
  icon TEXT DEFAULT 'building-2',
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'planning', 'archived')),
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);

CREATE TRIGGER trg_dashboard_businesses_updated_at
  BEFORE UPDATE ON dashboard_businesses
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

INSERT INTO dashboard_businesses (name, slug, description, icon, status)
VALUES ('AI B2B自動営業', 'ai-b2b-sales', 'AIで地方企業にHP制作やDXを自動提案・営業するB2Bビジネス', 'building-2', 'active')
ON CONFLICT (slug) DO NOTHING;

-- 2. b2b_areas
CREATE TABLE b2b_areas (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  prefecture TEXT NOT NULL,
  city TEXT NOT NULL,
  priority INTEGER DEFAULT 0,
  target_industries TEXT[] DEFAULT '{}',
  is_active BOOLEAN DEFAULT true,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  UNIQUE (prefecture, city)
);
CREATE TRIGGER trg_b2b_areas_updated_at BEFORE UPDATE ON b2b_areas FOR EACH ROW EXECUTE FUNCTION update_updated_at();
INSERT INTO b2b_areas (prefecture, city, priority, is_active) VALUES ('鳥取県', '米子市', 1, true);

-- 3. b2b_companies
CREATE TABLE b2b_companies (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  area_id UUID REFERENCES b2b_areas(id) ON DELETE SET NULL,
  name TEXT NOT NULL,
  industry TEXT,
  sub_industry TEXT,
  address TEXT,
  phone TEXT,
  email TEXT,
  website_url TEXT,
  has_website BOOLEAN,
  website_quality_score INTEGER CHECK (website_quality_score BETWEEN 0 AND 100),
  status TEXT NOT NULL DEFAULT 'new' CHECK (status IN (
    'new', 'researched', 'hypothesis_ready', 'prototype_ready',
    'email_sent', 'replied', 'in_negotiation', 'contracted', 'excluded'
  )),
  overall_score INTEGER DEFAULT 0 CHECK (overall_score BETWEEN 0 AND 100),
  source TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX idx_b2b_companies_area ON b2b_companies(area_id);
CREATE INDEX idx_b2b_companies_status ON b2b_companies(status);
CREATE INDEX idx_b2b_companies_score ON b2b_companies(overall_score DESC);
CREATE TRIGGER trg_b2b_companies_updated_at BEFORE UPDATE ON b2b_companies FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 4. b2b_company_research
CREATE TABLE b2b_company_research (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  company_id UUID NOT NULL REFERENCES b2b_companies(id) ON DELETE CASCADE,
  research_type TEXT NOT NULL CHECK (research_type IN ('website_analysis', 'seo_check', 'sns_check', 'competitor_analysis', 'manual')),
  result_summary TEXT,
  result_data JSONB DEFAULT '{}',
  ai_model TEXT,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX idx_b2b_company_research_company ON b2b_company_research(company_id);
CREATE TRIGGER trg_b2b_company_research_updated_at BEFORE UPDATE ON b2b_company_research FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 5. b2b_hypotheses
CREATE TABLE b2b_hypotheses (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  company_id UUID NOT NULL REFERENCES b2b_companies(id) ON DELETE CASCADE,
  category TEXT NOT NULL CHECK (category IN (
    'no_website', 'poor_website', 'no_seo', 'no_sns',
    'no_reservation', 'no_ec', 'poor_ux', 'outdated_design',
    'no_mobile', 'other'
  )),
  problem_description TEXT NOT NULL,
  proposed_solution TEXT NOT NULL,
  expected_impact TEXT,
  confidence_score INTEGER DEFAULT 50 CHECK (confidence_score BETWEEN 0 AND 100),
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'pending_review', 'approved', 'rejected')),
  rejection_reason TEXT,
  is_ai_generated BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX idx_b2b_hypotheses_company ON b2b_hypotheses(company_id);
CREATE INDEX idx_b2b_hypotheses_status ON b2b_hypotheses(status);
CREATE TRIGGER trg_b2b_hypotheses_updated_at BEFORE UPDATE ON b2b_hypotheses FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 6. b2b_prototypes
CREATE TABLE b2b_prototypes (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  company_id UUID NOT NULL REFERENCES b2b_companies(id) ON DELETE CASCADE,
  hypothesis_id UUID REFERENCES b2b_hypotheses(id) ON DELETE SET NULL,
  prototype_type TEXT NOT NULL CHECK (prototype_type IN (
    'homepage', 'landing_page', 'ec_site', 'reservation_system', 'redesign', 'other'
  )),
  title TEXT NOT NULL,
  description TEXT,
  preview_url TEXT,
  screenshot_urls TEXT[] DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'creating' CHECK (status IN ('creating', 'completed', 'sent', 'archived')),
  generation_params JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX idx_b2b_prototypes_company ON b2b_prototypes(company_id);
CREATE TRIGGER trg_b2b_prototypes_updated_at BEFORE UPDATE ON b2b_prototypes FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 7. b2b_email_templates
CREATE TABLE b2b_email_templates (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  name TEXT NOT NULL,
  template_type TEXT NOT NULL CHECK (template_type IN ('initial_proposal', 'follow_up', 'thank_you', 'meeting_request', 'custom')),
  subject_template TEXT NOT NULL,
  body_template TEXT NOT NULL,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE TRIGGER trg_b2b_email_templates_updated_at BEFORE UPDATE ON b2b_email_templates FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 8. b2b_emails
CREATE TABLE b2b_emails (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  company_id UUID NOT NULL REFERENCES b2b_companies(id) ON DELETE CASCADE,
  template_id UUID REFERENCES b2b_email_templates(id) ON DELETE SET NULL,
  prototype_id UUID REFERENCES b2b_prototypes(id) ON DELETE SET NULL,
  to_address TEXT NOT NULL,
  subject TEXT NOT NULL,
  body TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (
    'draft', 'scheduled', 'sent', 'opened', 'clicked', 'replied', 'bounced'
  )),
  scheduled_at TIMESTAMPTZ,
  sent_at TIMESTAMPTZ,
  opened_at TIMESTAMPTZ,
  replied_at TIMESTAMPTZ,
  external_message_id TEXT,
  is_ai_generated BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX idx_b2b_emails_company ON b2b_emails(company_id);
CREATE INDEX idx_b2b_emails_status ON b2b_emails(status);
CREATE TRIGGER trg_b2b_emails_updated_at BEFORE UPDATE ON b2b_emails FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 9. b2b_deals
CREATE TABLE b2b_deals (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  company_id UUID NOT NULL REFERENCES b2b_companies(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  contact_person TEXT,
  contact_role TEXT,
  stage TEXT NOT NULL DEFAULT 'initial_contact' CHECK (stage IN (
    'initial_contact', 'appointment_set', 'meeting_done',
    'quote_sent', 'negotiation', 'won', 'lost'
  )),
  probability TEXT DEFAULT 'D' CHECK (probability IN ('A', 'B', 'C', 'D')),
  estimated_amount INTEGER DEFAULT 0,
  proposed_services TEXT[] DEFAULT '{}',
  meeting_date TIMESTAMPTZ,
  next_action TEXT,
  next_action_date DATE,
  loss_reason TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX idx_b2b_deals_company ON b2b_deals(company_id);
CREATE INDEX idx_b2b_deals_stage ON b2b_deals(stage);
CREATE TRIGGER trg_b2b_deals_updated_at BEFORE UPDATE ON b2b_deals FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 10. b2b_deal_notes
CREATE TABLE b2b_deal_notes (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  deal_id UUID NOT NULL REFERENCES b2b_deals(id) ON DELETE CASCADE,
  note_type TEXT NOT NULL DEFAULT 'memo' CHECK (note_type IN ('memo', 'meeting_minutes', 'call_log')),
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX idx_b2b_deal_notes_deal ON b2b_deal_notes(deal_id);
CREATE TRIGGER trg_b2b_deal_notes_updated_at BEFORE UPDATE ON b2b_deal_notes FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 11. b2b_contracts
CREATE TABLE b2b_contracts (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  company_id UUID NOT NULL REFERENCES b2b_companies(id) ON DELETE CASCADE,
  deal_id UUID REFERENCES b2b_deals(id) ON DELETE SET NULL,
  plan_name TEXT NOT NULL,
  contract_type TEXT NOT NULL DEFAULT 'monthly' CHECK (contract_type IN ('monthly', 'yearly', 'one_time')),
  amount INTEGER NOT NULL,
  start_date DATE NOT NULL,
  end_date DATE,
  auto_renew BOOLEAN DEFAULT false,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'pending_renewal', 'cancelled', 'expired')),
  services TEXT[] DEFAULT '{}',
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX idx_b2b_contracts_company ON b2b_contracts(company_id);
CREATE INDEX idx_b2b_contracts_status ON b2b_contracts(status);
CREATE TRIGGER trg_b2b_contracts_updated_at BEFORE UPDATE ON b2b_contracts FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 12. b2b_pipeline_log
CREATE TABLE b2b_pipeline_log (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  company_id UUID NOT NULL REFERENCES b2b_companies(id) ON DELETE CASCADE,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('company', 'hypothesis', 'prototype', 'email', 'deal', 'contract')),
  entity_id UUID NOT NULL,
  from_status TEXT,
  to_status TEXT NOT NULL,
  changed_by TEXT DEFAULT 'system',
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE INDEX idx_b2b_pipeline_log_company ON b2b_pipeline_log(company_id);
CREATE INDEX idx_b2b_pipeline_log_entity ON b2b_pipeline_log(entity_type, entity_id);
CREATE TRIGGER trg_b2b_pipeline_log_updated_at BEFORE UPDATE ON b2b_pipeline_log FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- 13. b2b_settings
CREATE TABLE b2b_settings (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  setting_key TEXT NOT NULL UNIQUE,
  setting_value JSONB NOT NULL DEFAULT '{}',
  description TEXT,
  created_at TIMESTAMPTZ DEFAULT now() NOT NULL,
  updated_at TIMESTAMPTZ DEFAULT now() NOT NULL
);
CREATE TRIGGER trg_b2b_settings_updated_at BEFORE UPDATE ON b2b_settings FOR EACH ROW EXECUTE FUNCTION update_updated_at();

INSERT INTO b2b_settings (setting_key, setting_value, description) VALUES
  ('email_config', '{"from_name": "", "from_address": "", "signature": ""}', 'メール送信設定'),
  ('ai_config', '{"hypothesis_model": "claude-sonnet", "prototype_model": "claude-sonnet", "auto_generate": false}', 'AI生成設定'),
  ('target_config', '{"min_score": 30, "excluded_industries": [], "max_emails_per_day": 20}', 'ターゲット設定'),
  ('notification_config', '{"on_reply": true, "on_meeting_reminder": true, "reminder_hours_before": 24}', '通知設定');

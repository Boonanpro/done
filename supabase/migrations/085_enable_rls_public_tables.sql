-- 085: public スキーマで RLS が無効だった59表に RLS を有効にする
--
-- 2026-10-14 に Supabase の警告（rls_disabled_in_public / sensitive_columns_exposed）を
-- 受けて、本番DB（omcnusihkpfyvzglttop）へ Management API で適用済み。このファイルはその記録。
-- 何度流しても同じ結果になる。
--
-- 有効にする前は、公開用の鍵（anon）で credentials・users・chat_rooms などを
-- 読み書き・削除できた。ポリシーは足していないので、anon / authenticated は0件・書き込み拒否、
-- service_role（ダン本体・ポルノブロッカーのサーバー）は従来どおり通る。
--
-- 公開用の鍵で読む画面やアプリを後から足す時は、その表にだけポリシーを足す（RLS を無効に戻さない）。
-- 新しい表を public に作る時は、同じ文で RLS を有効にする。
--
-- アクセス解析用の別プロジェクト dan-analytics（zwsgeaedbcgljwzholft、Umami の18表）にも
-- 同じ日に同じ対応をした。Umami のスキーマはこのリポジトリの管理外なので、ここには書かない。

ALTER TABLE IF EXISTS public."achievement_cursors" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."artifact_publication" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_areas" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_companies" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_company_research" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_contracts" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_deal_notes" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_deals" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_email_templates" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_emails" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_hypotheses" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_pipeline_log" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_prototypes" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."b2b_settings" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."bookings" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."chat_ai_settings" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."chat_friendships" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."chat_invites" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."chat_room_members" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."chat_rooms" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."clients" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."credentials" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."daily_achievements" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."dashboard_businesses" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."document_categories" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."document_files" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."document_relations" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."document_shares" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."documents" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."dx_clients" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."dx_media" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."dx_projects" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."event_links" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."execution_events" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."heartbeat_runs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."invoice_history" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."invoices" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."learned_rules" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."messages" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."meta_ad_accounts" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."notifications" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."pending_followups" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."phone_number_rules" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."pornblocker_cancellations" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."pornblocker_messages" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."pornblocker_subscriptions" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."salonboard_credentials" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."salonboard_post_jobs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."saved_bank_accounts" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."studio_channels" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."studio_episodes" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."studio_video_clips" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."studio_voice_tracks" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."task_logs" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."tasks" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."users" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."voice_call_messages" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."voice_calls" ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public."voice_settings" ENABLE ROW LEVEL SECURITY;

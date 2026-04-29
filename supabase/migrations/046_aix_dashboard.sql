-- aix_dashboard は 045_aix_dashboard.sql で 7 テーブル（aix_clients ほか）として実装済み。
-- create_feature が生成した単一テーブル雛形は使わないため、ここで掃除する。

DROP TRIGGER IF EXISTS aix_dashboard_updated_at ON aix_dashboard;
DROP FUNCTION IF EXISTS update_aix_dashboard_updated_at();
DROP TABLE IF EXISTS aix_dashboard;

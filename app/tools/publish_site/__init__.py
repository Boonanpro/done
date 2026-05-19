"""
Publish Site tool package.

クライアントartifactをカスタムドメインで公開するための統合機能群。

- cloudflare_registrar: ドメイン購入 (オーナー取得フロー)
- cloudflare_dns: 購入済みドメインの DNS レコード操作
- vercel_domains: Vercel プロジェクトへのドメイン紐付け
- seo_generator: sitemap / robots / JSON-LD / metadata 自動生成
- search_console: Google Search Console 所有権確認 + sitemap 申請
- orchestrator: 公開フロー全体の司令塔。
    - publish_with_custom_domain: オーナー取得フロー (購入〜公開〜検索登録)
    - create_domain_setup / get_domain_setup_state / verify_domain_setup:
      クライアント所有フロー (案内URL発行〜クライアント自身で取得・設定・公開)
"""

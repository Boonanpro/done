# 公開基盤の新しい約束

## 一サイト、一公開先

成果物はチャットで作られます。公開する時は、その成果物だけの release を作り、その release だけを専用の Vercel project に配備します。
他の成果物を再ビルドしたり、別サイトのURLを書き換えたりしません。

## ドメインは任意

すべての公開済み成果物には `shared_url` があります。これは独自ドメインを買わなくても使える公開URLです。
独自ドメインを希望した場合だけ、同じ release に `custom_domain` を接続します。接続後の正規URLは `production_url` になります。

```
成果物 → release → shared_url
                     └→ (任意) custom_domain → production_url
```

## Git と Vercel の役割

Git はソースの履歴、Vercel deployment は配信する完成品です。`artifact_publication` は「この成果物の何番目のreleaseが、どの完成品か」を記録します。
GitHubが停止しても、記録済みの完成品のURLや本番ドメインが他サイトの更新で変わることはありません。

## 状態の言葉

- `draft`: ダン内だけの成果物
- `shared`: 独自ドメインなしでも外部共有できる
- `deploying`: releaseをVercelへ配備中
- `live`: 配備済み
- `domain_status=live`: 任意の独自ドメインも接続済み

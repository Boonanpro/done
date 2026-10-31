"""Describe observable shell operations without exposing commands or full paths."""
import re
import shlex


def file_subject(value):
    name = re.split(r'[/\\]', str(value or '').strip('"\''))[-1]
    if not name or re.search(r'[^\w.() -]', name):
        return ''
    if name.startswith('.') or re.search(r'(?:secret|credential|token|auth)', name, re.I):
        return '設定ファイル'
    if not re.search(r'\.(?:py|tsx?|jsx?|json|toml|ini|ya?ml|md|txt|css|html|sql|csv|log|sh|ps1)$', name, re.I):
        return ''
    return '「' + (name if len(name) <= 28 else name[:25] + '…') + '」'


def command_activity(command):
    if not isinstance(command,str) or not command.strip():
        return ''
    text=command
    for _ in range(3):
        try:tokens=shlex.split(text)
        except ValueError:return ''
        if not tokens:return ''
        exe=tokens[0].replace('\\','/').rsplit('/',1)[-1].lower().removesuffix('.exe')
        if exe in ('bash','zsh','sh','powershell','pwsh','cmd'):
            index=next((i for i,t in enumerate(tokens[1:],1) if t.lower() in ('-c','-lc','-command','/c')),None)
            if index is not None and index+1<len(tokens):
                text=tokens[index+1];continue
        break
    # Report the first operation in a compound command. A later word inside a
    # search pattern or script is not evidence that that operation is executing.
    boundary=next((i for i,t in enumerate(tokens) if t in ('&&','||',';','|')),len(tokens))
    args=tokens[1:boundary]
    subject=next((s for t in reversed(args) if (s:=file_subject(t))), '')
    if exe in ('cat','head','tail','sed','get-content'):
        return f'{subject or "ファイル"}の内容を確認しています'
    if exe in ('rg','grep','findstr','select-string'):
        return f'{subject}の該当箇所を探しています' if subject else 'コードや資料から該当箇所を探しています'
    if exe in ('ls','find','get-childitem'):
        return '対象のファイルを探しています'
    if exe == 'git':
        action=next((a for a in args if a in ('diff','status','log','show','fetch','pull','push')), '')
        return {'diff':'変更した内容を確認しています','status':'変更したファイルを確認しています',
                'log':'変更の履歴を確認しています','show':'変更の履歴を確認しています',
                'fetch':'最新の変更を取得しています','pull':'最新の変更を取り込んでいます',
                'push':'変更をリポジトリへ反映しています'}.get(action,'')
    if exe in ('pytest','vitest','jest') or (exe.startswith('python') and args[:2]==['-m','pytest']):
        return f'{subject or "変更した機能"}のテストを実行しています'
    if exe in ('npm','pnpm','yarn','bun','npx'):
        action=args[1] if args[:1] in (['run'],['exec']) and len(args)>1 else (args[0] if args else '')
        if action in ('test','vitest','jest'):return '変更した機能のテストを実行しています'
        if action in ('build','typecheck','tsc','lint'):
            return {'build':'画面をビルドしています','typecheck':'コードの型を確認しています','tsc':'コードの型を確認しています','lint':'コードの書き方を確認しています'}[action]
    if exe in ('curl','wget','invoke-webrequest','invoke-restmethod'):
        return '接続先の応答を確認しています'
    return ''

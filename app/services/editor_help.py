"""On-demand facts about editor behavior; shared by conversation and production."""

EXECUTION_CONTRACT = '''制作の正はダンのエディターのタイムラインです。既存素材の配置・カット・文字・音量などは公開されたtimelineツールで編集できます。操作ごとに構造を検証して画面へ反映し、apply_editsは一まとまりの変更を反映します。手編集を受け取ったら最新の状態を読んで続けます。
スキルは必要な制作技術や操作仕様を調べる資料です。素材生成・録画・モーショングラフィックなど、今回必要な能力に応じて選びます。外部の制作方式を使う場合も、エディターで組む作品との接続と編集元を保ちます。既存作品の小さな変更からヒアリングや作品全体の設計をやり直す必要はありません。
検証は変更の影響に合わせて選びます。配置・文字・見た目は構造と対象フレーム、カット・音・動きは変更区間の再生で確認できます。全編を新しく制作した場合や広い範囲に影響する変更は通しで確認します。書き出しは依頼された成果物か、他の方法で確認できない問題の検証に使います。素材配置だけの依頼を自動で動画納品へ広げません。未確認の品質は確認済みとして扱わず、report_resultで変更内容と確認結果・残る問題を記録します。'''
def read(topic='workflow'):
    if topic == 'playback':
        return {'ok': True, 'topic': topic, 'facts': {
            'preview': 'render_frameは合成後の静止画、watch_renderは指定区間の合成後の映像と音声を確認する。',
            'audio': 'probe_audioはネイティブ音声経路の短い信号検査。各対象クリップの開始地点から最大0.5秒を測る。台詞・音質・同期や全区間の検品にはならない。',
            'window': 'editor_stateのopen=falseは利用者のネイティブ画面を観測できない状態。ブラウザの空白ページはネイティブエディターではない。フレームや音声の検証と、利用者画面での操作確認を区別する。'}}
    if topic == 'saving':
        return {'ok': True, 'topic': topic, 'facts': {'contract': EXECUTION_CONTRACT}}
    if topic=='production_methods':
        from app.services.editor_methods import read as methods
        return methods()
    topics={
        'motion':{'media':'画像・動画の移動と拡大はset_clip_propsのtransform_keys [{t,x,y,w,h}]。tはクリップ先頭からの秒、x/y/w/hはキャンバスに対する正規化値。例: [{t:0,x:0.1,y:0.1,w:0.8,h:0.8},{t:2,x:0,y:0,w:1,h:1}]。静的なpositionは{x,y,width,height}でキー名が異なる。',
            'captions':'文字もtransform_keysで連続移動・拡大できる。本文とstyleはset_clipで編集し、動きはそのまま保持できる。文字のキーはデザイン全体の平面に作用し、標準はx=0,y=0,w=1,h=1。x/yは右/下への移動量、w/hは拡大倍率。style.yは下端からの位置で、キーのyとは向きが異なる。',
            'authoring':'animate_clip(clip_id,poses:[{t,x,y,w,h},...],easing:cubic_out)で少数の通過点から滑らかな動きを作れる。文字・素材・領域に対応。文字を何十個もの短いクリップに分ける必要はない。linearとcubic_in_outも選べる。既存の動きを変更する時はtimeline_stateで先に読む。',
            'layers':'add_caption/add_region/add_clipのlaneで上下を指定できる。lane="front"で実行時点の最前面へ新しい映像レーン。背景→図形→文字の順で重ねる場合、別の空きレーンに自動配置すると順序が変わることがあるので明示する。',
            'proposal':'提案compositionは文字・図形の動きを再生できるが、nativeタイムラインの字幕機能とは別。compositionを作っただけではタイムラインに置かれない。'},
        'workflow':{'timeline':'下書きも仕上げも同じタイムライン。担当の編集は操作ごとに構造を検証して順次反映する。途中でも再生・手編集でき、Undoで戻せる。手編集後は最新の内容を読み直して続ける。保存と映像・音声の品質検品は別。',
            'progress':'クリップ上を流れるアニメーションは、そのクリップが制作対象である印。動画内の演出や、編集中の内容のプレビューではない。',
            'work':'担当は会話サーバーとは別プロセスで動く。タイムラインは操作ごとに更新し、完了時は音声接続中なら結果を通知する。途中の下書き・生成素材も保存される。'},
        'proposals':{'media':'動画の区間・画像・音声・文字・compositionをpresent_referencesで表示できる。初めは1案を大きく、番号付きタブで切替、並べて比較、拡大が可能。',
            'composition':'文字、矩形、既存画像・動画を重ね、opacity/x/y/scaleのキーフレームで動かす。無料。文字サイズと位置はキャンバスのピクセル。人物の対比も図形・素材の組合せで試せる。',
            'selection':'choose_referenceで選んだ案と好みを保存。試作は判断が必要な時に使い、毎回必須にはしない。'},
        'operations':{'batch':'制作担当のapply_editsで複数の編集操作を一括適用できる。各操作の引数は通常ツールと同じ。作成結果のID等は {"$result":0,"path":"clip_id"} で先行操作を参照でき、作成→そのクリップへの編集も1回で実行できる。途中で失敗したら下書き全体を呼び出し前へ戻す。画像・音声の生成は別で並行実行する。',
            'coordinates':'タイムラインの領域クリップは正規化座標0〜1。字幕のfontSizeは相対倍率（標準1、少し大きく1.25）。proposal compositionの文字サイズは別でピクセル。',
            'assets':'素材はタイムラインに置いてなくても利用可能。list_assetsで探し、内容が不明なら確認する。元ファイルの区間を参照して配置できる。',
            'parallel':'生成と調査は並行可能。GPU処理はGPUごとに順番待ち。完成した素材の登録やタイムラインの変更は競合しない順番で保存される。'},
    }
    return {'ok':True,'topic':topic,'facts':topics.get(topic,topics),'available_topics':list(topics)}

"""Jev-only creative discovery: current beliefs, next distinction, evidenced pairs.

Beliefs are recomputed from original conversation, never multiplied into an
irreversible posterior. A user's change of mind can therefore replace a prior
direction without deleting unaffected intentions. Axes are comparison aids,
not a whitelist of things Dan can make.
"""
from app.services import editor_jev

AXES = {
 'form': ('伝え方', {'observation':'日常を観察する','story':'物語で見せる','demo':'使う場面や実演で見せる','explanation':'説明で伝える','abstract':'抽象的な映像や文字で伝える'}),
 'medium': ('映像の主な見た目（制作技術ではない）', {'live':'実写風・写実的','animation_2d':'2Dアニメ','animation_3d':'3Dアニメ','graphics':'モーショングラフィックス','mixed':'実写とイラスト等の異なる見た目を目立たせて組み合わせる'}),
 'tone': ('感じてほしい空気', {'calm':'静かで落ち着く','playful':'楽しくユーモラス','tense':'緊張感がある','energetic':'勢いがある','intimate':'親密で感情に寄り添う'}),
 'setting': ('作品内の舞台・生活環境（映像品質ではない）', {'ordinary':'普通の生活環境・自宅・質素な仕事場','polished':'裕福で豪華な生活環境','fantasy':'架空の非日常世界'}),
 'focus': ('何を主に見せるか', {'person':'人の顔や表情','action':'手元や行動','environment':'場所や空間','text':'文字や図'}),
 'pace': ('時間の使い方', {'lingering':'間をとって見せる','brisk':'テンポよく切り替える','varied':'緩急をつける'}),
 'voice': ('言葉の使い方', {'speech':'語りや会話で伝える','minimal':'言葉を抑えて映像で伝える'}),
}

def questions():
    result={
      'discovery_level':{'type':'choice','instructions':
        'What is the user currently trying to decide? Start with whole-work direction, across every video genre. '
        'Do not jump to rooms, typography or camera details before an overall direction is shared, unless the user asks for that detail. '
        'A named reference is a clue, not automatic approval of every feature.',
        'criteria':{'overall':'作品全体の方向性を見比べる','detail':'共有済みの方向を基に細部を比較する'}},
      'discovery_change':{'type':'choice','instructions':
        'Read the CURRENT user statement in the whole conversation. Is this a new direction, a refinement, or no preference update? '
        'A complete pivot may replace style, purpose or both. Preserve only unaffected user intentions. '
        'Hypotheticals, quoted ideas and assistant suggestions are not user decisions. '
        'Compare with the immediately preceding active direction, not the beginning of the conversation. '
        'Returning from 3D to a previously preferred live-action direction is pivot. Asking whether 3D is possible without choosing it is none.',
        'criteria':{'pivot':'ユーザーが以前と異なる方向へ変更','refine':'好みが具体化、部分的な訂正や選択','none':'好みの更新なし'}},
      'discovery_next':{'type':'choice','instructions':
        'Which ONE unresolved distinction would most help this user judge what they want next? '
        'Use their purpose, current choices, rejections and corrections. Do not ask about an already settled property just to fill a questionnaire. '
        'This question only selects the useful difference for a reference comparison, not whether to produce something. '
        'The user need not settle every axis. Naming a style is not evidence that the look has been understood. '
        'For a capability question with no preference update choose none; do not turn every utterance into narrowing. '
        'Choose other when these axes do not express the real uncertainty. A new direction overrides conflicting old choices, not all history.',
        'criteria':{**{k:v[0] for k,v in AXES.items()},'other':'別の不明点を自然に確認','none':'今は絞り込みの相談ではない'}}}
    for axis,(label,values) in AXES.items():
        result['discovery_value_'+axis]={'type':'choice','instructions':
          'What does the USER currently prefer about '+label+'? Use explicit user words, including corrections, not assistant proposals. '
          'A current pivot supersedes conflicting earlier choices. Keep unaffected preferences. '
          'Open if not established or multiple alternatives remain. Endorsing one reference does not endorse every property of it. '
          'Judge the intended finished video, not how the user wants to conduct this consultation. '
          'Wanting to look at references does not mean minimal voiceover. Wanting to encourage product use does not establish demo form. '
          'Do not infer abstract form from 3D space, or a pace from a mood: these are independent attributes.',
          'criteria':{**values,'open':'まだ決まっていない・複数が残る','irrelevant':'今回の相談には関係しない'}}
        result['discovery_avoid_'+axis]={'type':'choice','instructions':
          'Which treatment of '+label+' has the user most clearly rejected for their CURRENT direction? '
          'A later change of mind can revoke a rejection. Do not infer rejection merely because another trait was liked. '
          'For example choosing live action does NOT reject motion graphics; choose none unless the user explicitly ruled it out.',
          'criteria':{**values,'none':'現在有効な明確な拒否はない'}}
    for key,question in result.items():
        if key.startswith('discovery_value_') or key.startswith('discovery_avoid_'):
            question['instructions']+=' Read prior USER turns too: an earlier explicit preference remains established until the user changes it. A reference title supplies only the qualities the user borrowed. It does not replace their explicit setting, subject or story. Rejecting interviews does not reject character dialogue or narration in general.'
    return result

def _choice(answer, minimum=.65):
    value=answer.get('choice')
    return value if answer.get('probabilities',{}).get(value,0)>=minimum else None

def plan(answers):
    # Several next questions may be useful. Their ranking is not confidence in
    # the user's preference: uncertainty here must not erase known preferences.
    recommendation=answers.get('discovery_next',{})
    next_axis=recommendation.get('choice')
    if next_axis not in {*AXES,'sample','other','none'}:return None
    beliefs={}
    for axis,(label,values) in AXES.items():
        preferred=_choice(answers.get('discovery_value_'+axis,{}))
        avoided=_choice(answers.get('discovery_avoid_'+axis,{}))
        if preferred==avoided:avoided=None
        beliefs[axis]={'preferred':preferred if preferred in values else None,'avoid':avoided if avoided in values else None,
                      'probabilities':answers.get('discovery_value_'+axis,{}).get('probabilities',{})}
    if next_axis in beliefs and beliefs[next_axis]['preferred'] is not None:
        unresolved={k:p for k,p in recommendation.get('probabilities',{}).items()
                    if k in AXES and beliefs[k]['preferred'] is None}
        next_axis=max(unresolved,key=unresolved.get) if unresolved else 'other'
    level=_choice(answers.get('discovery_level',{})) or 'overall'
    if level=='overall' and next_axis in ('focus','setting','voice'):
        eligible={k:recommendation.get('probabilities',{}).get(k,0) for k in ('medium','tone','form','pace') if beliefs[k]['preferred'] is None}
        next_axis=max(eligible,key=eligible.get) if eligible else 'other'
    return {'next_axis':next_axis,'axis_label':AXES[next_axis][0] if next_axis in AXES else next_axis,
            'change':_choice(answers.get('discovery_change',{})) or 'uncertain','beliefs':beliefs,
            'level':level,
            'basis':'current_user_conversation','progress_claim':False,
            'next_probabilities':recommendation.get('probabilities',{})}

async def select_pair(user, dialogue, rows, discovery):
    """Compare useful evidence, not simply the two highest similar hits."""
    if not rows:return {'ids':[],'sides':[],'reason':'insufficient_comparison_evidence','available':True}
    allowed=('form','medium','tone','pace') if discovery.get('level','overall')=='overall' else tuple(AXES)
    axes=[k for k in allowed if not discovery['beliefs'][k]['preferred']]
    if not axes:return {'ids':[],'sides':[],'reason':'no_comparison_axis','available':True}
    questions={}
    for row in rows:
        ident=row['id']
        for axis in axes:
            questions['side_'+axis+'_'+ident]={'type':'choice','instructions':
              'Which side of '+AXES[axis][0]+' does candidate '+ident+' actually demonstrate according to supplied evidence? '
              'Title/description are not visual inspection. Do not imagine camera, sound, facial expression or editing that is not established. Unknown if evidence is insufficient.',
              'criteria':{**AXES[axis][1],'unknown':'この違いを示す根拠が足りない'}}
        questions['fit_'+ident]={'type':'score','instructions':
          'How useful is '+ident+' for judging the CURRENT unresolved distinction while preserving current user preferences and rejections? '
          'For overall discovery, judge transferable whole-work storytelling and visual treatment, not an exact reproduction of the user\'s story. '
          'Different subjects, products or locations are acceptable reference differences; do not change the user\'s own setting to match them. '
          'The requested format still matters: a cinematic narrative is not a creator challenge or how-to with a similar subject. '
          'For detail discovery, judge the specific detail the user is discussing. '
          'Use title and description for what they establish; uninspected camera or sound must remain unknown, not invented. '
          'A pivot supersedes incompatible earlier preferences. '
          'Judge the existing reference, not an imagined adaptation.',
          'criteria':['Contradicts current intention','Loose or unsupported match','Useful comparison evidence','Strong comparison evidence']}
    result=await editor_jev.judge(user,{'conversation':dialogue,'comparison_axes':axes,'discovery_level':discovery.get('level','overall'),
        'settled_preferences':{k:v['preferred'] for k,v in discovery['beliefs'].items() if v['preferred']},
        'candidates':{r['id']:r.get('search_text',r.get('description','')) for r in rows}},questions,timeout=3)
    answers=result.get('answers',{});pairs=[]
    for axis in axes:
        sides={};values=AXES[axis][1]
        for row in rows:
            ident=row['id'];side=_choice(answers.get('side_'+axis+'_'+ident,{}),.7)
            fit=answers.get('fit_'+ident,{})
            if side in values and sum(fit.get('probabilities',{}).get(str(i),0) for i in (2,3))>=.65:
                if side not in sides or fit.get('score',0)>sides[side][1]:sides[side]=(ident,fit.get('score',0))
        ordered=sorted(sides,key=lambda k:-sides[k][1])[:2]
        if len(ordered)==2:pairs.append((discovery.get('next_probabilities',{}).get(axis,0),axis,sides,ordered))
    ids=[];evidence=[]
    if pairs:
        _,axis,sides,ordered=max(pairs,key=lambda p:p[0])
        discovery['next_axis']=axis;discovery['axis_label']=AXES[axis][0]
        ids=[sides[k][0] for k in ordered]
        evidence=[{'id':sides[k][0],'value':k,'label':AXES[axis][1][k]} for k in ordered]
    supported=[r['id'] for r in rows if sum(answers.get('fit_'+r['id'],{}).get('probabilities',{}).get(str(i),0) for i in (2,3))>=.65]
    supported.sort(key=lambda ident:-answers.get('fit_'+ident,{}).get('score',0))
    return {'ids':ids,'sides':evidence,'supported_ids':supported,
            'reason':'evidenced_contrast' if ids else 'insufficient_comparison_evidence',
            'available':result.get('available',False),'elapsed_ms':result.get('elapsed_ms'),'answers':answers}

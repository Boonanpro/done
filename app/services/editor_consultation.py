"""Small evidence-backed consultation state, shared by voice and execution."""
FIELDS={'brief':'what the user wants to make', 'purpose':'why, for whom or where it will be used',
        'constraints':'duration, supplied assets or other production constraints',
        'direction':'the overall creative direction actually endorsed by the user'}
EVIDENCE={
 'brief':'A format or story premise counts here. It does NOT establish purpose or visual taste.',
 'purpose':'Require an actual reason, intended audience or publication destination. Saying film, describing a plot, or requesting examples is NOT purpose.',
 'constraints':'Require constraints on the work itself: duration, budget, assets. Three reference videos is a consultation request, NOT three videos to produce.',
 'direction':'Require explicitly preferred aesthetic, tone or a reference the user endorses. Film and a plot summary are NOT aesthetic agreement. A closest reference is a preference, not approval of every feature.'}

def questions(dialogue,memo):
    turns={str(i):r['text'] for i,r in enumerate(dialogue) if r.get('role')=='user'}
    result={}
    result['memo_pending']={'type':'choice','instructions':
        'Does the user explicitly cancel or replace the pending reference request in consultation_memo? '
        'Small talk, a reminder, or an acknowledgement does not cancel it.',
        'criteria':{'keep':'Keep outstanding request','clear':'Explicitly cancelled or superseded'}}
    for field,meaning in FIELDS.items():
        result['memo_'+field]={'type':'choice','instructions':
            'Select the USER statement establishing or updating '+meaning+'. '
            'Preserve previous evidence with keep if no update. clear only if revoked. '
            'A question, hypothetical, assistant proposal or feedback about consultation behavior is not a creative decision. '
            'For direction, require actual endorsement, not merely naming possible references. '
            'Use original words; the stored quote is evidence, not a summary.',
            'criteria':{**{k:field+' evidence: '+v for k,v in turns.items()},'keep':'Keep valid existing evidence','clear':'User revoked this field','unknown':'No user evidence establishing this field'}}
        result['memo_'+field]['instructions']+=' '+EVIDENCE[field]+' Choose unknown if no evidence exists. Do not choose a quote merely because it is the closest available.'
    result['consultation_next']={'type':'choice','instructions':
        'Choose Dan\'s useful next response from the latest USER turn, conversation and consultation_memo. '
        'Direct questions, requests for verbal ideas, and small talk: conversation. Explicit playback or execution requests: the corresponding action. '
        'Otherwise advance the creative consultation proactively: if the work itself is unspecified, ask; '
        'if the subject or purpose is concrete but overall visual direction is unresolved, compare actual references without waiting to be asked. '
        'If the user has endorsed a direction but essential duration, purpose or supplied materials remain unknown, ask one useful question. '
        'If direction and important constraints are established, propose the next concrete artifact; a final constraint answer calls for a proposal, not mere acknowledgement. '
        'A change of direction can reopen comparison. User feedback is not small talk. Never demand all possible details. '
        'Choosing references or proposing next steps does not authorize production. Preserve the latest explicit request over proactive suggestions.',
        'criteria':{
          'ask':'Ask what work they want when no concrete subject/purpose is known; or ask an essential production constraint AFTER a direction is endorsed',
          'propose':'Direction endorsed and essential conditions known: proactively propose the next artifact without starting production',
          'conversation':'Answer an explicit question or verbal brainstorm, or respond to unrelated small talk',
          'compare':'Show actual reference videos to discover or refine the look of a concrete intended work, proactively or on request',
          'select':'提示済みの参考の好み・採用を記録する',
          'reveal':'指定された既存の提示物をもう一度表示する',
          'play':'提示済みの動画を再生する',
          'pause':'提示済みの動画を一時停止する',
          'listen':'相槌や返事不要の発言を聞く',
          'execute':'新しい作品・素材を作成／編集する、参考以外の調査をする、実行中の仕事を確認／変更する'}}
    return result

def update(previous,dialogue,answers):
    memo={'version':2,'facts':dict((previous or {}).get('facts',{})) if (previous or {}).get('version')==2 else {},
          'pending_request':(previous or {}).get('pending_request')}
    pending_answer=answers.get('memo_pending',{})
    if pending_answer.get('probabilities',{}).get('clear',0)>=.8:memo['pending_request']=None
    for field in FIELDS:
        answer=answers.get('memo_'+field,{})
        selected=answer.get('choice')
        if answer.get('probabilities',{}).get(selected,0)<.65:continue
        if selected=='clear':memo['facts'].pop(field,None)
        elif str(selected).isdigit():
            i=int(selected)
            if i<len(dialogue) and dialogue[i].get('role')=='user':
                quote=dialogue[i]['text']
                memo['facts'][field]=[quote]
    choice=answers.get('consultation_next',{}).get('choice')
    # Available creative facts are context, not a command to search or advance.
    # A full brief must never replace a current question with another action.
    memo['next']=choice or 'conversation'
    if choice=='compare':
        memo['pending_request']={'kind':'reference','request':next((r['text'] for r in reversed(dialogue) if r.get('role')=='user'),''),'status':'requested_not_displayed'}
    memo['stage']='understand' if not memo['facts'].get('brief') else 'direction'
    if choice=='propose':memo['stage']='concretize'
    memo['guidance']={'ask':'Ask only the missing information that changes the next proposal.',
      'propose':'Propose the most useful next artifact and why; ask for agreement, do not automatically start production.',
      'conversation':'Respond naturally. Preserve the ongoing creative intention.',
      'compare':'Present actual whole-work references before describing their comparison.',
      'select':'Retain the liked reference. Clarify its overall tone with actual references if needed; do not force a choice between protagonist and technology, faces and hands, or other compatible parts. If sufficiently clear, proactively propose the next artifact.'}.get(choice,'Follow the current explicit request.')
    return memo

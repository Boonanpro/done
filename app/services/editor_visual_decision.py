"""Retrieve visual candidates and verify their fit to the current conversation.

This module does not execute edits or disguise missing library coverage as success.
"""
import time
from app.services import editor_jev, editor_reference_library as library


def fit_question(ident):
    return {'type':'score','instructions':
        'Rate this actual candidate for the CURRENT request: '+ident+'. Retain relevant user preferences, not assistant suggestions. '
        'Identify which part is being discussed now. A change from captions to scenes does not require the scene to demonstrate caption design. '
        'An explicit current setting, medium or treatment matters more than shared mood words; matching atmosphere does not compensate for a different requested setting. '
        'A requested comparison of two treatments needs evidence of each. Respect explicit medium, setting and rejected traits. '
        'A different cast or story is acceptable, but a rejected treatment is not. Do not imagine modifying the reference.',
        'criteria':['Contradicts current requested properties','Only loosely related or missing an explicitly requested property',
                    'Matches explicit properties and provides useful evidence','Strong visual match to the current requested treatment']}


async def decide(user, dialogue, items=(), focus=None, *, retrieval='choice', verify_candidates=True, include_url_index=False, pending_reference=None, execution_state=None, consultation_memo=None):
    started=time.perf_counter()
    # Version one could label a bare format as approved direction. Reconstruct
    # its facts from original dialogue rather than trusting polluted state.
    if consultation_memo and consultation_memo.get('version')!=2:consultation_memo=None
    rows=[r for r in library.catalog() if library.selectable(r)]
    # Keep catalog evidence in the candidate question, not duplicated in state.
    # The older scoring layout remains available for measured comparisons.
    indexed={r['id']:r for r in rows}
    if include_url_index:
        from app.services.reference_url_index import presentation_rows
        indexed.update({r['id']:r for r in presentation_rows()})
    displayed=[{**i,'description':library.selection_description(indexed.get(i.get('library_id'),{}))} for i in list(items)[-24:]]
    # Repeated presentations of one library reference are one visual choice.
    # Keep history in state, but do not split target probability across copies.
    target_items={}
    for item in displayed:
        key=(item.get('reference_identity'),item.get('title')) if item.get('reference_identity') else item.get('id')
        target_items[key]=item
    # Selection needs the original words, not a repeated per-word cursor trace.
    # Full observed views remain in the execution handoff for Astra.
    conversation=[{'role':r['role'],'text':r['text']} for r in dialogue[-30:]]
    state={'conversation':conversation, 'current_user_statement':next((r['text'] for r in reversed(dialogue) if r.get('role')=='user'),''),
           'displayed':displayed, 'pointer':focus}
    state['execution_state']=execution_state or {'known':False}
    state['consultation_memo']=consultation_memo or {'version':1,'facts':{}}
    consultation_result=None
    if include_url_index:
        from app.services import editor_consultation
        # Understand the request before asking about hundreds of visual items.
        # Mixing both jobs in one questionnaire changed "show references" into
        # production and polluted unrelated memo fields in the real dialogue.
        consultation_result=await editor_jev.judge(user,state,editor_consultation.questions(conversation,consultation_memo),timeout=2.5)
        consultation_answers=consultation_result.get('answers',{})
        preview_memo=editor_consultation.update(consultation_memo,conversation,consultation_answers)
        if not consultation_result.get('available') or preview_memo['next'] in ('ask','propose','conversation','listen'):
            return {'action':'listen' if preview_memo['next']=='listen' else 'talk','handled':True,
                    'available':consultation_result.get('available',False),'needs_backend':False,'coverage_missing':False,
                    'selected_library_ids':[],'consultation_memo':preview_memo,'answers':consultation_answers,
                    'elapsed_ms':round((time.perf_counter()-started)*1000),'failure':consultation_result.get('reason')}
        state['consultation_memo']=preview_memo
    questions={
        'action':{'type':'choice','instructions':
            'Choose the useful next action for current_user_statement IN CONTEXT. New topic or corrected preference supersedes incompatible earlier preferences. '
            'For a bare request to make a video with no meaningful purpose, subject or desired experience yet, choose talk: '
            'a short conversation about what the video is for is more useful than arbitrary style examples. '
            'Use purpose and audience already stated by the USER; do not demand a platform, commercial goal or full questionnaire. '
            'A personal film or exploration without publication is a valid purpose. '
            'A concrete visual question or explicit request for examples can be compared immediately even without a full brief. '
            'An unclear visual ambition or taste feedback can warrant showing contrasting examples without waiting for "show me". '
            'When the user answers your purpose/audience question and is exploring a look, proactively compare suitable references; '
            'do not wait for a separate command to show them or ask the user to describe an aesthetic they cannot name. '
            'A factual purpose answer in an unrelated discussion is not automatically an invitation to compare. '
            'Feedback about desired appearance (more elegant, slower, a different movement) is compare: find matching examples, not edit. '
            'select means endorsing a specific displayed item, including "the first is closest" or a named displayed reference. '
            'If they ALSO ask to change a visual property, compare preserving what they liked. Mere uncertainty in the endorsement is not a request to replace the options. '
            'Describing a desired look without choosing a displayed item is compare. '
            'Endorsing a displayed look while deferring production is select, not talk: saving a chosen look does not start production. '
            'Critique about process or unwanted work, hypothetical approval, or asking what comes next is talk. '
            'After a direction is chosen, a request for advice on the next step is talk, not more examples; explicit permission to make the proposed sample is execute. '
            'Asking how to structure a story using an already discussed treatment is talk when the user asks for advice, '
            'not another search/comparison. Do not turn a request to discuss a sequence into showing a single stock shot. '
            'Do not interpret those as permission to make/edit a movie. '
            'A request to stop, cancel or change an actual production job is execute, not talk or listen. '
            'Use execution_state as observed facts; a finished conversational handoff does not mean production stopped. '
            'A status question about a job requires execute so the backend reads authoritative job records. '
            'If the user wants silence without stopping work, select listen. An acknowledgement does not revive completed or abandoned work. '
            'But acceptance of an offered comparison and reminders about an unfulfilled comparison continue that request: choose compare. '
            'Do not confuse permission to show existing references with permission to produce a video.',
            'criteria':{
                'compare':'Show or refine useful visual examples from an understood intention or a concrete visual question',
                'reveal':'Show an already displayed item again', 'play':'Play a displayed example', 'pause':'Pause a displayed example',
                'select':'Endorse a currently displayed look without requesting production',
                'talk':'Discuss feedback, a hypothetical, or next steps; answer or clarify without editing or new comparisons',
                'listen':'Listen silently: stop talking, noise, unfinished thought or acknowledgment alone',
                'execute':'Explicitly requested new production, editing, research beyond available examples, or other backend work'}},
        'destination':{'type':'choice','instructions':
            'Where would the current requested result help the user judge it? Choose from purpose, not a keyword. '
            'Choose comparison when the user is still describing an ambition and has not requested a playable work. '
            'Timing, shot order, or an explicitly requested playable storyboard belongs on the timeline; style alternatives belong in comparison.',
            'criteria':{'comparison':'Compare appearance alternatives side by side at equal size',
                        'viewer':'Inspect one existing visual at a larger size',
                        'timeline':'Evaluate an actual work over time, including cuts, duration and sound'}},
        'target':{'type':'choice','instructions':
                  'Which displayed item does the latest user refer to? Items carry their comparison group, position and is_latest. '
                  'Numbers refer to positions within the latest comparison unless an older group is explicitly indicated. '
                  'If the user names a look repeated in history, choose its most recent matching occurrence unless an older one is requested. '
                  'Repeated copies of the same library reference share the latest occurrence in the choices below. Choose that equivalent reference even when an earlier copy was mentioned. none if genuinely ambiguous.',
                  'criteria':{**{i['id']:i.get('title','')+' '+i.get('description','') for i in target_items.values() if i.get('id')},'none':'No unambiguous displayed target'}},
        'same_style':{'type':'noul','instructions':'Has the user chosen a specific look and now wants variants within it, rather than contrasting looks?'}
    }
    for r in rows if retrieval=='scores' else []:
        questions['fit_'+r['id']]={'type':'score','instructions':
            'Evaluate ONLY the candidate specified at the end of this question, not a displayed item. '
            'Rate it as the next useful visual comparison for current_user_statement in conversation. '
            'A change of topic supersedes the old topic. '
            'Use retained preferences and rejected traits. Match cinematic/design treatment, not just subject keywords. '
            'An unchosen direction benefits from distinct plausible alternatives. Do not invent an adaptation. '
            'This is evidence for choosing a look, NOT the requested finished work: a short excerpt can inform a long film. '
            'Before a look is chosen, different plausible visual treatments are useful even when the cast, location or story differs. '
            +'Candidate '+r['id']+' ('+r['title']+'): '+r['description'],
            'criteria':['Wrong medium or rejected look','Weak evidence or superficial subject match','Useful plausible comparison','Strong fit with retained preferences']}
    if retrieval=='choice':
        questions['scope']={'type':'choice','instructions':
            'What is the user trying to choose visually RIGHT NOW? A change of topic supersedes the previous one. '
            'mixed when multiple distinct parts are genuinely requested, or the overall mood is still open. '
            'This scopes reference retrieval, not what the system can produce.',
            'criteria':{'text':'Captions, typography or text design',
                        'scene':'A filmed or animated scene, people in a setting, cinematic treatment',
                        'character':'Character appearance or illustration style',
                        'data':'Charts, diagrams, maps and information structure',
                        'interface':'App, code or social interface presentation',
                        'motion':'An isolated effect, transition or motion mechanism',
                        'mixed':'Several kinds or still open'}}
        questions['count']={'type':'choice','instructions':
            'How many existing approaches help answer this CURRENT request? Respect explicit comparisons. '
            'A specific requested treatment can use one matching example. Do not pad a concrete request with loosely related looks.',
            'criteria':{'1':'One concrete requested approach','2':'Two approaches to compare','3':'Three distinct plausible approaches for an open direction'}}
        questions['candidate']={'type':'choice','instructions':
            'Choose the most useful existing visual to show next, based on the original conversation and retained preferences. '
            'Evaluate how the treatment serves the intended audience, purpose and desired feeling, not only visual keywords. '
            'The same subject may need observational intimacy, instructional clarity, advertising energy or dramatic tension. '
            'Prefer examples that distinguish plausible approaches to this intention. A simple mechanics demo is useful for '
            'a question about that mechanism, but is not evidence of finished production quality. '
            'This is a reference for choosing a look, not the completed work; cast, location and length may differ. '
            'When actual examples matching the requested visual properties exist, prefer them over approximate mood matches. '
            'Do not ignore a requested setting, camera treatment, lighting or medium merely because another example shares an emotional keyword. '
            'Before a look is chosen, plausible distinct visual treatments are useful; after feedback, reject incompatible traits. '
            'A refinement retains earlier USER preferences, including rejected media, unless the user explicitly changes them. '
            'Assistant proposals or descriptions are not user choices and cannot override those preferences. '
            'A topic change supersedes earlier incompatible preferences. Never invent an adaptation. '
            'A reference must provide useful evidence for the requested experience: do not substitute a generic effect '
            'demo for finished storytelling, or force unrelated film genres merely because both contain people. '
            'Choose none if no actual candidate is useful.',
            'criteria':{**{r['id']:r['title']+': '+library.selection_description(r) for r in rows},'none':'No useful actual visual in the library'}}
        # A high runner-up rank does not mean the user still wants a previously
        # shown treatment. Judge those exclusions in the same request, avoiding
        # a second network/model round trip on the critical display path.
        for ident in {i.get('library_id') for i in displayed} & indexed.keys():
            questions['exclude_'+ident]={'type':'noul','instructions':
                'Does this unchanged candidate retain a property the user wants to move away from in the CURRENT comparison? '
                'A critique such as too formal, too energetic or the wrong medium counts even without an explicit ban. '
                'Liking a different property of it does not remove that mismatch. Do not imagine an edited version of the candidate. '
                'Do not confuse uncertainty about which option to choose with rejection. '
                'A request to compare two approaches does not reject either of those approaches. '
                'Candidate: '+library.selection_description(indexed[ident])}
    if include_url_index:
        from app.services import editor_discovery
        questions.update(editor_discovery.questions())
        questions['reference_level']={'type':'choice','instructions':
            'Choose the kind of reference needed for the CURRENT conversation. A launch video, film, vlog, tutorial or campaign is a whole work. '
            'An isolated caption, effect or motion mechanism is a component. Do not substitute a component for a whole work.',
            'criteria':{'work':'Whole video, storytelling or overall creative direction','component':'Individual visual element or mechanism'}}
    pending_ids=[i for i in (pending_reference or {}).get('ids',[])[:3] if isinstance(i,str) and i in indexed]
    if pending_ids:
        state['pending_reference']={'request':str(pending_reference.get('text',''))[:3000],
            'candidates':{i:indexed[i].get('title','') for i in pending_ids},'displayed':False}
        questions['pending_disposition']={'type':'choice','instructions':
            'Does the conversation still call for showing pending_reference? It was retrieved but not displayed. '
            'An acknowledgement, permission to proceed, repeated request, or asking what is taking so long does not cancel it. '
            'Choose retain only if the original requested comparison remains wanted without a new creative constraint. '
            'A new visual constraint requires revise; cancellation or a different topic requires discard. '
            'Read the conversation, not just the last word. If ambiguous choose uncertain.',
            'criteria':{'retain':'Show the pending comparison; latest words continue or ask about that request',
                        'revise':'Change the comparison to reflect new preferences',
                        'discard':'Cancelled or moved to another topic','uncertain':'Cannot establish whether it is still wanted'}}
    if include_url_index:
        from app.services import editor_consultation
        # One owner for the next action; remove the old parallel action gate.
        questions.pop('action')
        questions.pop('destination')
    result=await editor_jev.judge(user,state,questions,timeout=2.5)
    answers=result.get('answers',{})
    if consultation_result:answers.update(consultation_result.get('answers',{}))
    memo=None
    if include_url_index:
        memo=editor_consultation.update(consultation_memo,conversation,answers)
        mapped={'ask':'talk','propose':'talk','conversation':'talk'}
        next_answer=answers.get('consultation_next',{})
        action_name=mapped.get(memo['next'],memo['next'])
        action_probabilities={}
        for name,value in next_answer.get('probabilities',{}).items():
            key=mapped.get(name,name)
            action_probabilities[key]=action_probabilities.get(key,0)+value
        answers['action']={'choice':action_name,'probabilities':action_probabilities}
        questions['action']={'criteria':{k:k for k in ('talk','listen','compare','select','reveal','play','pause','execute')}}
        destination_name='viewer' if action_name in ('reveal','play','pause') else 'comparison'
        questions['destination']={'criteria':{destination_name:destination_name}}
        answers['destination']={'choice':destination_name,'probabilities':{destination_name:1}}
    def choice(name, minimum):
        a=answers.get(name,{})
        return a.get('choice') if a.get('choice') in questions[name]['criteria'] and a.get('probabilities',{}).get(a.get('choice'),0)>=minimum else None
    action=choice('action',.85)
    if action is None and answers.get('action',{}).get('choice') in ('talk','listen'):
        action=choice('action',.6)
    if include_url_index:
        action=action_name if action_name in questions['action']['criteria'] else None
    destination=choice('destination',.8)
    disposition=choice('pending_disposition',.85) if pending_ids else None
    if disposition=='retain' and (not include_url_index or action=='compare'):
        return {'action':'compare','destination':'comparison','selected_library_ids':pending_ids,
                'consultation_memo':memo,
                'handled':True,'needs_backend':False,'available':True,'coverage_missing':False,
                'elapsed_ms':round((time.perf_counter()-started)*1000),'answers':answers,
                'pending_disposition':'retain','reused_pending':True}
    scores={r['id']:answers.get('fit_'+r['id'],{}) for r in rows}
    def useful(answer):
        probabilities=answer.get('probabilities',{})
        return (probabilities.get('2',0)+probabilities.get('3',0)>=.7
                if probabilities else answer.get('score',0)>=2)
    eligible=[r for r in rows if useful(scores.get(r['id'],{}))]
    selected=library.rank(scores,eligible,answers.get('same_style',{}).get('noul',0)<.8,count=3)
    if retrieval=='choice':
        probabilities=answers.get('candidate',{}).get('probabilities',{})
        candidates=sorted(rows,key=lambda r:-probabilities.get(r['id'],0))
        scope=choice('scope',.8)
        if scope and scope!='mixed' and not verify_candidates:
            candidates=[r for r in candidates if r.get('reference_role') in (None,scope)]
        count=int(choice('count',.7) or 3)
        selected=[];families=set();top=max((probabilities.get(r['id'],0) for r in rows),default=0)
        if probabilities and probabilities.get('none',1)<=.2:
            for row in candidates:
                if probabilities.get(row['id'],0)<max(.0001,top*.2):continue
                # A ranked runner-up can still retain a rejected trait. Filter
                # before filling the comparison, so a compatible alternative
                # can occupy its slot instead of padding with the rejected look.
                if answers.get('exclude_'+row['id'],{}).get('noul',0)>=.7:continue
                if answers.get('same_style',{}).get('noul',0)<.8 and row['family'] in families:continue
                selected.append(row);families.add(row['family'])
                if len(selected)==count:break
    target=editor_jev.confident(answers.get('target'),{i['id'] for i in items})
    # Uncertainty between choosing a look and refining it is not uncertainty
    # about editing permission. Both belong to reversible visual discussion.
    probabilities=answers.get('action',{}).get('probabilities',{})
    visual_actions=('compare','select','reveal')
    if not include_url_index and action is None and sum(probabilities.get(k,0) for k in visual_actions)>=.9:
        preferred=max(visual_actions,key=lambda k:probabilities.get(k,0))
        action=preferred if target else 'compare'
    local_actions=tuple(k for k in questions['action']['criteria'] if k!='execute')
    if not include_url_index and action is None and sum(probabilities.get(k,0) for k in local_actions)>=.9:
        action=max(local_actions,key=lambda k:probabilities.get(k,0))
    if action=='select' and not target:
        # Unclear which example was endorsed is a conversational ambiguity,
        # not a reason to boot a production agent or infer editing permission.
        action='talk'
    if action in ('play','pause','reveal') and not target:
        action='talk'
        if memo:memo['guidance']='The requested playback/display target is unclear. Ask which item; do not claim a search or execution started.'
    if action=='compare' and retrieval=='choice':
        selected=[r for r in selected if answers.get('exclude_'+r['id'],{}).get('noul',0)<.7]
    verification=None
    url_retrieval=None
    discovery=editor_discovery.plan(answers) if include_url_index else None
    whole_work=include_url_index and choice('reference_level',.7)=='work'
    if action=='compare' and whole_work:
        from app.services.reference_url_index import search
        # Route initial requests too when their purpose is already clear.
        # The router retains full coverage when intent is uncertain, and an
        # unsuccessful routed lookup retries the full index.
        routing='genres'
        url_retrieval=await search(user,state['current_user_statement'],dialogue=conversation,displayed=displayed,limit=3,embedded=True,discovery=discovery,routing=routing,verify_matches=True)
        selected=[indexed[r['id']] for r in url_retrieval['results'] if r['id'] in indexed]
        if discovery:
            comparison=await editor_discovery.select_pair(user,conversation,url_retrieval['shortlist'],discovery)
            discovery['comparison']=comparison
            if comparison['ids']:
                selected=[indexed[i] for i in comparison['ids'] if i in indexed]
            elif comparison.get('available') and 'supported_ids' in comparison:
                # Lack of evidence for a particular contrast is not evidence
                # that an independently retrieved/checked work is unusable.
                # Keep actual references; do not invent a contrast between them.
                comparison['shown_without_contrast']=True
            # A relevant but uninspected reference can still be useful to the
            # user. Keep it visible; never describe it as an evidenced contrast.
            discovery['reused_ids']=[r['id'] for r in selected if any(d.get('library_id')==r['id'] for d in displayed)]
        if not url_retrieval.get('available'):
            # A failed lookup is not evidence of missing library coverage and
            # must not silently launch a different, long-running research task.
            action='talk';selected=[]
            if discovery:discovery['comparison']={'ids':[],'sides':[],'reason':'retrieval_failed'}
        # These references have metadata evidence, not inspected visual claims.
        # Do not fall back to a stock component if the work search is empty.
    if action=='compare' and not whole_work and retrieval=='choice' and verify_candidates and candidates:
        # Ranking answers "which is best", not whether the runners-up are
        # suitable. Verify a small shortlist against the actual request.
        shortlist=candidates[:6]
        check_questions={'count':questions['count'],**{'fit_'+r['id']:fit_question(r['id']) for r in shortlist}}
        verification=await editor_jev.judge(user,{'conversation':conversation,'current_user_statement':state['current_user_statement'],
            'candidates':{r['id']:r['title']+': '+library.selection_description(r) for r in shortlist}},check_questions,timeout=1.5)
        verification['source']='shortlist_request'
        checked=verification.get('answers',{})
        if all('fit_'+r['id'] in checked for r in shortlist):
            quantity=checked.get('count',{})
            limit=int(quantity['choice']) if quantity.get('choice') in ('1','2','3') and quantity.get('probabilities',{}).get(quantity['choice'],0)>=.7 else count
            compatible=[r for r in shortlist if sum(checked['fit_'+r['id']].get('probabilities',{}).get(str(n),0) for n in (2,3))>=.5]
            selected=sorted(compatible,key=lambda r:-checked['fit_'+r['id']].get('score',0))[:limit]
    # A tentative comparison with no useful examples is not authorization for
    # a research job. Let the conversation clarify what the feedback concerns.
    # Strong requests with missing coverage still reach backend research.
    if action=='compare' and not selected and probabilities.get('compare',0)<.85 and probabilities.get('execute',0)<=.05:
        action='talk'
    ids=[r['id'] for r in selected] if action=='compare' else []
    return {'action':action,'destination':destination,'selected_library_ids':ids,'item_id':target,'pending_disposition':disposition,
            'handled':bool(action in ('listen','talk') or (action=='compare' and ids and destination!='timeline') or (action in ('reveal','play','pause','select') and target)),
            'coverage_missing':action=='compare' and not ids,
            'needs_backend':action=='execute' or destination=='timeline',
            'available':result.get('available',False),'elapsed_ms':round((time.perf_counter()-started)*1000),
            'failure':{k:result.get(k) for k in ('reason','error_type','http_status')} if not result.get('available') else None,
            'model':editor_jev.MODEL,'consultation_memo':memo,'answers':answers,'ranked_count':len(rows),'retrieval':retrieval,'verification':verification,'url_retrieval':url_retrieval,'discovery':discovery}

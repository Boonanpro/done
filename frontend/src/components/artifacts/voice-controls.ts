/** Common DOM controls for every artifact. Only a same-origin call frame can connect.
 * No selectors, scripts or model-supplied approval flags are executable here. */
export type ScreenControl = { id: string; name: string; role: string; action?: string; risk: string; fingerprint: string; value?: string; options?: string[] };
export type ScreenSnapshot = { page_id: string; url: string; title: string; controls: ScreenControl[]; text: string };
export type ScreenCommand = { request_id: string; page_id: string; target?: string; fingerprint?: string; op: 'click' | 'fill' | 'select' | 'scroll' | 'inspect'; value?: string; direction?: 'up' | 'down'; authorized?: boolean; guard?: { text: string; values: unknown } };

export function installVoiceControls() {
  if (window.parent === window || new URLSearchParams(location.search).get('call') !== '1') return () => {};
  const pageId = crypto.randomUUID();
  const ids = new WeakMap<Element, string>();
  const targets = new Map<string, HTMLElement>();
  let next = 0, connected = false, timer: ReturnType<typeof setTimeout> | undefined;
  let previous = '';
  const done = new Set<string>();
  const selector = 'button,a[href],input,textarea,select,[role="button"],[role="tab"],[role="menuitem"],[role="option"],[contenteditable="true"],[data-voice-action]';
  const send = (data: object) => { if (connected) window.parent.postMessage(data, location.origin); };
  const visible = (el: HTMLElement) => !!el.getClientRects().length && el.checkVisibility({checkOpacity:true,checkVisibilityCSS:true}) && !el.closest('[inert],[aria-hidden="true"]');
  const name = (el: HTMLElement): string => {
    const labelled = (el.getAttribute('aria-labelledby') || '').split(/\s+/).map(id => document.getElementById(id)?.textContent || '').join(' ').trim();
    const labels = 'labels' in el ? Array.from((el as HTMLInputElement).labels || []).map(x => x.textContent).join(' ') : '';
    return (el.getAttribute('aria-label') || labelled || labels || el.getAttribute('title') || el.getAttribute('placeholder') || el.innerText || el.getAttribute('name') || '').trim().replace(/\s+/g, ' ').slice(0, 160);
  };
  const describe = (el: HTMLElement): ScreenControl => {
    let id = ids.get(el); if (!id) { id = 'c' + (++next); ids.set(el, id); }
    const label = name(el), tag = el.tagName.toLowerCase();
    const role = el.getAttribute('role') || tag;
    const type = el.getAttribute('type') || '';
    const named = el.getAttribute('data-voice-action') || '';
    const hint = el.getAttribute('data-voice-risk') || '';
    const words = [label, named, type, hint].join(' ');
    const risk = role === 'tab' ? 'navigate' : /送信|送る|投稿|公開|注文|購入|支払|振込|削除|消去|退会|契約|本番|GO|send|submit|publish|delete|pay|buy|external|payment|destructive/i.test(words) ? 'confirm'
      : tag === 'a' && !/^javascript:/i.test(el.getAttribute('href') || '') ? 'navigate'
      : ['input','textarea','select'].includes(tag) || el.isContentEditable ? 'edit'
      : role === 'tab' || /^(閉じる|戻る|一覧へ戻る|キャンセル|検索|開く|一覧|次へ|前へ|拡大|縮小|更新|再読込|読み直す|設定|小さくする|大きくする|全体|全部開く|細部を閉じる|×|✕|✖|close|back|cancel)$/i.test(label) || ['navigate','edit'].includes(hint) ? hint || 'navigate' : 'confirm';
    const value = 'value' in el && type !== 'password' ? String((el as HTMLInputElement).value).slice(0, 1000) : undefined;
    return { id, name: label || role, role, action: named || undefined, risk,
      fingerprint: JSON.stringify([label, role, named, risk, el.getAttribute('href'), type, (el.closest('tr,li,article,[data-voice-item]')?.textContent || '').trim().slice(0,200)]), value,
      options: tag === 'select' ? Array.from((el as HTMLSelectElement).options).map(o => o.label).slice(0, 80) : undefined };
  };
  const snapshot = (): ScreenSnapshot => {
    targets.clear();
    const controls: ScreenControl[] = [];
    for (const el of document.querySelectorAll<HTMLElement>(selector)) {
      if (!visible(el) || el.matches(':disabled,[aria-disabled="true"],input[type="password"],input[type="hidden"],input[type="file"]')) continue;
      const c = describe(el); targets.set(c.id, el); controls.push(c);
      if (controls.length >= 300) break;
    }
    return {page_id: pageId, url: location.pathname + location.search, title: document.title, controls, text: (document.body?.innerText || '').slice(0, 8000)};
  };
  const publish = () => {
    const screen = snapshot(), serialized = JSON.stringify(screen);
    if (serialized !== previous) { previous = serialized; send({type:'dan-screen-snapshot', screen}); }
  };
  const schedule = () => { clearTimeout(timer); timer = setTimeout(publish, 80); };
  const highlight = (el: HTMLElement) => {
    el.scrollIntoView({block:'center', inline:'nearest', behavior:'instant'});
    el.animate([{outline:'3px solid #38bdf8', outlineOffset:'3px'}, {outline:'3px solid transparent', outlineOffset:'3px'}], {duration:1000});
  };
  const execute = async (c: ScreenCommand) => {
    if (!c.request_id || done.has(c.request_id)) return;
    done.add(c.request_id);
    let result: Record<string, unknown> = {ok:false, dispatched:false};
    try {
      if (c.page_id !== pageId) throw Error('画面が替わりました。読み直してください。');
      if (c.op === 'inspect') { result = {ok:true, dispatched:false}; }
      else if (c.op === 'scroll') {
        const candidates = [document.scrollingElement, ...document.querySelectorAll<HTMLElement>('main,section,div')].filter((x): x is HTMLElement => !!x && visible(x as HTMLElement) && x.scrollHeight > x.clientHeight + 50 && ['auto','scroll'].includes(getComputedStyle(x).overflowY));
        const el = candidates.sort((a,b) => b.clientWidth*b.clientHeight-a.clientWidth*a.clientHeight)[0] || document.scrollingElement;
        el?.scrollBy({top:(c.direction === 'up' ? -1 : 1)*innerHeight*.75, behavior:'instant'});
        result = {ok:true, dispatched:true};
      } else {
        const el = targets.get(c.target || '');
        if (!el || !el.isConnected || !visible(el) || el.matches(':disabled,[aria-disabled="true"]')) throw Error('操作先が変わりました。読み直してください。');
        const observed = describe(el);
        if (observed.fingerprint !== c.fingerprint) throw Error('操作先の内容が変わりました。読み直してください。');
        if (observed.risk === 'confirm' && c.authorized !== true) throw Error('本人の承認が必要です。');
        if (c.authorized) {
          const current = snapshot();
          const values = current.controls.map(x => [x.id,x.name,x.value,x.fingerprint]);
          if (!c.guard || c.guard.text !== current.text || JSON.stringify(c.guard.values) !== JSON.stringify(values)) throw Error('承認後に内容が変わりました。もう一度確認してください。');
        }
        highlight(el);
        if (c.op === 'click') {
          if (el instanceof HTMLAnchorElement) {
            const url = new URL(el.href, location.href);
            if (url.origin !== location.origin || !['http:','https:'].includes(url.protocol) || el.hasAttribute('download') || el.target === '_blank') throw Error('外の画面はダンのブラウザで開いてください。');
          }
          const rect = el.getBoundingClientRect();
          const hit = document.elementFromPoint(Math.max(0, Math.min(innerWidth-1,rect.left+rect.width/2)), Math.max(0,Math.min(innerHeight-1,rect.top+rect.height/2)));
          if (!hit || (hit !== el && !el.contains(hit))) throw Error('操作先の上に別の画面が開いています。読み直してください。');
          el.click(); result = {ok:true, dispatched:true};
        } else if (c.op === 'fill' || c.op === 'select') {
          const value = String(c.value ?? '');
          if (el instanceof HTMLInputElement && ['password','file','hidden','submit','button','checkbox','radio'].includes(el.type)) throw Error('この欄には入力できません。');
          if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement || el instanceof HTMLSelectElement) {
            if (el instanceof HTMLSelectElement) {
              const option = Array.from(el.options).find(o => o.value === value || o.label === value);
              if (!option || option.disabled) throw Error('その選択肢はありません。');
              Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, 'value')!.set!.call(el, option.value);
            } else {
              if (c.op === 'select' || el.readOnly) throw Error('この欄は編集できません。');
              Object.getOwnPropertyDescriptor(el instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype, 'value')!.set!.call(el, value);
            }
            el.dispatchEvent(new Event('input',{bubbles:true})); el.dispatchEvent(new Event('change',{bubbles:true}));
            result = {ok:true, dispatched:true, value:el.value};
          } else throw Error('この欄の編集は編集アシスタントで行ってください。');
        } else throw Error('その操作は使えません。');
      }
    } catch (e) { result.error = e instanceof Error ? e.message : '操作できませんでした。'; }
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    const screen = snapshot();
    send({type:'dan-screen-result', request_id:c.request_id, result, screen});
    previous = JSON.stringify(screen);
  };
  const listener = (event: MessageEvent) => {
    if (event.source !== window.parent || event.origin !== location.origin) return;
    if (event.data?.type === 'dan-screen-connect') { connected = true; previous = ''; publish(); }
    if (connected && event.data?.type === 'dan-screen-command') void execute(event.data.command);
  };
  window.addEventListener('message', listener);
  const observer = new MutationObserver(schedule); observer.observe(document.body,{subtree:true,childList:true,attributes:true,characterData:true});
  document.addEventListener('input', schedule); window.addEventListener('popstate',schedule);
  const heartbeat = setInterval(() => { previous = ''; publish(); }, 5000);
  window.parent.postMessage({type:'dan-screen-ready'}, location.origin);
  return () => { observer.disconnect(); clearTimeout(timer); clearInterval(heartbeat); window.removeEventListener('message', listener); document.removeEventListener('input', schedule); window.removeEventListener('popstate',schedule); };
}

'use client';

import { useEffect, useRef, useState, type MouseEvent } from 'react';
import { EditableProvider } from '@/components/dan/editable';
import { toEditableOverrides, type ReleaseOverrides } from '@/lib/editable-release';
import { FloorLpReconstruction, FLOOR_ASSETS } from './floor-lp-reconstruction';
import './floor-lp-comparison.css';

type Selection = { id: string; text: string; fontSize: number; color: string; photo: boolean; src: string };
const STORAGE = 'dan-floor-lp-comparison-v1';

export function FloorLpComparison() {
  const [edits, setEdits] = useState<ReleaseOverrides>({});
  const [undo, setUndo] = useState<ReleaseOverrides[]>([]);
  const [selected, setSelected] = useState<Selection | null>(null);
  const [mode, setMode] = useState<'compare' | 'original' | 'editable'>('compare');
  const [hidePhotos, setHidePhotos] = useState(false);
  const [editMode, setEditMode] = useState(true);
  const [status, setStatus] = useState('文字をクリックすると変更できます');
  const [ready, setReady] = useState(false);
  const output = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const timer = setTimeout(() => {
      try { setEdits(JSON.parse(localStorage.getItem(STORAGE) || '{}')); } catch { /* Start clean. */ }
      setReady(true);
    }, 0);
    return () => clearTimeout(timer);
  }, []);

  function save(next: ReleaseOverrides) {
    setUndo((history) => [...history.slice(-49), edits]);
    setEdits(next);
    try { localStorage.setItem(STORAGE, JSON.stringify(next)); setStatus('このブラウザーに保存しました'); }
    catch { setStatus('保存できませんでした。ページを閉じると変更が失われます'); }
  }

  function update(text?: string, styles?: Record<string, string>, attrs?: Record<string, string>) {
    if (!selected) return;
    const key = `@${selected.id}`;
    const previous = edits[key] || {};
    let model = { v: 2, text: null as string | null, spans: [], blockStyle: {}, attrs: {} };
    if (typeof previous.attrs?.model_v2 === 'string') model = JSON.parse(previous.attrs.model_v2);
    if (text !== undefined) model.text = text;
    save({ ...edits, [key]: {
      styles: { ...previous.styles, ...styles },
      attrs: { ...previous.attrs, ...attrs, model_v2: JSON.stringify(model) },
    } });
  }

  function select(event: MouseEvent<HTMLDivElement>) {
    if (!editMode) return;
    const target = (event.target as Element).closest<HTMLElement>('[data-edit-id]');
    if (!target || !output.current?.contains(target)) return;
    if (!['H1', 'H2', 'P', 'SPAN', 'BUTTON', 'IMG'].includes(target.tagName)) return;
    event.preventDefault();
    const style = getComputedStyle(target);
    const rgb = style.color.match(/\d+/g)?.slice(0, 3).map(v => Number(v).toString(16).padStart(2, '0')).join('');
    setSelected({ id: target.dataset.editId!, text: target.innerText || '', fontSize: Math.round(parseFloat(style.fontSize)), color: rgb ? `#${rgb}` : '#30302b', photo: target.tagName === 'IMG', src: target.getAttribute('src') || '' });
    setStatus(target.tagName === 'IMG' ? '写真を選択しました' : '選んだ文字を下の入力欄で変更できます');
  }

  function undoEdit() {
    const previous = undo[undo.length - 1];
    if (!previous) return;
    setEdits(previous);
    setUndo(undo.slice(0, -1));
    setSelected(null);
    try { localStorage.setItem(STORAGE, JSON.stringify(previous)); setStatus('変更を元に戻しました'); }
    catch { setStatus('元に戻しましたが保存できませんでした'); }
  }

  return (
    <main className="floor-lab">
      <header className="floor-lab-header">
        <div><h1>元の画像と、編集できるページ。</h1><p>床暖房LPの冒頭2区間を同じ内容・構成で再構成。右側の文字や写真をクリックして試せます。</p></div>
        <div className="floor-lab-modes" aria-label="表示切替">
          {([['compare', '並べて比較'], ['original', '元画像'], ['editable', '編集版だけ']] as const).map(([value, label]) => <button key={value} type="button" aria-pressed={mode === value} onClick={() => setMode(value)}>{label}</button>)}
        </div>
      </header>
      <div className="floor-lab-body">
        <div className={`floor-lab-pages floor-lab-${mode}`}>
          {mode !== 'editable' && <section className="floor-lab-column">
            <h2>元のImage 2画像 <span>変更できない1枚画像</span></h2>
            <div className="floor-lab-original">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`${FLOOR_ASSETS}/original-hero.webp`} alt="元の床暖房LP・ヒーロー" />
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={`${FLOOR_ASSETS}/original-problem.webp`} alt="元の床暖房LP・エアコンとの比較" />
            </div>
          </section>}
          {mode !== 'original' && <section className="floor-lab-column">
            <h2>編集可能な再構成 <span>文字・ボタン・表はHTML</span></h2>
            <div ref={output} onClickCapture={select} className={`floor-lab-result ${editMode ? 'is-editing' : ''} ${hidePhotos ? 'hide-photos' : ''}`}>
              <EditableProvider overrides={toEditableOverrides(edits)}><FloorLpReconstruction /></EditableProvider>
            </div>
          </section>}
        </div>
        <aside className="floor-lab-tools">
          <h2>実際に編集する</h2>
          <label className="floor-lab-check"><input type="checkbox" checked={editMode} onChange={e => setEditMode(e.target.checked)} />手動編集ON</label>
          <label className="floor-lab-check"><input type="checkbox" checked={hidePhotos} onChange={e => setHidePhotos(e.target.checked)} />写真を隠す</label>
          <p className="floor-lab-help">写真を隠すと、画像に焼き込まれていない文字・ボタン・表だけを確認できます。</p>
          {selected && !selected.photo && <>
            <label>テキスト<textarea aria-label="選択したテキスト" value={selected.text} rows={4} onChange={e => { setSelected({ ...selected, text: e.target.value }); update(e.target.value); }} /></label>
            <div className="floor-lab-pair">
              <label>文字サイズ<input type="number" aria-label="文字サイズ" min="8" max="200" value={selected.fontSize} onChange={e => { const fontSize = Number(e.target.value); setSelected({ ...selected, fontSize }); update(undefined, { 'font-size': `${fontSize}px` }); }} /></label>
              <label>文字色<input type="color" aria-label="文字色" value={selected.color} onChange={e => { setSelected({ ...selected, color: e.target.value }); update(undefined, { color: e.target.value }); }} /></label>
            </div>
          </>}
          {selected?.photo && <label>画像URL<input aria-label="画像URL" value={selected.src} onChange={e => { setSelected({ ...selected, src: e.target.value }); update(undefined, undefined, { src: e.target.value }); }} /></label>}
          {!selected && <p className="floor-lab-empty">編集版の見出しや表の文字をクリックしてください。</p>}
          <div className="floor-lab-actions">
            <button type="button" onClick={undoEdit} disabled={!undo.length}>元に戻す</button>
            <button type="button" onClick={() => { save({}); setSelected(null); }}>初期状態に戻す</button>
          </div>
          <p role="status" className="floor-lab-status">{ready ? status : '保存した編集を読み込み中…'}</p>
          <div className="floor-lab-explanation"><h3>今回、何をしたか</h3><p>元の写真領域はそのまま使用。見出し・本文・ボタン・比較表を、独立した文字と図形で組み直しました。</p><p>フォントとアイコンには差が残ります。写真は画像素材のままです。</p><p>この比較用エディターの変更は、このブラウザーだけに保存します。元LPは変更しません。登録ボタンは見た目の検証用です。</p></div>
        </aside>
      </div>
    </main>
  );
}

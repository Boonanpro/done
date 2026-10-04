'use client';

// Internal render target. The export pipeline (app/api/production_asset_routes.py) points a
// headless Chromium at /caption-frame?p=<base64 json> and screenshots it with a transparent
// background. Because it renders the SAME <CaptionLayer> as the live editor preview, the burned
// caption matches the timeline pixel-for-pixel. Not linked from any UI.
//
// For ANIMATED captions the screenshotter loads the page ONCE then drives the playhead via
// window.__renderCaptionAt(t) per frame (much faster than navigating per frame).

import { Suspense, useEffect, useState, useRef } from 'react';
import { useSearchParams } from 'next/navigation';
import { CaptionLayer, type RenderCaption } from '@/components/video-review/caption-layer';
import { CAPTION_FONT_FILES } from '@/components/video-review/caption-design';

type Payload = {
  outW: number;
  outH: number;
  time: number;
  fps?: number;
  hiddenCaptionIds?: string[];
  captions: (RenderCaption & {scene?: Record<string, unknown>})[];
};

type SceneHost = HTMLDivElement & {ready?: Promise<{ok:boolean}>;seek?: (t:number)=>void;dispose?:()=>void};
let sceneScript: Promise<void> | undefined;
function loadSceneScript(){
  return sceneScript ||= new Promise<void>((resolve,reject)=>{
    const s=document.createElement('script');s.src='/api/v1/editor-assistant/native-scene-script';
    s.onload=()=>resolve();s.onerror=()=>{sceneScript=undefined;reject(Error('Scene renderer unavailable'));};document.head.append(s);
  });
}
function EditableScene({clip,time}:{clip:RenderCaption & {scene?:Record<string,unknown>};time:number}){
  const ref=useRef<HTMLDivElement>(null),host=useRef<SceneHost|null>(null),latest=useRef(time);
  latest.current=time;
  useEffect(()=>{
    let canceled=false;
    const target=ref.current;
    loadSceneScript().then(()=>{
      if(canceled||!target)return;
      const h=document.createElement('div') as SceneHost;h.style.cssText='position:absolute;inset:0';target.append(h);host.current=h;
      window.createScenePreview?.({id:clip.id,title:'動画コンテ',scene:clip.scene},h);
      const frame=h.querySelector('iframe');if(frame)frame.style.cssText='width:100%;height:100%;border:0;display:block';
      const controls=h.querySelector<HTMLElement>('.proposal-controls');if(controls)controls.style.display='none';
      h.seek?.(latest.current-clip.start);
      h.ready?.then(result=>{if(!canceled){target.dataset.sceneReady=String(result.ok);h.seek?.(latest.current-clip.start);window.__nativeSceneTime=latest.current;}});
    }).catch(()=>{if(target)target.dataset.sceneReady='false';});
    return ()=>{canceled=true;host.current?.dispose?.();host.current=null;target?.replaceChildren();};
  },[clip.id,clip.scene,clip.start]);
  useEffect(()=>{
    host.current?.seek?.(time-clip.start);
    const handle=requestAnimationFrame(()=>requestAnimationFrame(()=>{window.__nativeSceneTime=time;}));
    return ()=>cancelAnimationFrame(handle);
  },[time,clip.start]);
  return <div ref={ref} style={{position:'absolute',inset:0,zIndex:-1}}/>;
}

declare global {
  interface Window {
    createScenePreview?: (item:unknown,host:SceneHost)=>SceneHost;
    __nativeSceneTime?:number;
    __renderCaptionAt?: (t: number, hiddenCaptionIds?: string[]) => Promise<void>;
    __setCaptionPayload?: (payload: Payload) => Promise<void>;
    __nativeCaptionPayload?: Payload;
  }
}

function decodePayload(raw: string | null): Payload | null {
  if (!raw) return null;
  try {
    // URL-safe base64 (-/_) -> standard, then base64(UTF-8 JSON) -> JSON. escape/atob handles
    // multibyte (Japanese) text. URL-safe is required: a '+' in the query becomes a space.
    const std = raw.replace(/-/g, '+').replace(/_/g, '/');
    return JSON.parse(decodeURIComponent(escape(atob(std)))) as Payload;
  } catch {
    return null;
  }
}

function Inner() {
  const sp = useSearchParams();
  const initialPayload = decodePayload(sp.get('p'));
  const [payload, setPayload] = useState<Payload | null>(initialPayload);
  const [viewport, setViewport] = useState({ w: 1, h: 1 });
  const [ready, setReady] = useState(false);

  // Let the screenshotter set the playhead and await the next painted frame.
  useEffect(() => {
    window.__renderCaptionAt = (t: number, hiddenCaptionIds?: string[]) =>
      new Promise<void>((resolve) => {
        setPayload((current) => {
          if (!current) return current;
          const next = {
            ...current,
            time: t,
            hiddenCaptionIds: hiddenCaptionIds ?? current.hiddenCaptionIds ?? [],
          };
          window.__nativeCaptionPayload = next;
          return next;
        });
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      });
    window.__setCaptionPayload = (next: Payload) =>
      new Promise<void>((resolve) => {
        window.__nativeCaptionPayload = next;
        setPayload(next);
        requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
      });
    if (window.__nativeCaptionPayload) {
      void window.__setCaptionPayload(window.__nativeCaptionPayload);
    }
    return () => {
      delete window.__renderCaptionAt;
      delete window.__setCaptionPayload;
    };
  }, []);

  useEffect(() => {
    const update = () => setViewport({ w: window.innerWidth, h: window.innerHeight });
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  useEffect(() => {
    document.documentElement.style.background = 'transparent';
    document.body.style.background = 'transparent';
    document.body.style.margin = '0';
    let cancelled = false;
    (async () => {
      // The bundled faces use font-display:block (invisible until loaded), and @font-face in an
      // injected <style> does NOT register in document.fonts in time for the screenshot. So load
      // every face via the FontFace API and add it to document.fonts explicitly, then await.
      try {
        const fontSet = (document as unknown as { fonts?: FontFaceSet }).fonts;
        if (fontSet && typeof FontFace !== 'undefined') {
          await Promise.all(
            CAPTION_FONT_FILES.map(async ([family, url, weight]) => {
              try {
                const face = new FontFace(family, `url("${url}")`, { weight: String(weight) });
                await face.load();
                fontSet.add(face);
              } catch {
                /* a single face failing must not block the rest */
              }
            }),
          );
          await fontSet.ready;
        }
      } catch {
        /* ignore */
      }
      requestAnimationFrame(() =>
        requestAnimationFrame(() => {
          if (cancelled) return;
          setReady(true);
          document.body.setAttribute('data-caption-ready', '1');
        }),
      );
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  if (!payload) return null;
  const scale = Math.min(viewport.w / payload.outW, viewport.h / payload.outH);
  const left = (viewport.w - payload.outW * scale) / 2;
  const top = (viewport.h - payload.outH * scale) / 2;
  return (
    <div style={{ width: '100vw', height: '100vh', overflow: 'hidden', position: 'relative', pointerEvents: 'none' }} data-ready={ready ? '1' : '0'}>
      <div style={{ width: payload.outW, height: payload.outH, position: 'absolute', left, top, transform: `scale(${scale})`, transformOrigin: 'top left',isolation:'isolate' }}>
        <CaptionLayer
          outW={payload.outW}
          outH={payload.outH}
          captions={payload.captions.filter(c=>!c.scene)}
          time={payload.time}
          fps={payload.fps}
          hiddenCaptionIds={payload.hiddenCaptionIds}
        />
        {payload.captions.filter(c=>c.scene && payload.time>=c.start && payload.time<c.end).map(c=><EditableScene key={c.id} clip={c} time={payload.time}/>)}
      </div>
    </div>
  );
}

export default function CaptionFramePage() {
  return (
    <Suspense fallback={null}>
      <Inner />
    </Suspense>
  );
}

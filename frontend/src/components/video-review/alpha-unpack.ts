// 透明な映像（ProRes 4444 などの背景が透けた動画）をプレビューで透かして描く（2026-11-16）。
//
// Why: the preview decodes H.264 (WebCodecs / <video>), which has no alpha. The server therefore
// makes the watching copy of a transparent video as a "stacked" frame: the colour on the top half
// and the alpha (as grey) on the bottom half (production_asset_routes._make_view_copy). Here one
// small WebGL pass per asset joins the two halves back into a picture with real transparency, which
// the 2D canvas then draws like any other frame (placement, opacity, blend all unchanged).

export const ALPHA_ASSET_IDS = new Set<string>();

type Unpacker = { canvas: HTMLCanvasElement; gl: WebGLRenderingContext; tex: WebGLTexture; w: number; h: number; ok: boolean };

const VS = 'attribute vec2 p;varying vec2 uv;void main(){uv=vec2((p.x+1.)*.5,(1.-p.y)*.5);gl_Position=vec4(p,0.,1.);}';
// top half = colour (already premultiplied by the server), bottom half = alpha as grey. The WebGL
// canvas is premultiplied too, so drawImage composites it like any transparent picture.
const FS = 'precision mediump float;varying vec2 uv;uniform sampler2D t;void main(){vec3 c=texture2D(t,vec2(uv.x,uv.y*.5)).rgb;float a=texture2D(t,vec2(uv.x,.5+uv.y*.5)).r;gl_FragColor=vec4(min(c,vec3(a)),a);}';

function makeUnpacker(): Unpacker | null {
  const canvas = document.createElement('canvas');
  const gl = canvas.getContext('webgl', { premultipliedAlpha: true, alpha: true, preserveDrawingBuffer: true, antialias: false });
  if (!gl) return null;
  const sh = (type: number, src: string) => {
    const s = gl.createShader(type)!;
    gl.shaderSource(s, src);
    gl.compileShader(s);
    return s;
  };
  const prog = gl.createProgram()!;
  gl.attachShader(prog, sh(gl.VERTEX_SHADER, VS));
  gl.attachShader(prog, sh(gl.FRAGMENT_SHADER, FS));
  gl.linkProgram(prog);
  if (!gl.getProgramParameter(prog, gl.LINK_STATUS)) return null;
  gl.useProgram(prog);
  const buf = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, 'p');
  gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const tex = gl.createTexture()!;
  gl.bindTexture(gl.TEXTURE_2D, tex);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
  gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
  gl.pixelStorei(gl.UNPACK_PREMULTIPLY_ALPHA_WEBGL, false);
  return { canvas, gl, tex, w: 0, h: 0, ok: true };
}

// ONE WebGL context for the whole editor (a page may only hold ~16; a timeline can have a hundred
// transparent clips). Each asset gets its own small 2D canvas holding its last joined picture, so
// two transparent clips on screen at once don't overwrite each other before the canvas draws them.
let shared: Unpacker | null | undefined;
type Out = { canvas: HTMLCanvasElement; ctx: CanvasRenderingContext2D; src: unknown };
const outs = new Map<string, Out>();
const MAX_OUTS = 12;

function outFor(key: string, w: number, h: number): Out | null {
  let o = outs.get(key);
  if (o) { outs.delete(key); outs.set(key, o); } // most recently used last
  else {
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    o = { canvas, ctx, src: null };
    outs.set(key, o);
    while (outs.size > MAX_OUTS) outs.delete(outs.keys().next().value as string);
  }
  if (o.canvas.width !== w || o.canvas.height !== h) { o.canvas.width = w; o.canvas.height = h; o.src = null; }
  return o;
}

/** Join a stacked (colour over alpha) frame into a transparent picture. Returns null when WebGL
 *  is unavailable — the caller then draws the frame as it is. */
export function unpackStacked(key: string, src: CanvasImageSource, vw: number, vh: number): { src: HTMLCanvasElement; vw: number; vh: number } | null {
  if (shared === undefined) shared = makeUnpacker();
  const u = shared;
  if (!u || !u.ok || !vw || vh < 2) return null;
  const w = Math.round(vw);
  const h = Math.round(vh / 2);
  const o = outFor(key, w, h);
  if (!o) return null;
  // the same decoded frame asked again (several draws of one frame): reuse the picture.
  // A <video> element is the same object every frame, so it is always joined again.
  const isVideoEl = typeof HTMLVideoElement !== 'undefined' && src instanceof HTMLVideoElement;
  if (!isVideoEl && o.src === src) return { src: o.canvas, vw: w, vh: h };
  const { gl } = u;
  if (u.w !== w || u.h !== h) { u.canvas.width = w; u.canvas.height = h; u.w = w; u.h = h; gl.viewport(0, 0, w, h); }
  try {
    gl.bindTexture(gl.TEXTURE_2D, u.tex);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, src as TexImageSource);
    gl.clearColor(0, 0, 0, 0);
    gl.clear(gl.COLOR_BUFFER_BIT);
    gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    o.ctx.clearRect(0, 0, w, h);
    o.ctx.drawImage(u.canvas, 0, 0);
  } catch {
    return null;
  }
  o.src = isVideoEl ? null : src;
  return { src: o.canvas, vw: w, vh: h };
}

/** Is the picture of this asset solid at (fx, fy) (0-1 of the picture)? Reads the last joined
 *  picture; true when nothing was drawn yet (treat as solid). */
export function alphaSolidAt(key: string, fx: number, fy: number): boolean {
  const o = outs.get(key);
  if (!o || !o.canvas.width) return true;
  try {
    const x = Math.max(0, Math.min(o.canvas.width - 1, Math.floor(fx * o.canvas.width)));
    const y = Math.max(0, Math.min(o.canvas.height - 1, Math.floor(fy * o.canvas.height)));
    return o.ctx.getImageData(x, y, 1, 1).data[3] > 24;
  } catch { return true; }
}

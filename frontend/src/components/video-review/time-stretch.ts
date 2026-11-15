// 音を速く鳴らしても声の高さを変えない（2026-11-15 本人「L を押したら、音のピッチを変えずに倍速再生」）。
//
// 解読済みの波形をそのまま速く鳴らすと（AudioBufferSourceNode.playbackRate）、声が高くなる。
// ここでは WSOLA（波形の短い切れ端を、つなぎ目の形が一番そろう所で選び直しながら重ねる）で、
// 長さだけを 1/rate に縮めた波形を作る。音の高さと声の質はそのまま。
// 1 区切り（4 秒）を縮めるのに数ミリ秒。似た所を探すのは間引いた単声で、重ねるのは全部の声部。

const FRAME_SEC = 0.03;  // 切れ端の長さ（話し声に合う 30ms）
const SEEK_SEC = 0.012;  // つなぎ目をそろえるために前後に探す幅

/** channels（同じ長さの Float32Array の並び）を rate 倍速に縮めた波形。長さは round(n / rate) */
export function stretchChannels(channels: Float32Array[], sampleRate: number, rate: number): Float32Array[] {
  const n = channels[0]?.length || 0;
  const nOut = Math.max(1, Math.round(n / rate));
  const out = channels.map(() => new Float32Array(nOut));
  if (!n) return out;
  if (Math.abs(rate - 1) < 1e-3) { channels.forEach((c, i) => out[i].set(c.subarray(0, nOut))); return out; }
  const W = Math.max(64, Math.round(FRAME_SEC * sampleRate) & ~1);
  const Hs = W >> 1;                     // 書き出す側の間隔（半分ずつ重ねる）
  const Ha = Hs * rate;                  // 読む側の間隔
  const D = Math.round(SEEK_SEC * sampleRate);
  const win = new Float32Array(W);
  for (let i = 0; i < W; i++) win[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * (i + 0.5)) / W);
  // 似た所探し用の単声
  const mono = new Float32Array(n);
  for (const c of channels) for (let i = 0; i < n; i++) mono[i] += c[i];
  const norm = new Float32Array(nOut);
  const sampleAt = (arr: Float32Array, i: number) => (i >= 0 && i < n ? arr[i] : 0);
  // 前の切れ端の続き（nat）と一番形がそろう読み位置を、nominal の前後 D の中から選ぶ
  const corr = (cand: number, nat: number, step: number) => {
    let s = 0;
    for (let i = 0; i < W; i += step) s += sampleAt(mono, cand + i) * sampleAt(mono, nat + i);
    return s;
  };
  let prev = 0;
  for (let k = 0; ; k++) {
    const outPos = k * Hs;
    if (outPos >= nOut) break;
    let pos = 0;
    if (k > 0) {
      const nominal = Math.round(k * Ha);
      const nat = prev + Hs;
      const lo = Math.max(0, nominal - D);
      const hi = Math.max(lo, Math.min(n - 1, nominal + D));
      // 粗く探してから、その周りを細かく
      let best = Math.min(Math.max(nominal, lo), hi), bestV = -Infinity;
      for (let c = lo; c <= hi; c += 8) { const v = corr(c, nat, 8); if (v > bestV) { bestV = v; best = c; } }
      const lo2 = Math.max(lo, best - 8), hi2 = Math.min(hi, best + 8);
      bestV = -Infinity;
      for (let c = lo2; c <= hi2; c++) { const v = corr(c, nat, 2); if (v > bestV) { bestV = v; best = c; } }
      pos = best;
    }
    prev = pos;
    const len = Math.min(W, nOut - outPos);
    for (let ch = 0; ch < channels.length; ch++) {
      const src = channels[ch], dst = out[ch];
      for (let i = 0; i < len; i++) dst[outPos + i] += sampleAt(src, pos + i) * win[i];
    }
    for (let i = 0; i < len; i++) norm[outPos + i] += win[i];
  }
  for (let i = 0; i < nOut; i++) {
    const w = norm[i];
    if (w > 1e-4) for (const o of out) o[i] /= w;
  }
  return out;
}

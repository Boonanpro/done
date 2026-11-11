// タイムラインのクリップを AI で作る時に選べるモデル（2026-11-12 本人「クリップの長さの動画を作れるモデルを選んで
// プロンプトを打つと AI 動画が生成される」）。長さは各モデルが作れる秒数で、サーバー側
// （app/api/production_asset_routes.py の higgsfield_generate）と同じ値にそろえる。

export type AiVideoModel = { id: string; label: string; note: string; durations: number[] };

export const AI_VIDEO_MODELS: AiVideoModel[] = [
  { id: 'seedance_2_0', label: 'Seedance 2.0', note: '動きのある映像', durations: [5, 10, 15] },
  { id: 'seedance_2_5', label: 'Seedance 2.5', note: '長い場面・音つき', durations: [5, 10, 15, 30] },
  { id: 'kling3_0', label: 'Kling 3.0', note: '1つの場面', durations: [5, 10] },
];

const maxOf = (m: AiVideoModel) => m.durations[m.durations.length - 1];

/** この長さのクリップを1回で作れるモデル（無ければ一番長く作れるモデルだけ）。 */
export function aiModelsForLength(seconds: number): AiVideoModel[] {
  const fit = AI_VIDEO_MODELS.filter((m) => maxOf(m) >= Math.ceil(seconds - 0.01));
  if (fit.length) return fit;
  const longest = Math.max(...AI_VIDEO_MODELS.map(maxOf));
  return AI_VIDEO_MODELS.filter((m) => maxOf(m) === longest);
}

/** 選ばれたモデルがこの長さを作れればそれ、作れなければ作れる最初のモデル。 */
export function aiModelFor(seconds: number, wanted?: string | null): AiVideoModel {
  const fit = aiModelsForLength(seconds);
  return fit.find((m) => m.id === wanted) || fit[0];
}

/** モデルが作れる秒数のうち、クリップの長さ以上で一番短いもの。 */
export function aiDurationFor(model: AiVideoModel, seconds: number): number {
  const want = Math.ceil(seconds - 0.01);
  return model.durations.find((d) => d >= want) ?? maxOf(model);
}

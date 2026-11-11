// スマホのアプリ用の写し: frontend/src/lib/chat-shapes/map-geometry.ts と同じ中身（同じフォルダの読み込みの名前だけ違う）。
// frontend/scripts/sync-mobile-chat-shapes.mjs が作る。手で直さず、元を直して写し直す
// （tests/chat_shapes_program.test.mjs が同じ中身かを見る）。
/**
 * 地図の部品（Map）の形: 場所の座標から、地図の画像（タイル）の並びとピンの位置を計算する（2026-11-12）。
 * 地図の部品集（Leaflet など）を使わず、タイルを並べるだけにした: PC の画面・通話の画面・スマホのアプリ（React Native）で
 * 同じ計算を使い、どこでも同じ地図になる（写しは frontend/scripts/sync-mobile-chat-shapes.mjs）。
 *
 * タイル: 日本の中は国土地理院の淡色地図（地理院タイル。出典の表示が要る）、外は OpenStreetMap（© OpenStreetMap contributors）。
 * 計算は Web メルカトル（どちらのタイルも同じ）。React にも DOM にも依存しない。
 */

export const TILE = 256;

export type LatLng = { lat: number; lng: number };
export type MapTile = { key: string; url: string; left: number; top: number };
export type MapPoint = { left: number; top: number };
export type MapView = {
  zoom: number;
  tiles: MapTile[];
  /** 場所（places の順）とその場所の画面の中の位置（左上が 0,0） */
  points: MapPoint[];
  here: MapPoint | null;
  credit: string;
  /** 中心の世界座標（ずらす時に使う） */
  cx: number;
  cy: number;
};

const inJapan = (p: LatLng) => p.lat >= 20 && p.lat <= 46 && p.lng >= 122 && p.lng <= 154;

/** 緯度経度 → その zoom の世界座標（px） */
export function project(p: LatLng, zoom: number): { x: number; y: number } {
  const s = TILE * 2 ** zoom;
  const lat = Math.max(-85.05, Math.min(85.05, p.lat));
  const sin = Math.sin((lat * Math.PI) / 180);
  return { x: ((p.lng + 180) / 360) * s, y: (0.5 - Math.log((1 + sin) / (1 - sin)) / (4 * Math.PI)) * s };
}

/** 全部の点が余白つきで入る一番大きい zoom（1点だけなら町が見える 15） */
export function fitZoom(points: LatLng[], width: number, height: number, pad = 44, max = 17): number {
  if (points.length <= 1) return 15;
  for (let z = max; z >= 2; z--) {
    const xs = points.map((p) => project(p, z));
    const w = Math.max(...xs.map((q) => q.x)) - Math.min(...xs.map((q) => q.x));
    const h = Math.max(...xs.map((q) => q.y)) - Math.min(...xs.map((q) => q.y));
    if (w <= width - pad * 2 && h <= height - pad * 2) return z;
  }
  return 2;
}

/**
 * 地図の形。width・height は地図の枠の大きさ（px）。zoomDelta は本人が + − で変えた分、shift は指でずらした分（px）。
 * 中心は全部の点の真ん中（ずらした分だけ動く）。
 */
export function mapView(places: LatLng[], here: LatLng | null, width: number, height: number, zoomDelta = 0, shift = { x: 0, y: 0 }): MapView {
  const all = [...places, ...(here ? [here] : [])];
  const japan = all.length > 0 && all.every(inJapan);
  const zoom = Math.max(japan ? 5 : 2, Math.min(18, fitZoom(all, width, height) + zoomDelta));
  const ws = all.map((p) => project(p, zoom));
  const minX = Math.min(...ws.map((q) => q.x)), maxX = Math.max(...ws.map((q) => q.x));
  const minY = Math.min(...ws.map((q) => q.y)), maxY = Math.max(...ws.map((q) => q.y));
  const cx = (minX + maxX) / 2 - shift.x, cy = (minY + maxY) / 2 - shift.y;
  const ox = cx - width / 2, oy = cy - height / 2;   // 画面の左上の世界座標
  const n = 2 ** zoom;
  const tiles: MapTile[] = [];
  for (let ty = Math.floor(oy / TILE); ty <= Math.floor((oy + height) / TILE); ty++) {
    if (ty < 0 || ty >= n) continue;
    for (let tx = Math.floor(ox / TILE); tx <= Math.floor((ox + width) / TILE); tx++) {
      const wx = ((tx % n) + n) % n;
      const url = japan
        ? `https://cyberjapandata.gsi.go.jp/xyz/pale/${zoom}/${wx}/${ty}.png`
        : `https://tile.openstreetmap.org/${zoom}/${wx}/${ty}.png`;
      tiles.push({ key: `${zoom}/${tx}/${ty}`, url, left: Math.round(tx * TILE - ox), top: Math.round(ty * TILE - oy) });
    }
  }
  const at = (p: LatLng): MapPoint => { const q = project(p, zoom); return { left: q.x - ox, top: q.y - oy }; };
  return {
    zoom, tiles, points: places.map(at), here: here ? at(here) : null, cx, cy,
    credit: japan ? '地理院タイル' : '© OpenStreetMap',
  };
}

/** ピンの横に名前の札を出すか（多い時は番号だけにして、名前は下の一覧で） */
export function pinLabels(count: number): boolean {
  return count <= 4;
}

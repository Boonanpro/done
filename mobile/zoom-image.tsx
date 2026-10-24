import React, {useEffect, useMemo, useRef, useState} from 'react';
import {Animated, Image, PanResponder, StyleSheet, View, type GestureResponderEvent, type ImageProps} from 'react-native';

// 拡大して見られる画像。2本の指でつまむと拡大・縮小、拡大中は1本の指で動かせる、2回たたくと拡大／元に戻る（10-24 本人「チャットの画像みたいに拡大縮小を普通にできるように」）。
// 等倍の時は1本の指を受け取らないので、外側の横送り（次の写真へ）はそのまま効く。
export const MAX_ZOOM = 6;
const TAP_ZOOM = 2.5;
type Xf = {k: number; x: number; y: number};
type Pt = {x: number; y: number};
const IDENTITY: Xf = {k: 1, x: 0, y: 0};

// 写真が枠の中に収まって見えている大きさ（contain）
export function fitted(box: {w: number; h: number}, natural: {w: number; h: number} | null) {
 if (!natural || !natural.w || !natural.h) return box;
 const k = Math.min(box.w / natural.w, box.h / natural.h);
 return {w: natural.w * k, h: natural.h * k};
}
// 拡大した写真が枠からはみ出す分だけ動かせる。はみ出さない向きは真ん中に置く
export function clampXf(t: Xf, box: {w: number; h: number}, content: {w: number; h: number}): Xf {
 const k = Math.min(MAX_ZOOM, Math.max(1, t.k));
 if (k <= 1.001) return IDENTITY;
 const mx = Math.max(0, (content.w * k - box.w) / 2), my = Math.max(0, (content.h * k - box.h) / 2);
 return {k, x: Math.min(mx, Math.max(-mx, t.x)), y: Math.min(my, Math.max(-my, t.y))};
}
// 枠の真ん中から見た点 p を動かさずに、倍率を k にする
export function zoomAbout(t: Xf, p: Pt, k: number): Xf {
 const r = k / t.k;
 return {k, x: p.x - (p.x - t.x) * r, y: p.y - (p.y - t.y) * r};
}

type Props = Omit<ImageProps, 'style' | 'resizeMode'> & {onZoomChange?: (zoomed: boolean) => void};
export function ZoomImage({onZoomChange, onLoad, ...image}: Props) {
 const [box, setBox] = useState({w: 0, h: 0});
 const [natural, setNatural] = useState<{w: number; h: number} | null>(null);
 const boxRef = useRef(box); boxRef.current = box;
 const content = useRef(box); content.current = fitted(box, natural);
 const origin = useRef<Pt>({x: 0, y: 0});   // 枠の左上の画面上の位置
 const wrap = useRef<View>(null);
 const xf = useRef<Xf>(IDENTITY);
 const k = useRef(new Animated.Value(1)).current, x = useRef(new Animated.Value(0)).current, y = useRef(new Animated.Value(0)).current;
 const zoomCb = useRef(onZoomChange); zoomCb.current = onZoomChange;
 const zoomedNow = useRef(false);
 const report = (t: Xf) => { const z = t.k > 1.001; if (z !== zoomedNow.current) { zoomedNow.current = z; zoomCb.current?.(z); } };
 const show = (t: Xf) => { xf.current = t; k.setValue(t.k); x.setValue(t.x); y.setValue(t.y); };
 const glide = (t: Xf) => {
  xf.current = t; report(t);
  Animated.parallel([Animated.timing(k, {toValue: t.k, duration: 180, useNativeDriver: true}), Animated.timing(x, {toValue: t.x, duration: 180, useNativeDriver: true}), Animated.timing(y, {toValue: t.y, duration: 180, useNativeDriver: true})]).start();
 };
 useEffect(() => () => { if (zoomedNow.current) zoomCb.current?.(false); }, []);
 // 画面上の点を、枠の真ん中から見た点に直す
 const rel = (px: number, py: number): Pt => ({x: px - origin.current.x - boxRef.current.w / 2, y: py - origin.current.y - boxRef.current.h / 2});
 const gesture = useRef<{base: Xf; fingers: number; dist: number; mid: Pt; start: Pt} | null>(null);
 const begin = (e: GestureResponderEvent) => {
  const ts = e.nativeEvent.touches;
  if (ts.length >= 2) {
   const [a, b] = [ts[0], ts[1]];
   gesture.current = {base: xf.current, fingers: 2, dist: Math.hypot(a.pageX - b.pageX, a.pageY - b.pageY) || 1, mid: rel((a.pageX + b.pageX) / 2, (a.pageY + b.pageY) / 2), start: {x: 0, y: 0}};
  } else {
   const a = ts[0] || e.nativeEvent;
   gesture.current = {base: xf.current, fingers: 1, dist: 1, mid: {x: 0, y: 0}, start: {x: a.pageX, y: a.pageY}};
  }
 };
 const responder = useMemo(() => PanResponder.create({
  onStartShouldSetPanResponder: e => e.nativeEvent.touches.length >= 2 || xf.current.k > 1.001,
  onMoveShouldSetPanResponder: e => e.nativeEvent.touches.length >= 2 || xf.current.k > 1.001,
  onPanResponderTerminationRequest: () => false,
  onPanResponderGrant: e => begin(e),
  onPanResponderMove: e => {
   const ts = e.nativeEvent.touches;
   if (!gesture.current || (ts.length >= 2) !== (gesture.current.fingers === 2)) begin(e);   // 指が増えた・減った時は、今の形から測り直す
   const g = gesture.current!;
   if (g.fingers === 2 && ts.length >= 2) {
    const [a, b] = [ts[0], ts[1]];
    const kk = Math.min(MAX_ZOOM, Math.max(1, g.base.k * Math.hypot(a.pageX - b.pageX, a.pageY - b.pageY) / g.dist));
    const moved = zoomAbout(g.base, g.mid, kk), mid = rel((a.pageX + b.pageX) / 2, (a.pageY + b.pageY) / 2);
    show(clampXf({k: kk, x: moved.x + mid.x - g.mid.x, y: moved.y + mid.y - g.mid.y}, boxRef.current, content.current));
   } else if (ts.length === 1 && g.base.k > 1.001) {
    show(clampXf({k: g.base.k, x: g.base.x + ts[0].pageX - g.start.x, y: g.base.y + ts[0].pageY - g.start.y}, boxRef.current, content.current));
   }
  },
  onPanResponderRelease: () => { gesture.current = null; const t = clampXf(xf.current, boxRef.current, content.current); if (t.k === 1 && xf.current.k !== 1) glide(t); else { xf.current = t; report(t); } },
  onPanResponderTerminate: () => { gesture.current = null; report(xf.current); },
  // eslint-disable-next-line react-hooks/exhaustive-deps
 }), []);
 // 2回たたく。指の生の動きで見るので、等倍の時も外側の横送りを邪魔しない
 const press = useRef<{at: number; x: number; y: number; multi: boolean} | null>(null);
 const lastTap = useRef<{at: number; x: number; y: number} | null>(null);
 const touchStart = (e: GestureResponderEvent) => {
  const ts = e.nativeEvent.touches;
  if (ts.length > 1) { if (press.current) press.current.multi = true; return; }
  press.current = {at: Date.now(), x: e.nativeEvent.pageX, y: e.nativeEvent.pageY, multi: false};
 };
 const touchEnd = (e: GestureResponderEvent) => {
  const p = press.current;
  if (!p || e.nativeEvent.touches.length) return;
  press.current = null;
  const now = Date.now(), px = e.nativeEvent.pageX, py = e.nativeEvent.pageY;
  if (p.multi || now - p.at > 250 || Math.hypot(px - p.x, py - p.y) > 12) { lastTap.current = null; return; }
  const last = lastTap.current;
  if (last && now - last.at < 320 && Math.hypot(px - last.x, py - last.y) < 40) {
   lastTap.current = null;
   glide(xf.current.k > 1.001 ? IDENTITY : clampXf(zoomAbout(xf.current, rel(px, py), TAP_ZOOM), boxRef.current, content.current));
  } else lastTap.current = {at: now, x: px, y: py};
 };
 return <View ref={wrap} style={StyleSheet.absoluteFill} collapsable={false}
  onLayout={e => { const {width, height} = e.nativeEvent.layout; setBox({w: width, h: height}); wrap.current?.measureInWindow((ox, oy) => { origin.current = {x: ox, y: oy}; }); if (xf.current.k !== 1) show(IDENTITY); }}
  onTouchStart={touchStart} onTouchEnd={touchEnd} {...responder.panHandlers}>
  <Animated.View style={[StyleSheet.absoluteFill, {transform: [{translateX: x}, {translateY: y}, {scale: k}]}]}>
   <Image {...image} resizeMode="contain" style={StyleSheet.absoluteFill} onLoad={e => { const s = e.nativeEvent.source; if (s?.width && s?.height) setNatural({w: s.width, h: s.height}); onLoad?.(e); }}/>
  </Animated.View>
 </View>;
}

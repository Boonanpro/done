// 複数の画像・動画を LINE 式にまとめて表示する共通部品（APK）。
// 1枚: 縦横比を保って表示 / 2枚: 横2列 / 3枚: 左1大＋右2小 / 4枚以上: 正方形タイル
// （4=2列、5枚以上=3列、7枚以上は「+N」で畳む）。Web の components/chat/media-grid.tsx と同じ規則。
// プロジェクトチャットの吹き出しとコラボチャットで同じものを使う。
import React, { useEffect, useState } from 'react';
import { Image, Modal, Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';
import * as VideoThumbnails from 'expo-video-thumbnails';
import { useVideoPlayer, VideoView } from 'expo-video';

export type MediaGridItem = { url: string; kind: 'image' | 'video'; name?: string };

const MAX_TILES = 6;
const GAP = 2;

export function MediaGrid({
  items,
  width = 240,
  onOpenImage,
}: {
  items: MediaGridItem[];
  /** グリッド全体の幅（吹き出しの内側に収める） */
  width?: number;
  /** 画像タップ。未指定なら内蔵ビューアで開く */
  onOpenImage?: (url: string) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const [viewing, setViewing] = useState<MediaGridItem | null>(null);
  if (items.length === 0) return null;

  const open = (it: MediaGridItem) => {
    if (it.kind === 'image' && onOpenImage) onOpenImage(it.url);
    else setViewing(it);
  };

  const viewer = viewing ? <MediaViewer item={viewing} onClose={() => setViewing(null)} /> : null;

  if (items.length === 1) {
    const it = items[0];
    return (
      <View style={{ width }}>
        {it.kind === 'video' ? (
          <Pressable onPress={() => open(it)} style={[st.tile, { width, height: Math.round(width * 0.6) }]}>
            <VideoTile url={it.url} />
          </Pressable>
        ) : (
          <SingleImage url={it.url} width={width} onPress={() => open(it)} />
        )}
        {viewer}
      </View>
    );
  }

  const visible = expanded ? items : items.slice(0, MAX_TILES);
  const hidden = items.length - visible.length;

  const tile = (it: MediaGridItem, i: number, size: { width: number; height: number }) => {
    const isLast = i === visible.length - 1 && hidden > 0;
    return (
      <Pressable
        key={`${it.url}-${i}`}
        onPress={() => (isLast ? setExpanded(true) : open(it))}
        style={[st.tile, size]}
      >
        {it.kind === 'video' ? <VideoTile url={it.url} hidePlay={isLast} /> : (
          <Image source={{ uri: it.url }} style={StyleSheet.absoluteFill} resizeMode="cover" />
        )}
        {isLast && (
          <View style={st.more}><Text style={st.moreText}>+{hidden}</Text></View>
        )}
      </Pressable>
    );
  };

  let body: React.ReactNode;
  if (items.length === 3) {
    const h = Math.round(width * 0.75);
    const big = { width: Math.floor((width - GAP) / 2), height: h };
    const small = { width: Math.floor((width - GAP) / 2), height: Math.floor((h - GAP) / 2) };
    body = (
      <View style={{ flexDirection: 'row', gap: GAP }}>
        {tile(visible[0], 0, big)}
        <View style={{ gap: GAP }}>
          {tile(visible[1], 1, small)}
          {tile(visible[2], 2, small)}
        </View>
      </View>
    );
  } else {
    const cols = items.length <= 4 ? 2 : 3;
    const cell = Math.floor((width - GAP * (cols - 1)) / cols);
    body = (
      <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: GAP, width }}>
        {visible.map((it, i) => tile(it, i, { width: cell, height: cell }))}
      </View>
    );
  }

  return (
    <View style={[st.grid, { width }]}>
      {body}
      {viewer}
    </View>
  );
}

// 1枚の画像: 実寸の縦横比で表示（取得前は 4:3）
function SingleImage({ url, width, onPress }: { url: string; width: number; onPress: () => void }) {
  const [ratio, setRatio] = useState(4 / 3);
  useEffect(() => {
    let alive = true;
    Image.getSize(url, (w, h) => { if (alive && w > 0 && h > 0) setRatio(w / h); }, () => {});
    return () => { alive = false; };
  }, [url]);
  const height = Math.min(320, Math.round(width / ratio));
  return (
    <Pressable onPress={onPress} style={[st.tile, { width, height }]}>
      <Image source={{ uri: url }} style={StyleSheet.absoluteFill} resizeMode="cover" />
    </Pressable>
  );
}

function VideoTile({ url, hidePlay }: { url: string; hidePlay?: boolean }) {
  const [thumb, setThumb] = useState<string | null>(null);
  useEffect(() => {
    let alive = true;
    VideoThumbnails.getThumbnailAsync(url, { time: 1000, quality: 0.6 })
      .then((r) => { if (alive) setThumb(r.uri); })
      .catch(() => {});
    return () => { alive = false; };
  }, [url]);
  return (
    <View style={StyleSheet.absoluteFill}>
      {thumb ? <Image source={{ uri: thumb }} style={StyleSheet.absoluteFill} resizeMode="cover" /> : <View style={[StyleSheet.absoluteFill, { backgroundColor: '#000' }]} />}
      {!hidePlay && (
        <View style={st.playWrap}>
          <View style={st.playBtn}><Ionicons name="play" size={22} color="#fff" /></View>
        </View>
      )}
    </View>
  );
}

// 内蔵ビューア（画像は原寸フィット、動画は再生）
function MediaViewer({ item, onClose }: { item: MediaGridItem; onClose: () => void }) {
  return (
    <Modal visible animationType="fade" transparent onRequestClose={onClose}>
      <View style={st.viewer}>
        {item.kind === 'video' ? <ViewerVideo url={item.url} /> : (
          <Image source={{ uri: item.url }} style={StyleSheet.absoluteFill} resizeMode="contain" />
        )}
        <Pressable style={st.viewerClose} onPress={onClose} hitSlop={12}>
          <Ionicons name="close" size={28} color="#fff" />
        </Pressable>
      </View>
    </Modal>
  );
}

function ViewerVideo({ url }: { url: string }) {
  const player = useVideoPlayer(url, (p) => { p.loop = false; p.play(); });
  return <VideoView player={player} style={StyleSheet.absoluteFill} contentFit="contain" allowsFullscreen nativeControls />;
}

const st = StyleSheet.create({
  grid: { borderRadius: 12, overflow: 'hidden' },
  tile: { borderRadius: 8, overflow: 'hidden', backgroundColor: '#2a2823' },
  more: { ...StyleSheet.absoluteFillObject, backgroundColor: 'rgba(0,0,0,0.55)', alignItems: 'center', justifyContent: 'center' },
  moreText: { color: '#fff', fontSize: 20, fontWeight: '600' },
  playWrap: { ...StyleSheet.absoluteFillObject, alignItems: 'center', justifyContent: 'center' },
  playBtn: { backgroundColor: 'rgba(0,0,0,0.55)', borderRadius: 24, padding: 10 },
  viewer: { flex: 1, backgroundColor: '#000' },
  viewerClose: { position: 'absolute', top: 44, right: 16, backgroundColor: 'rgba(0,0,0,0.5)', borderRadius: 20, padding: 6 },
});

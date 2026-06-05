import { StatusBar } from 'expo-status-bar';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import * as SecureStore from 'expo-secure-store';
import { Ionicons } from '@expo/vector-icons';
import * as ImagePicker from 'expo-image-picker';
import * as DocumentPicker from 'expo-document-picker';
import * as VideoThumbnails from 'expo-video-thumbnails';
import { useVideoPlayer, VideoView } from 'expo-video';
import Svg, { Circle } from 'react-native-svg';
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  ActivityIndicator,
  Alert,
  AppState,
  BackHandler,
  FlatList,
  Image,
  KeyboardAvoidingView,
  Linking,
  Modal,
  NativeModules,
  PermissionsAndroid,
  Platform,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
  type StyleProp,
  type ViewStyle,
} from 'react-native';
import { SafeAreaProvider, SafeAreaView, useSafeAreaInsets } from 'react-native-safe-area-context';
import EventSource from 'react-native-sse';
import { WebView } from 'react-native-webview';

const DEFAULT_API_BASE_URL = 'https://frontend-liard-rho-29.vercel.app';
const API_BASE_URL =
  typeof Constants.expoConfig?.extra?.apiBaseUrl === 'string' &&
  Constants.expoConfig.extra.apiBaseUrl.trim()
    ? Constants.expoConfig.extra.apiBaseUrl.trim().replace(/\/+$/, '')
    : DEFAULT_API_BASE_URL;
const LEGACY_BASE_URL = 'https://frontend-mikis-projects-86652663.vercel.app';
const LEGACY_VERCEL_HOST_PATTERN = /^https?:\/\/frontend-[^.]*mikis-projects-86652663\.vercel\.app/i;
const KNOWN_ARTIFACT_URLS: Record<string, string> = {
  'salonboard-styleup': 'https://salonboard-styleup-done.vercel.app',
  kittoku: 'https://kittoku.vercel.app',
};
const TOKEN_KEY = 'done_mobile_access_token';
const PROJECT_KEY = 'done_mobile_project_id';
const PUSH_KEY = 'done_mobile_push_enabled';
const EAS_PROJECT_ID = 'db295575-26c1-4088-99aa-4887eb27e2e2';
const DanSmsForwarder = NativeModules.DanSmsForwarder as
  | {
      configure(apiBaseUrl: string, deviceToken: string): Promise<boolean>;
      disable(): Promise<boolean>;
      isEnabled(): Promise<boolean>;
    }
  | undefined;

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldPlaySound: true,
    shouldSetBadge: true,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

type UserResponse = {
  id: string;
  email: string;
  display_name: string;
};

// One step in an AI turn's inline timeline (mirrors the web chat's ai_context.blocks).
type TurnBlock =
  | { type: 'text'; text?: string }
  | { type: 'tool'; name?: string; label?: string; detail?: string }
  | { type: 'reasoning'; text?: string }
  | { type: 'error'; text?: string };

// Server-side live-run reconstruction (mirrors the web chat). The live timeline
// is rebuilt from /current-run + /execution-events rather than only from the
// SSE stream, so it SURVIVES navigating away and back (and SSE drops) — the
// in-memory-only approach loses the timeline the moment the stream is torn down.
type ExecutionEvent = {
  id: string;
  run_id?: string | null;
  turn_id?: string | null;
  event_type: 'tool_use' | 'reasoning' | 'phase' | 'error' | 'text' | 'done' | string;
  tool_name?: string | null;
  tool_label?: string | null;
  content?: string | null;
  metadata?: Record<string, unknown> | null;
  seq?: number | null;
  created_at: string;
};

type AgentRun = {
  id: string;
  project_id: string;
  state: 'running' | 'paused' | 'completed' | 'failed' | 'interrupted' | string;
  created_at: string;
};

function eventToStep(event: ExecutionEvent): TurnBlock {
  if (event.event_type === 'tool_use') {
    return { type: 'tool', label: event.tool_label || event.tool_name || 'ツール実行' };
  }
  if (event.event_type === 'error') {
    return { type: 'error', text: event.content || 'エラー' };
  }
  return { type: 'text', text: event.content || event.event_type };
}

type MessageResponse = {
  id: string;
  room_id?: string;
  sender_name: string;
  sender_type: 'human' | 'ai' | string;
  content: string;
  created_at: string;
  ai_context?: {
    blocks?: TurnBlock[];
    turn_id?: string;
  } | null;
};

type ProjectResponse = {
  id: string;
  title: string;
  description?: string | null;
  status?: string;
  room_id?: string | null;
  summary?: string | null;
  icon?: string | null;
  unread_count?: number;
  last_message_at?: string | null;
  last_message_preview?: string | null;
  pinned_at?: string | null;
  updated_at?: string | null;
  created_at: string;
};

type ProjectListResponse = {
  projects: ProjectResponse[];
};

type MessagesListResponse = {
  messages: MessageResponse[];
};

type ChatArtifactResponse = {
  id: string;
  slug: string;
  label?: string | null;
  preview_url?: string | null;
  share_url?: string | null;
  draft_url?: string | null;
  production_url?: string | null;
  custom_domain?: string | null;
  artifact_type?: string | null;
};

type AuthState =
  | { status: 'checking' }
  | { status: 'signed_out' }
  | { status: 'signed_in'; token: string; user: UserResponse };

type StreamEvent =
  | { type: 'user_message'; session_id?: string; created_project_id?: string; message: MessageResponse }
  | { type: 'ai_message'; session_id?: string; created_project_id?: string; message: MessageResponse }
  | { type: 'process'; session_id?: string; created_project_id?: string; step?: { label?: string } }
  | { type: 'done'; session_id?: string; created_project_id?: string }
  | { type: 'error'; session_id?: string; created_project_id?: string; message?: string }
  | { type: string; session_id?: string; created_project_id?: string; [key: string]: unknown };

type ParsedLink = {
  kind: 'link';
  label: string;
  url: string;
};

type ParsedText = {
  kind: 'text';
  value: string;
};

type ParsedMediaContent = {
  images: string[];
  videos: { name: string; url: string }[];
  files: { name: string; url: string }[];
  parts: Array<ParsedText | ParsedLink>;
};

function isMessageResponse(value: unknown): value is MessageResponse {
  if (!value || typeof value !== 'object') return false;
  const message = value as Partial<MessageResponse>;
  return (
    typeof message.id === 'string' &&
    typeof message.content === 'string' &&
    typeof message.created_at === 'string'
  );
}

function upsertMessage(list: MessageResponse[], incoming: MessageResponse) {
  const index = list.findIndex((message) => message.id === incoming.id);
  if (index === -1) return [...list, incoming];
  const next = [...list];
  next[index] = incoming;
  return next;
}

type PendingAttachment = {
  key: string;
  uri: string;
  name: string;
  mime: string;
  kind: 'image' | 'video' | 'file';
  size?: number; // bytes (取得できた場合のみ)
};

// サーバー (app/api/file_routes.py) の MAX_FILE_SIZE と一致させること。
const MAX_UPLOAD_BYTES = 500 * 1024 * 1024; // 500MB

// Upload one local file to the chat upload endpoint and return its hosted URL.
// React Native FormData takes {uri,name,type}; we must NOT set Content-Type
// ourselves so fetch can add the multipart boundary.
function uploadAttachment(
  att: PendingAttachment,
  token: string,
  onProgress?: (fraction: number) => void,
): Promise<{ kind: PendingAttachment['kind']; name: string; url: string }> {
  // XMLHttpRequest を使うのは upload.onprogress で進捗が取れるため（fetch では不可）。
  // これで LINE 風の円形プログレスを駆動する。
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', `${API_BASE_URL}/api/v1/files/upload`);
    xhr.setRequestHeader('Authorization', `Bearer ${token}`);
    xhr.upload.onprogress = (e) => {
      if (onProgress && e.lengthComputable && e.total > 0) {
        onProgress(e.loaded / e.total);
      }
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try {
          const data = JSON.parse(xhr.responseText) as { url: string };
          onProgress?.(1);
          resolve({ kind: att.kind, name: att.name, url: data.url });
        } catch {
          reject(new Error('Upload response was not valid JSON'));
        }
      } else {
        let detail = '';
        try {
          const body = JSON.parse(xhr.responseText);
          detail = body?.detail?.message || body?.detail || xhr.responseText;
        } catch {
          detail = xhr.responseText;
        }
        reject(new Error(detail || `Upload failed: ${xhr.status}`));
      }
    };
    xhr.onerror = () => reject(new Error('Network error during upload'));
    xhr.ontimeout = () => reject(new Error('Upload timed out'));
    const form = new FormData();
    form.append('file', { uri: att.uri, name: att.name, type: att.mime } as unknown as Blob);
    xhr.send(form);
  });
}

function mediaTag(kind: PendingAttachment['kind'], name: string, url: string): string {
  if (kind === 'image') return `[添付画像: ${url}]`;
  if (kind === 'video') return `[添付動画: ${name} (${url})]`;
  return `[添付ファイル: ${name} (${url})]`;
}

async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {},
  token?: string,
): Promise<T> {
  const response = await fetch(`${API_BASE_URL}/api/v1${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers ?? {}),
    },
  });

  if (!response.ok) {
    let detail = '';
    try {
      const body = await response.json();
      detail = body?.detail?.message || body?.detail || body?.message || JSON.stringify(body);
    } catch {
      detail = await response.text().catch(() => '');
    }
    // Attach the HTTP status so callers can tell a real auth failure (401)
    // apart from a transient network/server error.
    const error = new Error(detail || `Request failed: ${response.status}`) as Error & {
      status?: number;
    };
    error.status = response.status;
    throw error;
  }

  if (response.status === 204) return {} as T;
  return response.json() as Promise<T>;
}

function formatTime(value?: string | null) {
  if (!value) return '';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('ja-JP', {
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function projectTime(project: ProjectResponse) {
  return project.last_message_at || project.updated_at || project.created_at;
}

function normalizeUrl(raw: string) {
  let value = raw.trim().replace(/\s+(?=\/)/g, '');
  value = value.replace(/[)\],.;"'`]+$/, '');

  if (/^https?:\/\/localhost(?::3000)?/i.test(value)) {
    value = value.replace(/^https?:\/\/localhost(?::3000)?/i, API_BASE_URL);
  }

  if (/^https?:\/\/127\.0\.0\.1(?::3000)?/i.test(value)) {
    value = value.replace(/^https?:\/\/127\.0\.0\.1(?::3000)?/i, API_BASE_URL);
  }

  if (value.toLowerCase().startsWith(LEGACY_BASE_URL.toLowerCase())) {
    value = API_BASE_URL + value.slice(LEGACY_BASE_URL.length);
  }
  if (LEGACY_VERCEL_HOST_PATTERN.test(value)) {
    value = value.replace(LEGACY_VERCEL_HOST_PATTERN, API_BASE_URL);
  }

  value = value.replace(
    new RegExp(`^${API_BASE_URL.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}/artifacts/`, 'i'),
    `${API_BASE_URL}/preview/`,
  );
  if (value.startsWith('/artifacts/')) return `${API_BASE_URL}${value.replace('/artifacts/', '/preview/')}`;
  if (value.startsWith('/')) return `${API_BASE_URL}${value}`;

  if (/^[A-Za-z]:[\\/]/.test(value)) {
    const filename = value.replace(/\\/g, '/').split('/').pop();
    return filename ? `${API_BASE_URL}/api/v1/files/${filename}` : value;
  }

  return value;
}

function artifactRouteParts(raw?: string | null) {
  if (!raw) return null;
  try {
    const url = raw.startsWith('http') ? new URL(raw) : new URL(raw, API_BASE_URL);
    const match = url.pathname.match(/^\/(?:artifacts|preview)\/([^/?#]+)(.*)$/);
    if (!match) return null;
    return {
      slug: decodeURIComponent(match[1]),
      rest: `${match[2] || ''}${url.search || ''}${url.hash || ''}`,
    };
  } catch {
    return null;
  }
}

function cleanArtifactUrl(artifact: ChatArtifactResponse) {
  const path = artifact.share_url || artifact.draft_url || artifact.preview_url || `/preview/${artifact.slug}`;
  const route = artifactRouteParts(path);
  const routeSlug = route?.slug || artifact.slug;
  const base =
    artifact.production_url ||
    (artifact.custom_domain ? `https://${artifact.custom_domain}` : null) ||
    KNOWN_ARTIFACT_URLS[routeSlug];

  if (base) {
    try {
      return new URL(route?.rest || '/', base).toString();
    } catch {
      return base;
    }
  }

  return normalizeUrl(path);
}

function parseRichContent(content: string): ParsedMediaContent {
  const images: string[] = [];
  const videos: { name: string; url: string }[] = [];
  const files: { name: string; url: string }[] = [];

  let text = content
    .replace(/<dan-context>[\s\S]*?<\/dan-context>/g, '')
    .replace(/\[添付画像: ([^\]]+)\]/g, (_, raw: string) => {
      images.push(normalizeUrl(raw));
      return '';
    })
    .replace(/\[添付動画: (.+?) \((.+?)\)\](?:\s*※分析に失敗しました)?/g, (_, name: string, url: string) => {
      videos.push({ name, url: normalizeUrl(url) });
      return '';
    })
    .replace(/\[添付ファイル: (.+?) \((.+?)\)\]/g, (_, name: string, url: string) => {
      const normalized = normalizeUrl(url);
      if (/\.(mp4|mov|m4v|webm|avi|mkv)$/i.test(name) || /\.(mp4|mov|m4v|webm|avi|mkv)(?:[?#].*)?$/i.test(normalized)) {
        videos.push({ name, url: normalized });
      } else {
        files.push({ name, url: normalized });
      }
      return '';
    })
    .trim();

  const parts: Array<ParsedText | ParsedLink> = [];
  const markdownLinkPattern = /\[([^\]]+)\]\(([^)]+)\)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = markdownLinkPattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push({ kind: 'text', value: text.slice(lastIndex, match.index) });
    }
    parts.push({ kind: 'link', label: match[1], url: normalizeUrl(match[2]) });
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push({ kind: 'text', value: text.slice(lastIndex) });
  }

  return { images, videos, files, parts };
}

function openUrl(url: string) {
  void Linking.openURL(url).catch(() => {
    Alert.alert('Open failed', url);
  });
}

function isArtifactUrl(url: string) {
  return /\/(?:artifacts|preview)\/[\w-]+/i.test(url);
}

function artifactTitleFromUrl(url: string) {
  const match = url.match(/\/(?:artifacts|preview)\/([\w-]+)/i);
  return match ? match[1].replace(/[-_]/g, ' ') : 'Artifact';
}

// Inline markdown for chat text: **bold**, *italic* / _italic_, `code`.
// Kept intentionally minimal — we render as nested <Text> spans so the
// parent's selection + line-wrap behavior survives. Returns React nodes
// so callers can drop them straight into a <Text>.
const INLINE_MD_TOKEN = /(\*\*[^*\n]+?\*\*|__[^_\n]+?__|`[^`\n]+?`|(?<![*\w])\*[^*\n]+?\*(?!\*)|(?<![_\w])_[^_\n]+?_(?!_))/g;

function renderInlineMarkdown(text: string, keyPrefix: string): ReactNode[] {
  const parts = text.split(INLINE_MD_TOKEN);
  return parts.filter(Boolean).map((part, idx) => {
    const key = `${keyPrefix}-${idx}`;
    if ((part.startsWith('**') && part.endsWith('**')) || (part.startsWith('__') && part.endsWith('__'))) {
      return (
        <Text key={key} style={styles.mdBold}>
          {part.slice(2, -2)}
        </Text>
      );
    }
    if (part.startsWith('`') && part.endsWith('`') && part.length > 2) {
      return (
        <Text key={key} style={styles.mdCode}>
          {part.slice(1, -1)}
        </Text>
      );
    }
    if (
      (part.startsWith('*') && part.endsWith('*') && !part.startsWith('**') && part.length > 2) ||
      (part.startsWith('_') && part.endsWith('_') && !part.startsWith('__') && part.length > 2)
    ) {
      return (
        <Text key={key} style={styles.mdItalic}>
          {part.slice(1, -1)}
        </Text>
      );
    }
    return <Fragment key={key}>{part}</Fragment>;
  });
}

// 動画のサムネ（最初のフレーム）を生成して表示する。Web版の <video> が
// 自動でフレームを見せるのに合わせ、APKでも「何の動画か」が一目で分かるようにする。
// expo-video-thumbnails はローカル/リモート両方の URI に対応。ファイル名は出さない。
function VideoThumb({
  uri,
  style,
  onPress,
  small = false,
  progress,
}: {
  uri: string;
  style?: StyleProp<ViewStyle>;
  onPress?: () => void;
  small?: boolean;
  progress?: number;
}) {
  const [thumb, setThumb] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setThumb(null);
    setFailed(false);
    (async () => {
      try {
        const result = await VideoThumbnails.getThumbnailAsync(uri, { time: 1000, quality: 0.6 });
        if (!cancelled) setThumb(result.uri);
      } catch {
        if (!cancelled) setFailed(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [uri]);

  // アップロード中: 動画は即表示しつつ、円形リングが満ちていく（LINE風）。
  const uploading = typeof progress === 'number' && progress < 1;

  const inner = (
    <View style={[styles.videoThumbWrap, style]}>
      {thumb ? <Image source={{ uri: thumb }} style={StyleSheet.absoluteFill} resizeMode="cover" /> : null}
      {uploading ? (
        <View style={styles.videoCenterOverlay}>
          <CircularProgress size={small ? 28 : 48} stroke={small ? 3 : 4} progress={progress} />
        </View>
      ) : thumb ? (
        // 再生バッジ。添付チップ(small)では小さく半透明にして後ろの動画が見えるようにする。
        <View style={small ? styles.videoPlayBadgeSmall : styles.videoPlayBadge} pointerEvents="none">
          <Ionicons name="play" size={small ? 11 : 18} color={small ? '#f4f0e8' : '#12110f'} />
        </View>
      ) : failed ? (
        <Ionicons name="videocam" size={small ? 18 : 24} color="#d9d2c8" />
      ) : (
        <ActivityIndicator color="#7fd1c7" size="small" />
      )}
    </View>
  );

  return onPress ? <Pressable onPress={onPress}>{inner}</Pressable> : inner;
}

// LINE風アップロード進捗の円形リング（react-native-svg）。progress: 0..1。
function CircularProgress({
  size = 46,
  stroke = 4,
  progress,
}: {
  size?: number;
  stroke?: number;
  progress: number;
}) {
  const p = Math.max(0, Math.min(1, progress));
  const r = (size - stroke) / 2;
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - p);
  const half = size / 2;
  return (
    <Svg width={size} height={size}>
      <Circle cx={half} cy={half} r={r} stroke="rgba(255,255,255,0.28)" strokeWidth={stroke} fill="none" />
      <Circle
        cx={half}
        cy={half}
        r={r}
        stroke="#ffffff"
        strokeWidth={stroke}
        fill="none"
        strokeDasharray={circumference}
        strokeDashoffset={offset}
        strokeLinecap="round"
        transform={`rotate(-90 ${half} ${half})`}
      />
    </Svg>
  );
}

// アプリ内・全画面の動画プレイヤー（expo-video のネイティブプレイヤー）。
// 外部ブラウザを開かず、音だけ問題も解消、ネイティブコントロールで全画面再生できる。
function VideoPlayerModal({ uri, onClose }: { uri: string; onClose: () => void }) {
  const player = useVideoPlayer(uri, (p) => {
    p.loop = false;
    p.play();
  });
  return (
    <Modal visible animationType="fade" statusBarTranslucent onRequestClose={onClose}>
      <View style={styles.videoPlayerBackdrop}>
        <VideoView
          style={styles.videoPlayerView}
          player={player}
          contentFit="contain"
          nativeControls
          allowsFullscreen
        />
        <Pressable style={styles.videoPlayerClose} onPress={onClose} hitSlop={12}>
          <Ionicons name="close" size={28} color="#fff" />
        </Pressable>
      </View>
    </Modal>
  );
}

function RichMessageContent({
  content,
  mine,
  onOpenUrl,
  onPlayVideo,
  videoProgress,
}: {
  content: string;
  mine: boolean;
  onOpenUrl: (url: string) => void;
  onPlayVideo?: (url: string) => void;
  videoProgress?: number;
}) {
  const parsed = useMemo(() => parseRichContent(content), [content]);
  const isUploading = typeof videoProgress === 'number' && videoProgress < 1;

  return (
    <View style={styles.messageContentWrap}>
      {parsed.images.map((url, index) => (
        <Pressable key={`${url}-${index}`} onPress={() => onOpenUrl(url)}>
          <Image resizeMode="contain" source={{ uri: url }} style={styles.messageImage} />
        </Pressable>
      ))}

      {parsed.videos.map((video, index) => (
        <VideoThumb
          key={`${video.url}-${index}`}
          uri={video.url}
          style={styles.messageVideoThumb}
          progress={isUploading ? videoProgress : undefined}
          onPress={
            isUploading ? undefined : () => (onPlayVideo ? onPlayVideo(video.url) : onOpenUrl(video.url))
          }
        />
      ))}

      {parsed.files.map((file, index) => (
        <Pressable
          key={`${file.url}-${index}`}
          onPress={() => onOpenUrl(file.url)}
          style={[styles.mediaCard, mine && styles.myMediaCard]}
        >
          <Text style={[styles.mediaCardTitle, mine && styles.myMessageText]} numberOfLines={1}>
            ファイルを開く
          </Text>
          <Text style={[styles.mediaCardUrl, mine && styles.myMediaCardUrl]} numberOfLines={2}>
            {file.name || file.url}
          </Text>
        </Pressable>
      ))}

      {parsed.parts.length > 0 ? (
        <Text selectable style={[styles.messageText, mine && styles.myMessageText]}>
          {parsed.parts.map((part, index) =>
            part.kind === 'link' ? (
              <Text
                key={`${part.url}-${index}`}
                onPress={() => onOpenUrl(part.url)}
                selectable
                style={[styles.messageLink, mine && styles.myMessageLink]}
              >
                {part.label}
              </Text>
            ) : (
              <Text key={`text-${index}`}>{renderInlineMarkdown(part.value, `md-${index}`)}</Text>
            ),
          )}
        </Text>
      ) : null}
    </View>
  );
}

// A run of tool/reasoning/error steps, collapsed under "N件の作業 を表示" —
// the same inline-timeline treatment the web chat gives ai_context.blocks.
function TurnToolGroup({ items, defaultOpen = false }: { items: TurnBlock[]; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <View style={styles.toolGroup}>
      <Pressable onPress={() => setOpen((o) => !o)} style={styles.toolGroupHeader} hitSlop={6}>
        <Ionicons name={open ? 'chevron-down' : 'chevron-forward'} size={13} color="#a7a19a" />
        <Ionicons name="terminal-outline" size={13} color="#7fd1c7" />
        <Text style={styles.toolGroupLabel}>
          {items.length}件の作業{open ? '' : ' を表示'}
        </Text>
      </Pressable>
      {open ? (
        <View style={styles.toolGroupBody}>
          {items.map((it, i) => {
            const isErr = it.type === 'error';
            const label =
              it.type === 'tool'
                ? it.label || 'ツール実行'
                : it.type === 'error'
                  ? it.text || 'エラー'
                  : it.type === 'reasoning'
                    ? it.text || '思考'
                    : 'ツール実行';
            const detail = it.type === 'tool' ? it.detail || '' : '';
            return (
              <View key={i} style={styles.toolRow}>
                <Ionicons
                  name={isErr ? 'alert-circle' : 'checkmark-circle'}
                  size={13}
                  color={isErr ? '#ff5a3d' : '#6ec98a'}
                  style={styles.toolRowIcon}
                />
                <View style={styles.toolRowMain}>
                  <Text style={[styles.toolRowText, isErr && styles.toolRowErr]}>{label}</Text>
                  {detail && detail !== label ? (
                    <Text style={styles.toolRowDetail} numberOfLines={4}>
                      {detail}
                    </Text>
                  ) : null}
                </View>
              </View>
            );
          })}
        </View>
      ) : null}
    </View>
  );
}

// Render an AI message's full inline timeline (text segments + tool groups),
// matching the PC web chat. Intermediate narration text is dimmed; the last
// text segment is the real answer.
// A short snippet around the matched keyword (match shown highlighted) for the
// search hit-list. Strips attachment/tool markup so the text reads clean.
function renderSearchSnippet(content: string, query: string) {
  const clean = (content || '')
    .replace(/\[(添付[^\]]*|画像生成[^\]]*|TOOL:[^\]]*)\]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  const q = query.trim();
  const idx = q ? clean.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (idx === -1) {
    return (
      <Text style={styles.searchHitText} numberOfLines={2}>
        {clean.slice(0, 140)}
        {clean.length > 140 ? '…' : ''}
      </Text>
    );
  }
  const start = Math.max(0, idx - 40);
  const end = Math.min(clean.length, idx + q.length + 80);
  return (
    <Text style={styles.searchHitText} numberOfLines={2}>
      {start > 0 ? '…' : ''}
      {clean.slice(start, idx)}
      <Text style={styles.searchHitMark}>{clean.slice(idx, idx + q.length)}</Text>
      {clean.slice(idx + q.length, end)}
      {end < clean.length ? '…' : ''}
    </Text>
  );
}

function AiTurnBlocks({
  blocks,
  mine,
  onOpenUrl,
  onPlayVideo,
  defaultOpen = false,
}: {
  blocks: TurnBlock[];
  mine: boolean;
  onOpenUrl: (url: string) => void;
  onPlayVideo?: (url: string) => void;
  defaultOpen?: boolean;
}) {
  const grouped: Array<{ kind: 'text'; text: string } | { kind: 'tools'; items: TurnBlock[] }> = [];
  for (const b of blocks) {
    if (b.type === 'text' || b.type === 'reasoning') {
      const t = (b.text || '').trim();
      if (!t) continue;
      grouped.push({ kind: 'text', text: t });
    } else {
      const last = grouped[grouped.length - 1];
      if (last && last.kind === 'tools') last.items.push(b);
      else grouped.push({ kind: 'tools', items: [b] });
    }
  }
  const lastTextIndex = grouped.reduce((acc, g, i) => (g.kind === 'text' ? i : acc), -1);
  return (
    <View>
      {grouped.map((g, i) =>
        g.kind === 'text' ? (
          <View key={i} style={i !== lastTextIndex ? styles.mutedSegment : undefined}>
            <RichMessageContent content={g.text} mine={mine} onOpenUrl={onOpenUrl} onPlayVideo={onPlayVideo} />
          </View>
        ) : (
          <TurnToolGroup key={i} items={g.items} defaultOpen={defaultOpen} />
        ),
      )}
    </View>
  );
}

async function streamDanMessage(
  token: string,
  content: string,
  roomId: string,
  onEvent: (event: StreamEvent) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const source = new EventSource(`${API_BASE_URL}/api/v1/chat/dan/messages/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({
        content,
        session_id: roomId,
      }),
      pollingInterval: 0,
    });

    // Idle-based timeout: re-armed on every event (incl. keepalive) so a long
    // but actively-streaming turn is never cut off — mirrors the backend's
    // idle-timeout fix. Only a genuinely silent/dead connection trips it, and
    // the chat-screen poll is a further backstop that surfaces the reply even
    // if this ever fires early.
    let timeout: ReturnType<typeof setTimeout>;
    const armTimeout = () => {
      if (timeout) clearTimeout(timeout);
      timeout = setTimeout(() => {
        source.close();
        reject(new Error('DAN response timed out.'));
      }, 1000 * 60 * 10);
    };
    armTimeout();

    source.addEventListener('message', (event) => {
      armTimeout();
      if (!event.data) return;
      let parsed: StreamEvent;
      try {
        parsed = JSON.parse(String(event.data)) as StreamEvent;
      } catch {
        return;
      }

      onEvent(parsed);

      if (parsed.type === 'error') {
        clearTimeout(timeout);
        source.close();
        reject(new Error(typeof parsed.message === 'string' ? parsed.message : 'DAN returned an error.'));
      } else if (parsed.type === 'done') {
        clearTimeout(timeout);
        source.close();
        resolve();
      }
    });

    source.addEventListener('error', () => {
      clearTimeout(timeout);
      source.close();
      reject(new Error('Could not connect to DAN.'));
    });
  });
}

type ActionSheetState = {
  project: ProjectResponse;
  mode: 'menu' | 'confirm-delete';
};

function ProjectActionSheet({
  sheet,
  insetsBottom,
  onClose,
  onPin,
  onRequestDelete,
  onConfirmDelete,
}: {
  sheet: ActionSheetState | null;
  insetsBottom: number;
  onClose: () => void;
  onPin: (project: ProjectResponse) => void;
  onRequestDelete: (project: ProjectResponse) => void;
  onConfirmDelete: (project: ProjectResponse) => void;
}) {
  const visible = sheet !== null;
  // Keep rendering the previous project's content during the slide-out so
  // the labels don't pop to empty as the user dismisses the sheet.
  const lastSheetRef = useRef<ActionSheetState | null>(sheet);
  if (sheet) lastSheetRef.current = sheet;
  const active = sheet ?? lastSheetRef.current;
  if (!active) return null;

  const { project, mode } = active;
  const pinned = !!project.pinned_at;

  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent>
      <View style={styles.sheetRoot}>
        <Pressable style={styles.sheetBackdrop} onPress={onClose} />
        <View style={[styles.sheet, { paddingBottom: Math.max(insetsBottom, 12) + 12 }]}>
          <View style={styles.sheetGrabber} />
          <Text style={styles.sheetHeading} numberOfLines={1}>
            {project.title || 'Untitled'}
          </Text>

          {mode === 'menu' ? (
            <>
              <Pressable
                onPress={() => onPin(project)}
                style={({ pressed }) => [styles.sheetAction, pressed && styles.sheetActionPressed]}
              >
                <Ionicons name={pinned ? 'pin-outline' : 'pin'} size={22} color="#f4f0e8" />
                <Text style={styles.sheetActionText}>
                  {pinned ? 'ピン留めを外す' : 'ピン留めして上部に固定'}
                </Text>
              </Pressable>
              <View style={styles.sheetDivider} />
              <Pressable
                onPress={() => onRequestDelete(project)}
                style={({ pressed }) => [styles.sheetAction, pressed && styles.sheetActionPressed]}
              >
                <Ionicons name="trash-outline" size={22} color="#ff5a3d" />
                <Text style={[styles.sheetActionText, styles.sheetActionTextDanger]}>削除</Text>
              </Pressable>
            </>
          ) : (
            <>
              <Text style={styles.sheetConfirmBody}>
                このチャットを削除します。{'\n'}この操作は取り消せません。
              </Text>
              <Pressable
                onPress={() => onConfirmDelete(project)}
                style={({ pressed }) => [styles.sheetPrimaryDanger, pressed && styles.buttonPressed]}
              >
                <Ionicons name="trash" size={18} color="#fff" />
                <Text style={styles.sheetPrimaryDangerText}>削除する</Text>
              </Pressable>
            </>
          )}

          <Pressable
            onPress={onClose}
            style={({ pressed }) => [styles.sheetCancel, pressed && styles.sheetActionPressed]}
          >
            <Text style={styles.sheetCancelText}>キャンセル</Text>
          </Pressable>
        </View>
      </View>
    </Modal>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <AppMain />
    </SafeAreaProvider>
  );
}

function AppMain() {
  const insets = useSafeAreaInsets();
  const [auth, setAuth] = useState<AuthState>({ status: 'checking' });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loginBusy, setLoginBusy] = useState(false);
  const [messages, setMessages] = useState<MessageResponse[]>([]);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [currentProject, setCurrentProject] = useState<ProjectResponse | null>(null);
  const [draft, setDraft] = useState('');
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [attachSheetOpen, setAttachSheetOpen] = useState(false);
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [sending, setSending] = useState(false);
  // Which project the in-flight stream belongs to. Lets the user navigate away
  // to other chats while Dan is still working, and only renders the live
  // timeline / activity in the chat that is actually streaming. null when idle.
  const [streamingProjectId, setStreamingProjectId] = useState<string | null>(null);
  const [activity, setActivity] = useState('');
  // 添付アップロード中フラグ。大きい動画は数十秒かかるので、この間も必ずライブ表示
  // （「アップロード中...」スピナー）を出して「固まった/失敗した」と誤解させない。
  // アプリ内で再生中の動画URL（expo-video のネイティブプレイヤーで全画面再生）。
  const [playingVideo, setPlayingVideo] = useState<string | null>(null);
  // アップロード中の楽観メッセージと進捗（0..1）。動画の上に円形リングで表示する。
  const [uploadProgress, setUploadProgress] = useState<{ id: string; value: number } | null>(null);
  // Live in-progress turn, reconstructed FROM THE SERVER (current-run +
  // execution-events) so it survives navigating away/back and SSE drops — like
  // the web chat. The SSE stream only triggers an immediate refetch for low
  // latency; the rendered timeline always comes from these two values.
  const [currentRun, setCurrentRun] = useState<AgentRun | null>(null);
  const [runEvents, setRunEvents] = useState<ExecutionEvent[]>([]);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [screen, setScreen] = useState<'projects' | 'chat' | 'artifact' | 'settings'>('projects');
  const [artifacts, setArtifacts] = useState<ChatArtifactResponse[]>([]);
  const [loadingArtifacts, setLoadingArtifacts] = useState(false);
  const [artifactView, setArtifactView] = useState<{ title: string; url: string } | null>(null);
  const [notificationStatus, setNotificationStatus] = useState('Off');
  const [smsForwardingStatus, setSmsForwardingStatus] = useState('Off');
  // In-chat keyword search (find past messages across full history).
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<MessageResponse[] | null>(null);
  const [searchLoading, setSearchLoading] = useState(false);
  const [highlightId, setHighlightId] = useState<string | null>(null);
  const [pendingJumpId, setPendingJumpId] = useState<string | null>(null);
  // Long-press action sheet for a chat list item. `mode` lets the same
  // sheet host both the primary menu and the secondary "really delete?"
  // confirm without spawning a second modal.
  const [actionSheet, setActionSheet] = useState<{
    project: ProjectResponse;
    mode: 'menu' | 'confirm-delete';
  } | null>(null);
  const listRef = useRef<FlatList<MessageResponse>>(null);
  // Live-tracking ref for the notification listener (which we don't want to
  // re-subscribe on every project switch).
  const currentProjectIdRef = useRef<string | null>(null);
  useEffect(() => {
    currentProjectIdRef.current = currentProjectId;
  }, [currentProjectId]);
  // Tracks which screen is showing, so background→foreground logic can tell
  // "user is actually viewing this chat" from "user is on the chat list".
  const screenRef = useRef<'projects' | 'chat' | 'artifact' | 'settings'>('projects');
  useEffect(() => {
    screenRef.current = screen;
  }, [screen]);
  // When the app is cold-started by tapping a push, the project id to open is
  // captured here BEFORE loadInitialData runs. loadInitialData honours it and
  // jumps straight to that chat instead of resetting to the projects list —
  // otherwise the two race and the "back to projects" reset wins, leaving the
  // tapped chat unopened.
  const pendingLaunchProjectRef = useRef<string | null>(null);
  // Last message id we've already marked read in the open chat — so the chat
  // poll only POSTs /read when something new actually arrives, not every tick.
  const lastSyncedMsgIdRef = useRef<string | null>(null);

  const token = auth.status === 'signed_in' ? auth.token : undefined;
  const user = auth.status === 'signed_in' ? auth.user : undefined;

  useEffect(() => {
    if (!token || Platform.OS !== 'android' || !DanSmsForwarder) {
      setSmsForwardingStatus('Off');
      return;
    }
    void Promise.all([
      apiRequest<{ enabled: boolean }>('/otp/apk/status', {}, token),
      DanSmsForwarder.isEnabled(),
    ])
      .then(([server, localEnabled]) => {
        setSmsForwardingStatus(server.enabled && localEnabled ? 'On' : 'Off');
      })
      .catch(() => setSmsForwardingStatus('Off'));
  }, [token]);

  const newestMessages = useMemo(
    () =>
      [...messages].sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    [messages],
  );

  // Live in-progress turn for the OPEN chat, rebuilt from the server poll. Shows
  // whenever this chat's run is "running" — independent of the SSE stream — so
  // it persists across navigating away and back, and across SSE drops.
  const liveRunActive =
    !!currentRun &&
    currentRun.state === 'running' &&
    currentRun.project_id === currentProject?.id;
  const liveStepBlocks = useMemo<TurnBlock[]>(() => {
    if (!liveRunActive || !currentRun) return [];
    return runEvents
      .filter(
        (e) => e.run_id === currentRun.id && e.event_type !== 'done' && e.event_type !== 'phase',
      )
      .sort(
        (a, b) =>
          (a.seq ?? 0) - (b.seq ?? 0) ||
          new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
      )
      .map(eventToStep);
  }, [liveRunActive, currentRun, runEvents]);
  // Show the live bubble when the server says this chat's run is active, OR
  // (for instant feedback) right after sending here before the first poll lands.
  // The instant-feedback part stops as soon as the run is known to be finished,
  // so the bubble doesn't linger next to the final answer.
  const showLiveTurn =
    liveRunActive ||
    (sending &&
      !uploadProgress &&
      streamingProjectId === currentProject?.id &&
      (!currentRun || currentRun.state === 'running'));

  const unreadTotal = useMemo(
    () =>
      projects.reduce((total, project) => {
        // The chat you're currently viewing is read by definition — a reply that
        // arrives while you're looking at it must not light up the badge.
        if (screen === 'chat' && project.id === currentProject?.id) return total;
        return total + (project.unread_count || 0);
      }, 0),
    [projects, screen, currentProject?.id],
  );

  const headerTitle = currentProject?.title || 'DAN';

  const markProjectReadLocally = useCallback((projectId: string) => {
    setProjects((current) =>
      current.map((project) =>
        project.id === projectId ? { ...project, unread_count: 0 } : project,
      ),
    );
  }, []);

  // Clear any OS-tray push notifications that belong to this project so the
  // app-icon badge (which on Android reflects tray entries) drops as soon as
  // the user reads the room — without having to tap the push in the
  // notification center.
  const dismissNotificationsForProject = useCallback(async (projectId: string) => {
    try {
      const presented = await Notifications.getPresentedNotificationsAsync();
      for (const n of presented) {
        const url = n.request.content.data?.url;
        if (typeof url === 'string' && url.includes(`/chat/${projectId}`)) {
          await Notifications.dismissNotificationAsync(n.request.identifier);
        }
      }
    } catch {
      // best-effort; ignore
    }
  }, []);

  const syncNotificationBadge = useCallback(async (count: number) => {
    await Notifications.setBadgeCountAsync(count).catch(() => null);
    if (count === 0) {
      await Notifications.dismissAllNotificationsAsync().catch(() => null);
    }
  }, []);

  const refreshProjects = useCallback(async (activeToken: string) => {
    setLoadingProjects(true);
    try {
      const data = await apiRequest<ProjectListResponse>('/projects', {}, activeToken);
      setProjects(data.projects ?? []);
      return data.projects ?? [];
    } finally {
      setLoadingProjects(false);
    }
  }, []);

  const refreshArtifacts = useCallback(async (activeToken: string, projectId: string) => {
    setLoadingArtifacts(true);
    try {
      const data = await apiRequest<ChatArtifactResponse[]>(
        `/chat-artifact?project_id=${encodeURIComponent(projectId)}`,
        {},
        activeToken,
      );
      setArtifacts(data ?? []);
      return data ?? [];
    } catch {
      setArtifacts([]);
      return [];
    } finally {
      setLoadingArtifacts(false);
    }
  }, []);

  // Pull the live in-progress run + its steps from the server for a project.
  // Mirrors the web chat's current-run / execution-events polling so the live
  // timeline can be reconstructed even after navigating away (SSE-independent).
  const pollRun = useCallback(async (activeToken: string, projectId: string) => {
    try {
      const run = await apiRequest<AgentRun>(`/projects/${projectId}/current-run`, {}, activeToken);
      setCurrentRun(run);
      if (run && run.state === 'running') {
        const events = await apiRequest<ExecutionEvent[]>(
          `/projects/${projectId}/execution-events?limit=200`,
          {},
          activeToken,
        ).catch(() => [] as ExecutionEvent[]);
        setRunEvents(events ?? []);
      } else {
        setRunEvents([]);
      }
    } catch {
      // 404 = no run for this project (the common idle case).
      setCurrentRun(null);
      setRunEvents([]);
    }
  }, []);

  const loadProjectMessages = useCallback(
    async (activeToken: string, projectId: string) => {
      setLoadingMessages(true);
      try {
        const project = await apiRequest<ProjectResponse>(`/projects/${projectId}`, {}, activeToken);
        setCurrentProject(project);
        setCurrentProjectId(project.id);
        await SecureStore.setItemAsync(PROJECT_KEY, project.id);
        void refreshArtifacts(activeToken, project.id);

        if (!project.room_id) {
          setMessages([]);
          return project;
        }

        const data = await apiRequest<MessagesListResponse>(
          `/chat/rooms/${project.room_id}/messages?limit=120`,
          {},
          activeToken,
        );
        setMessages(data.messages ?? []);
        await apiRequest(`/chat/rooms/${project.room_id}/read`, { method: 'POST' }, activeToken).catch(() => null);
        setCurrentProject((current) =>
          current?.id === project.id ? { ...current, unread_count: 0 } : current,
        );
        markProjectReadLocally(project.id);
        void dismissNotificationsForProject(project.id);
        return project;
      } catch (error) {
        Alert.alert('Load failed', String((error as Error).message));
        return null;
      } finally {
        setLoadingMessages(false);
      }
    },
    [dismissNotificationsForProject, markProjectReadLocally, refreshArtifacts],
  );

  const runSearch = useCallback(
    async (q: string) => {
      const roomId = currentProject?.room_id;
      const query = q.trim();
      if (!roomId || !query) {
        setSearchResults(null);
        return;
      }
      setSearchLoading(true);
      try {
        const data = await apiRequest<MessagesListResponse>(
          `/chat/rooms/${roomId}/messages/search?q=${encodeURIComponent(query)}&limit=50`,
          {},
          token,
        );
        setSearchResults(data.messages ?? []);
      } catch (error) {
        Alert.alert('検索失敗', String((error as Error).message));
        setSearchResults([]);
      } finally {
        setSearchLoading(false);
      }
    },
    [currentProject?.room_id, token],
  );

  // Jump from a search hit to that message in the transcript. If it's older than
  // the loaded 120-message window, pull a context window and merge it in first;
  // the pendingJump effect scrolls to it once it appears.
  const jumpToMessage = useCallback(
    async (msg: MessageResponse) => {
      setSearchOpen(false);
      setHighlightId(msg.id);
      const loaded = messages.some((m) => m.id === msg.id);
      if (loaded) {
        setPendingJumpId(msg.id);
        return;
      }
      const roomId = currentProject?.room_id;
      if (!roomId) return;
      try {
        const before = new Date(new Date(msg.created_at).getTime() + 2000).toISOString();
        const ctx = await apiRequest<MessagesListResponse>(
          `/chat/rooms/${roomId}/messages?limit=100&before=${encodeURIComponent(before)}`,
          {},
          token,
        );
        setMessages((prev) => {
          const map = new Map(prev.map((m) => [m.id, m]));
          for (const m of ctx.messages ?? []) map.set(m.id, m);
          return [...map.values()];
        });
        setPendingJumpId(msg.id);
      } catch {
        Alert.alert('移動できません', 'メッセージへ移動できませんでした');
      }
    },
    [messages, currentProject?.room_id, token],
  );

  // Complete a pending jump once the target message is in the list.
  useEffect(() => {
    if (!pendingJumpId) return;
    const target = newestMessages.find((m) => m.id === pendingJumpId);
    if (!target) return;
    const t = setTimeout(() => {
      try {
        listRef.current?.scrollToItem({ item: target, animated: true, viewPosition: 0.5 });
      } catch {
        // ignore — onScrollToIndexFailed handles off-screen targets
      }
      setPendingJumpId(null);
    }, 180);
    return () => clearTimeout(t);
  }, [pendingJumpId, newestMessages]);

  // Clear the hit highlight a moment after a jump.
  useEffect(() => {
    if (!highlightId) return;
    const t = setTimeout(() => setHighlightId(null), 2200);
    return () => clearTimeout(t);
  }, [highlightId]);

  const loadInitialData = useCallback(
    async (activeToken: string, navigateHome = true) => {
      await refreshProjects(activeToken);
      // Cold-started from a notification tap: open that chat directly instead
      // of landing on (and resetting to) the projects list.
      const launchTarget = pendingLaunchProjectRef.current;
      if (launchTarget) {
        pendingLaunchProjectRef.current = null;
        setScreen('chat');
        setDrawerOpen(false);
        await loadProjectMessages(activeToken, launchTarget);
        return;
      }
      if (!navigateHome) {
        // Cold-start restore: do NOT force the projects list. If this launch was
        // a notification tap whose response wasn't ready yet when restoreSession
        // checked, the notification effect (getLastNotificationResponseAsync)
        // opens that chat a moment later — forcing 'projects' here would race it
        // and bounce the user straight back out of the chat that just opened.
        return;
      }
      setCurrentProject(null);
      setCurrentProjectId(null);
      setMessages([]);
      setArtifacts([]);
      setArtifactView(null);
      setScreen('projects');
    },
    [refreshProjects, loadProjectMessages],
  );

  const openProjectFromNotificationUrl = useCallback(
    async (url?: unknown) => {
      if (!token || typeof url !== 'string') return;
      await syncNotificationBadge(0);
      const match = url.match(/\/chat\/([^/?#]+)/);
      const projectId = match?.[1];
      if (!projectId) {
        await refreshProjects(token).catch(() => null);
        setScreen('projects');
        return;
      }
      setScreen('chat');
      setDrawerOpen(false);
      await loadProjectMessages(token, projectId);
      await refreshProjects(token).catch(() => null);
    },
    [loadProjectMessages, refreshProjects, syncNotificationBadge, token],
  );

  useEffect(() => {
    void syncNotificationBadge(unreadTotal);
  }, [syncNotificationBadge, unreadTotal]);

  useEffect(() => {
    if (!token) return;
    const subscription = AppState.addEventListener('change', (state) => {
      if (state === 'active') {
        refreshProjects(token).catch(() => null);
        // Reload the open chat too: a reply that finished while the app was
        // backgrounded never streams in (the SSE connection is suspended).
        // Only do this when the user is *actually viewing* that chat — doing
        // it whenever a currentProjectId exists would silently mark the
        // last-opened room as read just by foregrounding the app (the chat
        // list would never keep an unread badge long enough to see).
        if (screenRef.current === 'chat' && currentProjectIdRef.current) {
          loadProjectMessages(token, currentProjectIdRef.current).catch(() => null);
        }
      }
    });
    return () => subscription.remove();
  }, [refreshProjects, loadProjectMessages, token]);

  // Keep the unread badge honest even when the room is read on another device
  // (e.g. the PC). Without this poll the local projects cache — and therefore
  // the header badge and OS app-icon badge — could stay > 0 until the next
  // foreground/notification refresh. 20s is frequent enough to feel live but
  // light on the backend.
  useEffect(() => {
    if (!token) return;
    const id = setInterval(() => {
      if (AppState.currentState === 'active') {
        refreshProjects(token).catch(() => null);
      }
    }, 20000);
    return () => clearInterval(id);
  }, [refreshProjects, token]);

  // Poll the OPEN chat for new messages while the user is sitting in it. Without
  // this, a message that arrives after the immediate stream — Dan's scheduled
  // auto follow-up, or a reply from another device — would not show until the
  // user backgrounds/foregrounds, taps a push, or pulls to refresh. Mirrors the
  // PC web chat, which polls its messages every few seconds while idle. Off
  // while backgrounded, and off for the chat that is actively streaming (its
  // SSE stream drives updates — but a DIFFERENT chat viewed during a background
  // stream still polls, so its messages stay fresh).
  useEffect(() => {
    if (!token || screen !== 'chat') return;
    const roomId = currentProject?.room_id;
    if (!roomId) return;
    if (sending && streamingProjectId === currentProject?.id) return;
    const projectId = currentProject?.id;
    const id = setInterval(() => {
      if (AppState.currentState !== 'active') return;
      apiRequest<MessagesListResponse>(`/chat/rooms/${roomId}/messages?limit=120`, {}, token)
        .then((data) => {
          if (!data?.messages) return;
          setMessages(data.messages);
          // The chat is open ⇒ a reply that just arrived is already read. Mark it
          // read on the server (only when the newest message actually changed) so
          // leaving the chat doesn't leave a phantom unread badge behind.
          const last = data.messages[data.messages.length - 1];
          if (last && last.id !== lastSyncedMsgIdRef.current) {
            lastSyncedMsgIdRef.current = last.id;
            apiRequest(`/chat/rooms/${roomId}/read`, { method: 'POST' }, token).catch(() => null);
            if (projectId) markProjectReadLocally(projectId);
          }
        })
        .catch(() => null);
    }, 4000);
    return () => clearInterval(id);
  }, [token, screen, sending, streamingProjectId, currentProject?.room_id, currentProject?.id, markProjectReadLocally]);

  // Poll the live run for the OPEN chat so the in-progress timeline shows even
  // when the SSE stream isn't this device's (e.g. we navigated back into a chat
  // Dan is still working on, or another device sent the message). Mirrors the
  // web chat's 2s current-run / execution-events polling. The SSE handler also
  // calls pollRun directly for low latency while actively streaming here.
  useEffect(() => {
    if (!token || screen !== 'chat') return;
    const projectId = currentProject?.id;
    if (!projectId) return;
    let cancelled = false;
    const tick = () => {
      if (AppState.currentState === 'active' && !cancelled) {
        void pollRun(token, projectId);
      }
    };
    tick();
    const id = setInterval(tick, 2500);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [token, screen, currentProject?.id, pollRun]);

  // Reset the live run view immediately when switching chats so a previous
  // chat's timeline never flashes in the newly-opened one before the first poll.
  useEffect(() => {
    setCurrentRun(null);
    setRunEvents([]);
    lastSyncedMsgIdRef.current = null;
  }, [currentProject?.id]);

  useEffect(() => {
    if (!token) return;

    const received = Notifications.addNotificationReceivedListener((event) => {
      refreshProjects(token).catch(() => null);
      // If the push is for the room the user is currently viewing, reload its
      // messages so the new reply appears without a manual refresh. The ref
      // gives us the latest project id without making this effect re-subscribe
      // on every project switch.
      const url = event.request.content.data?.url;
      if (typeof url === 'string') {
        const match = url.match(/\/chat\/([^/?#]+)/);
        const pid = match?.[1];
        if (pid && pid === currentProjectIdRef.current) {
          loadProjectMessages(token, pid).catch(() => null);
        }
      }
    });
    const response = Notifications.addNotificationResponseReceivedListener((event) => {
      void openProjectFromNotificationUrl(event.notification.request.content.data?.url);
    });

    Notifications.getLastNotificationResponseAsync()
      .then((event) => {
        if (event) {
          void openProjectFromNotificationUrl(event.notification.request.content.data?.url);
        }
      })
      .catch(() => null);

    return () => {
      received.remove();
      response.remove();
    };
  }, [loadProjectMessages, openProjectFromNotificationUrl, refreshProjects, token]);

  // Restore the notification toggle state on launch. `notificationStatus` is
  // plain component state, so without this it always resets to 'Off'. The
  // source of truth is "we saved a subscription" AND "the OS still grants
  // permission" (the user may have revoked it from system settings).
  useEffect(() => {
    if (!token) return;
    let alive = true;
    (async () => {
      try {
        const enabled = await SecureStore.getItemAsync(PUSH_KEY);
        if (enabled !== '1') return;
        const perm = await Notifications.getPermissionsAsync();
        if (!alive) return;
        if (perm.status === 'granted') {
          setNotificationStatus('On');
        } else {
          setNotificationStatus('Off');
          await SecureStore.setItemAsync(PUSH_KEY, '0').catch(() => null);
        }
      } catch {
        // best-effort: leave the default 'Off'
      }
    })();
    return () => {
      alive = false;
    };
  }, [token]);

  useEffect(() => {
    let alive = true;
    async function restoreSession() {
      const storedToken = await SecureStore.getItemAsync(TOKEN_KEY);
      if (!storedToken) {
        if (alive) setAuth({ status: 'signed_out' });
        return;
      }

      // If this launch was triggered by tapping a push, remember which chat to
      // open. loadInitialData (below) reads this and jumps to that chat instead
      // of resetting to the projects list. Captured up-front so it can't lose a
      // race with the projects reset.
      try {
        const launch = await Notifications.getLastNotificationResponseAsync();
        const launchUrl = launch?.notification?.request?.content?.data?.url;
        const launchMatch =
          typeof launchUrl === 'string' ? launchUrl.match(/\/chat\/([^/?#]+)/) : null;
        if (launchMatch?.[1]) pendingLaunchProjectRef.current = launchMatch[1];
      } catch {
        // best-effort — fall back to the projects list
      }

      // Cold-starting from a notification tap, the network is often not ready
      // for a moment. Only a real 401 means the token is invalid — for any
      // transient failure we retry and, crucially, never discard the saved
      // token (discarding it was what logged the user out).
      for (let attempt = 0; attempt < 4 && alive; attempt++) {
        try {
          const restoredUser = await apiRequest<UserResponse>('/chat/me', {}, storedToken);
          if (!alive) return;
          setAuth({ status: 'signed_in', token: storedToken, user: restoredUser });
          // navigateHome=false: don't force the projects list on cold start, so a
          // notification-tap launch isn't bounced out of its chat (see loadInitialData).
          await loadInitialData(storedToken, false);
          return;
        } catch (error) {
          if ((error as { status?: number }).status === 401) {
            await SecureStore.deleteItemAsync(TOKEN_KEY);
            await SecureStore.deleteItemAsync(PROJECT_KEY);
            if (alive) setAuth({ status: 'signed_out' });
            return;
          }
          await new Promise((resolve) => setTimeout(resolve, 1500));
        }
      }
      // Retries exhausted but not a 401: keep the token so the next launch
      // restores the session; just fall back to the signed-out screen.
      if (alive) setAuth({ status: 'signed_out' });
    }
    restoreSession();
    return () => {
      alive = false;
    };
  }, [loadInitialData]);

  useEffect(() => {
    const subscription = BackHandler.addEventListener('hardwareBackPress', () => {
      if (screen === 'artifact') {
        setScreen(currentProject ? 'chat' : 'projects');
        return true;
      }
      if (screen !== 'chat') return false;
      setScreen('projects');
      setDrawerOpen(false);
      return true;
    });
    return () => subscription.remove();
  }, [currentProject, screen]);

  async function handleLogin() {
    const cleanEmail = email.trim();
    if (!cleanEmail || !password) {
      Alert.alert('Missing input', 'Email and password are required.');
      return;
    }

    setLoginBusy(true);
    try {
      const result = await apiRequest<{ access_token: string }>('/chat/login', {
        method: 'POST',
        body: JSON.stringify({ email: cleanEmail, password }),
      });
      await SecureStore.setItemAsync(TOKEN_KEY, result.access_token);
      const signedInUser = await apiRequest<UserResponse>('/chat/me', {}, result.access_token);
      setAuth({ status: 'signed_in', token: result.access_token, user: signedInUser });
      setPassword('');
      await loadInitialData(result.access_token);
    } catch (error) {
      Alert.alert('Login failed', String((error as Error).message));
    } finally {
      setLoginBusy(false);
    }
  }

  async function handleLogout() {
    if (token && Platform.OS === 'android' && DanSmsForwarder) {
      await apiRequest('/otp/apk/register', { method: 'DELETE' }, token).catch(() => null);
      await DanSmsForwarder.disable().catch(() => null);
    }
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    await SecureStore.deleteItemAsync(PROJECT_KEY);
    setMessages([]);
    setProjects([]);
    setCurrentProject(null);
    setCurrentProjectId(null);
    setArtifacts([]);
    setArtifactView(null);
    setAuth({ status: 'signed_out' });
  }

  async function handleSelectProject(projectId: string) {
    // No `sending` guard: a stream in another chat must not block navigation.
    // The stream is scoped to streamingProjectId, so switching chats is safe.
    if (!token) return;
    const project = projects.find((item) => item.id === projectId) ?? null;
    setDrawerOpen(false);
    setMessages([]);
    setCurrentProject(project);
    setCurrentProjectId(projectId);
    setArtifacts([]);
    setArtifactView(null);
    setScreen('chat');
    void loadProjectMessages(token, projectId);
  }

  async function handleNewProject() {
    if (!token) return;
    try {
      const project = await apiRequest<ProjectResponse>(
        '/projects',
        {
          method: 'POST',
          body: JSON.stringify({ title: '新しいプロジェクト' }),
        },
        token,
      );
      setProjects((current) => [project, ...current.filter((item) => item.id !== project.id)]);
      setCurrentProject(project);
      setCurrentProjectId(project.id);
      await SecureStore.setItemAsync(PROJECT_KEY, project.id);
      setMessages([]);
      setScreen('chat');
      setDrawerOpen(false);
    } catch (error) {
      Alert.alert('Could not create project', String((error as Error).message));
    }
  }

  async function handleTogglePin(project: ProjectResponse) {
    if (!token) return;
    try {
      await apiRequest(
        `/projects/${project.id}`,
        { method: 'PATCH', body: JSON.stringify({ pinned: !project.pinned_at }) },
        token,
      );
      await refreshProjects(token).catch(() => null);
    } catch (error) {
      Alert.alert('Pin failed', String((error as Error).message));
    }
  }

  async function handleDeleteProject(project: ProjectResponse) {
    if (!token) return;
    try {
      await apiRequest(`/projects/${project.id}`, { method: 'DELETE' }, token);
      if (project.id === currentProjectId) {
        setCurrentProject(null);
        setCurrentProjectId(null);
        setMessages([]);
        setArtifacts([]);
        await SecureStore.deleteItemAsync(PROJECT_KEY).catch(() => null);
        setScreen('projects');
      }
      await refreshProjects(token).catch(() => null);
    } catch (error) {
      Alert.alert('Delete failed', String((error as Error).message));
    }
  }

  function handleProjectLongPress(project: ProjectResponse) {
    setActionSheet({ project, mode: 'menu' });
  }

  async function handleToggleSmsForwarding() {
    if (!token) return;
    if (Platform.OS !== 'android' || !DanSmsForwarder) {
      Alert.alert('Android APK required', 'SMS OTP forwarding is available in the installed Android APK.');
      return;
    }

    const previous = smsForwardingStatus;
    setSmsForwardingStatus('Updating...');
    try {
      if (previous === 'On') {
        await apiRequest('/otp/apk/register', { method: 'DELETE' }, token);
        await DanSmsForwarder.disable();
        setSmsForwardingStatus('Off');
        return;
      }

      const permission = await PermissionsAndroid.request(
        PermissionsAndroid.PERMISSIONS.RECEIVE_SMS,
        {
          title: 'SMS OTP forwarding',
          message: 'Done uses received SMS messages only to forward one-time authentication codes to your browser session.',
          buttonPositive: 'Allow',
          buttonNegative: 'Cancel',
        },
      );
      if (permission !== PermissionsAndroid.RESULTS.GRANTED) {
        setSmsForwardingStatus('Permission denied');
        return;
      }

      const registration = await apiRequest<{ device_token: string }>(
        '/otp/apk/register',
        {
          method: 'POST',
          body: JSON.stringify({ device_name: Device.modelName || 'Android device' }),
        },
        token,
      );
      await DanSmsForwarder.configure(API_BASE_URL, registration.device_token);
      setSmsForwardingStatus('On');
    } catch (error) {
      setSmsForwardingStatus(previous);
      Alert.alert('SMS forwarding setup failed', String((error as Error).message));
    }
  }

  async function handleToggleNotifications() {
    if (!token) return;
    if (!Device.isDevice) {
      setNotificationStatus('Physical device required');
      return;
    }

    // Currently On -> turn Off by removing the server-side push subscription.
    // (OS-level permission cannot be revoked from inside the app; "Off" here
    // means Dan will no longer push to this device.)
    if (notificationStatus === 'On') {
      const previous = notificationStatus;
      setNotificationStatus('Updating...');
      try {
        const expoToken = await Notifications.getExpoPushTokenAsync({
          projectId: EAS_PROJECT_ID,
        });
        await apiRequest(
          '/push/native/unsubscribe',
          {
            method: 'POST',
            body: JSON.stringify({ token: expoToken.data }),
          },
          token,
        );
        await SecureStore.setItemAsync(PUSH_KEY, '0').catch(() => null);
        setNotificationStatus('Off');
      } catch (error) {
        setNotificationStatus(previous);
        Alert.alert('Could not turn off notifications', String((error as Error).message));
      }
      return;
    }

    // Off -> turn On.
    setNotificationStatus('Updating...');
    try {
      if (Platform.OS === 'android') {
        await Notifications.setNotificationChannelAsync('default', {
          name: 'Done',
          importance: Notifications.AndroidImportance.MAX,
          vibrationPattern: [0, 250, 250, 250],
          lightColor: '#f4f0e8',
        });
      }

      const current = await Notifications.getPermissionsAsync();
      let finalStatus = current.status;
      if (finalStatus !== 'granted') {
        const requested = await Notifications.requestPermissionsAsync();
        finalStatus = requested.status;
      }
      if (finalStatus !== 'granted') {
        setNotificationStatus('Permission denied');
        return;
      }

      const expoToken = await Notifications.getExpoPushTokenAsync({
        projectId: EAS_PROJECT_ID,
      });
      await apiRequest(
        '/push/native/subscribe',
        {
          method: 'POST',
          body: JSON.stringify({ token: expoToken.data }),
        },
        token,
      );
      await SecureStore.setItemAsync(PUSH_KEY, '1').catch(() => null);
      setNotificationStatus('On');
    } catch (error) {
      setNotificationStatus('Failed');
      Alert.alert('Notification setup failed', String((error as Error).message));
    }
  }

  async function pickMedia() {
    setAttachSheetOpen(false);
    try {
      const perm = await ImagePicker.requestMediaLibraryPermissionsAsync();
      if (!perm.granted) {
        Alert.alert('権限が必要です', '設定アプリから写真へのアクセスを許可してください。');
        return;
      }
      const result = await ImagePicker.launchImageLibraryAsync({
        mediaTypes: ['images', 'videos'],
        allowsMultipleSelection: true,
        quality: 0.9,
      });
      if (result.canceled) return;
      const picked: PendingAttachment[] = result.assets.map((a, i) => {
        const isVideo = a.type === 'video';
        const name =
          a.fileName || `${isVideo ? 'video' : 'image'}-${Date.now()}-${i}.${isVideo ? 'mp4' : 'jpg'}`;
        return {
          key: `${a.assetId || a.uri}-${i}-${Date.now()}`,
          uri: a.uri,
          name,
          mime: a.mimeType || (isVideo ? 'video/mp4' : 'image/jpeg'),
          kind: isVideo ? 'video' : 'image',
          size: typeof a.fileSize === 'number' ? a.fileSize : undefined,
        };
      });
      setAttachments((cur) => [...cur, ...picked]);
    } catch (error) {
      Alert.alert('選択に失敗しました', String((error as Error).message));
    }
  }

  async function pickDocument() {
    setAttachSheetOpen(false);
    try {
      const result = await DocumentPicker.getDocumentAsync({
        multiple: true,
        copyToCacheDirectory: true,
      });
      if (result.canceled) return;
      const picked: PendingAttachment[] = result.assets.map((a, i) => {
        const name = a.name || `file-${Date.now()}-${i}`;
        const kind: PendingAttachment['kind'] = /\.(mp4|mov|m4v|webm|avi|mkv)$/i.test(name)
          ? 'video'
          : /\.(png|jpe?g|gif|webp|heic|heif)$/i.test(name)
            ? 'image'
            : 'file';
        return {
          key: `${a.uri}-${i}-${Date.now()}`,
          uri: a.uri,
          name,
          mime: a.mimeType || 'application/octet-stream',
          kind,
          size: typeof a.size === 'number' ? a.size : undefined,
        };
      });
      setAttachments((cur) => [...cur, ...picked]);
    } catch (error) {
      Alert.alert('選択に失敗しました', String((error as Error).message));
    }
  }

  function removeAttachment(key: string) {
    setAttachments((cur) => cur.filter((a) => a.key !== key));
  }

  // チャットのタイトル自動生成（Web版と同条件）。ターン完了後、タイトルが既定
  // （新しいプロジェクト）のままなら suggest-title で生成して保存する。
  // 多重発火は guard で防ぎ、既にカスタム名なら何もしない。
  const titleGenGuard = useRef<Set<string>>(new Set());
  const maybeGenerateTitle = useCallback(
    async (projectId: string, roomId: string) => {
      if (!token || titleGenGuard.current.has(projectId)) return;
      const proj =
        projects.find((p) => p.id === projectId) ||
        (currentProjectIdRef.current === projectId ? currentProject ?? undefined : undefined);
      const title = (proj?.title || '').trim();
      if (title && title !== '新しいプロジェクト') return;
      titleGenGuard.current.add(projectId);
      try {
        const res = await apiRequest<{ title: string }>(
          `/projects/suggest-title?room_id=${roomId}`,
          {},
          token,
        );
        const suggested = (res?.title || '').trim();
        if (suggested && suggested !== '新しいプロジェクト') {
          await apiRequest<ProjectResponse>(
            `/projects/${projectId}`,
            { method: 'PATCH', body: JSON.stringify({ title: suggested }) },
            token,
          );
          await refreshProjects(token).catch(() => null);
        }
      } catch {
        // best-effort（失敗時は次のターンで再試行）
      } finally {
        titleGenGuard.current.delete(projectId);
      }
    },
    [token, projects, currentProject, refreshProjects],
  );

  async function handleSend() {
    if (!token || sending) return;
    const content = draft.trim();
    const pending = attachments;
    if (!content && pending.length === 0) return;

    // 送信前にサイズ超過を弾く。ここで return すれば入力欄・添付はそのまま残る
    // ので「押した瞬間に全部消えて理由も分からない」状態にならない。
    const tooBig = pending.filter((a) => typeof a.size === 'number' && a.size > MAX_UPLOAD_BYTES);
    if (tooBig.length > 0) {
      const names = tooBig
        .map((a) => `・${a.name}（${(a.size! / 1024 / 1024).toFixed(0)}MB）`)
        .join('\n');
      Alert.alert(
        'ファイルが大きすぎます',
        `次のファイルは上限 ${MAX_UPLOAD_BYTES / 1024 / 1024}MB を超えています。外して送るか、短く撮り直してください:\n\n${names}`,
      );
      return;
    }

    let project = currentProject;
    if (!project) {
      project = await apiRequest<ProjectResponse>(
        '/projects',
        {
          method: 'POST',
          body: JSON.stringify({ title: '新しいプロジェクト' }),
        },
        token,
      );
      setCurrentProject(project);
      setCurrentProjectId(project.id);
      await SecureStore.setItemAsync(PROJECT_KEY, project.id);
      setScreen('chat');
      setProjects((current) => [project!, ...current.filter((item) => item.id !== project!.id)]);
    }

    if (!project.room_id) {
      Alert.alert('Send failed', 'This project does not have a room yet.');
      return;
    }

    setDraft('');
    setAttachments([]);
    setSending(true);
    setStreamingProjectId(project.id);

    // LINE風: 送信した瞬間に動画/画像入りのメッセージを画面に出し、アップロードは
    // その動画の上の円形リングが満ちていく形で進める。完了したらローカルURIを
    // サーバーURLへ差し替えて Dan に送信する。失敗時は楽観メッセージを取り消す。
    const optimisticId = `local-${Date.now()}`;
    const localTags = pending.map((a) => mediaTag(a.kind, a.name, a.uri)).join('\n');
    const localContent = pending.length > 0 ? (content ? `${localTags}\n\n${content}` : localTags) : content;
    const optimistic: MessageResponse = {
      id: optimisticId,
      room_id: project.room_id,
      sender_name: 'You',
      sender_type: 'human',
      content: localContent,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimistic]);

    let finalContent = content;
    if (pending.length > 0) {
      setUploadProgress({ id: optimisticId, value: 0 });
      try {
        const uploaded: { kind: PendingAttachment['kind']; name: string; url: string }[] = [];
        const total = pending.length;
        for (let i = 0; i < total; i++) {
          const cur = pending[i];
          try {
            uploaded.push(
              await uploadAttachment(cur, token, (frac) =>
                setUploadProgress({ id: optimisticId, value: (i + frac) / total }),
              ),
            );
          } catch (e) {
            // どのファイルで失敗したか分かるよう名前を付けて投げ直す
            throw new Error(`「${cur.name}」のアップロードに失敗しました: ${(e as Error).message}`);
          }
        }
        const tags = uploaded.map((u) => mediaTag(u.kind, u.name, u.url)).join('\n');
        finalContent = content ? `${tags}\n\n${content}` : tags;
        // 楽観メッセージの中身をサーバーURLへ差し替え（以後の再生・サーバー整合用）。
        optimistic.content = finalContent;
        setMessages((current) =>
          current.map((m) => (m.id === optimisticId ? { ...m, content: finalContent } : m)),
        );
        setUploadProgress(null);
      } catch (error) {
        setUploadProgress(null);
        setSending(false);
        setStreamingProjectId(null);
        setActivity('');
        setMessages((current) => current.filter((m) => m.id !== optimisticId));
        setDraft(content);
        setAttachments(pending);
        Alert.alert('アップロード失敗', String((error as Error).message));
        return;
      }
    }

    setActivity('Thinking...');

    let selectedProjectId = project.id;
    // Becomes true once the server has acked the message via the stream (echoes
    // it back as user_message, or starts replying / finishes). A fast-path for
    // "definitely saved" — but NOT required: the reconcile also checks the DB.
    let sent = false;
    // Set if the SSE throws. On its own this does NOT mean the send failed — the
    // reconcile verifies against the server before restoring the draft.
    let streamFailure: Error | null = null;

    try {
      await streamDanMessage(token, finalContent, project.room_id, (event) => {
        if (event.created_project_id && event.created_project_id !== selectedProjectId) {
          selectedProjectId = event.created_project_id;
          setStreamingProjectId(event.created_project_id);
          setCurrentProjectId(event.created_project_id);
          SecureStore.setItemAsync(PROJECT_KEY, event.created_project_id).catch(() => null);
        }

        // Is the user currently looking at the chat this stream belongs to? If
        // they navigated to another chat, we keep the stream running (so the
        // turn finishes + the reply is saved to the DB), but we DON'T touch the
        // visible message list — otherwise this chat's reply would leak into the
        // chat they're now viewing. The live timeline itself comes from the
        // server poll (pollRun), so it shows regardless of which chat is open.
        const viewing = currentProjectIdRef.current === selectedProjectId;

        if (event.type === 'process') {
          const step = event.step as { label?: string } | undefined;
          const label = (step?.label || '').trim();
          if (viewing) setActivity(label || 'Thinking...');
          // Refetch the live run immediately for low latency (don't wait for the
          // 2.5s interval). Only when viewing this chat — otherwise the open
          // chat's own poll owns currentRun. The timeline renders from server state.
          if (viewing) void pollRun(token, selectedProjectId);
        } else if (event.type === 'user_message' && isMessageResponse(event.message)) {
          sent = true;
          const incoming = event.message;
          if (viewing) {
            setMessages((current) =>
              upsertMessage(
                current.filter((message) => message.id !== optimistic.id),
                incoming,
              ),
            );
          }
        } else if (event.type === 'ai_message' && isMessageResponse(event.message)) {
          sent = true;
          const incoming = event.message;
          if (viewing) setMessages((current) => upsertMessage(current, incoming));
        } else if (event.type === 'done') {
          sent = true;
          if (viewing) {
            setActivity('Done');
            void pollRun(token, selectedProjectId);
          }
        }
      });
    } catch (error) {
      // Don't decide success/failure from the connection state — it's unreliable.
      // The SSE can drop AFTER the server already saved the message (reply still
      // arrives via the poll), or before the client ever sees the 200 even though
      // the POST was delivered. Deciding "failed" here is exactly what caused the
      // sent text to reappear in the input. Record the error and let the
      // server-truth reconcile below decide whether the message actually landed.
      streamFailure = error as Error;
    }

    // Reconcile from the server (the source of truth). Pull the saved messages
    // and check whether OUR message actually landed. Only treat it as a real
    // failure — and only then restore the draft — if the server has no record of
    // it. This is connection-state-independent, so a dropped SSE on an
    // already-saved message never resurrects the text in the input.
    try {
      const list = await refreshProjects(token).catch(() => projects);
      const nextProject =
        list.find((item) => item.id === selectedProjectId) ||
        list.find((item) => item.room_id === project?.room_id) ||
        project;
      const viewing = currentProjectIdRef.current === selectedProjectId;

      if (streamFailure && !sent && nextProject?.room_id) {
        // Stream errored and we never got a server ack: verify against the DB.
        // Retry once, since the DB write can briefly lag the SSE drop.
        const fetchMsgs = async () =>
          (
            await apiRequest<MessagesListResponse>(
              `/chat/rooms/${nextProject.room_id}/messages?limit=120`,
              {},
              token,
            ).catch(() => null)
          )?.messages ?? [];
        const isSaved = (msgs: MessageResponse[]) =>
          msgs.some((m) => m.sender_type === 'human' && m.content === finalContent);

        let serverMsgs = await fetchMsgs();
        if (!isSaved(serverMsgs)) {
          await new Promise((r) => setTimeout(r, 900));
          serverMsgs = await fetchMsgs();
        }
        const saved = isSaved(serverMsgs);
        if (saved) {
          // Safely on the server — show the truth, never restore the draft.
          if (viewing) setMessages(serverMsgs);
        } else {
          // Genuinely not saved — restore the text so nothing is lost (but don't
          // clobber a new message the user may have started typing meanwhile).
          if (viewing) setMessages((current) => current.filter((m) => m.id !== optimistic.id));
          setDraft((d) => (d ? d : content));
          Alert.alert('Send failed', streamFailure.message);
        }
      } else if (viewing && nextProject?.id) {
        // Clean finish (or server-acked): pull the saved messages into view.
        await loadProjectMessages(token, nextProject.id);
      }
      // ターン完了後、タイトルが既定のままなら自動生成（Web版と同じ挙動）。
      if (nextProject?.id && nextProject?.room_id) {
        void maybeGenerateTitle(nextProject.id, nextProject.room_id);
      }
    } catch {
      // best-effort reconcile
    } finally {
      setUploadProgress(null);
      setSending(false);
      setStreamingProjectId(null);
      setActivity('');
    }
  }

  async function handleRefreshProjectList() {
    if (!token) return;
    await refreshProjects(token).catch((error) => {
      Alert.alert('Refresh failed', String((error as Error).message));
    });
  }

  function artifactUrl(artifact: ChatArtifactResponse) {
    return cleanArtifactUrl(artifact);
  }

  function handleOpenArtifact(artifact: ChatArtifactResponse) {
    setArtifactView({
      title: artifact.label || artifact.slug || 'Artifact',
      url: artifactUrl(artifact),
    });
    setScreen('artifact');
  }

  const handleOpenMessageUrl = useCallback((url: string) => {
    const normalized = normalizeUrl(url);
    if (isArtifactUrl(normalized)) {
      setArtifactView({
        title: artifactTitleFromUrl(normalized),
        url: normalized,
      });
      setScreen('artifact');
      return;
    }
    openUrl(normalized);
  }, []);

  function handleBackToProjects() {
    setScreen('projects');
    setDrawerOpen(false);
  }

  if (auth.status === 'checking') {
    return (
      <SafeAreaView style={styles.centerScreen}>
        <StatusBar style="light" />
        <ActivityIndicator color="#f4f0e8" />
        <Text style={styles.mutedText}>Loading Done</Text>
      </SafeAreaView>
    );
  }

  if (auth.status === 'signed_out') {
    return (
      <SafeAreaView style={styles.screen}>
        <StatusBar style="light" />
        <KeyboardAvoidingView
          behavior={Platform.OS === 'ios' ? 'padding' : undefined}
          style={styles.loginWrap}
        >
          <View style={styles.brandMark}>
            <Text style={styles.brandMarkText}>D</Text>
          </View>
          <Text style={styles.title}>Done</Text>
          <Text style={styles.subtitle}>Native development build</Text>

          <View style={styles.form}>
            <TextInput
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="email-address"
              onChangeText={setEmail}
              placeholder="Email"
              placeholderTextColor="#77736b"
              style={styles.input}
              textContentType="emailAddress"
              value={email}
            />
            <TextInput
              onChangeText={setPassword}
              placeholder="Password"
              placeholderTextColor="#77736b"
              secureTextEntry
              style={styles.input}
              textContentType="password"
              value={password}
            />
            <Pressable
              disabled={loginBusy}
              onPress={handleLogin}
              style={({ pressed }) => [
                styles.primaryButton,
                (pressed || loginBusy) && styles.buttonPressed,
              ]}
            >
              {loginBusy ? (
                <ActivityIndicator color="#111" />
              ) : (
                <Text style={styles.primaryButtonText}>Log in</Text>
              )}
            </Pressable>
          </View>
        </KeyboardAvoidingView>
      </SafeAreaView>
    );
  }

  if (screen === 'projects') {
    return (
      <View style={styles.screen}>
        <StatusBar style="light" />
        <View style={[styles.appBar, { paddingTop: insets.top + 8 }]}>
          <View style={styles.appBarTitleBlock}>
            <Text style={styles.appBarTitle}>Done</Text>
          </View>
          <Pressable
            onPress={() => setScreen('settings')}
            hitSlop={10}
            style={({ pressed }) => [styles.appBarIconButton, pressed && styles.buttonPressed]}
          >
            <Ionicons name="settings-outline" size={22} color="#f4f0e8" />
          </Pressable>
        </View>

        <FlatList
          contentContainerStyle={[styles.projectListContent, { paddingBottom: insets.bottom + 96 }]}
          data={projects}
          keyExtractor={(item) => item.id}
          refreshControl={
            <RefreshControl
              refreshing={loadingProjects}
              onRefresh={handleRefreshProjectList}
              tintColor="#d9d2c8"
              colors={['#d9d2c8']}
            />
          }
          ListEmptyComponent={
            !loadingProjects ? (
              <View style={styles.emptyState}>
                <Ionicons name="chatbubbles-outline" size={48} color="#5a5550" />
                <Text style={styles.emptyTitle}>No chats yet</Text>
                <Text style={styles.emptyHint}>Tap + to start a new conversation with DAN.</Text>
              </View>
            ) : null
          }
          renderItem={({ item }) => (
            <Pressable
              onPress={() => handleSelectProject(item.id)}
              onLongPress={() => handleProjectLongPress(item)}
              delayLongPress={350}
              style={({ pressed }) => [
                styles.chatListItem,
                pressed && styles.chatListItemPressed,
              ]}
            >
              <View style={styles.chatAvatar}>
                <Text style={styles.chatAvatarText}>{item.icon || 'D'}</Text>
              </View>
              <View style={styles.chatListBody}>
                <View style={styles.chatListTopRow}>
                  <View style={styles.chatListTitleRow}>
                    {item.pinned_at ? (
                      <Ionicons name="pin" size={13} color="#a7a19a" style={styles.chatListPinIcon} />
                    ) : null}
                    <Text style={styles.chatListTitle} numberOfLines={1}>
                      {item.title || 'Untitled'}
                    </Text>
                  </View>
                  <Text style={styles.chatListTime}>{formatTime(projectTime(item))}</Text>
                </View>
                <Text style={styles.chatListPreview} numberOfLines={1}>
                  {item.last_message_preview || 'メッセージはまだありません'}
                </Text>
              </View>
              {(item.unread_count || 0) > 0 ? (
                <View style={styles.unreadBadge}>
                  <Text style={styles.unreadBadgeText}>
                    {(item.unread_count || 0) > 99 ? '99+' : item.unread_count}
                  </Text>
                </View>
              ) : null}
            </Pressable>
          )}
        />

        <Pressable
          onPress={handleNewProject}
          style={({ pressed }) => [
            styles.fab,
            { bottom: insets.bottom + 20 },
            pressed && styles.fabPressed,
          ]}
        >
          <Ionicons name="add" size={28} color="#111" />
        </Pressable>

        <ProjectActionSheet
          sheet={actionSheet}
          insetsBottom={insets.bottom}
          onClose={() => setActionSheet(null)}
          onPin={(project) => {
            setActionSheet(null);
            void handleTogglePin(project);
          }}
          onRequestDelete={(project) => setActionSheet({ project, mode: 'confirm-delete' })}
          onConfirmDelete={(project) => {
            setActionSheet(null);
            void handleDeleteProject(project);
          }}
        />
      </View>
    );
  }

  if (screen === 'settings') {
    return (
      <View style={styles.screen}>
        <StatusBar style="light" />
        <View style={[styles.appBar, { paddingTop: insets.top + 8 }]}>
          <Pressable
            onPress={() => setScreen('projects')}
            hitSlop={10}
            style={({ pressed }) => [styles.appBarIconButton, pressed && styles.buttonPressed]}
          >
            <Ionicons name="chevron-back" size={26} color="#f4f0e8" />
          </Pressable>
          <View style={styles.appBarTitleBlockCenter}>
            <Text style={styles.appBarTitleSingle}>Settings</Text>
          </View>
          <View style={styles.appBarIconButton} />
        </View>

        <ScrollView contentContainerStyle={{ paddingBottom: insets.bottom + 32 }}>
          <Text style={styles.settingsSectionLabel}>ACCOUNT</Text>
          <View style={styles.settingsCard}>
            <View style={styles.settingsRow}>
              <View style={styles.settingsRowMain}>
                <Text style={styles.settingsRowLabel}>Name</Text>
                <Text style={styles.settingsRowValue} numberOfLines={1}>
                  {user?.display_name || '—'}
                </Text>
              </View>
            </View>
            <View style={styles.settingsRowDivider} />
            <View style={styles.settingsRow}>
              <View style={styles.settingsRowMain}>
                <Text style={styles.settingsRowLabel}>Email</Text>
                <Text style={styles.settingsRowValue} numberOfLines={1}>
                  {user?.email || '—'}
                </Text>
              </View>
            </View>
          </View>

          <Text style={styles.settingsSectionLabel}>AUTHENTICATION</Text>
          <View style={styles.settingsCard}>
            <Pressable
              onPress={handleToggleSmsForwarding}
              style={({ pressed }) => [styles.settingsRow, pressed && styles.buttonPressed]}
            >
              <View style={styles.settingsRowMain}>
                <Text style={styles.settingsRowLabel}>SMS OTP forwarding</Text>
                <Text style={styles.settingsRowValue}>{smsForwardingStatus}</Text>
              </View>
              <Ionicons
                name={smsForwardingStatus === 'On' ? 'shield-checkmark' : 'shield-outline'}
                size={20}
                color={smsForwardingStatus === 'On' ? '#7fd1c7' : '#77736b'}
              />
            </Pressable>
            <View style={styles.settingsRowDivider} />
            <View style={styles.settingsRowHint}>
              <Text style={styles.settingsHintText}>
                Android APK only. If forwarding fails, Dan keeps the browser open and asks you for the code.
              </Text>
            </View>
          </View>

          <Text style={styles.settingsSectionLabel}>NOTIFICATIONS</Text>
          <View style={styles.settingsCard}>
            <Pressable
              onPress={handleToggleNotifications}
              style={({ pressed }) => [styles.settingsRow, pressed && styles.buttonPressed]}
            >
              <View style={styles.settingsRowMain}>
                <Text style={styles.settingsRowLabel}>Push notifications</Text>
                <Text style={styles.settingsRowValue}>{notificationStatus}</Text>
              </View>
              <Ionicons
                name={notificationStatus === 'On' ? 'notifications' : 'notifications-off-outline'}
                size={20}
                color={notificationStatus === 'On' ? '#7fd1c7' : '#77736b'}
              />
            </Pressable>
            <View style={styles.settingsRowDivider} />
            <View style={styles.settingsRowHint}>
              <Text style={styles.settingsHintText}>
                Tap to toggle. iOS/Android system permission is requested on first enable.
              </Text>
            </View>
          </View>

          <Text style={styles.settingsSectionLabel}>SESSION</Text>
          <View style={styles.settingsCard}>
            <Pressable
              onPress={handleLogout}
              style={({ pressed }) => [styles.settingsRow, pressed && styles.buttonPressed]}
            >
              <Text style={styles.settingsDangerLabel}>Log out</Text>
              <Ionicons name="log-out-outline" size={20} color="#ff5a3d" />
            </Pressable>
          </View>

          <Text style={styles.settingsFootnote}>Done mobile · v1.0.0</Text>
        </ScrollView>
      </View>
    );
  }

  if (screen === 'artifact' && artifactView) {
    return (
      <View style={styles.screen}>
        <StatusBar style="light" />
        <View style={[styles.appBar, { paddingTop: insets.top + 8 }]}>
          <Pressable
            onPress={() => setScreen(currentProject ? 'chat' : 'projects')}
            hitSlop={10}
            style={({ pressed }) => [styles.appBarIconButton, pressed && styles.buttonPressed]}
          >
            <Ionicons name="chevron-back" size={26} color="#f4f0e8" />
          </Pressable>
          <View style={styles.appBarTitleBlockCenter}>
            <Text style={styles.appBarTitleSingle} numberOfLines={1}>
              {artifactView.title}
            </Text>
            <Text style={styles.appBarSubtitle} numberOfLines={1}>
              {artifactView.url}
            </Text>
          </View>
          <Pressable
            onPress={() => openUrl(artifactView.url)}
            hitSlop={10}
            style={({ pressed }) => [styles.appBarIconButton, pressed && styles.buttonPressed]}
          >
            <Ionicons name="open-outline" size={22} color="#f4f0e8" />
          </Pressable>
        </View>
        <WebView
          source={{ uri: artifactView.url }}
          startInLoadingState
          style={styles.webView}
          renderLoading={() => (
            <View style={styles.webViewLoading}>
              <ActivityIndicator color="#f4f0e8" />
            </View>
          )}
        />
      </View>
    );
  }

  return (
    <View style={styles.screen}>
      <StatusBar style="light" />
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 8 : 0}
        style={styles.chatWrap}
      >
        <View style={[styles.appBar, { paddingTop: insets.top + 8 }]}>
          <Pressable
            onPress={handleBackToProjects}
            hitSlop={10}
            style={({ pressed }) => [styles.appBarBackButton, pressed && styles.buttonPressed]}
          >
            <Ionicons name="chevron-back" size={26} color="#f4f0e8" />
            {/* LINE-style unread count from OTHER chats, shown next to the back
                button (neutral color, not an alarming red badge). */}
            {unreadTotal > 0 ? (
              <View style={styles.backBadge}>
                <Text style={styles.backBadgeText}>{unreadTotal > 99 ? '99+' : unreadTotal}</Text>
              </View>
            ) : null}
          </Pressable>
          <View style={styles.appBarTitleBlockCenter}>
            <Text style={styles.appBarTitleSingle} numberOfLines={1}>
              {headerTitle}
            </Text>
          </View>
          <View style={styles.appBarRight}>
            <Pressable
              onPress={() => setSearchOpen(true)}
              hitSlop={10}
              style={({ pressed }) => [styles.appBarIconButton, pressed && styles.buttonPressed]}
            >
              <Ionicons name="search" size={22} color="#f4f0e8" />
            </Pressable>
          </View>
        </View>

        {artifacts.length > 0 || loadingArtifacts ? (
          <View style={styles.artifactTabs}>
            {loadingArtifacts ? (
              <ActivityIndicator color="#d9d2c8" size="small" />
            ) : (
              artifacts.map((artifact) => (
                <Pressable
                  key={artifact.id}
                  onPress={() => handleOpenArtifact(artifact)}
                  style={({ pressed }) => [
                    styles.artifactTab,
                    pressed && styles.buttonPressed,
                  ]}
                >
                  <Text style={styles.artifactTabText} numberOfLines={1}>
                    {artifact.label || artifact.slug || 'Artifact'}
                  </Text>
                </Pressable>
              ))
            )}
          </View>
        ) : null}

        {loadingMessages && newestMessages.length === 0 && !showLiveTurn ? (
          <View style={styles.centerPanel}>
            <ActivityIndicator color="#f4f0e8" />
            <Text style={styles.mutedText}>Loading history</Text>
          </View>
        ) : newestMessages.length === 0 && !showLiveTurn ? (
          <View style={styles.centerPanel}>
            <Text style={styles.emptyTitle}>Done</Text>
            <Text style={styles.mutedText}>メッセージを入力してください</Text>
          </View>
        ) : (
          <FlatList
            contentContainerStyle={styles.messageList}
            data={
              showLiveTurn
                ? [
                    {
                      id: '__live__',
                      room_id: currentProject?.room_id,
                      sender_name: 'DAN',
                      sender_type: 'ai',
                      content: '',
                      created_at: '',
                    } as MessageResponse,
                    ...newestMessages,
                  ]
                : newestMessages
            }
            initialNumToRender={14}
            inverted
            keyExtractor={(item) => item.id}
            maxToRenderPerBatch={8}
            ref={listRef}
            removeClippedSubviews
            renderItem={({ item }) => {
              // Live in-progress turn: render the timeline as it builds (tool
              // steps expanded) with a spinner, like the web chat's live view.
              if (item.id === '__live__') {
                return (
                  <View style={[styles.messageBubble, styles.aiBubble]}>
                    <View style={styles.messageMetaRow}>
                      <Text style={styles.messageSender}>DAN</Text>
                    </View>
                    {liveStepBlocks.length > 0 ? (
                      <AiTurnBlocks blocks={liveStepBlocks} mine={false} onOpenUrl={handleOpenMessageUrl} onPlayVideo={setPlayingVideo} defaultOpen />
                    ) : null}
                    {/* The "running now" spinner sits at the bottom next to the
                        latest log line, so it's obvious which step is live. */}
                    <View style={styles.liveStatusRow}>
                      <ActivityIndicator color="#7fd1c7" size="small" />
                      <Text style={styles.liveStatusText} numberOfLines={1}>
                        {activity || '考えています…'}
                      </Text>
                    </View>
                  </View>
                );
              }
              const mine = item.sender_type === 'human';
              // Render the full timeline (text + "N件の作業") when the AI message
              // carries blocks with tool steps or multiple text segments — same
              // rule as the web chat. Otherwise just render the final content.
              const blocks = item.sender_type === 'ai' ? item.ai_context?.blocks : undefined;
              const useBlocks =
                !!blocks &&
                blocks.length > 0 &&
                (blocks.some((b) => b.type === 'tool' || b.type === 'error') ||
                  blocks.filter((b) => b.type === 'text' || b.type === 'reasoning').length > 1);
              return (
                <View
                  style={[
                    styles.messageBubble,
                    mine ? styles.myBubble : styles.aiBubble,
                    highlightId === item.id && styles.messageBubbleHighlight,
                  ]}
                >
                  <View style={styles.messageMetaRow}>
                    <Text style={styles.messageSender}>{mine ? 'You' : item.sender_name || 'DAN'}</Text>
                    <Text style={styles.messageTime}>{formatTime(item.created_at)}</Text>
                  </View>
                  {useBlocks ? (
                    <AiTurnBlocks blocks={blocks!} mine={mine} onOpenUrl={handleOpenMessageUrl} onPlayVideo={setPlayingVideo} />
                  ) : (
                    <RichMessageContent
                      content={item.content}
                      mine={mine}
                      onOpenUrl={handleOpenMessageUrl}
                      onPlayVideo={setPlayingVideo}
                      videoProgress={uploadProgress?.id === item.id ? uploadProgress.value : undefined}
                    />
                  )}
                </View>
              );
            }}
            updateCellsBatchingPeriod={30}
            windowSize={7}
            onScrollToIndexFailed={(info) => {
              // Target not measured yet — scroll near it, then retry once.
              listRef.current?.scrollToOffset({
                offset: info.averageItemLength * info.index,
                animated: false,
              });
              setTimeout(() => {
                try {
                  listRef.current?.scrollToIndex({
                    index: info.index,
                    animated: true,
                    viewPosition: 0.5,
                  });
                } catch {
                  // give up silently
                }
              }, 320);
            }}
          />
        )}

        {/* The live in-progress status now lives inside the __live__ bubble
            (server-driven timeline), so no separate activity bar is needed. */}

        {attachments.length > 0 ? (
          <ScrollView
            horizontal
            showsHorizontalScrollIndicator={false}
            style={styles.attachmentBar}
            contentContainerStyle={styles.attachmentBarContent}
          >
            {attachments.map((att) => (
              <View key={att.key} style={styles.attachmentChip}>
                {att.kind === 'image' ? (
                  <Image source={{ uri: att.uri }} style={styles.attachmentThumb} />
                ) : att.kind === 'video' ? (
                  <VideoThumb uri={att.uri} style={styles.attachmentThumb} small />
                ) : (
                  <View style={[styles.attachmentThumb, styles.attachmentThumbIcon]}>
                    <Ionicons name="document" size={20} color="#d9d2c8" />
                  </View>
                )}
                {att.kind === 'file' ? (
                  <Text style={styles.attachmentName} numberOfLines={1}>
                    {att.name}
                  </Text>
                ) : null}
                <Pressable
                  onPress={() => removeAttachment(att.key)}
                  hitSlop={8}
                  style={styles.attachmentRemove}
                >
                  <Ionicons name="close-circle" size={18} color="#111" />
                </Pressable>
              </View>
            ))}
          </ScrollView>
        ) : null}

        <View style={[styles.composer, { paddingBottom: 10 + insets.bottom }]}>
          <Pressable
            onPress={() => setAttachSheetOpen(true)}
            disabled={sending}
            hitSlop={6}
            style={({ pressed }) => [styles.attachButton, pressed && styles.buttonPressed]}
          >
            <Ionicons name="add-circle-outline" size={28} color="#a7a19a" />
          </Pressable>
          <TextInput
            multiline
            onChangeText={setDraft}
            placeholder="Ask DAN"
            placeholderTextColor="#77736b"
            style={styles.composerInput}
            value={draft}
          />
          <Pressable
            disabled={sending || (!draft.trim() && attachments.length === 0)}
            onPress={handleSend}
            style={({ pressed }) => [
              styles.sendButton,
              (pressed || sending || (!draft.trim() && attachments.length === 0)) && styles.buttonPressed,
            ]}
          >
            {/* No spinner here — the live "working" indicator already shows in
                Dan's chat bubble; a second one on the send button is redundant. */}
            <Text style={styles.sendButtonText}>Send</Text>
          </Pressable>
        </View>
      </KeyboardAvoidingView>

      <Modal
        visible={searchOpen}
        animationType="slide"
        onRequestClose={() => setSearchOpen(false)}
        statusBarTranslucent
      >
        <View style={[styles.searchModalRoot, { paddingTop: insets.top + 8 }]}>
          <View style={styles.searchBar}>
            <Ionicons name="search" size={20} color="#a7a19a" />
            <TextInput
              autoFocus
              value={searchQuery}
              onChangeText={setSearchQuery}
              onSubmitEditing={() => runSearch(searchQuery)}
              returnKeyType="search"
              placeholder="チャット内をワード検索…"
              placeholderTextColor="#77736b"
              style={styles.searchInput}
            />
            {searchLoading ? <ActivityIndicator color="#7fd1c7" size="small" /> : null}
            <Pressable onPress={() => setSearchOpen(false)} hitSlop={8}>
              <Text style={styles.searchCancel}>閉じる</Text>
            </Pressable>
          </View>
          <FlatList
            data={searchResults ?? []}
            keyExtractor={(item) => item.id}
            keyboardShouldPersistTaps="handled"
            contentContainerStyle={styles.searchListContent}
            renderItem={({ item }) => (
              <Pressable
                onPress={() => jumpToMessage(item)}
                style={({ pressed }) => [styles.searchHit, pressed && styles.buttonPressed]}
              >
                <Text style={styles.searchHitMeta}>
                  {(item.sender_type === 'ai' ? 'ダン' : item.sender_name || 'You') +
                    ' ・ ' +
                    new Date(item.created_at).toLocaleString('ja-JP')}
                </Text>
                {renderSearchSnippet(item.content, searchQuery)}
              </Pressable>
            )}
            ListEmptyComponent={
              searchResults ? (
                <Text style={styles.searchEmpty}>
                  {searchLoading ? '検索中…' : '一致するメッセージはありません'}
                </Text>
              ) : (
                <Text style={styles.searchEmpty}>ワードを入力して検索してください</Text>
              )
            }
            ListHeaderComponent={
              searchResults && searchResults.length > 0 ? (
                <Text style={styles.searchCount}>{searchResults.length}件ヒット（新しい順）</Text>
              ) : null
            }
          />
        </View>
      </Modal>

      <Modal
        visible={attachSheetOpen}
        transparent
        animationType="slide"
        onRequestClose={() => setAttachSheetOpen(false)}
        statusBarTranslucent
      >
        <View style={styles.sheetRoot}>
          <Pressable style={styles.sheetBackdrop} onPress={() => setAttachSheetOpen(false)} />
          <View style={[styles.sheet, { paddingBottom: Math.max(insets.bottom, 12) + 12 }]}>
            <View style={styles.sheetGrabber} />
            <Text style={styles.sheetHeading}>添付する</Text>
            <Pressable
              onPress={() => void pickMedia()}
              style={({ pressed }) => [styles.sheetAction, pressed && styles.sheetActionPressed]}
            >
              <Ionicons name="image" size={22} color="#f4f0e8" />
              <Text style={styles.sheetActionText}>写真・動画</Text>
            </Pressable>
            <View style={styles.sheetDivider} />
            <Pressable
              onPress={() => void pickDocument()}
              style={({ pressed }) => [styles.sheetAction, pressed && styles.sheetActionPressed]}
            >
              <Ionicons name="document" size={22} color="#f4f0e8" />
              <Text style={styles.sheetActionText}>ファイル</Text>
            </Pressable>
            <Pressable
              onPress={() => setAttachSheetOpen(false)}
              style={({ pressed }) => [styles.sheetCancel, pressed && styles.sheetActionPressed]}
            >
              <Text style={styles.sheetCancelText}>キャンセル</Text>
            </Pressable>
          </View>
        </View>
      </Modal>

      {/* アプリ内・全画面の動画プレイヤー（expo-video のネイティブプレイヤー）。 */}
      {playingVideo ? (
        <VideoPlayerModal uri={playingVideo} onClose={() => setPlayingVideo(null)} />
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: '#12110f',
  },
  mdBold: {
    fontWeight: '800',
  },
  mdItalic: {
    fontStyle: 'italic',
  },
  mdCode: {
    backgroundColor: 'rgba(244, 240, 232, 0.08)',
    borderRadius: 4,
    color: '#f4f0e8',
    fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace',
    fontSize: 13,
    paddingHorizontal: 4,
  },
  sheetRoot: {
    flex: 1,
    justifyContent: 'flex-end',
  },
  sheetBackdrop: {
    backgroundColor: 'rgba(0, 0, 0, 0.55)',
    bottom: 0,
    left: 0,
    position: 'absolute',
    right: 0,
    top: 0,
  },
  sheet: {
    backgroundColor: '#1d1b18',
    borderTopLeftRadius: 24,
    borderTopRightRadius: 24,
    paddingHorizontal: 12,
    paddingTop: 8,
  },
  sheetGrabber: {
    alignSelf: 'center',
    backgroundColor: '#3a3631',
    borderRadius: 2,
    height: 4,
    marginBottom: 12,
    width: 40,
  },
  sheetHeading: {
    color: '#a7a19a',
    fontSize: 13,
    fontWeight: '600',
    paddingHorizontal: 8,
    paddingVertical: 8,
    textAlign: 'center',
  },
  sheetAction: {
    alignItems: 'center',
    borderRadius: 12,
    flexDirection: 'row',
    gap: 14,
    paddingHorizontal: 14,
    paddingVertical: 14,
  },
  sheetActionPressed: {
    backgroundColor: 'rgba(244, 240, 232, 0.06)',
  },
  sheetActionText: {
    color: '#f4f0e8',
    fontSize: 16,
    fontWeight: '600',
  },
  sheetActionTextDanger: {
    color: '#ff5a3d',
  },
  sheetDivider: {
    backgroundColor: '#28251f',
    height: 1,
    marginHorizontal: 14,
  },
  sheetConfirmBody: {
    color: '#a7a19a',
    fontSize: 14,
    lineHeight: 22,
    paddingHorizontal: 18,
    paddingVertical: 16,
    textAlign: 'center',
  },
  sheetPrimaryDanger: {
    alignItems: 'center',
    backgroundColor: '#ff5a3d',
    borderRadius: 12,
    flexDirection: 'row',
    gap: 10,
    justifyContent: 'center',
    marginHorizontal: 4,
    marginTop: 4,
    paddingVertical: 14,
  },
  sheetPrimaryDangerText: {
    color: '#fff',
    fontSize: 16,
    fontWeight: '800',
  },
  sheetCancel: {
    alignItems: 'center',
    borderRadius: 12,
    marginTop: 8,
    paddingVertical: 14,
  },
  sheetCancelText: {
    color: '#7c766f',
    fontSize: 15,
    fontWeight: '600',
  },
  appBar: {
    alignItems: 'center',
    backgroundColor: '#12110f',
    borderBottomColor: '#1f1d1a',
    borderBottomWidth: 1,
    flexDirection: 'row',
    gap: 4,
    paddingBottom: 12,
    paddingHorizontal: 12,
  },
  appBarIconButton: {
    alignItems: 'center',
    height: 40,
    justifyContent: 'center',
    width: 40,
  },
  appBarRight: {
    alignItems: 'center',
    flexDirection: 'row',
  },
  appBarBackButton: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 3,
    height: 40,
    justifyContent: 'center',
    paddingLeft: 2,
    paddingRight: 6,
  },
  backBadge: {
    alignItems: 'center',
    backgroundColor: '#3f3a33',
    borderRadius: 10,
    height: 20,
    justifyContent: 'center',
    minWidth: 20,
    paddingHorizontal: 6,
  },
  backBadgeText: {
    color: '#f4f0e8',
    fontSize: 11,
    fontWeight: '800',
  },
  appBarTitleBlock: {
    alignItems: 'center',
    flex: 1,
    flexDirection: 'row',
    gap: 10,
    paddingLeft: 8,
  },
  appBarTitleBlockCenter: {
    alignItems: 'center',
    flex: 1,
    justifyContent: 'center',
  },
  appBarTitle: {
    color: '#f4f0e8',
    fontSize: 28,
    fontWeight: '800',
    letterSpacing: -0.5,
  },
  appBarTitleSingle: {
    color: '#f4f0e8',
    fontSize: 17,
    fontWeight: '700',
    letterSpacing: -0.2,
    maxWidth: '85%',
  },
  appBarSubtitle: {
    color: '#77736b',
    fontSize: 11,
    marginTop: 2,
    maxWidth: '85%',
  },
  emptyState: {
    alignItems: 'center',
    flex: 1,
    gap: 14,
    justifyContent: 'center',
    paddingHorizontal: 36,
    paddingTop: 80,
  },
  emptyHint: {
    color: '#77736b',
    fontSize: 14,
    textAlign: 'center',
  },
  chatListItemPressed: {
    backgroundColor: '#1a1815',
  },
  fab: {
    alignItems: 'center',
    backgroundColor: '#f4f0e8',
    borderRadius: 30,
    elevation: 6,
    height: 60,
    justifyContent: 'center',
    position: 'absolute',
    right: 20,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 4 },
    shadowOpacity: 0.4,
    shadowRadius: 8,
    width: 60,
  },
  fabPressed: {
    opacity: 0.8,
    transform: [{ scale: 0.96 }],
  },
  settingsSectionLabel: {
    color: '#77736b',
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 1,
    marginBottom: 8,
    marginLeft: 20,
    marginTop: 24,
  },
  settingsCard: {
    backgroundColor: '#1d1b18',
    borderColor: '#282520',
    borderRadius: 14,
    borderWidth: 1,
    marginHorizontal: 12,
    overflow: 'hidden',
  },
  settingsRow: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 12,
    minHeight: 56,
    paddingHorizontal: 16,
    paddingVertical: 12,
  },
  settingsRowDivider: {
    backgroundColor: '#282520',
    height: 1,
    marginLeft: 16,
  },
  settingsRowMain: {
    flex: 1,
  },
  settingsRowLabel: {
    color: '#f4f0e8',
    fontSize: 15,
    fontWeight: '600',
  },
  settingsRowValue: {
    color: '#a7a19a',
    fontSize: 13,
    marginTop: 2,
  },
  settingsRowHint: {
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  settingsHintText: {
    color: '#77736b',
    fontSize: 12,
    lineHeight: 17,
  },
  settingsDangerLabel: {
    color: '#ff5a3d',
    flex: 1,
    fontSize: 15,
    fontWeight: '600',
  },
  settingsFootnote: {
    color: '#4a4640',
    fontSize: 11,
    marginTop: 32,
    textAlign: 'center',
  },
  centerScreen: {
    alignItems: 'center',
    backgroundColor: '#12110f',
    flex: 1,
    gap: 14,
    justifyContent: 'center',
  },
  loginWrap: {
    flex: 1,
    justifyContent: 'center',
    padding: 24,
  },
  brandMark: {
    alignItems: 'center',
    alignSelf: 'center',
    backgroundColor: '#f4f0e8',
    borderRadius: 18,
    height: 72,
    justifyContent: 'center',
    marginBottom: 18,
    width: 72,
  },
  brandMarkText: {
    color: '#12110f',
    fontSize: 38,
    fontWeight: '800',
  },
  title: {
    color: '#f4f0e8',
    fontSize: 34,
    fontWeight: '800',
    textAlign: 'center',
  },
  subtitle: {
    color: '#a7a19a',
    fontSize: 14,
    marginBottom: 34,
    marginTop: 6,
    textAlign: 'center',
  },
  form: {
    gap: 12,
  },
  input: {
    backgroundColor: '#1d1b18',
    borderColor: '#34302a',
    borderRadius: 14,
    borderWidth: 1,
    color: '#f4f0e8',
    fontSize: 16,
    minHeight: 54,
    paddingHorizontal: 16,
  },
  primaryButton: {
    alignItems: 'center',
    backgroundColor: '#f4f0e8',
    borderRadius: 14,
    height: 54,
    justifyContent: 'center',
    marginTop: 6,
  },
  primaryButtonText: {
    color: '#12110f',
    fontSize: 16,
    fontWeight: '800',
  },
  buttonPressed: {
    opacity: 0.55,
  },
  listHeader: {
    alignItems: 'center',
    borderBottomColor: '#282520',
    borderBottomWidth: 1,
    flexDirection: 'row',
    gap: 12,
    minHeight: 68,
    paddingHorizontal: 16,
    paddingVertical: 10,
  },
  listTitle: {
    color: '#f4f0e8',
    fontSize: 26,
    fontWeight: '800',
  },
  projectListContent: {
    paddingHorizontal: 10,
    paddingVertical: 8,
  },
  chatListItem: {
    alignItems: 'center',
    borderBottomColor: '#282520',
    borderBottomWidth: 1,
    flexDirection: 'row',
    gap: 12,
    minHeight: 76,
    paddingHorizontal: 6,
    paddingVertical: 10,
  },
  chatAvatar: {
    alignItems: 'center',
    backgroundColor: '#f4f0e8',
    borderRadius: 24,
    height: 48,
    justifyContent: 'center',
    width: 48,
  },
  chatAvatarText: {
    color: '#12110f',
    fontSize: 20,
    fontWeight: '800',
  },
  chatListBody: {
    flex: 1,
    minWidth: 0,
  },
  chatListTopRow: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 8,
  },
  chatListTitleRow: {
    alignItems: 'center',
    flex: 1,
    flexDirection: 'row',
    gap: 4,
  },
  chatListPinIcon: {
    transform: [{ rotate: '45deg' }],
  },
  chatListTitle: {
    color: '#f4f0e8',
    flex: 1,
    fontSize: 16,
    fontWeight: '800',
  },
  chatListTime: {
    color: '#7c766f',
    fontSize: 11,
  },
  chatListPreview: {
    color: '#a7a19a',
    fontSize: 13,
    lineHeight: 18,
    marginTop: 4,
  },
  listFooter: {
    borderTopColor: '#282520',
    borderTopWidth: 1,
    gap: 8,
    padding: 12,
  },
  secondaryFooterButton: {
    alignItems: 'center',
    backgroundColor: '#22201c',
    borderColor: '#34302a',
    borderRadius: 12,
    borderWidth: 1,
    minHeight: 42,
    justifyContent: 'center',
    paddingHorizontal: 12,
  },
  secondaryFooterButtonText: {
    color: '#d9d2c8',
    fontSize: 13,
    fontWeight: '700',
  },
  chatWrap: {
    flex: 1,
  },
  header: {
    alignItems: 'center',
    borderBottomColor: '#282520',
    borderBottomWidth: 1,
    flexDirection: 'row',
    gap: 10,
    minHeight: 64,
    paddingHorizontal: 12,
    paddingVertical: 9,
  },
  headerCenter: {
    flex: 1,
    minWidth: 0,
  },
  headerTitle: {
    color: '#f4f0e8',
    fontSize: 17,
    fontWeight: '800',
  },
  headerMeta: {
    color: '#908a83',
    fontSize: 11,
    marginTop: 2,
  },
  iconButton: {
    alignItems: 'center',
    backgroundColor: '#22201c',
    borderColor: '#34302a',
    borderRadius: 12,
    borderWidth: 1,
    height: 42,
    justifyContent: 'center',
    minWidth: 42,
    paddingHorizontal: 8,
  },
  iconButtonText: {
    color: '#f4f0e8',
    fontSize: 14,
    fontWeight: '800',
  },
  headerUnreadBadge: {
    alignItems: 'center',
    backgroundColor: '#ff5a3d',
    borderRadius: 14,
    minWidth: 28,
    height: 28,
    justifyContent: 'center',
    paddingHorizontal: 8,
  },
  headerUnreadText: {
    color: '#fffaf5',
    fontSize: 12,
    fontWeight: '900',
  },
  unreadBadge: {
    alignItems: 'center',
    backgroundColor: '#ff5a3d',
    borderRadius: 13,
    minWidth: 26,
    height: 26,
    justifyContent: 'center',
    paddingHorizontal: 7,
  },
  unreadBadgeText: {
    color: '#fffaf5',
    fontSize: 11,
    fontWeight: '900',
  },
  artifactTabs: {
    alignItems: 'center',
    borderBottomColor: '#282520',
    borderBottomWidth: 1,
    flexDirection: 'row',
    gap: 8,
    minHeight: 48,
    paddingHorizontal: 12,
    paddingVertical: 7,
  },
  artifactTab: {
    backgroundColor: '#2c261b',
    borderColor: '#5a4930',
    borderRadius: 12,
    borderWidth: 1,
    maxWidth: 220,
    minHeight: 34,
    justifyContent: 'center',
    paddingHorizontal: 12,
  },
  artifactTabText: {
    color: '#f4f0e8',
    fontSize: 13,
    fontWeight: '800',
  },
  webView: {
    backgroundColor: '#12110f',
    flex: 1,
  },
  webViewLoading: {
    ...StyleSheet.absoluteFillObject,
    alignItems: 'center',
    backgroundColor: '#12110f',
    justifyContent: 'center',
  },
  centerPanel: {
    alignItems: 'center',
    flex: 1,
    gap: 10,
    justifyContent: 'center',
    paddingHorizontal: 24,
  },
  emptyTitle: {
    color: '#f4f0e8',
    fontSize: 22,
    fontWeight: '800',
  },
  mutedText: {
    color: '#a7a19a',
    fontSize: 14,
  },
  messageList: {
    gap: 10,
    padding: 14,
    paddingBottom: 18,
  },
  messageBubble: {
    borderRadius: 16,
    maxWidth: '88%',
    overflow: 'hidden',
    paddingHorizontal: 14,
    paddingVertical: 10,
  },
  myBubble: {
    alignSelf: 'flex-end',
    backgroundColor: '#f4f0e8',
  },
  aiBubble: {
    alignSelf: 'flex-start',
    backgroundColor: '#1f1d19',
    borderColor: '#34302a',
    borderWidth: 1,
  },
  mutedSegment: {
    opacity: 0.55,
  },
  toolGroup: {
    marginVertical: 6,
  },
  toolGroupHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 5,
  },
  toolGroupLabel: {
    color: '#a7a19a',
    fontSize: 12.5,
  },
  toolGroupBody: {
    borderLeftColor: '#3a352e',
    borderLeftWidth: 2,
    gap: 6,
    marginLeft: 6,
    marginTop: 6,
    paddingLeft: 10,
  },
  toolRow: {
    flexDirection: 'row',
    gap: 6,
  },
  toolRowIcon: {
    marginTop: 2,
  },
  toolRowMain: {
    flex: 1,
    // RN flex items default to minWidth:auto, so a long command/path (one
    // unbreakable "word") refuses to shrink and overflows the bubble. minWidth:0
    // lets it shrink and the Text wrap/break instead.
    minWidth: 0,
  },
  toolRowText: {
    color: '#c8c2b8',
    flexShrink: 1,
    fontSize: 12.5,
    lineHeight: 18,
  },
  liveStatusRow: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 8,
    marginTop: 6,
  },
  liveStatusText: {
    color: '#7fd1c7',
    flexShrink: 1,
    fontSize: 12.5,
    lineHeight: 18,
  },
  messageBubbleHighlight: {
    borderColor: '#7fd1c7',
    borderWidth: 2,
  },
  searchModalRoot: {
    backgroundColor: '#12110f',
    flex: 1,
  },
  searchBar: {
    alignItems: 'center',
    borderBottomColor: '#282520',
    borderBottomWidth: 1,
    flexDirection: 'row',
    gap: 8,
    paddingBottom: 10,
    paddingHorizontal: 14,
  },
  searchInput: {
    color: '#f4f0e8',
    flex: 1,
    fontSize: 15,
    paddingVertical: 4,
  },
  searchCancel: {
    color: '#7fd1c7',
    fontSize: 14,
    fontWeight: '600',
  },
  searchListContent: {
    paddingBottom: 40,
  },
  searchCount: {
    color: '#7c766f',
    fontSize: 12,
    paddingHorizontal: 16,
    paddingTop: 10,
    paddingBottom: 4,
  },
  searchHit: {
    borderBottomColor: '#1f1d1a',
    borderBottomWidth: 1,
    paddingHorizontal: 16,
    paddingVertical: 11,
  },
  searchHitMeta: {
    color: '#7c766f',
    fontSize: 11.5,
    marginBottom: 3,
  },
  searchHitText: {
    color: '#c8c2b8',
    fontSize: 13.5,
    lineHeight: 19,
  },
  searchHitMark: {
    backgroundColor: '#caa83a',
    color: '#111',
  },
  searchEmpty: {
    color: '#77736b',
    fontSize: 14,
    paddingHorizontal: 16,
    paddingVertical: 28,
    textAlign: 'center',
  },
  toolRowErr: {
    color: '#ff8a73',
  },
  toolRowDetail: {
    color: '#8a847b',
    fontSize: 11.5,
    lineHeight: 16,
    marginTop: 2,
  },
  messageMetaRow: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 8,
    marginBottom: 5,
  },
  messageSender: {
    color: '#7c766f',
    fontSize: 11,
    fontWeight: '800',
  },
  messageTime: {
    color: '#7c766f',
    fontSize: 11,
  },
  messageText: {
    color: '#f4f0e8',
    fontSize: 15,
    lineHeight: 22,
  },
  messageContentWrap: {
    gap: 8,
  },
  messageLink: {
    color: '#8db8ff',
    fontWeight: '800',
    textDecorationLine: 'underline',
  },
  myMessageText: {
    color: '#12110f',
  },
  myMessageLink: {
    color: '#0b4aa0',
  },
  messageImage: {
    backgroundColor: '#12110f',
    borderColor: '#34302a',
    borderRadius: 12,
    borderWidth: 1,
    height: 220,
    maxWidth: '100%',
    width: 260,
  },
  videoThumbWrap: {
    alignItems: 'center',
    backgroundColor: '#000',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  messageVideoThumb: {
    borderColor: '#34302a',
    borderRadius: 12,
    borderWidth: 1,
    height: 220,
    maxWidth: '100%',
    width: 260,
  },
  videoPlayBadge: {
    alignItems: 'center',
    backgroundColor: 'rgba(244,240,232,0.92)',
    borderRadius: 999,
    height: 30,
    justifyContent: 'center',
    width: 30,
  },
  videoPlayBadgeSmall: {
    alignItems: 'center',
    backgroundColor: 'rgba(18,17,15,0.45)',
    borderRadius: 999,
    height: 20,
    justifyContent: 'center',
    width: 20,
  },
  videoPlayerBackdrop: {
    backgroundColor: '#000',
    flex: 1,
  },
  videoPlayerView: {
    backgroundColor: '#000',
    flex: 1,
    width: '100%',
  },
  videoCenterOverlay: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  videoPlayerClose: {
    alignItems: 'center',
    backgroundColor: 'rgba(0,0,0,0.55)',
    borderRadius: 999,
    height: 40,
    justifyContent: 'center',
    position: 'absolute',
    right: 16,
    top: 44,
    width: 40,
  },
  mediaCard: {
    backgroundColor: '#15130f',
    borderColor: '#34302a',
    borderRadius: 12,
    borderWidth: 1,
    gap: 3,
    padding: 10,
  },
  mediaCardRow: {
    alignItems: 'center',
    flexDirection: 'row',
    gap: 8,
  },
  myMediaCard: {
    backgroundColor: '#ebe4d8',
    borderColor: '#d2c8b8',
  },
  mediaCardTitle: {
    color: '#f4f0e8',
    fontSize: 13,
    fontWeight: '800',
  },
  mediaCardUrl: {
    color: '#a7a19a',
    fontSize: 12,
    lineHeight: 17,
  },
  myMediaCardUrl: {
    color: '#4d463e',
  },
  activityBar: {
    alignItems: 'center',
    borderTopColor: '#282520',
    borderTopWidth: 1,
    flexDirection: 'row',
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 8,
  },
  activityText: {
    color: '#d9d2c8',
    flex: 1,
    fontSize: 12,
  },
  composer: {
    alignItems: 'flex-end',
    borderTopColor: '#282520',
    borderTopWidth: 1,
    flexDirection: 'row',
    gap: 10,
    paddingHorizontal: 12,
    paddingBottom: Platform.OS === 'android' ? 8 : 12,
    paddingTop: 10,
  },
  attachButton: {
    alignItems: 'center',
    height: 44,
    justifyContent: 'center',
    width: 32,
  },
  attachmentBar: {
    borderTopColor: '#282520',
    borderTopWidth: 1,
    maxHeight: 84,
  },
  attachmentBarContent: {
    gap: 8,
    padding: 10,
  },
  attachmentChip: {
    alignItems: 'center',
    backgroundColor: '#1d1b18',
    borderColor: '#34302a',
    borderRadius: 12,
    borderWidth: 1,
    flexDirection: 'row',
    gap: 8,
    maxWidth: 200,
    paddingLeft: 6,
    paddingRight: 26,
    paddingVertical: 6,
  },
  attachmentThumb: {
    backgroundColor: '#2a2620',
    borderRadius: 8,
    height: 56,
    width: 56,
  },
  attachmentThumbIcon: {
    alignItems: 'center',
    justifyContent: 'center',
  },
  attachmentName: {
    color: '#d9d2c8',
    flexShrink: 1,
    fontSize: 12,
  },
  attachmentRemove: {
    alignItems: 'center',
    backgroundColor: '#d9d2c8',
    borderRadius: 9,
    height: 18,
    justifyContent: 'center',
    position: 'absolute',
    right: 4,
    top: 4,
    width: 18,
  },
  composerInput: {
    backgroundColor: '#1d1b18',
    borderColor: '#34302a',
    borderRadius: 16,
    borderWidth: 1,
    color: '#f4f0e8',
    flex: 1,
    fontSize: 16,
    maxHeight: 128,
    minHeight: 48,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  sendButton: {
    alignItems: 'center',
    backgroundColor: '#f4f0e8',
    borderRadius: 15,
    height: 48,
    justifyContent: 'center',
    width: 68,
  },
  sendButtonText: {
    color: '#12110f',
    fontSize: 14,
    fontWeight: '800',
  },
  drawerBackdrop: {
    ...StyleSheet.absoluteFillObject,
    flexDirection: 'row',
    zIndex: 20,
  },
  drawerShade: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(0,0,0,0.45)',
  },
  drawer: {
    backgroundColor: '#171511',
    borderRightColor: '#34302a',
    borderRightWidth: 1,
    height: '100%',
    padding: 14,
    width: 318,
  },
  drawerHeader: {
    alignItems: 'center',
    flexDirection: 'row',
    justifyContent: 'space-between',
    marginBottom: 12,
  },
  drawerTitle: {
    color: '#f4f0e8',
    fontSize: 20,
    fontWeight: '800',
  },
  closeButton: {
    alignItems: 'center',
    height: 36,
    justifyContent: 'center',
    width: 36,
  },
  closeButtonText: {
    color: '#f4f0e8',
    fontSize: 28,
  },
  newProjectButton: {
    alignItems: 'center',
    backgroundColor: '#f4f0e8',
    borderRadius: 12,
    height: 44,
    justifyContent: 'center',
    marginBottom: 12,
  },
  newProjectText: {
    color: '#12110f',
    fontSize: 14,
    fontWeight: '800',
  },
  projectList: {
    flex: 1,
  },
  projectItem: {
    backgroundColor: '#201e1a',
    borderColor: '#34302a',
    borderRadius: 12,
    borderWidth: 1,
    marginBottom: 8,
    padding: 12,
    position: 'relative',
  },
  projectItemActive: {
    borderColor: '#f4f0e8',
  },
  projectTitle: {
    color: '#f4f0e8',
    fontSize: 14,
    fontWeight: '800',
  },
  projectMeta: {
    color: '#a7a19a',
    fontSize: 12,
    lineHeight: 17,
    marginTop: 5,
  },
  projectTime: {
    color: '#7c766f',
    fontSize: 11,
    marginTop: 7,
  },
  drawerUnreadBadge: {
    alignItems: 'center',
    backgroundColor: '#ff5a3d',
    borderRadius: 12,
    minWidth: 24,
    height: 24,
    justifyContent: 'center',
    paddingHorizontal: 7,
    position: 'absolute',
    right: 10,
    top: 10,
  },
  drawerFooter: {
    borderTopColor: '#282520',
    borderTopWidth: 1,
    gap: 8,
    paddingTop: 12,
  },
  drawerAction: {
    backgroundColor: '#22201c',
    borderColor: '#34302a',
    borderRadius: 12,
    borderWidth: 1,
    padding: 12,
  },
  drawerActionText: {
    color: '#d9d2c8',
    fontSize: 13,
    fontWeight: '700',
  },
});

import { StatusBar } from 'expo-status-bar';
import * as Device from 'expo-device';
import * as Notifications from 'expo-notifications';
import * as SecureStore from 'expo-secure-store';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  BackHandler,
  FlatList,
  Image,
  KeyboardAvoidingView,
  Linking,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';
import EventSource from 'react-native-sse';
import { WebView } from 'react-native-webview';

const API_BASE_URL = 'https://frontend-mikis-projects-86652663.vercel.app';
const TOKEN_KEY = 'done_mobile_access_token';
const PROJECT_KEY = 'done_mobile_project_id';
const EAS_PROJECT_ID = 'db295575-26c1-4088-99aa-4887eb27e2e2';

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

type MessageResponse = {
  id: string;
  room_id?: string;
  sender_name: string;
  sender_type: 'human' | 'ai' | string;
  content: string;
  created_at: string;
};

type ProjectResponse = {
  id: string;
  title: string;
  description?: string | null;
  status?: string;
  room_id?: string | null;
  summary?: string | null;
  icon?: string | null;
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
    throw new Error(detail || `Request failed: ${response.status}`);
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
  return project.updated_at || project.created_at;
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

function RichMessageContent({
  content,
  mine,
  onOpenUrl,
}: {
  content: string;
  mine: boolean;
  onOpenUrl: (url: string) => void;
}) {
  const parsed = useMemo(() => parseRichContent(content), [content]);

  return (
    <View style={styles.messageContentWrap}>
      {parsed.images.map((url, index) => (
        <Pressable key={`${url}-${index}`} onPress={() => onOpenUrl(url)}>
          <Image resizeMode="contain" source={{ uri: url }} style={styles.messageImage} />
        </Pressable>
      ))}

      {parsed.videos.map((video, index) => (
        <Pressable
          key={`${video.url}-${index}`}
          onPress={() => onOpenUrl(video.url)}
          style={[styles.mediaCard, mine && styles.myMediaCard]}
        >
          <Text style={[styles.mediaCardTitle, mine && styles.myMessageText]} numberOfLines={1}>
            動画を開く
          </Text>
          <Text style={[styles.mediaCardUrl, mine && styles.myMediaCardUrl]} numberOfLines={2}>
            {video.name || video.url}
          </Text>
        </Pressable>
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
              <Text key={`${part.value}-${index}`}>{part.value}</Text>
            ),
          )}
        </Text>
      ) : null}
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

    const timeout = setTimeout(() => {
      source.close();
      reject(new Error('DAN response timed out.'));
    }, 1000 * 60 * 10);

    source.addEventListener('message', (event) => {
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

export default function App() {
  const [auth, setAuth] = useState<AuthState>({ status: 'checking' });
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loginBusy, setLoginBusy] = useState(false);
  const [messages, setMessages] = useState<MessageResponse[]>([]);
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [currentProjectId, setCurrentProjectId] = useState<string | null>(null);
  const [currentProject, setCurrentProject] = useState<ProjectResponse | null>(null);
  const [draft, setDraft] = useState('');
  const [loadingMessages, setLoadingMessages] = useState(false);
  const [loadingProjects, setLoadingProjects] = useState(false);
  const [sending, setSending] = useState(false);
  const [activity, setActivity] = useState('');
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [screen, setScreen] = useState<'projects' | 'chat' | 'artifact'>('projects');
  const [artifacts, setArtifacts] = useState<ChatArtifactResponse[]>([]);
  const [loadingArtifacts, setLoadingArtifacts] = useState(false);
  const [artifactView, setArtifactView] = useState<{ title: string; url: string } | null>(null);
  const [notificationStatus, setNotificationStatus] = useState('Off');
  const listRef = useRef<FlatList<MessageResponse>>(null);

  const token = auth.status === 'signed_in' ? auth.token : undefined;
  const user = auth.status === 'signed_in' ? auth.user : undefined;

  const newestMessages = useMemo(
    () =>
      [...messages].sort(
        (a, b) =>
          new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
      ),
    [messages],
  );

  const headerTitle = currentProject?.title || 'DAN';

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
        return project;
      } catch (error) {
        Alert.alert('Load failed', String((error as Error).message));
        return null;
      } finally {
        setLoadingMessages(false);
      }
    },
    [refreshArtifacts],
  );

  const loadInitialData = useCallback(
    async (activeToken: string) => {
      await refreshProjects(activeToken);
      setCurrentProject(null);
      setCurrentProjectId(null);
      setMessages([]);
      setArtifacts([]);
      setArtifactView(null);
      setScreen('projects');
    },
    [refreshProjects],
  );

  useEffect(() => {
    let alive = true;
    async function restoreSession() {
      const storedToken = await SecureStore.getItemAsync(TOKEN_KEY);
      if (!storedToken) {
        if (alive) setAuth({ status: 'signed_out' });
        return;
      }

      try {
        const restoredUser = await apiRequest<UserResponse>('/chat/me', {}, storedToken);
        if (!alive) return;
        setAuth({ status: 'signed_in', token: storedToken, user: restoredUser });
        await loadInitialData(storedToken);
      } catch {
        await SecureStore.deleteItemAsync(TOKEN_KEY);
        await SecureStore.deleteItemAsync(PROJECT_KEY);
        if (alive) setAuth({ status: 'signed_out' });
      }
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
    if (!token || sending) return;
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
    if (!token || sending) return;
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

  async function handleEnableNotifications() {
    if (!token) return;
    if (!Device.isDevice) {
      setNotificationStatus('Physical device required');
      return;
    }

    try {
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
      setNotificationStatus('On');
    } catch (error) {
      setNotificationStatus('Failed');
      Alert.alert('Notification setup failed', String((error as Error).message));
    }
  }

  async function handleSend() {
    if (!token || sending) return;
    const content = draft.trim();
    if (!content) return;

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
    setSending(true);
    setActivity('DAN is working...');

    const optimistic: MessageResponse = {
      id: `local-${Date.now()}`,
      room_id: project.room_id,
      sender_name: 'You',
      sender_type: 'human',
      content,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimistic]);

    let selectedProjectId = project.id;

    try {
      await streamDanMessage(token, content, project.room_id, (event) => {
        if (event.created_project_id && event.created_project_id !== selectedProjectId) {
          selectedProjectId = event.created_project_id;
          setCurrentProjectId(event.created_project_id);
          SecureStore.setItemAsync(PROJECT_KEY, event.created_project_id).catch(() => null);
        }

        if (event.type === 'process') {
          const step = event.step as { label?: string } | undefined;
          setActivity(step?.label || 'DAN is working...');
        } else if (event.type === 'user_message' && isMessageResponse(event.message)) {
          const incoming = event.message;
          setMessages((current) =>
            upsertMessage(
              current.filter((message) => message.id !== optimistic.id),
              incoming,
            ),
          );
        } else if (event.type === 'ai_message' && isMessageResponse(event.message)) {
          const incoming = event.message;
          setMessages((current) => upsertMessage(current, incoming));
        } else if (event.type === 'done') {
          setActivity('Done');
        }
      });

      const list = await refreshProjects(token).catch(() => projects);
      const nextProject =
        list.find((item) => item.id === selectedProjectId) ||
        list.find((item) => item.room_id === project?.room_id) ||
        project;
      if (nextProject?.id) {
        await loadProjectMessages(token, nextProject.id);
      }
    } catch (error) {
      setDraft(content);
      setMessages((current) => current.filter((message) => message.id !== optimistic.id));
      Alert.alert('Send failed', String((error as Error).message));
    } finally {
      setSending(false);
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
    return normalizeUrl(
      artifact.share_url ||
        artifact.draft_url ||
        artifact.preview_url ||
        `/preview/${artifact.slug}`,
    );
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
        <Text style={styles.mutedText}>Loading DAN</Text>
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
          <Text style={styles.title}>DAN</Text>
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
      <SafeAreaView style={styles.screen}>
        <StatusBar style="light" />
        <View style={styles.listHeader}>
          <View style={styles.headerCenter}>
            <Text style={styles.listTitle}>DAN</Text>
            <Text style={styles.headerMeta} numberOfLines={1}>
              {user?.email}
            </Text>
          </View>
          <Pressable
            disabled={loadingProjects}
            onPress={handleRefreshProjectList}
            style={styles.iconButton}
          >
            <Text style={styles.iconButtonText}>↻</Text>
          </Pressable>
        </View>

        <FlatList
          contentContainerStyle={styles.projectListContent}
          data={projects}
          keyExtractor={(item) => item.id}
          ListEmptyComponent={
            <View style={styles.centerPanel}>
              {loadingProjects ? (
                <ActivityIndicator color="#f4f0e8" />
              ) : (
                <>
                  <Text style={styles.emptyTitle}>DAN</Text>
                  <Text style={styles.mutedText}>No chats yet</Text>
                </>
              )}
            </View>
          }
          renderItem={({ item }) => (
            <Pressable
              onPress={() => handleSelectProject(item.id)}
              style={({ pressed }) => [
                styles.chatListItem,
                pressed && styles.buttonPressed,
              ]}
            >
              <View style={styles.chatAvatar}>
                <Text style={styles.chatAvatarText}>{item.icon || 'D'}</Text>
              </View>
              <View style={styles.chatListBody}>
                <View style={styles.chatListTopRow}>
                  <Text style={styles.chatListTitle} numberOfLines={1}>
                    {item.title || 'Untitled'}
                  </Text>
                  <Text style={styles.chatListTime}>{formatTime(projectTime(item))}</Text>
                </View>
                <Text style={styles.chatListPreview} numberOfLines={2}>
                  {item.summary || item.description || 'No summary yet'}
                </Text>
              </View>
            </Pressable>
          )}
        />

        <View style={styles.listFooter}>
          <Pressable onPress={handleNewProject} style={styles.newProjectButton}>
            <Text style={styles.newProjectText}>New chat</Text>
          </Pressable>
          <Pressable onPress={handleEnableNotifications} style={styles.secondaryFooterButton}>
            <Text style={styles.secondaryFooterButtonText}>Notifications: {notificationStatus}</Text>
          </Pressable>
          <Pressable onPress={handleLogout} style={styles.secondaryFooterButton}>
            <Text style={styles.secondaryFooterButtonText}>Log out</Text>
          </Pressable>
        </View>
      </SafeAreaView>
    );
  }

  if (screen === 'artifact' && artifactView) {
    return (
      <SafeAreaView style={styles.screen}>
        <StatusBar style="light" />
        <View style={styles.header}>
          <Pressable onPress={() => setScreen(currentProject ? 'chat' : 'projects')} style={styles.iconButton}>
            <Text style={styles.iconButtonText}>{'<'}</Text>
          </Pressable>
          <View style={styles.headerCenter}>
            <Text style={styles.headerTitle} numberOfLines={1}>
              {artifactView.title}
            </Text>
            <Text style={styles.headerMeta} numberOfLines={1}>
              {artifactView.url}
            </Text>
          </View>
          <Pressable onPress={() => openUrl(artifactView.url)} style={styles.iconButton}>
            <Text style={styles.iconButtonText}>{'Open'}</Text>
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
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.screen}>
      <StatusBar style="light" />
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 8 : 0}
        style={styles.chatWrap}
      >
        <View style={styles.header}>
          <Pressable onPress={handleBackToProjects} style={styles.iconButton}>
            <Text style={styles.iconButtonText}>‹</Text>
          </Pressable>
          <View style={styles.headerCenter}>
            <Text style={styles.headerTitle} numberOfLines={1}>
              {headerTitle}
            </Text>
            <Text style={styles.headerMeta} numberOfLines={1}>
              {user?.email}
            </Text>
          </View>
          <Pressable
            disabled={loadingMessages || !token || !currentProjectId}
            onPress={() => token && currentProjectId && loadProjectMessages(token, currentProjectId)}
            style={styles.iconButton}
          >
            <Text style={styles.iconButtonText}>↻</Text>
          </Pressable>
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

        {loadingMessages && newestMessages.length === 0 ? (
          <View style={styles.centerPanel}>
            <ActivityIndicator color="#f4f0e8" />
            <Text style={styles.mutedText}>Loading history</Text>
          </View>
        ) : newestMessages.length === 0 ? (
          <View style={styles.centerPanel}>
            <Text style={styles.emptyTitle}>DAN</Text>
            <Text style={styles.mutedText}>メッセージを入力してください</Text>
          </View>
        ) : (
          <FlatList
            contentContainerStyle={styles.messageList}
            data={newestMessages}
            initialNumToRender={14}
            inverted
            keyExtractor={(item) => item.id}
            maxToRenderPerBatch={8}
            ref={listRef}
            removeClippedSubviews
            renderItem={({ item }) => {
              const mine = item.sender_type === 'human';
              return (
                <View style={[styles.messageBubble, mine ? styles.myBubble : styles.aiBubble]}>
                  <View style={styles.messageMetaRow}>
                    <Text style={styles.messageSender}>{mine ? 'You' : item.sender_name || 'DAN'}</Text>
                    <Text style={styles.messageTime}>{formatTime(item.created_at)}</Text>
                  </View>
                  <RichMessageContent content={item.content} mine={mine} onOpenUrl={handleOpenMessageUrl} />
                </View>
              );
            }}
            updateCellsBatchingPeriod={30}
            windowSize={7}
          />
        )}

        {activity ? (
          <View style={styles.activityBar}>
            <ActivityIndicator color="#d9d2c8" size="small" />
            <Text style={styles.activityText} numberOfLines={2}>
              {activity}
            </Text>
          </View>
        ) : null}

        <View style={styles.composer}>
          <TextInput
            multiline
            onChangeText={setDraft}
            placeholder="Ask DAN"
            placeholderTextColor="#77736b"
            style={styles.composerInput}
            value={draft}
          />
          <Pressable
            disabled={sending || !draft.trim()}
            onPress={handleSend}
            style={({ pressed }) => [
              styles.sendButton,
              (pressed || sending || !draft.trim()) && styles.buttonPressed,
            ]}
          >
            {sending ? (
              <ActivityIndicator color="#111" />
            ) : (
              <Text style={styles.sendButtonText}>Send</Text>
            )}
          </Pressable>
        </View>
      </KeyboardAvoidingView>

      {drawerOpen ? (
        <View style={styles.drawerBackdrop}>
          <Pressable style={styles.drawerShade} onPress={() => setDrawerOpen(false)} />
          <View style={styles.drawer}>
            <View style={styles.drawerHeader}>
              <Text style={styles.drawerTitle}>Projects</Text>
              <Pressable onPress={() => setDrawerOpen(false)} style={styles.closeButton}>
                <Text style={styles.closeButtonText}>×</Text>
              </Pressable>
            </View>
            <Pressable onPress={handleNewProject} style={styles.newProjectButton}>
              <Text style={styles.newProjectText}>New chat</Text>
            </Pressable>
            <ScrollView style={styles.projectList}>
              {loadingProjects ? <ActivityIndicator color="#f4f0e8" /> : null}
              {projects.map((project) => (
                <Pressable
                  key={project.id}
                  onPress={() => handleSelectProject(project.id)}
                  style={[
                    styles.projectItem,
                    project.id === currentProjectId && styles.projectItemActive,
                  ]}
                >
                  <Text style={styles.projectTitle} numberOfLines={1}>
                    {project.icon ? `${project.icon} ` : ''}
                    {project.title || 'Untitled'}
                  </Text>
                  <Text style={styles.projectMeta} numberOfLines={2}>
                    {project.summary || project.description || 'No summary yet'}
                  </Text>
                  <Text style={styles.projectTime}>{formatTime(projectTime(project))}</Text>
                </Pressable>
              ))}
            </ScrollView>
            <View style={styles.drawerFooter}>
              <Pressable onPress={handleEnableNotifications} style={styles.drawerAction}>
                <Text style={styles.drawerActionText}>Notifications: {notificationStatus}</Text>
              </Pressable>
              <Pressable onPress={handleLogout} style={styles.drawerAction}>
                <Text style={styles.drawerActionText}>Log out</Text>
              </Pressable>
            </View>
          </View>
        </View>
      ) : null}
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  screen: {
    flex: 1,
    backgroundColor: '#12110f',
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
    width: 260,
  },
  mediaCard: {
    backgroundColor: '#15130f',
    borderColor: '#34302a',
    borderRadius: 12,
    borderWidth: 1,
    gap: 3,
    padding: 10,
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

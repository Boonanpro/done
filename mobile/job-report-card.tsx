// 並行作業の報告の札（作業の名前と「終わった／止まった」の1行）。押すと報告の全文が開く。
// PC（frontend/src/components/layout/project-chat-panel.tsx の JobReportCard）・開発室のチャットと同じ形（2026-10-23）。
// 読み手は chat-shapes-job-report.ts（PC と同じ物の写し）。本文の描き方は呼び出し側が渡す（アプリの吹き出しの文章と同じ描き方）。
import { useState, type ReactNode } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import { Ionicons } from '@expo/vector-icons';

import { ShapeMessageContext } from './chat-shapes';
import { JOB_STATE_TEXT, type JobReport } from './chat-shapes-job-report';

export function JobReportCard({ report, messageId, renderBody }: { report: JobReport; messageId: string; renderBody: (body: string) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const stopped = report.state === 'stopped';
  return (
    <View style={styles.wrap}>
      <Pressable onPress={() => setOpen((o) => !o)} accessibilityRole="button" accessibilityState={{ expanded: open }} style={styles.chip} hitSlop={6}>
        <Ionicons name={stopped ? 'alert-circle' : 'checkmark-circle'} size={15} color={stopped ? '#c98a00' : '#2f9e5b'} />
        <Text style={styles.title} numberOfLines={1}>{report.title}</Text>
        <Text style={styles.state}>{JOB_STATE_TEXT[report.state]}</Text>
        <Ionicons name={open ? 'chevron-down' : 'chevron-forward'} size={13} color="#59685f" />
      </Pressable>
      {open ? (
        <View style={styles.body}>
          <ShapeMessageContext.Provider value={messageId}>{renderBody(report.body)}</ShapeMessageContext.Provider>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignSelf: 'flex-start', maxWidth: '92%', marginVertical: 4, gap: 6 },
  chip: { flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start', maxWidth: '100%', borderWidth: 1, borderColor: '#dbe2da', backgroundColor: '#f1f4f1', borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6 },
  title: { fontSize: 14, fontWeight: '600', color: '#1f2724', flexShrink: 1 },
  state: { fontSize: 13, color: '#59685f' },
  body: { borderWidth: 1, borderColor: '#dbe2da', backgroundColor: '#ffffff', borderRadius: 14, padding: 12 },
});

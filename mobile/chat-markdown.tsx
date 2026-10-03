// チャットの本文を「段落・見出し・表」に分けて描く（スマホでも表が表として読めるように）。
// 文中の太字・リンクなどは呼び出し側の renderText に任せる（これまでと同じ描き方）。
import { Fragment, type ReactNode } from 'react';
import { Platform, ScrollView, StyleSheet, Text, View, type StyleProp, type TextStyle } from 'react-native';

import { splitMarkdownBlocks } from './markdown-blocks';

export { splitLinks } from './markdown-blocks';

function isDiff(block: { lang: string; text: string }) {
  if (/^(diff|patch)$/i.test(block.lang)) return true;
  const lines = block.text.split('\n').filter((l) => l.trim());
  const marked = lines.filter((l) => /^[+-](?![+-]{2})|^@@/.test(l)).length;
  return lines.length >= 2 && marked / lines.length >= 0.5;
}

function columnWidth(texts: string[]): number {
  const longest = Math.max(...texts.map((t) => Array.from(t).reduce((n, ch) => n + (ch.charCodeAt(0) > 0xff ? 2 : 1), 0)));
  return Math.max(56, Math.min(220, longest * 7.5 + 20));
}

export function ChatMarkdown({
  text,
  textStyle,
  renderText,
}: {
  text: string;
  textStyle: StyleProp<TextStyle>;
  renderText: (text: string, key: string) => ReactNode;
}) {
  const blocks = splitMarkdownBlocks(text);
  return (
    <>
      {blocks.map((block, index) => {
        if (block.kind === 'heading') {
          return (
            <Text key={index} selectable style={[textStyle, styles.heading]}>
              {renderText(block.text, `h${index}`)}
            </Text>
          );
        }
        if (block.kind === 'code' && isDiff(block)) {
          // 変更の差分: 足した行は緑、消した行は赤（Beautiful UI の Code Block の差分表示を見本に）
          return (
            <View key={index} style={styles.code}>
              {block.lang ? <Text style={styles.codeLang}>{block.lang}</Text> : null}
              <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                <View>
                  {block.text.split('\n').map((line, i) => {
                    const kind = line.startsWith('+') && !line.startsWith('+++') ? 'add' : line.startsWith('-') && !line.startsWith('---') ? 'del' : line.startsWith('@@') ? 'hunk' : '';
                    return (
                      <Text key={i} selectable style={[styles.codeText, kind === 'add' && styles.diffAdd, kind === 'del' && styles.diffDel, kind === 'hunk' && styles.diffHunk]}>
                        {line || ' '}
                      </Text>
                    );
                  })}
                </View>
              </ScrollView>
            </View>
          );
        }
        if (block.kind === 'code') {
          // コードは等幅・折り返さず横にずらして読む。長押しで選んでコピーできる。
          return (
            <View key={index} style={styles.code}>
              {block.lang ? <Text style={styles.codeLang}>{block.lang}</Text> : null}
              <ScrollView horizontal showsHorizontalScrollIndicator={false}>
                <Text selectable style={styles.codeText}>{block.text}</Text>
              </ScrollView>
            </View>
          );
        }
        if (block.kind === 'table') {
          const count = Math.max(block.header.length, ...block.rows.map((r) => r.length));
          const widths = Array.from({ length: count }, (_, c) => columnWidth([block.header[c] || '', ...block.rows.map((r) => r[c] || '')]));
          const row = (cellsOf: string[], header: boolean, key: string) => (
            <View key={key} style={[styles.row, header && styles.headerRow]}>
              {widths.map((width, c) => (
                <View key={c} style={[styles.cell, { width }, c > 0 && styles.cellDivider]}>
                  <Text selectable style={[textStyle, styles.cellText, header && styles.headerText]}>
                    {renderText(cellsOf[c] || '', `${key}-${c}`)}
                  </Text>
                </View>
              ))}
            </View>
          );
          return (
            <ScrollView key={index} horizontal showsHorizontalScrollIndicator={false} style={styles.tableScroll}>
              <View style={styles.table}>
                {row(block.header, true, `t${index}-h`)}
                {block.rows.map((r, ri) => (
                  <Fragment key={ri}>{row(r, false, `t${index}-${ri}`)}</Fragment>
                ))}
              </View>
            </ScrollView>
          );
        }
        return (
          <Text key={index} selectable style={textStyle}>
            {renderText(block.text, `p${index}`)}
          </Text>
        );
      })}
    </>
  );
}

const styles = StyleSheet.create({
  heading: { fontWeight: '800', fontSize: 16, marginTop: 4 },
  tableScroll: { flexGrow: 0 },
  table: { borderWidth: StyleSheet.hairlineWidth * 2, borderColor: 'rgba(110,120,115,0.35)', borderRadius: 8, overflow: 'hidden' },
  row: { flexDirection: 'row', borderTopWidth: StyleSheet.hairlineWidth * 2, borderTopColor: 'rgba(110,120,115,0.25)' },
  headerRow: { backgroundColor: 'rgba(36,94,73,0.08)', borderTopWidth: 0 },
  cell: { paddingHorizontal: 8, paddingVertical: 6 },
  cellDivider: { borderLeftWidth: StyleSheet.hairlineWidth * 2, borderLeftColor: 'rgba(110,120,115,0.25)' },
  cellText: { fontSize: 13, lineHeight: 19 },
  headerText: { fontWeight: '700' },
  code: { backgroundColor: '#1f2724', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, gap: 4 },
  codeLang: { color: '#8fa69b', fontSize: 11, letterSpacing: 0.4 },
  diffAdd: { backgroundColor: 'rgba(76,175,110,0.22)', color: '#bdf0cc' },
  diffDel: { backgroundColor: 'rgba(220,90,80,0.22)', color: '#ffc9c2' },
  diffHunk: { color: '#8fb3d9' },
  codeText: { color: '#e4ece8', fontSize: 12.5, lineHeight: 19, fontFamily: Platform.OS === 'ios' ? 'Menlo' : 'monospace' },
});

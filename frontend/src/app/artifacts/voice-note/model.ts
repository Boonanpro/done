export const ROOM_ID = 'e47f056e-77b1-4e39-9173-4a01dfadbc03';
export const KIND = 'voice_note_workspace';
export type Article = {
  title: string; transcript: string; free: string; paid: string;
  price: number; audio: {name: string; url: string}[];
  status: '素材' | '編集中' | '確認待ち' | '公開済み';
  noteUrl: string; scheduledAt: string; purchases: number; gross: number;
  received: number; salesMonth: string; checkedAt: string; questions: string[];
};
export type Row = {id: string; properties: Record<string, unknown>; content: unknown; updated_at: string};
export const emptyArticle = (): Article => ({title:'無題の記事',transcript:'',free:'',paid:'',price:0,audio:[],status:'素材',noteUrl:'',scheduledAt:'',purchases:0,gross:0,received:0,salesMonth:new Date().toLocaleDateString('sv-SE',{timeZone:'Asia/Tokyo'}).slice(0,7),checkedAt:'',questions:[]});
export function articleOf(row: Row): Article { return {...emptyArticle(), ...(row.properties.article as Partial<Article> || {})}; }
export function validArticle(a: Article): string | null {
  if (!Number.isInteger(a.price) || a.price < 0) return '価格は0以上の整数で入力してください。';
  if ([a.purchases,a.gross,a.received].some(n=>!Number.isFinite(n)||n<0)) return '実績は0以上の数値で入力してください。';
  if (a.noteUrl && !/^https:\/\/note\.com\/[^/]+\/n\/n[a-zA-Z0-9]+(?:\?.*)?$/.test(a.noteUrl)) return '公開記事のnote URLを入力してください。';
  return null;
}
export function editorialRequest(id: string) {
  return `音声noteの記事制作を実行してください。対象は非公開blocksの ${id}（所有者の権限で取得）。D:/done/frontend/src/app/artifacts/voice-note/WORKFLOW.mdに従い、properties.article.transcriptとaudioの音声を素材にする。音声は実際に文字起こしし、原文をtranscriptに保存。タイトル、無料本文、有料本文、適切な価格案、確認事項を作り、元のpropertiesを保持してarticleだけ更新する。体験・実績を捏造しない。素材が足りなければquestionsに短い質問を残す。statusは確認待ち。まだnoteへ送信・公開しない。処理が終わったら保存結果を確認し、この部屋で短く報告。`;
}
export function publishRequest(id: string) {
  return `音声noteの記事 ${id} について、保存済みのタイトル・無料本文・有料本文・価格を確認したのでnoteへの投稿を承認します。D:/done/frontend/src/app/artifacts/voice-note/WORKFLOW.mdに従い、所有者のデータを取得し、接続先noteの本人アカウントを確認して、見出し・太字・有料ラインを反映して投稿してください。scheduledAtがあればその日時に公開し、未来ならwatchで登録してください。二重投稿を避け、既にnoteUrlがあれば既存記事を確認してください。公開成功を実ページで確認できた場合だけnoteUrlとstatusを更新。失敗・未接続は公開済みにしない。`;
}

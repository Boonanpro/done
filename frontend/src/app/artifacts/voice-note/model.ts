export const ROOM_ID = 'e47f056e-77b1-4e39-9173-4a01dfadbc03';
export const KIND = 'voice_note_workspace';
export type Article = {
  editorialNotes?: string;
  editorial?: {id:string; state:'running'|'done'|'error'; message:string; updatedAt:number};
  transcribedAudio?: string[];
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
export function publishRequest(id: string) {
  return `音声noteの記事 ${id} について、保存済みのタイトル・無料本文・有料本文・価格を確認したのでnoteへの投稿を承認します。D:/done/frontend/src/app/artifacts/voice-note/WORKFLOW.mdに従い、所有者のデータを取得し、接続先noteの本人アカウントを確認して、見出し・太字・有料ラインを反映して投稿してください。scheduledAtがあればその日時に公開し、未来ならwatchで登録してください。二重投稿を避け、既にnoteUrlがあれば既存記事を確認してください。公開成功を実ページで確認できた場合だけnoteUrlとstatusを更新。失敗・未接続は公開済みにしない。`;
}

export function isEmptyArticle(a: Article): boolean {
 return (!a.title.trim() || a.title==='無題の記事') && !a.transcript.trim() && !a.free.trim() && !a.paid.trim() && !a.audio.length && !a.questions.length && !a.transcribedAudio?.length && !a.editorial && a.status==='素材' && !a.noteUrl && !a.scheduledAt && !a.checkedAt && !a.price && !a.purchases && !a.gross && !a.received;
}

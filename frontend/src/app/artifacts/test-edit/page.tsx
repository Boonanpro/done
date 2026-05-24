/**
 * Inspector の手動編集を実機テストするためのページ。
 * - 様々な data-edit-id 持ち/無しのパターン
 * - wrapper、self-closing、ネスト構造
 * 本番には公開しない。test-inspector ハーネスから読み込まれる。
 */
import { InspectorRuntime } from '@/components/dan/inspector-runtime';

export default function TestEditPage() {
  return (
    <main className="min-h-screen bg-slate-50 p-8 text-slate-900">
      <InspectorRuntime slug="test-edit" />
      <h1 data-edit-id="te-h1" className="text-3xl font-bold">
        Hello Test
      </h1>
      <p data-edit-id="te-p-direct" className="mt-2">
        Paragraph with data-edit-id directly.
      </p>

      <section
        data-edit-id="te-section-wrapper"
        className="mt-6 rounded-md border border-slate-200 bg-white p-4"
      >
        <h2 data-edit-id="te-section-h2" className="text-xl font-semibold">
          Section title
        </h2>
        <p data-edit-id="te-section-body" className="mt-1 text-sm">
          Body text inside the section.
        </p>
      </section>

      {/* wrapper without data-edit-id, but children have it */}
      <div className="mt-6 rounded-md border border-dashed border-slate-300 p-4">
        <p data-edit-id="te-wrapper-child" className="text-sm">
          I am inside a wrapper that lacks data-edit-id.
        </p>
      </div>

      {/* element with no data-edit-id, no descendant either */}
      <div className="mt-6 rounded-md bg-amber-50 p-4 text-sm text-amber-900">
        This whole block has no data-edit-id, neither do its children.
      </div>

      <p data-edit-id="te-final" className="mt-6 text-xs text-slate-500">
        Final paragraph.
      </p>

      {/* 太字消滅バグの再現ケース: <p> は data-edit-id 持ちだが子に <strong> あり。
          原則「子 Element を持つ要素は text 編集不可」により dblclick が拒否されるはず。 */}
      <p data-edit-id="te-strong-mixed" className="mt-6">
        前 <strong>太字部分</strong> 後
      </p>

      {/* 装飾そのものを編集できる正しい構造: <strong> 自身が data-edit-id を持ち、leaf。 */}
      <strong data-edit-id="te-strong-only" className="mt-4 block">
        独立太字 leaf
      </strong>
    </main>
  );
}

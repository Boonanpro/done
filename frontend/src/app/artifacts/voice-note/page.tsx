import { EditableProvider } from '@/components/dan/editable';
import { toEditableOverrides, type ReleaseOverrides } from '@/lib/editable-release';
import { PageBody } from './page-body';
import release from './release.gen.json';

export const metadata = { title: "話して、noteに。" };
export default function Page() {
  return <EditableProvider overrides={toEditableOverrides(release as ReleaseOverrides)}>
    <div data-dan-artifact="voice-note"><PageBody /></div>
  </EditableProvider>;
}

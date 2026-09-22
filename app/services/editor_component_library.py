"""Read curated source without exposing arbitrary filesystem paths."""
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
MANIFEST=ROOT/'docs/component-library.json'
SOURCES=ROOT/'app/data/component-library'


def read(ident, file=None):
    rows=json.loads(MANIFEST.read_text(encoding='utf-8')) if MANIFEST.exists() else []
    row=next((r for r in rows if r['id']==ident and r.get('inspection')!='pending'),None)
    if row is None:raise ValueError('Unknown or unverified component')
    files={r['file']:r for r in row['files']}
    output={k:row.get(k) for k in ('id','title','description','source_url','revision','license','variables','dimensions','duration','files','use_cases','limitations','quality_evidence')}
    output['quality_status']=row.get('quality_status','unreviewed')
    output['technical_inspection']=row.get('inspection')
    output['quality_note']='Playback inspection is not aesthetic approval. Verify motion and adaptation against a concrete quality reference before using as a finished component.'
    output['source_directory']=str(SOURCES/row['component'])
    output['note']='保存済みの元実装。既存6部品に置き換える必要はない。改変したHTML/GSAPはpresent_referencesのscene.htmlで直接表示できる。単一のpaused timelineをwindow.__timelinesに登録し、GSAP以外の外部依存はそのプレビューでは使わない。見本の文言・数字は例示でありユーザーの事実ではない。外部フォント/画像/JS依存は元ソースで確認する。'
    if file is not None:
        if file not in files or Path(file).suffix.lower() not in ('.html','.js','.css','.json','.svg','.txt','.md'):
            raise ValueError('Choose a listed text source file')
        source=(SOURCES/row['component']/file).resolve()
        if not source.is_relative_to(SOURCES.resolve()):raise ValueError('Invalid source path')
        output['file']=file;output['source']=source.read_text(encoding='utf-8')
    return output

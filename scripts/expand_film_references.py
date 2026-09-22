"""Fill the missing feature-film trailer family; URL metadata only."""
import concurrent.futures,datetime,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import yt_dlp
from scripts.build_reference_url_pilot import Quiet
QUERIES=['official movie trailer engineering science true story drama',
         'official movie trailer character drama independent film',
         'official movie trailer romantic comedy','official movie trailer science fiction thriller']
PUBLISHERS={'20th Century Studios','Netflix','A24','MUBI','Sony Pictures Entertainment',
            'Independent Film Company','Prime Video','Warner Bros.',
            'Rotten Tomatoes Classic Trailers','Rotten Tomatoes Trailers'}
def collect(query):
    options={'quiet':True,'logger':Quiet(),'extract_flat':'in_playlist','skip_download':True,'socket_timeout':20,'retries':1}
    with yt_dlp.YoutubeDL(options) as ydl:
        return query,ydl.extract_info('ytsearch5:'+query,download=False).get('entries',[])
def main():
    target=ROOT/'docs/reference-index/videos.json';data=json.loads(target.read_text(encoding='utf8'))
    known={r['id'] for r in data['references']};added=[]
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for query,entries in pool.map(collect,QUERIES):
            for r in entries:
                ident=r.get('id','');key='yt-'+ident
                if len(ident)!=11 or key in known or r.get('channel') not in PUBLISHERS:continue
                row={'id':key,'video_id':ident,'url':'https://www.youtube.com/watch?v='+ident,
                     'title':r['title'],'publisher':r.get('channel'),'publisher_id':r.get('channel_id'),
                     'duration_seconds':r.get('duration'),'views_at_discovery':r.get('view_count'),
                     'retrieved_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
                     'description_excerpt':r.get('description') or '',
                     'thumbnail_url':(r.get('thumbnails') or [{}])[-1].get('url'),
                     'labels':{'primary_genre':'film_trailer','genre_probabilities':{'film_trailer':1},'related_genres':['narrative_short'],'medium':'unknown','taste':[]},
                     'label_basis':'search_metadata','visual_inspection':'not_performed',
                     'embed_status':'unchecked','discovery':{'queries':[query]}}
                known.add(key);data['references'].append(row);added.append(row)
    out=ROOT/'scratch/overall-discovery/added-references.json'
    out.write_text(json.dumps(added,ensure_ascii=False,indent=2),encoding='utf8')
    temporary=target.with_suffix('.tmp');temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');temporary.replace(target)
    print(json.dumps({'added':len(added),'titles':[r['title'] for r in added]},ensure_ascii=True))
if __name__=='__main__':main()

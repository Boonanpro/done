"""Render source-grounded editorial diagrams; never simulated evidence."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont


def insert_visuals(article, session, base, directory):
    font_path = Path('C:/Windows/Fonts/YuGothM.ttc')
    if not font_path.exists():
        font_path = Path('C:/Windows/Fonts/meiryo.ttc')
    def font(size):
        return ImageFont.truetype(str(font_path), size)
    def wrap(text, width):
        return [text[i:i+width] for i in range(0, len(text), width)]
    inserted = 0
    for i, visual in enumerate(article.get('visuals', [])[:3]):
        after = visual.get('after', '').strip()
        key = next((k for k in ('free','paid') if after and after in article[k]), None)
        items = visual.get('items', [])
        if not key or not 2 <= len(items) <= 5:
            continue
        lines = [wrap(str(v)[:70], 27) for v in items]
        height = 170 + sum(48 * len(v) + 38 for v in lines) + 80
        img = Image.new('RGB', (1120, height), '#f6f5f0')
        draw = ImageDraw.Draw(img)
        draw.text((64,38), '本文の内容を整理した図', font=font(22), fill='#66756d')
        draw.text((64,83), visual.get('title','')[:24], font=font(37), fill='#15392f')
        y=170
        for n, rows in enumerate(lines):
            draw.rounded_rectangle((55,y-9,1065,y+48*len(rows)+10),radius=12,fill='white')
            draw.text((76,y),str(n+1).zfill(2),font=font(30),fill='#16856d')
            for line in rows:
                draw.text((146,y),line,font=font(32),fill='#233b34');y+=48
            y+=38
        filename=Path(directory)/f'article-diagram-{i}.png'
        img.save(filename)
        with filename.open('rb') as f:
            response=session.post(base+'/api/v1/files/upload',files={'file':(filename.name,f,'image/png')},timeout=60)
        response.raise_for_status()
        url=response.json()['url']
        if not url.startswith('/api/v1/files/'):
            raise RuntimeError('図解の保存先を確認できませんでした。')
        caption=visual.get('caption','本文の内容を整理した図').replace('[','').replace(']','').replace('\n',' ')
        article[key]=article[key].replace(after,after+f'\n\n![{caption}]({url})\n\n',1)
        inserted+=1
    if article.get('free') and inserted==0:
        raise RuntimeError('図解の挿入位置を確認できませんでした。前の原稿を残しています。再試行してください。')
    article['editorialNotes']+='\n\n図解 '+str(inserted)+' 枚を作成し本文へ挿入済み。本文の整理図であり、実画面や実測結果ではありません。'

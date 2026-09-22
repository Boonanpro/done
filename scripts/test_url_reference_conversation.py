"""Reuse the actual editor browser harness with whole-work conversation turns."""
import ast
import asyncio
import os
from pathlib import Path

path=Path(__file__).with_name('test_visual_decision_browser.py')
source=path.read_text(encoding='utf8').replace("await page.screenshot(path=str(out/f'browser-{n+1}.png'))", "await page.wait_for_timeout(5000)\n   await page.screenshot(path=str(out/f'browser-{n+1}.png'))")
tree=ast.parse(source)
# Load definitions without executing the harness's default run.
tree.body=tree.body[:-1]
namespace={'__file__':str(path),'__name__':'url_reference_trial'}
exec(compile(tree,str(path),'exec'),namespace)
namespace['UTTERANCES']=[
 '一人で事業をしている人にダンというAIサービスを紹介するローンチ動画をYouTubeに出したい。まず発表映像の参考を見比べたい。',
 'もっと自宅で使う日常の感じがいい。静かな暮らしを見せるVlogの参考で比べたい。まだ作らないで。',
 '別の動画です。After Effectsのモーショングラフィックスの作り方を教えるチュートリアルを作りたい。参考になる動画を見せて。',
]
os.environ['DAN_TEST_OUTPUT']='scratch/reference-url-pilot/conversation'
asyncio.run(namespace['main']())

// Deterministic export of the existing, editable scene. No model calls.
const fs = require('node:fs');
const path = require('node:path');
const {createRequire} = require('node:module');
const {chromium} = createRequire('D:/MCP/package.json')('playwright-core');
async function main() {
  const [sceneFile, output, secondsArg='6', fpsArg='24'] = process.argv.slice(2);
  if (!sceneFile || !output) throw Error('Usage: node export_conte_scene.cjs scene.json output-dir [seconds] [fps]');
  const seconds=Number(secondsArg), fps=Number(fpsArg);
  if (!(seconds>0 && seconds<=30 && Number.isInteger(fps) && fps>=1 && fps<=60)) throw Error('Invalid duration/fps');
  const state=JSON.parse(fs.readFileSync(sceneFile,'utf8').replace(/^\uFEFF/,''));
  const out=path.resolve(output);fs.mkdirSync(out,{recursive:true});
  if(fs.existsSync(path.join(out,'frame-00000.png')))throw Error('Output already contains frames; use a new directory');
  const browser=await chromium.connectOverCDP('http://127.0.0.1:9223');
  const context=await browser.newContext({viewport:{width:1400,height:1000},deviceScaleFactor:1});
  try {
    await context.addInitScript(s=>localStorage.setItem('dan-conte-lab-v1',JSON.stringify(s)),state);
    const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:3018');await page.waitForFunction(()=>!!window.conteLab);
    await page.addStyleTag({content:'#stage{position:fixed;top:0;left:0;z-index:100;width:1280px;height:720px;min-height:0;border-radius:0}.layout{display:block}main{max-width:none;padding:0}.stamp{display:none}'});
    await page.waitForTimeout(100);
    const canvas=page.locator('#stage canvas');
    for(let i=0;i<Math.round(seconds*fps);i++){
      await page.evaluate(t=>new Promise(resolve=>{window.conteLab.setTime(t);requestAnimationFrame(()=>requestAnimationFrame(resolve));}),i/fps);
      await canvas.screenshot({path:path.join(out,`frame-${String(i).padStart(5,'0')}.png`)});
      if(i%fps===0)console.log(`Captured ${i/fps}/${seconds}s`);
    }
    if(errors.length)throw Error(errors.join('\n'));
    fs.writeFileSync(path.join(out,'scene.json'),JSON.stringify(state,null,2));
    fs.writeFileSync(path.join(out,'capture.json'),JSON.stringify({seconds,fps,width:1280,height:720,frames:Math.round(seconds*fps),errors},null,2));
    console.log('Saved '+out);
  }finally{await context.close();}
}
main().then(()=>process.exit(0)).catch(e=>{console.error(e);process.exit(1);});

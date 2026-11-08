// Offline checks for the app's navigation, drafts and calls. No messages or calls are sent.
const {spawnSync}=require('node:child_process');
const path=require('node:path');
function run(args) {
 const result=spawnSync(process.execPath,args,{stdio:'inherit'});
 if(result.error)console.error(result.error);
 if(result.signal)console.error(result.signal);
 if(result.status!==0)process.exit(result.status??1);
}
for(const name of ['test-collab-rooms.cjs','test-dashboard-state.cjs','test-private-artifact.cjs','test-signed-in-browser.cjs','test-send-card.cjs','test-voice-shortcut.cjs','test-voice-host.cjs']) run([path.join(__dirname,name)]);
run([path.join(__dirname,'../node_modules/typescript/bin/tsc'),'--noEmit','-p',path.join(__dirname,'../tsconfig.json')]);
console.log('PASS: mobile interaction checks and typecheck');

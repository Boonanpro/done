// Deterministic native scene. Data lives in params; every frame is seekable.
const canvas=document.createElement('canvas');canvas.width=1280;canvas.height=720;
Object.assign(canvas.style,{width:'100%',height:'100%',objectFit:'contain'});stage.append(canvas);
const ctx=canvas.getContext('2d'),W=1280,H=720;
const clamp=x=>Math.max(0,Math.min(1,x)),ease=x=>1-Math.pow(1-clamp(x),3);
const mix=(a,b,t)=>a+(b-a)*t;
function tint(a,b,k){return '#'+[1,3,5].map(i=>Math.round(mix(parseInt(a.slice(i,i+2),16),parseInt(b.slice(i,i+2),16),k)).toString(16).padStart(2,'0')).join('');}
const surface=tint(params.background,params.foreground,.085),surfaceStrong=tint(params.background,params.accent,.16);
function text(s,x,y,size=48,color=params.foreground,align='center',weight=600,max=1080){
 ctx.fillStyle=color;ctx.textAlign=align;ctx.textBaseline='middle';
 ctx.font=`${weight} ${size}px "Yu Gothic","Meiryo",sans-serif`;
 while(ctx.measureText(s).width>max&&size>20){size-=1;ctx.font=`${weight} ${size}px "Yu Gothic","Meiryo",sans-serif`;}
 ctx.fillText(s,x,y);
}
function label(s,x,y,max,size=27){
 ctx.font=`600 ${size}px "Yu Gothic","Meiryo",sans-serif`;
 const lines=[];let row='';for(const char of s){if(row&&ctx.measureText(row+char).width>max){lines.push(row);row='';}row+=char;}if(row)lines.push(row);
 lines.forEach((row,i)=>text(row,x,y+(i-(lines.length-1)/2)*(size+5),size,params.foreground,'center',600,max));
}
function box(x,y,w,h,r,fill){ctx.fillStyle=fill;ctx.beginPath();ctx.roundRect(x,y,w,h,r);ctx.fill();}
function line(x,y,x2,y2,alpha=.3){ctx.globalAlpha*=alpha;ctx.strokeStyle=params.accent;ctx.lineWidth=2;ctx.beginPath();ctx.moveTo(x,y);ctx.lineTo(x2,y2);ctx.stroke();ctx.globalAlpha/=alpha;}
function circle(x,y,r,fill){ctx.fillStyle=fill;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();}
function paint(b,t){
 const motionLength={reveal:1.3,focus:1.3,gather:1.5+.15*(b.labels.length-1),path:2,rhythm:.38*b.labels.length+.5}[b.pattern];
 // Fit the entrance into the scene while retaining a readable final hold.
 b={...b,pace:Math.max(b.pace,motionLength/(b.duration-.6))};
 const p=ease(t*b.pace/1.3),left=b.layout==='left',x=left?100:640,align=left?'left':'center';
 if(b.pattern==='reveal'){
  const r=210+35*p;ctx.globalAlpha=.09;circle(1030,280,r,params.accent);ctx.globalAlpha=1;
  box(100,150,52+120*p,4,2,params.accent);
  ctx.globalAlpha=.4+.6*p;text(b.headline,x,310+28*(1-p),76,params.foreground,align,650,1080);
  ctx.globalAlpha=ease((t-.5)*b.pace);text(b.detail,x,420,28,params.accent,align,400);ctx.globalAlpha=1;
 }else if(b.pattern==='compare'){
  text(b.headline,100,125,43,params.foreground,'left');
  for(let i=0;i<2;i++){
   const a=ease((t*b.pace-i*.45)/.8),bx=100+i*552;ctx.globalAlpha=.25+.75*a;
   box(bx,230+24*(1-a),528,290,20,i?surfaceStrong:surface);
   text(i?'02':'01',bx+35,278,20,params.accent,'left',400);
   label(b.labels[i],bx+264,374,460,42);
   box(bx+35,474,458*a,3,1,params.accent);
  }ctx.globalAlpha=1;text(b.detail,100,590,26,params.accent,'left',400);
 }else if(b.pattern==='gather'){
  text(b.headline,x,110,46,params.foreground,align);const n=b.labels.length;
  for(let i=0;i<n;i++){
   const a=ease((t*b.pace-.15*i)/1.5);
   const px=640+(i-(n-1)/2)*205,py=mix(i%2?460:230,360,a);
   box(px-94,py-55,188,110,16,surfaceStrong);label(b.labels[i],px,py,168);
  }ctx.globalAlpha=ease((t*b.pace-1.6)/.7);line(150,470,1130,470,.6);text(b.detail,640,554,30,params.accent);ctx.globalAlpha=1;
 }else if(b.pattern==='path'){
  text(b.headline,x,125,48,params.foreground,align);const n=b.labels.length;
  const total=ease(t*b.pace/2),span=980;
  line(150,340,1130,340,.18);line(150,340,150+span*total,340,.9);
  for(let i=0;i<n;i++){
   const px=150+span*i/(n-1),a=ease(t*b.pace-i*.4);ctx.globalAlpha=.2+.8*a;
   circle(px,340,13+4*a,params.accent);text(String(i+1).padStart(2,'0'),px,282,22,params.accent,'center',400);
   label(b.labels[i],px,422,190,28);
  }ctx.globalAlpha=1;text(b.detail,640,555,29,params.accent);
 }else if(b.pattern==='focus'){
  for(let i=0;i<4;i++){ctx.globalAlpha=.025+(3-i)*.013;circle(640,340,140+i*68-p*25,params.accent);}ctx.globalAlpha=1;
  ctx.save();ctx.translate(640,340);ctx.scale(.92+.08*p,.92+.08*p);text(b.headline,0,0,68,params.foreground,'center',600,1060);ctx.restore();
  ctx.globalAlpha=ease((t-.4)*b.pace);text(b.detail,640,470,29,params.accent,'center',400);ctx.globalAlpha=1;
 }else if(b.pattern==='rhythm'){
  const n=b.labels.length;
  for(let i=0;i<n;i++){
   const a=ease((t*b.pace-i*.38)/.45),yy=170+i*(340/Math.max(1,n-1));ctx.globalAlpha=a;
   text(b.labels[i],i%2?1140:140+40*(1-a),yy,i%2?54:68,i%2?params.accent:params.foreground,i%2?'right':'left',700,1000);
  }ctx.globalAlpha=ease((t*b.pace-.38*n)/.5);text(b.headline,640,620,28,params.accent);ctx.globalAlpha=1;
 }
}
setFrame(t=>{
 ctx.globalAlpha=1;ctx.fillStyle=params.background;ctx.fillRect(0,0,W,H);
 let start=0,index=params.beats.length-1,b=params.beats[index];
 for(let i=0;i<params.beats.length;i++){if(t<start+params.beats[i].duration){b=params.beats[i];index=i;break;}start+=params.beats[i].duration;}
 if(t>=params.beats.reduce((s,x)=>s+x.duration,0))start=params.beats.slice(0,-1).reduce((s,x)=>s+x.duration,0);
 const local=Math.max(0,t-start);ctx.save();
 const entrance=index===0?1:ease(local/.3);ctx.globalAlpha=entrance;paint(b,local);ctx.restore();
 ctx.globalAlpha=.45;text(params.title,100,664,16,params.foreground,'left',400,920);
 text(String(index+1).padStart(2,'0'),1180,664,16,params.foreground,'right',400);ctx.globalAlpha=1;
});

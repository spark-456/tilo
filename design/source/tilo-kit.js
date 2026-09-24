(function(){
const hx=c=>{c=c.replace('#','');return[0,2,4].map(i=>parseInt(c.slice(i,i+2),16))};
const toHex=a=>'#'+a.map(v=>Math.max(0,Math.min(255,Math.round(v))).toString(16).padStart(2,'0')).join('');
const mix=(a,b,t)=>{const A=hx(a),B=hx(b);return toHex(A.map((v,i)=>v+(B[i]-v)*t))};
const dk=(c,t)=>mix(c,'#000000',t==null?.2:t), lt=(c,t)=>mix(c,'#ffffff',t==null?.5:t);
const gray=c=>{const[r,g,b]=hx(c);const y=.3*r+.59*g+.11*b;return toHex([y,y,y])};
const ST={ok:'#1F7F44',amber:'#F0A500',amberLip:'#B97E00',red:'#D23B30',blue:'#2A6FD6',grey:'#66717A'};
const TH={
 crisp:{proj:'top',cs:'simple',hero:'#0E6A73',ink:'#16222A',ink2:'#51606A',bg:'#F5F6F4',road:'#FFFFFF',roadEdge:'#CDD4CF',dash:'#9AA6AD',hs:.85,rx:3,plots:true,body:"'Figtree',sans-serif",
  roles:{research:'#4F7DCB',builder:'#CF8249',tester:'#B38E2E',browser:'#7E68C6',connector:'#C0628A',delivery:'#6B8A3F'},
  dist:{hall:'#7F8A92',research:'#7D72C4',analysis:'#C78657',delivery:'#C4678A'},wall:.84,burst:1},
 balanced:{proj:'iso',cs:'full',hero:'#5A3FE0',ink:'#1F1D2B',ink2:'#5A5768',bg:'#F7F6F2',road:'#FFFFFF',roadEdge:'#D6D1C6',dash:'#A9A4B5',hs:1,rx:4,plots:true,body:"'Nunito Sans',sans-serif",
  roles:{research:'#3F7FE0',builder:'#E57F3E',tester:'#C9982A',browser:'#2BA3B8',connector:'#D9588C',delivery:'#76A035'},
  dist:{hall:'#7D8793',research:'#D0628C',analysis:'#D7864F',delivery:'#2B98B5'},wall:.8,burst:2},
 lively:{proj:'street',cs:'big',hero:'#D1277A',ink:'#24182A',ink2:'#5E4F63',bg:'#FFF8EF',road:'#4A3D52',roadEdge:'#2F2535',dash:'#FFFFFF',hs:1.15,rx:6,plots:false,body:"'Nunito Sans',sans-serif",
  roles:{research:'#3478F0',builder:'#F07A2E',tester:'#D9A21E',browser:'#12A7C0',connector:'#8A5CF0',delivery:'#6DAE2A'},
  dist:{hall:'#8A7F95',research:'#7C5CE0',analysis:'#E27D3F',delivery:'#1F9DBF'},wall:.74,burst:3}
};
TH.balanced2={...TH.balanced,dist:{hall:'#7D8793',research:'#2B98B5',analysis:'#D7864F',delivery:'#B35C8F'},ring:true,cscale:.7};
const B={
 townhall:{n:'Town Hall',f:3,b:'hall',r:'dome',i:'hall',d:'hall'},
 library:{n:'Library',f:2,b:'block',r:'gable',i:'search',d:'research'},
 browser:{n:'Browser Station',f:2,b:'block',r:'flat',i:'screen',d:'research'},
 workshop:{n:'Workshop',f:2,b:'hall',r:'gable',i:'make',d:'analysis'},
 testyard:{n:'Test Yard',f:2,b:'low',r:'flat',i:'flask',d:'analysis'},
 connector:{n:'Connector Post',f:1,b:'tower',r:'flat',i:'key',d:'hall'},
 vault:{n:'Memory Vault',f:2,b:'block',r:'dome',i:'vault',d:'analysis'},
 treasury:{n:'Treasury',f:1,b:'block',r:'dome',i:'coin',d:'hall'},
 watchtower:{n:'Watchtower',f:1,b:'tower',r:'gable',i:'eye',d:'hall'},
 dock:{n:'Delivery Dock',f:2,b:'low',r:'flat',i:'parcel',d:'delivery'},
 observatory:{n:'Price Observatory',f:1,b:'tower',r:'dome',i:'tag',d:'research'},
 chart:{n:'Chart Studio',f:2,b:'block',r:'gable',i:'chart',d:'analysis'},
 writing:{n:'Writing Room',f:1,b:'block',r:'gable',i:'doc',d:'delivery'}
};
const BH={low:38,block:60,tower:90,hall:50};

window.TiloKit=function(h,tk){
const T=TH[tk]||TH.crisp;
const E=(t,p,...c)=>h(t,p,...c.flat(9).filter(x=>x!=null&&x!==false));

function icon(n,c,x,y,s,bg){
 s=s||1;bg=bg||'#fff';
 const sw={stroke:c,strokeWidth:2.4,strokeLinecap:'round',strokeLinejoin:'round',fill:'none'},f={fill:c};
 const R=(x,y,w,hh,r,o)=>E('rect',{x,y,width:w,height:hh,rx:r,...(o||f)});
 const K={
  search:[E('circle',{cx:-1.5,cy:-1.5,r:4.8,...sw}),E('path',{d:'M2.2 2.2 L6.5 6.5',...sw,strokeWidth:3})],
  screen:[R(-7,-6,14,10,2.2),E('path',{d:'M-3 7 H3',...sw})],
  hall:[E('path',{d:'M-8 -2 L0 -8 L8 -2 Z',...f,stroke:c,strokeWidth:1.5,strokeLinejoin:'round'}),R(-6.5,-1,3,7.5,1),R(-1.5,-1,3,7.5,1),R(3.5,-1,3,7.5,1)],
  make:[R(-7,-7,11,6,1.8),R(-2.2,-2,3.6,10,1.6)],
  flask:[E('path',{d:'M-3.5 -7 H3.5 M-2.5 -7 V-1.5 L-6.5 6 H6.5 L2.5 -1.5 V-7',...sw})],
  key:[E('circle',{cx:-3.5,cy:0,r:3.6,...sw}),E('path',{d:'M0 0 H7.5 M5 0 V3 M7.5 0 V2.5',...sw})],
  vault:[E('circle',{cx:0,cy:0,r:6.5,...sw}),E('circle',{cx:0,cy:0,r:2.2,...f})],
  coin:[E('circle',{cx:0,cy:0,r:7,...f}),R(-1.3,-4,2.6,8,1.3,{fill:bg})],
  eye:[E('path',{d:'M-7.5 0 Q0 -7 7.5 0 Q0 7 -7.5 0 Z',...sw}),E('circle',{cx:0,cy:0,r:2.2,...f})],
  parcel:[R(-7,-5.5,14,11,2),E('path',{d:'M-7 -1 H7 M0 -5.5 V-1',stroke:bg,strokeWidth:2,strokeLinecap:'round'})],
  clock:[E('circle',{cx:0,cy:0,r:6.8,...sw}),E('path',{d:'M0 -3.5 V0 L2.8 1.8',...sw})],
  tag:[E('path',{d:'M-7 -1 L-1 -7 H7 V1 L1 7 Z',...f,stroke:c,strokeWidth:1.5,strokeLinejoin:'round'}),E('circle',{cx:3.5,cy:-3.5,r:1.6,fill:bg})],
  chart:[R(-7,0,4,7,1.2),R(-2,-4,4,11,1.2),R(3,-7,4,14,1.2)],
  doc:[R(-6,-7.5,12,15,2.2,sw),E('path',{d:'M-3 -3 H3 M-3 0.5 H3 M-3 4 H1',...sw,strokeWidth:2})],
  lock:[R(-6,-1.5,12,9,2.2),E('path',{d:'M-3.5 -1.5 V-4 Q0 -8.5 3.5 -4 V-1.5',...sw})],
  check:[E('path',{d:'M-5 0.5 L-1.5 4 L5.5 -3.5',...sw,strokeWidth:3})],
  worlds:[R(-7,-7,6,6,1.8),R(1,-7,6,6,1.8),R(-7,1,6,6,1.8),R(1,1,6,6,1.8)],
  plus:[E('path',{d:'M0 -6 V6 M-6 0 H6',...sw,strokeWidth:3})],
  inbox:[E('path',{d:'M-7 1 L-5 -6 H5 L7 1 V6 H-7 Z M-7 1 H-2.5 L-1.5 3 H1.5 L2.5 1 H7',...sw,strokeWidth:2.2})],
  skills:[R(-7,-7,14,4,1.5),R(-7,-2,14,4,1.5),R(-7,3,14,4,1.5)],
  team:[E('circle',{cx:-3,cy:-3,r:3,...f}),E('circle',{cx:4,cy:-2,r:2.4,...f}),E('path',{d:'M-8 7 Q-3 -1 2 7 Z M1 7 Q4 1 8 7 Z',...f})],
  settings:[E('path',{d:'M-7 -4 H7 M-7 4 H7',...sw,strokeWidth:2.2}),E('circle',{cx:-2,cy:-4,r:2.8,...f}),E('circle',{cx:3,cy:4,r:2.8,...f})],
  pause:[R(-5,-6,3.8,12,1.4),R(1.2,-6,3.8,12,1.4)],
  play:[E('path',{d:'M-4 -6 L6 0 L-4 6 Z',...f,stroke:c,strokeWidth:2,strokeLinejoin:'round'})],
  back:[E('path',{d:'M3 -6 L-3 0 L3 6',...sw,strokeWidth:3})],
  close:[E('path',{d:'M-5 -5 L5 5 M5 -5 L-5 5',...sw,strokeWidth:3})],
  mic:[R(-3,-7,6,10,3),E('path',{d:'M-6 0 Q0 8 6 0 M0 4 V7',...sw,strokeWidth:2})],
  clip:[E('path',{d:'M4 -2 L-2 4 Q-4 6 -6 4 Q-8 2 -6 0 L1 -7 Q3 -9 5 -7 Q7 -5 5 -3 L-1 3',...sw,strokeWidth:2})],
  follow:[E('circle',{cx:0,cy:0,r:4.5,...sw}),E('path',{d:'M0 -8 V-5.5 M0 5.5 V8 M-8 0 H-5.5 M5.5 0 H8',...sw}),E('circle',{cx:0,cy:0,r:1.6,...f})],
  minus:[E('path',{d:'M-6 0 H6',...sw,strokeWidth:3})],
  download:[E('path',{d:'M0 -7 V3 M-4 -1 L0 3 L4 -1 M-7 7 H7',...sw,strokeWidth:2.6})],
  share:[E('circle',{cx:5,cy:-5,r:2.6,...f}),E('circle',{cx:-5,cy:0,r:2.6,...f}),E('circle',{cx:5,cy:5,r:2.6,...f}),E('path',{d:'M-5 0 L5 -5 M-5 0 L5 5',...sw,strokeWidth:2})],
  repeat:[E('path',{d:'M-6 0 V-2 Q-6 -5 -3 -5 H5 M2 -8 L5 -5 L2 -2 M6 0 V2 Q6 5 3 5 H-5 M-2 2 L-5 5 L-2 8',...sw,strokeWidth:2.2})],
  bookmark:[E('path',{d:'M-5 -7 H5 V7 L0 3.5 L-5 7 Z',...f,stroke:c,strokeWidth:1.5,strokeLinejoin:'round'})],
  flag:[E('path',{d:'M-5 7 V-7',...sw}),E('path',{d:'M-5 -7 H5 L3 -3.5 L5 0 H-5 Z',...f,stroke:c,strokeWidth:1.5,strokeLinejoin:'round'})],
  marker:[R(-5.5,-5.5,11,11,2.5,{fill:c,transform:'rotate(45)'}),E('path',{d:'M0 -3.5 V0.8',stroke:bg,strokeWidth:2.2,strokeLinecap:'round'}),E('circle',{cx:0,cy:3.3,r:1.2,fill:bg})],
  bell:[E('path',{d:'M-5 3 V-1 Q-5 -6 0 -6 Q5 -6 5 -1 V3 L6.5 5 H-6.5 Z',...f,stroke:c,strokeWidth:1.5,strokeLinejoin:'round'}),E('circle',{cx:0,cy:7,r:1.8,...f})],
  dot:[E('circle',{cx:0,cy:0,r:4,...f})]
 };
 return E('g',{transform:`translate(${x} ${y}) scale(${s})`},K[n]||K.dot);
}
function ui(n,sz){sz=sz||20;return E('svg',{width:sz,height:sz,viewBox:'-10 -10 20 20',style:{display:'block',flex:'none'}},icon(n,'currentColor',0,0,1,'#FFFFFF'));}

/* ---------- characters ---------- */
function charG(o){
 const rank=o.rank||'specialist',ex=o.expr||'neutral',cs=T.cs;
 const col=rank==='director'?T.hero:(T.roles[o.role]||T.hero);
 const side=dk(col,.24),limb=dk(col,.14),acc=dk(col,.52),ink=T.ink;
 const W={specialist:50,lead:54,director:58}[rank],H={specialist:46,lead:54,director:62}[rank]+(cs==='big'?4:0);
 const bx=50-W/2,by=104-H,sd=6,fw=W-sd,cx=bx+fw/2,R=cs==='simple'?10:cs==='full'?13:15;
 const P=[];
 if(rank==='lead')P.push(E('rect',{x:cx-7,y:by-9,width:14,height:16,rx:6,fill:col}));
 if(rank==='director')[-16,0,16].forEach((d,i)=>P.push(E('rect',{x:cx+d-6,y:by-(i==1?13:9),width:12,height:18,rx:5.5,fill:i==1?col:side})));
 const walk=ex==='walking';
 P.push(E('rect',{x:cx-15,y:walk?96:101,width:12,height:9,rx:4,fill:side}),E('rect',{x:cx+3,y:101,width:12,height:9,rx:4,fill:side}));
 P.push(E('rect',{x:bx,y:by,width:W,height:H,rx:R,fill:side}),E('rect',{x:bx,y:by,width:fw,height:H-4,rx:R,fill:col}));
 const pw=fw-(cs==='simple'?16:12),ph=cs==='simple'?20:cs==='full'?26:30,px=cx-pw/2,py=by+(cs==='big'?6:8);
 P.push(E('rect',{x:px,y:py,width:pw,height:ph,rx:ph*.42,fill:cs==='simple'?lt(col,.86):'#FFFFFF'}));
 const ey=py+ph*.45,ed=pw*.21,er=cs==='simple'?2.5:cs==='full'?3.1:3.8,my=py+ph*.78;
 const eye=(x,sc)=>{
  if(ex==='delighted')return E('path',{d:`M${x-er} ${ey+1} Q${x} ${ey-er*1.9} ${x+er} ${ey+1}`,stroke:ink,strokeWidth:er*.85,fill:'none',strokeLinecap:'round'});
  if(ex==='focused')return E('rect',{x:x-er*1.1,y:ey-er*.45,width:er*2.2,height:er*.95,rx:er*.45,fill:ink});
  const r=er*(sc||1)*(ex==='needs'?1.15:1);
  return [E('circle',{cx:x,cy:ey,r,fill:ink}),cs==='big'?E('circle',{cx:x+r*.35,cy:ey-r*.38,r:r*.33,fill:'#fff'}):null];
 };
 P.push(eye(cx-ed,ex==='puzzled'?1.15:1),eye(cx+ed,ex==='puzzled'?.75:1));
 const b0=ey-er-3.2,bw=er+1.4,bs={stroke:ink,strokeWidth:cs==='simple'?1.8:2.2,strokeLinecap:'round',fill:'none'};
 const L=(a,b,c,d)=>E('path',{d:`M${a} ${b} L${c} ${d}`,...bs});
 if(ex==='focused')P.push(L(cx-ed-bw,b0-.5,cx-ed+bw,b0+1.2),L(cx+ed+bw,b0-.5,cx+ed-bw,b0+1.2));
 if(ex==='recovering')P.push(L(cx-ed-bw,b0-2,cx-ed+bw,b0+1.6),L(cx+ed+bw,b0-2,cx+ed-bw,b0+1.6));
 if(ex==='puzzled')P.push(E('path',{d:`M${cx-ed-bw} ${b0} Q${cx-ed} ${b0-4} ${cx-ed+bw} ${b0-1.5}`,...bs}),L(cx+ed-bw,b0+1.4,cx+ed+bw,b0+1.4));
 if(ex==='needs'&&cs!=='simple')P.push(E('path',{d:`M${cx-ed-bw} ${b0-.5} Q${cx-ed} ${b0-3} ${cx-ed+bw} ${b0-.5}`,...bs}),E('path',{d:`M${cx+ed-bw} ${b0-.5} Q${cx+ed} ${b0-3} ${cx+ed+bw} ${b0-.5}`,...bs}));
 const ms={stroke:ink,strokeWidth:cs==='simple'?1.8:2.3,strokeLinecap:'round',strokeLinejoin:'round',fill:'none'},mw=cs==='simple'?4:5;
 const M={
  neutral:E('path',{d:`M${cx-mw} ${my} H${cx+mw}`,...ms}),
  walking:E('path',{d:`M${cx-mw} ${my-1} Q${cx} ${my+2.6} ${cx+mw} ${my-1}`,...ms}),
  focused:E('path',{d:`M${cx-mw*.55} ${my} H${cx+mw*.55}`,...ms}),
  talking:E('ellipse',{cx,cy:my,rx:mw*.65,ry:mw*.55,fill:ink}),
  needs:E('ellipse',{cx,cy:my,rx:mw*.45,ry:mw*.45,fill:ink}),
  puzzled:E('path',{d:`M${cx-mw} ${my} l${mw/2} -1.6 l${mw/2} 1.6 l${mw/2} -1.6 l${mw/2} 1.6`,...ms}),
  recovering:E('path',{d:`M${cx-mw} ${my+.6} L${cx+mw} ${my-.8}`,...ms,strokeWidth:ms.strokeWidth+.5}),
  delighted:E('path',{d:`M${cx-mw-1} ${my-2.5} Q${cx} ${my+6} ${cx+mw+1} ${my-2.5} Z`,fill:ink,stroke:ink,strokeWidth:1.5,strokeLinejoin:'round'})
 };
 P.push(M[ex]||M.neutral);
 if(cs==='big'||(cs==='full'&&ex==='delighted'))P.push(E('circle',{cx:cx-ed*1.7,cy:my-1,r:2.4,fill:lt(col,.5)}),E('circle',{cx:cx+ed*1.7,cy:my-1,r:2.4,fill:lt(col,.5)}));
 const A={neutral:[12,-12],walking:[30,-6],focused:[-36,36],talking:[12,-76],needs:[12,-168],puzzled:[40,-12],recovering:[12,-130],delighted:[152,-152]}[ex]||[12,-12];
 const al=cs==='simple'?16:cs==='full'?19:21,aw=cs==='simple'?8:9.5,shy=by+H*.52,lsx=bx+2,rsx=bx+W-2;
 const arm=(sx,a)=>E('rect',{x:sx-aw/2,y:shy-aw/2,width:aw,height:al+aw/2,rx:aw/2,fill:limb,transform:`rotate(${a} ${sx} ${shy})`});
 const hand=(sx,a)=>{const r=a*Math.PI/180;return[sx-al*Math.sin(r),shy+al*Math.cos(r)]};
 P.push(arm(lsx,A[0]),arm(rsx,A[1]));
 const [lhx,lhy]=hand(lsx,A[0]),[rhx,rhy]=hand(rsx,A[1]);
 const role=rank==='director'?null:o.role;
 if(role==='research')P.push(E('circle',{cx:lhx-2,cy:lhy+2,r:6.5,fill:'#FFFFFF',stroke:acc,strokeWidth:2.8}),E('path',{d:`M${lhx+2} ${lhy+7} L${lhx+6} ${lhy+12}`,stroke:acc,strokeWidth:3.4,strokeLinecap:'round'}));
 if(role==='builder')P.push(E('rect',{x:bx,y:by+H-17,width:fw,height:7,fill:acc}),E('rect',{x:bx+7,y:by+H-19,width:6,height:10,rx:2,fill:lt(col,.4)}),E('rect',{x:bx+fw-14,y:by+H-19,width:6,height:10,rx:2,fill:lt(col,.4)}));
 if(role==='tester')P.push(E('rect',{x:lhx-7,y:lhy-4,width:13,height:16,rx:2.5,fill:'#FFFFFF',stroke:acc,strokeWidth:2}),E('rect',{x:lhx-3,y:lhy-6,width:5,height:4,rx:1.5,fill:acc}),E('path',{d:`M${lhx-4} ${lhy+3} H${lhx+3} M${lhx-4} ${lhy+7} H${lhx+1}`,stroke:acc,strokeWidth:1.6,strokeLinecap:'round'}));
 if(role==='browser')P.push(E('path',{d:`M${bx+3} ${by+12} Q${cx} ${by-12} ${bx+fw-3} ${by+12}`,stroke:acc,strokeWidth:3.2,fill:'none',strokeLinecap:'round'}),E('rect',{x:bx-2,y:by+7,width:7,height:12,rx:3,fill:acc}),E('rect',{x:bx+fw-5,y:by+7,width:7,height:12,rx:3,fill:acc}),E('path',{d:`M${bx+2} ${by+18} Q${bx+3} ${my+2} ${cx-mw-3} ${my+2}`,stroke:acc,strokeWidth:2,fill:'none',strokeLinecap:'round'}));
 if(role==='connector')P.push(E('path',{d:`M${bx+fw-18} ${py+ph} L${bx+fw-10} ${by+H-18}`,stroke:acc,strokeWidth:2}),E('rect',{x:bx+fw-17,y:by+H-19,width:12,height:13,rx:2.5,fill:'#FFFFFF',stroke:acc,strokeWidth:2}),E('rect',{x:bx+fw-14,y:by+H-15,width:6,height:3,rx:1,fill:acc}));
 if(role==='delivery')P.push(E('path',{d:`M${bx+fw*.7} ${py+ph+1} L${bx+2} ${by+H-18}`,stroke:acc,strokeWidth:2.6,strokeLinecap:'round'}),E('rect',{x:bx-9,y:by+H-20,width:17,height:14,rx:3.5,fill:acc}),E('path',{d:`M${bx-9} ${by+H-15} H${bx+8}`,stroke:lt(acc,.35),strokeWidth:1.6}));
 if(ex==='talking')P.push(E('rect',{x:rhx-3,y:rhy-7,width:14,height:12,rx:2.5,fill:'#D8B27C',stroke:'#9E7A45',strokeWidth:1.6}),E('path',{d:`M${rhx+4} ${rhy-7} V${rhy+5}`,stroke:'#9E7A45',strokeWidth:1.6}));
 let tr=ex==='puzzled'?'rotate(-7 50 106)':ex==='delighted'&&cs!=='simple'?'translate(0 -4)':undefined;
 const inner=E('g',{transform:tr},P);
 return o.anim?E('g',{style:{animation:o.anim,transformBox:'fill-box',transformOrigin:'50% 100%'}},inner):inner;
}
function Char(o){const s=o.size||60;return E('svg',{width:s,height:s*88/84,viewBox:'8 26 84 88',style:{display:'block',overflow:'visible',flex:'none'}},charG(o));}
function charAt(o,x,y,s){return E('g',{transform:`translate(${x-50*s} ${y-110*s}) scale(${s})`},charG(o));}

/* ---------- badges ---------- */
function badge(k,x,y){
 if(k==='complete')return E('g',null,E('circle',{cx:x,cy:y,r:11,fill:ST.ok,stroke:'#FFFFFF',strokeWidth:2.5}),icon('check','#FFFFFF',x,y,.95));
 if(k==='needs')return E('g',null,E('path',{d:`M${x} ${y+12} V${y-24}`,stroke:T.ink,strokeWidth:3,strokeLinecap:'round'}),E('path',{d:`M${x+1} ${y-24} L${x+24} ${y-18} L${x+1} ${y-11} Z`,fill:ST.amber,stroke:ST.amberLip,strokeWidth:2,strokeLinejoin:'round'}));
 if(k==='blocked')return E('g',null,E('rect',{x:x-9,y:y-9,width:18,height:18,rx:4,fill:ST.red,stroke:'#FFFFFF',strokeWidth:2.5,transform:`rotate(45 ${x} ${y})`}),E('path',{d:`M${x} ${y-5} V${y+1}`,stroke:'#fff',strokeWidth:2.6,strokeLinecap:'round'}),E('circle',{cx:x,cy:y+4.6,r:1.5,fill:'#fff'}));
 if(k==='skipped')return E('g',null,E('circle',{cx:x,cy:y,r:10,fill:ST.grey,stroke:'#FFFFFF',strokeWidth:2.5}),E('path',{d:`M${x-4.5} ${y} H${x+4.5}`,stroke:'#fff',strokeWidth:2.8,strokeLinecap:'round'}));
 if(k==='fyi')return E('circle',{cx:x,cy:y,r:6.5,fill:ST.blue,stroke:'#FFFFFF',strokeWidth:2.5});
 return null;
}
function colors(b,st){
 const dc=T.dist[b.d];let c={dc,wall:lt(dc,T.wall),roof:dc,roofS:dk(dc,.24),door:dk(dc,.4),win:lt(dc,.42)};
 c.side=dk(c.wall,.15);c.plinth=dk(c.wall,.28);
 if(st==='skipped')for(const k in c)c[k]=gray(c[k]);
 return c;
}
function sign(b,c,st,x,y,r){
 const lit=st==='active'||st==='complete'||st==='needs';
 if(st==='planned')return E('g',null,E('circle',{cx:x,cy:y,r,fill:'none',stroke:T.ink2,strokeWidth:2,strokeDasharray:'4 3'}),icon(b.i,T.ink2,x,y,r/11));
 return E('g',null,E('circle',{cx:x,cy:y,r:r+1,fill:lit?c.dc:'#FFFFFF',stroke:lit?dk(c.dc,.25):c.dc,strokeWidth:2}),icon(b.i,lit?'#FFFFFF':c.dc,x,y,r/11,lit?c.dc:'#FFFFFF'));
}

/* ---------- front elevation building ---------- */
function bldFront(o){
 const b=B[o.type],st=o.state||'idle',c=colors(b,st);
 const W=b.f*64-14,bh=Math.round(BH[b.b]*T.hs),sd=8,fw=W-sd,x=o.x,y=o.y,fx=x+fw/2;
 const pl=st==='planned',cons=st==='construction';
 const dash={fill:'none',stroke:T.ink2,strokeWidth:2,strokeDasharray:'6 5',strokeLinejoin:'round'};
 const P=[],top=y-bh;let roofTop=top;
 if(!pl)P.push(E('rect',{x:x-4,y:y-4,width:W+8,height:9,rx:4,fill:c.plinth}));
 if(pl||cons)P.push(E('rect',{x,y:top,width:W,height:bh,rx:T.rx,...dash}));
 const hb=cons?Math.round(bh*.5):bh;
 if(!pl){P.push(E('rect',{x,y:y-hb,width:W,height:hb,rx:T.rx,fill:c.side}),E('rect',{x,y:y-hb,width:fw,height:hb,rx:T.rx,fill:c.wall}));}
 if(!cons){
  if(b.r==='flat'){P.push(E('rect',{x:x-5,y:top-13,width:W+10,height:15,rx:T.rx+1,...(pl?dash:{fill:c.roofS})}));if(!pl)P.push(E('rect',{x:x-5,y:top-13,width:W+10-sd,height:11,rx:T.rx+1,fill:c.roof}));roofTop=top-13;}
  if(b.r==='gable'){const rh=Math.min(30,W*.34);P.push(E('path',{d:`M${x-4} ${top+1} L${x+W/2} ${top-rh} L${x+W+4} ${top+1} Z`,...(pl?dash:{fill:c.roof,stroke:c.roof,strokeWidth:6,strokeLinejoin:'round'})}));if(!pl)P.push(E('rect',{x:x-8,y:top-2,width:W+16,height:7,rx:3.5,fill:c.roofS}));roofTop=top-rh-3;}
  if(b.r==='dome'){const rw=W*.5-5,rh=Math.min(rw*.85,30);P.push(E('path',{d:`M${x+W/2-rw} ${top+1} A${rw} ${rh} 0 0 1 ${x+W/2+rw} ${top+1} Z`,...(pl?dash:{fill:c.roof})}));if(!pl)P.push(E('rect',{x:x-5,y:top-2,width:W+10,height:7,rx:3.5,fill:c.roofS}));roofTop=top-rh;}
 }
 const sr=b.f==1?8:10,short=bh<64&&b.f>1;
 let sx=fx,sy=y-Math.max(38,bh*.62),dx=fx;
 if(short){sx=x+fw*.3;sy=y-bh*.55;dx=x+fw*.7;}
 if(cons)sy=y-hb*.5;
 if(!pl&&!cons){
  P.push(E('rect',{x:dx-7,y:y-21,width:14,height:21,rx:6,fill:c.door}),E('rect',{x:dx-7,y:y-10,width:14,height:10,fill:c.door}));
  if(!short&&b.f>1)P.push(E('rect',{x:x+9,y:y-26,width:12,height:12,rx:3,fill:c.win}),E('rect',{x:x+fw-21,y:y-26,width:12,height:12,rx:3,fill:c.win}));
  if(b.b==='tower')P.push(E('rect',{x:fx-5,y:y-bh+10,width:10,height:10,rx:3,fill:c.win}));
  if(short&&b.f==3)P.push(E('rect',{x:x+fw*.5-6,y:y-bh*.62,width:12,height:12,rx:3,fill:c.win}),E('rect',{x:x+fw*.86-6,y:y-bh*.62,width:12,height:12,rx:3,fill:c.win}));
 }
 if(cons){const s={stroke:dk(c.dc,.15),strokeWidth:2.6,strokeLinecap:'round'};P.push(E('path',{d:`M${x+3} ${y} V${top} M${x+W-3} ${y} V${top} M${fx} ${y} V${top} M${x} ${top+2} H${x+W} M${x} ${y-bh*.5} H${x+W} M${x+3} ${y-bh*.5} L${fx} ${top+2} M${fx} ${y-bh*.5} L${x+W-3} ${top+2}`,...s}));}
 else P.push(sign(b,c,st,sx,sy,sr));
 if(!['idle','active','construction','planned'].includes(st))P.push(badge(st,x+W-2,roofTop+4));
 if(o.label!==false)P.push(E('text',{x:x+W/2,y:y+20,textAnchor:'middle',fontFamily:T.body,fontSize:12.5,fontWeight:700,fill:pl?T.ink2:T.ink},o.label||b.n));
 return {el:E('g',null,P),W,bh,roofTop,cx:x+W/2,door:dx};
}

/* ---------- iso ---------- */
const IS=32,IH=16,CA=.978,SA=.208,SS=56;const PI=(gx,gy,z)=>[(gx*CA-gy*SA)*SS,(gx*SA+gy*CA)*SS*.62-(z||0)];const pts=a=>a.map(p=>p[0].toFixed(1)+','+p[1].toFixed(1)).join(' ');
function box(gx,gy,w,d,z0,z1,cT,cL,cR,ex){ex=ex||{};return[
 E('polygon',{points:pts([PI(gx,gy+d,z0),PI(gx+w,gy+d,z0),PI(gx+w,gy+d,z1),PI(gx,gy+d,z1)]),fill:cL,...ex}),
 E('polygon',{points:pts([PI(gx+w,gy,z0),PI(gx+w,gy+d,z0),PI(gx+w,gy+d,z1),PI(gx+w,gy,z1)]),fill:cR,...ex}),
 E('polygon',{points:pts([PI(gx,gy,z1),PI(gx+w,gy,z1),PI(gx+w,gy+d,z1),PI(gx,gy+d,z1)]),fill:cT,...ex})];}
function bldIso(o){
 const b=B[o.type],st=o.state||'idle',c=colors(b,st),w=b.f-.28,d=.82,gx=o.gx,gy=o.gy,bh=Math.round(BH[b.b]*.95);
 const pl=st==='planned',cons=st==='construction';
 const dash={fill:'none',stroke:T.ink2,strokeWidth:2,strokeDasharray:'6 5',strokeLinejoin:'round'};
 const P=[];let rt=bh;
 P.push(E('polygon',{points:pts([PI(gx-.06,gy-.06),PI(gx+w+.06,gy-.06),PI(gx+w+.06,gy+d+.06),PI(gx-.06,gy+d+.06)]),fill:pl?'none':c.plinth}));
 if(pl||cons)P.push(box(gx,gy,w,d,0,bh,'none','none','none',dash));
 const hb=cons?bh*.5:bh;
 if(!pl)P.push(box(gx,gy,w,d,0,hb,c.wall,c.wall,c.side));
 if(!pl&&!cons){
  if(b.r==='flat'){P.push(box(gx-.05,gy-.05,w+.1,d+.1,bh,bh+8,c.roof,c.roofS,dk(c.roofS,.12)));rt=bh+8;}
  if(b.r==='gable'){const rh=22;P.push(E('polygon',{points:pts([PI(gx,gy,bh),PI(gx+w,gy,bh),PI(gx+w,gy+d/2,bh+rh),PI(gx,gy+d/2,bh+rh)]),fill:c.roofS}),E('polygon',{points:pts([PI(gx+w,gy,bh),PI(gx+w,gy+d,bh),PI(gx+w,gy+d/2,bh+rh)]),fill:c.side}),E('polygon',{points:pts([PI(gx,gy+d,bh),PI(gx+w,gy+d,bh),PI(gx+w,gy+d/2,bh+rh),PI(gx,gy+d/2,bh+rh)]),fill:c.roof,stroke:c.roof,strokeWidth:2,strokeLinejoin:'round'}));rt=bh+rh;}
  if(b.r==='dome'){P.push(box(gx,gy,w,d,bh,bh+4,c.roofS,c.roofS,dk(c.roofS,.12)));const cc=PI(gx+w/2,gy+d/2,bh+4),r=Math.min(w,d)*IS*.62;P.push(E('path',{d:`M${cc[0]-r} ${cc[1]} A${r} ${r*.9} 0 0 1 ${cc[0]+r} ${cc[1]} A${r} ${r*.5} 0 0 1 ${cc[0]-r} ${cc[1]} Z`,fill:c.roof}));rt=bh+4+r*.9;}
 }
 const F=(u,z)=>PI(gx+u,gy+d,z);const short=bh<64&&b.f>1;
 let su=w*.5,sz=Math.max(34,bh*.64),du=w*.5;if(short){su=w*.28;sz=bh*.55;du=w*.72;}
 if(!pl&&!cons){
  P.push(E('polygon',{points:pts([F(du-.13,0),F(du+.13,0),F(du+.13,20),F(du-.13,20)]),fill:c.door}));
  if(!short&&b.f>1)P.push(E('polygon',{points:pts([F(.16,18),F(.36,18),F(.36,30),F(.16,30)]),fill:c.win}),E('polygon',{points:pts([F(w-.36,18),F(w-.16,18),F(w-.16,30),F(w-.36,30)]),fill:c.win}));
 }
 if(cons){const s={stroke:dk(c.dc,.15),strokeWidth:2.6,strokeLinecap:'round',fill:'none'};const q=[[0,d],[w,d],[w,0]];q.forEach(([u,v])=>{const a=PI(gx+u,gy+v,0),bb=PI(gx+u,gy+v,bh);P.push(E('path',{d:`M${a[0]} ${a[1]} L${bb[0]} ${bb[1]}`,...s}))});P.push(E('polyline',{points:pts([PI(gx,gy+d,bh),PI(gx+w,gy+d,bh),PI(gx+w,gy,bh)]),...s}),E('path',{d:`M${F(0,0).join(' ')} L${F(w,bh).join(' ')}`,...s}));}
 else{const sp=F(su,sz);P.push(sign(b,c,st,sp[0],sp[1],b.f==1?8:10));}
 const bp=PI(gx+w,gy,rt);
 if(!['idle','active','construction','planned'].includes(st))P.push(badge(st,bp[0]+2,bp[1]+2));
 if(o.label!==false){const lp=PI(gx+w/2,gy+d+.18,0);P.push(E('text',{x:lp[0],y:lp[1]+12,textAnchor:'middle',fontFamily:T.body,fontSize:12.5,fontWeight:700,fill:pl?T.ink2:T.ink},o.label||b.n));}
 const top=PI(gx+w/2,gy+d/2,rt);
 return {el:E('g',null,P),top,door:PI(gx+du,gy+d+.5,0)};
}

/* ---------- desktop world ---------- */
const ROW=[160,395,630];
const WB=[
 {t:'library',x:44,r:0,st:'complete'},{t:'observatory',x:212,r:0,st:'active'},{t:'browser',x:318,r:0,st:'needs'},
 {t:'townhall',x:44,r:1,st:'active'},{t:'treasury',x:268,r:1,st:'idle'},{t:'connector',x:364,r:1,st:'idle'},
 {t:'vault',x:44,r:2,st:'active'},{t:'chart',x:236,r:2,st:'construction'},{t:'writing',x:560,r:2,st:'planned'},{t:'dock',x:716,r:2,st:'planned'}
];
const AG=[
 {role:'research',rank:'specialist',expr:'walking',x:168,r:0},{role:'research',rank:'lead',expr:'focused',x:214,r:0},{role:'research',rank:'specialist',expr:'focused',x:262,r:0},
 {role:'browser',rank:'specialist',expr:'needs',x:371,r:0},{rank:'director',expr:'neutral',x:129,r:1},{role:'connector',rank:'specialist',expr:'neutral',x:385,r:1},
 {role:'builder',rank:'lead',expr:'focused',x:97,r:2},{role:'builder',rank:'specialist',expr:'focused',x:289,r:2},{role:'delivery',rank:'lead',expr:'neutral',x:581,r:2}
];
const DIST=[{k:'research',n:'Research',x:20,w:450,r:0},{k:'hall',n:'Town Hall',x:20,w:450,r:1},{k:'analysis',n:'Analysis',x:20,w:450,r:2},{k:'delivery',n:'Delivery',x:530,w:320,r:2}];
const anim=(a)=>({animation:a});
function distTag(d,x,y){const col=dk(T.dist[d.k],.32),w=d.n.length*7.4+34;return E('g',null,E('rect',{x,y,width:w,height:24,rx:12,fill:col}),icon(B[{research:'library',hall:'townhall',analysis:'vault',delivery:'dock'}[d.k]].i,'#FFFFFF',x+13,y+12,.62,col),E('text',{x:x+25,y:y+16.5,fontFamily:T.body,fontSize:12.5,fontWeight:800,fill:'#FFFFFF'},d.n));}
function gate(x,y,st){const c=st==='open'?ST.ok:T.ink2;return E('g',null,E('rect',{x:x-18,y:y-30,width:7,height:34,rx:3,fill:dk(c,.1)}),E('rect',{x:x+11,y:y-30,width:7,height:34,rx:3,fill:dk(c,.1)}),E('rect',{x:x-20,y:y-24,width:40,height:9,rx:4.5,fill:'#FFFFFF',stroke:c,strokeWidth:2.5}),E('circle',{cx:x,cy:y-40,r:10,fill:c}),icon('lock','#FFFFFF',x,y-40,.7,c));}
function worldFront(W0,H0){
 const P=[],street=T.proj==='street';
 P.push(E('rect',{x:0,y:0,width:W0,height:H0,fill:street?lt(T.hero,.93):T.bg}));
 if(street){ROW.forEach((y,i)=>{P.push(E('rect',{x:0,y:y-2,width:W0,height:52,fill:lt(T.dist[i==0?'research':i==1?'hall':'analysis'],.72)}));if(i==2)P.push(E('rect',{x:520,y:y-2,width:W0-520,height:52,fill:lt(T.dist.delivery,.72)}));});}
 if(T.plots)DIST.forEach(d=>{const y=ROW[d.r];P.push(E('rect',{x:d.x,y:y-132,width:d.w,height:158,rx:16,fill:lt(T.dist[d.k],.88),stroke:lt(T.dist[d.k],.62),strokeWidth:2}));});
 const rd=(x1,y1,x2,y2)=>{const w=24,hz=y1===y2;return[E('rect',{x:Math.min(x1,x2)-w/2,y:Math.min(y1,y2)-w/2+4,width:hz?Math.abs(x2-x1)+w:w,height:hz?w:Math.abs(y2-y1)+w,rx:w/2,fill:T.roadEdge}),E('rect',{x:Math.min(x1,x2)-w/2,y:Math.min(y1,y2)-w/2,width:hz?Math.abs(x2-x1)+w:w,height:hz?w:Math.abs(y2-y1)+w,rx:w/2,fill:T.road})];};
 const rY=ROW.map(y=>y+68);
 P.push(rd(500,rY[0],500,rY[2]),rd(20,rY[0],500,rY[0]),rd(20,rY[1],500,rY[1]),rd(20,rY[2],850,rY[2]));
 P.push(E('path',{d:`M110 ${rY[0]} H250`,stroke:T.dash,strokeWidth:3,strokeDasharray:'8 8',strokeLinecap:'round',style:anim('tiloDash 1s linear infinite')}));
 P.push(E('rect',{x:97,y:rY[2]-8,width:192,height:16,rx:8,fill:lt(T.hero,.72)}),E('path',{d:`M104 ${rY[2]} H282`,stroke:T.hero,strokeWidth:4,strokeDasharray:'10 8',strokeLinecap:'round',style:anim('tiloDash .8s linear infinite')}));
 if(T.plots)DIST.forEach(d=>P.push(distTag(d,d.x+12,ROW[d.r]-124)));
 else DIST.forEach(d=>P.push(distTag(d,d.x+(d.k==='delivery'?0:4),ROW[d.r]-(d.r==0?140:124))));
 let obs,brs;
 WB.forEach(b=>{const r=bldFront({type:b.t,state:b.st,x:b.x,y:ROW[b.r]});P.push(r.el);if(b.t==='observatory')obs=r;if(b.t==='browser')brs=r;});
 P.push(gate(668,rY[2]-2,'closed'));
 const my=obs.roofTop-20;
 P.push(E('g',{style:anim('tiloBob 1.6s ease-in-out infinite')},E('circle',{cx:obs.cx,cy:my,r:14,fill:'#FFFFFF',stroke:T.dist.research,strokeWidth:2.5}),icon('search',dk(T.dist.research,.2),obs.cx,my,.9)));
 P.push(E('rect',{x:obs.cx+18,y:my-11,width:44,height:22,rx:11,fill:T.ink}),E('text',{x:obs.cx+40,y:my+4.5,textAnchor:'middle',fontFamily:T.body,fontSize:12.5,fontWeight:800,fill:'#FFFFFF'},'4 / 7'));
 const s=T.cs==='big'?.64:.6;
 AG.forEach(a=>P.push(charAt({...a,anim:a.expr==='walking'?'tiloBob .5s ease-in-out infinite':'tiloBreath 3.4s ease-in-out infinite'},a.x,rY[a.r]+6,s)));
 return E('svg',{width:W0,height:H0,viewBox:`0 0 ${W0} ${H0}`,style:{display:'block'}},P);
}
function worldIso(W0,H0){
 const sc=1.05,ox=175,oy=120,P=[];const GY=[.6,6.6,12.6],rg=GY.map(g=>g+1.3);
 const WBI=[['library',.3,0,'complete'],['observatory',2.3,0,'active'],['browser',3.4,0,'needs'],['townhall',.3,1,'active'],['treasury',3.3,1,'idle'],['connector',4.4,1,'idle'],['vault',.3,2,'active'],['chart',2.4,2,'construction'],['writing',5.9,2,'planned'],['dock',7.7,2,'planned']];
 const AGI=[[1.85,0,{role:'research',expr:'walking'}],[2.45,0,{role:'research',rank:'lead',expr:'focused'}],[3.0,0,{role:'research',expr:'focused'}],[4.25,0,{role:'browser',expr:'needs'}],[1.65,1,{rank:'director',expr:'neutral'}],[4.75,1,{role:'connector',expr:'neutral'}],[1.15,2,{role:'builder',rank:'lead',expr:'focused'}],[3.25,2,{role:'builder',expr:'focused'}],[6.25,2,{role:'delivery',rank:'lead',expr:'neutral'}]];
 const plots=[{k:'research',n:'Research',a:[.1,-1.4,5.2,1.75]},{k:'hall',n:'Town Hall',a:[.1,4.6,5.2,7.75]},{k:'analysis',n:'Analysis',a:[.1,10.6,4.5,13.75]},{k:'delivery',n:'Delivery',a:[5.75,10.6,9.6,13.75]}];
 plots.forEach(p=>{const[a,b,c,d]=p.a;const col=lt(T.dist[p.k],.84);P.push(box(a,b,c-a,d-b,-8,0,col,dk(col,.12),dk(col,.2)));});
 const road=(x1,y1,x2,y2)=>{const w=.22;const q=x1===x2?[[x1-w,y1-w],[x1+w,y1-w],[x1+w,y2+w],[x1-w,y2+w]]:[[x1,y1-w],[x2,y1-w],[x2,y1+w],[x1,y1+w]];return[E('polygon',{points:pts(q.map(p=>PI(p[0],p[1],-4))),fill:T.roadEdge}),E('polygon',{points:pts(q.map(p=>PI(p[0],p[1],0))),fill:T.road})];};
 P.push(road(5.47,rg[0],5.47,rg[2]),road(.1,rg[0],5.47,rg[0]),road(.1,rg[1],5.47,rg[1]),road(.1,rg[2],9.6,rg[2]));
 const ln=(a,b,c)=>{const p1=PI(a,c),p2=PI(b,c);return 'M'+p1[0]+' '+p1[1]+' L'+p2[0]+' '+p2[1]};
 P.push(E('path',{d:ln(1.1,2.4,rg[0]),stroke:T.dash,strokeWidth:3,strokeDasharray:'8 8',strokeLinecap:'round',style:anim('tiloDash 1s linear infinite')}));
 P.push(E('path',{d:ln(1.15,3.25,rg[2]),stroke:lt(T.hero,.65),strokeWidth:12,strokeLinecap:'round'}),E('path',{d:ln(1.15,3.25,rg[2]),stroke:T.hero,strokeWidth:4,strokeDasharray:'10 8',strokeLinecap:'round',style:anim('tiloDash .8s linear infinite')}));
 const items=[];
 WBI.forEach(([t,gx,r,st])=>items.push({z:gx*.2+GY[r]+.5,f:()=>{const b=bldIso({type:t,state:st,gx,gy:GY[r]});if(t==='observatory'){const q=b.top;return[b.el,E('g',{style:anim('tiloBob 1.6s ease-in-out infinite')},E('circle',{cx:q[0],cy:q[1]-26,r:14,fill:'#FFFFFF',stroke:T.dist.research,strokeWidth:2.5}),icon('search',dk(T.dist.research,.2),q[0],q[1]-26,.9)),E('rect',{x:q[0]+18,y:q[1]-37,width:44,height:22,rx:11,fill:T.ink}),E('text',{x:q[0]+40,y:q[1]-21.5,textAnchor:'middle',fontFamily:T.body,fontSize:12.5,fontWeight:800,fill:'#FFFFFF'},'4 / 7')];}return b.el;}}));
 const gp=PI(7.15,rg[2],0);items.push({z:7.15*.2+rg[2],f:()=>gate(gp[0],gp[1]+4,'closed')});
 AGI.forEach(([gx,r,a])=>{const gy=rg[r],p=PI(gx,gy,0);items.push({z:gx*.2+gy+.1,f:()=>[a.expr==='needs'&&T.ring?E('ellipse',{cx:p[0],cy:p[1]+8,rx:28,ry:10,fill:'none',stroke:ST.amber,strokeWidth:4}):null,charAt({...a,anim:a.expr==='walking'?'tiloBob .5s ease-in-out infinite':'tiloBreath 3.4s ease-in-out infinite'},p[0],p[1]+8,T.cscale||.58)]});});
 items.sort((a,b)=>a.z-b.z).forEach(i=>P.push(i.f()));
 plots.forEach(p=>{const q=PI(p.a[0]+.2,p.a[1]+.25,0);P.push(distTag({k:p.k,n:p.n},q[0],q[1]-2));});
 return E('svg',{width:W0,height:H0,viewBox:'0 0 '+W0+' '+H0,style:{display:'block'}},E('rect',{x:0,y:0,width:W0,height:H0,fill:T.bg}),E('g',{transform:'translate('+ox+' '+oy+') scale('+sc+')'},P));
}
function worldDesk(W0,H0){return T.proj==='iso'?worldIso(W0||868,H0||728):worldFront(W0||868,H0||728);}

/* ---------- mobile path ---------- */
function worldPath(o){
 o=o||{};const W0=390,X=[112,272,196,110,276,190];let y=40,ni=0;const P=[],nodes=[];
 const secs=[
  {k:'hall',n:'Town Hall',s:'Plan approved · 2 agents',b:[['townhall','active'],['connector','idle']]},
  {k:'research',n:'Research',s:'1 of 3 done · 4 agents',b:[['library','complete'],['observatory','active'],['browser','needs']]},
  {k:'analysis',n:'Analysis',s:'Reusing March work · 2 agents',b:[['vault','active'],['chart','construction']]},
  {k:'delivery',n:'Delivery',s:'Planned · 1 agent',b:[['writing','planned'],['gate','gate'],['dock','planned']]}
 ];
 const banners=[];
 secs.forEach(sc=>{banners.push({sc,y});y+=96;sc.b.forEach(([t,st])=>{nodes.push({t,st,x:X[ni%X.length],y:y+70,k:sc.k});ni++;y+=128;});y+=10;});
 const Ht=y+40;
 P.push(E('rect',{x:0,y:0,width:W0,height:Ht,fill:T.proj==='street'?lt(T.hero,.93):T.bg}));
 let d=`M${nodes[0].x} ${nodes[0].y+30}`;for(let i=1;i<nodes.length;i++){const a=nodes[i-1],b=nodes[i];const m=(a.y+b.y)/2+30;d+=` C${a.x} ${m} ${b.x} ${m} ${b.x} ${b.y+30}`;}
 const cur=nodes.findIndex(n=>n.t==='browser');
 let dd=`M${nodes[0].x} ${nodes[0].y+30}`;for(let i=1;i<=cur;i++){const a=nodes[i-1],b=nodes[i];const m=(a.y+b.y)/2+30;dd+=` C${a.x} ${m} ${b.x} ${m} ${b.x} ${b.y+30}`;}
 P.push(E('path',{d,stroke:T.roadEdge,strokeWidth:30,fill:'none',strokeLinecap:'round',transform:'translate(0 4)'}),E('path',{d,stroke:T.road,strokeWidth:30,fill:'none',strokeLinecap:'round'}));
 P.push(E('path',{d:dd,stroke:lt(T.hero,.62),strokeWidth:12,fill:'none',strokeLinecap:'round'}));
 banners.forEach(({sc,y})=>{const col=T.dist[sc.k],dkc=dk(col,.32);P.push(E('rect',{x:16,y:y+4,width:W0-32,height:64,rx:16,fill:dk(col,.45)}),E('rect',{x:16,y,width:W0-32,height:64,rx:16,fill:dkc}),E('circle',{cx:48,cy:y+32,r:18,fill:'#FFFFFF'}),icon(B[{research:'library',hall:'townhall',analysis:'vault',delivery:'dock'}[sc.k]].i,dkc,48,y+32,1.05),E('text',{x:76,y:y+28,fontFamily:T.body,fontSize:17,fontWeight:800,fill:'#FFFFFF'},sc.n),E('text',{x:76,y:y+48,fontFamily:T.body,fontSize:14,fontWeight:600,fill:'#FFFFFF'},sc.s));});
 const AGm={townhall:{rank:'director',expr:'neutral'},connector:{role:'connector',expr:'neutral'},observatory:{role:'research',rank:'lead',expr:'focused'},browser:{role:'browser',expr:'needs'},vault:{role:'builder',rank:'lead',expr:'focused'},chart:{role:'builder',expr:'focused'},writing:{role:'delivery',rank:'lead',expr:'neutral'}};
 let focusY=0;
 nodes.forEach((n,i)=>{
  if(n.t==='gate'){P.push(gate(n.x,n.y+34,'closed'),E('text',{x:n.x+(n.x>195?-40:40),y:n.y+10,textAnchor:n.x>195?'end':'start',fontFamily:T.body,fontSize:14,fontWeight:700,fill:T.ink},'Gate: share with leadership'));return;}
  const b=B[n.t],Wb=b.f*64-14,sc=.82,bx=n.x-Wb*sc/2;
  const r=bldFront({type:n.t,state:n.st,x:0,y:0,label:false});
  P.push(E('g',{transform:`translate(${bx} ${n.y+14}) scale(${sc})`},r.el));
  const right=n.x<195;P.push(E('text',{x:right?n.x+Wb*sc/2+14:n.x-Wb*sc/2-14,y:n.y-6,textAnchor:right?'start':'end',fontFamily:T.body,fontSize:14,fontWeight:800,fill:n.st==='planned'?T.ink2:T.ink},b.n));
  const sub={complete:'Done',active:'Working',needs:'Needs you',construction:'Being built',planned:'Planned',idle:'Ready'}[n.st];
  P.push(E('text',{x:right?n.x+Wb*sc/2+14:n.x-Wb*sc/2-14,y:n.y+13,textAnchor:right?'start':'end',fontFamily:T.body,fontSize:13,fontWeight:700,fill:n.st==='needs'?ST.amberLip:T.ink2},n.t==='observatory'?'Working · 4 of 7':sub));
  const a=AGm[n.t];const ax=n.x+(right?-Wb*sc/2-6:Wb*sc/2+6);if(a&&a.expr==='needs'&&T.ring)P.push(E('ellipse',{cx:ax,cy:n.y+44,rx:22,ry:7,fill:'none',stroke:ST.amber,strokeWidth:4}));if(a)P.push(charAt({...a,anim:'tiloBreath 3.4s ease-in-out infinite'},n.x+(right?-Wb*sc/2-6:Wb*sc/2+6),n.y+44,T.cscale?.56:.5));
  if(n.t==='browser')focusY=n.y;
 });
 return {el:E('svg',{width:W0,height:Ht,viewBox:`0 0 ${W0} ${Ht}`,style:{display:'block'}},P),focusY,height:Ht};
}

/* ---------- celebration scene ---------- */
function celebrate(W0,H0){
 const P=[],cx=W0/2,base=H0-40,lvl=T.burst;
 P.push(E('rect',{x:0,y:0,width:W0,height:H0,fill:lvl==3?lt(T.hero,.88):lt(T.hero,.92)}));
 const rays=lvl==1?10:lvl==2?14:18,rl=lvl==1?[70,92]:lvl==2?[72,118]:[70,150];
 for(let i=0;i<rays;i++){const a=i/rays*Math.PI*2;const x1=cx+Math.cos(a)*rl[0],y1=base-70+Math.sin(a)*rl[0]*.8,x2=cx+Math.cos(a)*rl[1],y2=base-70+Math.sin(a)*rl[1]*.8;P.push(E('path',{d:`M${x1} ${y1} L${x2} ${y2}`,stroke:lvl==1?lt(T.hero,.55):T.hero,strokeWidth:lvl==3?8:6,strokeLinecap:'round',opacity:lvl==1?1:.9,style:{animation:`tiloPop ${.35+i%3*.08}s cubic-bezier(.3,1.6,.5,1) both`,transformBox:'fill-box',transformOrigin:'50% 50%'}}));}
 if(lvl==3){const cols=[T.dist.research,T.dist.delivery,T.roles.tester,T.hero];for(let i=0;i<14;i++){const x=20+((i*83)%(W0-40)),y=16+((i*47)%(H0*.45));P.push(E('rect',{x,y,width:12,height:12,rx:3.5,fill:cols[i%4],transform:`rotate(${i*23} ${x+6} ${y+6})`}));}}
 const th=bldFront({type:'townhall',state:'complete',x:cx-89,y:base-40,label:false});
 P.push(E('rect',{x:0,y:base-36,width:W0,height:80,fill:lt(T.dist.hall,.78)}),th.el);
 const cast=lvl==1?[{rank:'director',x:cx,s:.95}]:lvl==2?[{role:'research',rank:'lead',x:cx-110,s:.78},{rank:'director',x:cx,s:.95},{role:'builder',rank:'lead',x:cx+110,s:.78}]:[{role:'research',x:cx-150,s:.66},{role:'research',rank:'lead',x:cx-84,s:.76},{rank:'director',x:cx,s:.95},{role:'builder',rank:'lead',x:cx+84,s:.76},{role:'delivery',rank:'lead',x:cx+150,s:.66}];
 cast.forEach((c,i)=>P.push(charAt({...c,expr:lvl==1&&c.rank!=='director'?'neutral':'delighted',anim:lvl>1?`tiloJump ${lvl==3?.9:1.3}s ${i*.12}s ease-in-out ${lvl==3?3:2} both`:undefined},c.x,base+22,c.s)));
 if(lvl==2)P.push(E('g',{transform:`translate(${cx+44} ${base-112})`},E('rect',{x:0,y:0,width:26,height:22,rx:4,fill:'#D8B27C',stroke:'#9E7A45',strokeWidth:2}),E('path',{d:'M13 0 V22',stroke:'#9E7A45',strokeWidth:2})));
 return E('svg',{width:W0,height:H0,viewBox:`0 0 ${W0} ${H0}`,style:{display:'block'}},P);
}

/* ---------- sheet pieces ---------- */
function bldSheet(type,state,label){
 const b=B[type];
 if(T.proj==='iso'){const r=bldIso({type,state,gx:0,gy:0,label:false});const w=b.f*IS;return E('svg',{width:b.f*62+60,height:190,viewBox:`-30 -150 ${b.f*62+60} 190`,style:{display:'block'}},r.el);}
 const W=b.f*64-14,r=bldFront({type,state,x:0,y:0,label:false});
 return E('svg',{width:W+60,height:170,viewBox:`-26 -140 ${W+60} 170`,style:{display:'block'}},r.el);
}
return {T,ST,B,icon,ui,Char,charAt,bldFront,bldIso,bldSheet,worldDesk,worldPath,celebrate,dk,lt};
};
})();

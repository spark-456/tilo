(function(){
/* Park-city backdrop + glass-friendly world thumbnails. Static art is built as SVG strings and shown as images; only movers are live layers. */
const rng=seed=>{let a=seed>>>0;return()=>{a|=0;a=a+0x6D2B79F5|0;let t=Math.imul(a^a>>>15,1|a);t=t+Math.imul(t^t>>>7,61|t)^t;return((t^t>>>14)>>>0)/4294967296}};
const ATTR=/^(viewBox|preserveAspectRatio|patternUnits|patternTransform|gradientTransform|gradientUnits|attributeName|repeatCount|xmlns)$/;
const kb=k=>k.replace(/[A-Z]/g,m=>'-'+m.toLowerCase());
const esc=v=>String(v).replace(/&/g,'&amp;').replace(/"/g,'&quot;').replace(/</g,'&lt;');
const NAVY=[16,20,56],PAPER=[240,238,232];
const toward=(B,t,warm)=>c=>{if(typeof c!=='string'||c[0]!=='#'||c.length!==7)return c;const u=c.toUpperCase();if(warm&&u==='#FFFFFF')return'#FFD98A';return'#'+[1,3,5].map((i,j)=>{const v=parseInt(u.slice(i,i+2),16);return Math.round(v+(B[j]-v)*t).toString(16).padStart(2,'0')}).join('')};

window.TiloPark=function(h){
 let cmap=null;
 const E=(t,p,...c)=>{let a='';
  if(p)for(const k in p){let v=p[k];if(v==null||v===false||k==='key')continue;if(cmap&&(k==='fill'||k==='stroke'||k==='stopColor'))v=cmap(v);
   const val=k==='style'&&typeof v==='object'?Object.entries(v).filter(e=>e[1]!=null).map(([q,w])=>kb(q)+':'+w).join(';'):v;a+=' '+(ATTR.test(k)?k:kb(k))+'="'+esc(val)+'"';}
  const kids=c.flat(9).filter(x=>x!=null&&x!==false).map(x=>typeof x==='object'?x.s:String(x).replace(/&/g,'&amp;').replace(/</g,'&lt;')).join('');
  return{s:'<'+t+a+(kids?'>'+kids+'</'+t+'>':'/>')};};
 const W=window.TiloWorld(E);
 const using=(m,fn)=>{const p=cmap;cmap=m;try{return fn()}finally{cmap=p}};
 const blob=s=>URL.createObjectURL(new Blob([s],{type:'image/svg+xml'}));
 const svgUrl=(w,hh,vb,kids,par)=>blob(E('svg',{xmlns:'http://www.w3.org/2000/svg',width:w,height:hh,viewBox:vb,preserveAspectRatio:par||'xMidYMid slice'},kids).s);
 const cover=src=>h('img',{src,alt:'',draggable:false,style:{position:'absolute',left:0,top:0,width:'100%',height:'100%',display:'block',pointerEvents:'none'}});
 const motion=(dx,dy,dur,f,still)=>still?{transform:`translate(${(dx*f).toFixed(1)}px, ${(dy*f).toFixed(1)}px)`}:{animation:`mvXY ${dur.toFixed(1)}s linear ${(-f*dur).toFixed(1)}s infinite`,'--dx':dx.toFixed(1)+'px','--dy':dy.toFixed(1)+'px'};
 function mover(x,y,dx,dy,dur,f,vb,child,still){
  const sc=vb[4],src=svgUrl(vb[2]*sc,vb[3]*sc,vb.slice(0,4).join(' '),child,'xMidYMid meet');
  return h('div',{style:{position:'absolute',left:x.toFixed(1)+'px',top:y.toFixed(1)+'px',width:0,height:0,willChange:'transform',pointerEvents:'none',...motion(dx,dy,dur,f,still)}},
   h('img',{src,alt:'',draggable:false,style:{position:'absolute',left:vb[0]*sc+'px',top:vb[1]*sc+'px',width:vb[2]*sc+'px',height:vb[3]*sc+'px',display:'block'}}));
 }
 function walker(x,y,dx,dy,dur,f,vb,frames,still,cyc){
  const sc=vb[4],w=vb[2]*sc,hh=vb[3]*sc;
  const src=svgUrl(2*w,hh,`${vb[0]} ${vb[1]} ${2*vb[2]} ${vb[3]}`,[frames[0],E('g',{transform:`translate(${vb[2]} 0)`},frames[1])],'xMidYMid meet');
  const lag=(-(f*7)%cyc).toFixed(2)+'s';
  return h('div',{style:{position:'absolute',left:x.toFixed(1)+'px',top:y.toFixed(1)+'px',width:0,height:0,willChange:'transform',pointerEvents:'none',...motion(dx,dy,dur,f,still)}},
   h('div',{style:{position:'absolute',left:0,top:0,width:0,height:0,transformOrigin:'0 0',animation:still?'none':`waddle ${cyc}s ease-in-out ${lag} infinite`}},
    h('div',{style:{position:'absolute',left:vb[0]*sc+'px',top:vb[1]*sc+'px',width:w+'px',height:hh+'px',backgroundImage:`url("${src}")`,backgroundSize:'200% 100%',backgroundRepeat:'no-repeat',backgroundPosition:'0% 0',animation:still?'none':`sprite2 ${cyc}s steps(2, end) ${lag} infinite`}})));
 }
 function depthSort(list){
  const n=list.length,out=[],indeg=new Array(n).fill(0),adj=Array.from({length:n},()=>[]),done=new Array(n).fill(false);
  const bh=(A,B)=>A[1]<=B[0]+.01||A[3]<=B[2]+.01;
  for(let i=0;i<n;i++)for(let j=i+1;j<n;j++){const a=list[i].b,b=list[j].b,ab=bh(a,b),ba=bh(b,a);if(ab&&!ba){adj[i].push(j);indeg[j]++;}else if(ba&&!ab){adj[j].push(i);indeg[i]++;}}
  const ready=[];for(let i=0;i<n;i++)if(!indeg[i])ready.push(i);
  while(out.length<n){
   if(!ready.length){let m=-1;for(let i=0;i<n;i++)if(!done[i]&&(m<0||list[i].k<list[m].k))m=i;ready.push(m);}
   ready.sort((p,q)=>list[q].k-list[p].k);
   const i=ready.pop();if(done[i])continue;done[i]=true;out.push(list[i]);
   adj[i].forEach(j=>{if(--indeg[j]===0&&!done[j])ready.push(j);});
  }
  return out;
 }
 /* o: {w,h} artboard px, night, k (motion slow-down), still, mute (0..1 pull towards paper) */
 function scene(o){
  o=Object.assign({w:1440,h:900,vw:1120,seed:23,night:false,k:1,still:false,mute:0},o||{});
  const {P,box,poly,shade,lt,building,agent}=W,T=48,r=rng(o.seed),pick=a=>a[Math.floor(r()*a.length)],night=o.night,still=o.still,k=o.k;
  const SM=night?toward(NAVY,.64,true):o.mute?toward(PAPER,o.mute):null,MM=night?toward(NAVY,.3):o.mute?toward(PAPER,o.mute*.5):null;
  const prev=cmap;cmap=SM;
  try{
   const BW=4*T,BD=3*T,RD=46,PX=BW+RD,PY=BD+RD,C=8,R=9,X=C*PX+RD,Y=R*PY+RD;
   const VW=o.vw,VH=VW*o.h/o.w,ctr=P(X/2,Y/2,0),vx=ctr[0]-VW/2,vy=ctr[1]-VH/2-40;
   const s2=o.w/VW,toPx=p=>[(p[0]-vx)*s2,(p[1]-vy)*s2];
   const HUES=['#F2825F','#F4B23E','#3FBF8C','#3E9BE6','#8A6CF0','#EC6AA6','#22AFAF','#F07A3A','#5A7BEF'];
   const TC=[['#6CC56B','#47A653'],['#8FD45E','#69B640'],['#3FB487','#2A9470'],['#6CC56B','#47A653'],['#F59BC3','#E275A6'],['#F7BE4F','#E59E2C'],['#8FD45E','#69B640'],['#3FB487','#2A9470']];
   const CARS=['#F2825F','#3E9BE6','#F4B23E','#8A6CF0','#EC6AA6','#FFFFFF','#22AFAF'];
   const ROLES=['research','builder','tester','browser','connector','delivery','designer','finance'];
   const ICONS=['search','doc','mail','coin','people','clock','swap','laptop','cap','parcel','person','hall'];
   const TPL=[[[0,1,2,2],[2,2,2,1],[3,0,1,1]],[[0,2,2,1],[2,1,2,2],[0,0,1,1]],[[1,1,2,2],[3,2,1,1],[0,2,1,1]],[[0,1,1,2],[1,2,2,1],[3,1,1,2]],[[1,1,2,2]],[[0,2,1,1],[1,2,1,1],[2,1,2,2]]];
   const LAMP={t:'rgb(255,238,176)',l:'rgb(255,226,150)',r:'rgb(236,196,118)'},LOFF={t:'#F4F1EA',l:'#E2DDD2',r:'#CFC8BA'};
   const tree=(x,y,s,kind,c)=>{
    const out=[box(x-1.8,y-1.8,0,3.6,3.6,7,shade('#9C7556'))];
    if(kind==='pine'){const b=P(x,y,6),tp=P(x,y,6+s*2.8),w=s*1.25;out.push(E('path',{d:`M${b[0]-w} ${b[1]} L${tp[0]} ${tp[1]} L${b[0]} ${b[1]+w*.42} Z`,fill:c[0]}),E('path',{d:`M${b[0]+w} ${b[1]} L${tp[0]} ${tp[1]} L${b[0]} ${b[1]+w*.42} Z`,fill:c[1]}));}
    else{const cc=P(x,y,7+s),R0=s*1.2247;out.push(E('path',{d:`M${cc[0]} ${cc[1]-R0} A${R0} ${R0} 0 0 0 ${cc[0]} ${cc[1]+R0} Z`,fill:c[0]}),E('path',{d:`M${cc[0]} ${cc[1]-R0} A${R0} ${R0} 0 0 1 ${cc[0]} ${cc[1]+R0} Z`,fill:c[1]}));}
    return E('g',null,out);
   };
   const car=(x,y,col,dir)=>{
    const c=P(x,y,0),out=[E('ellipse',{cx:c[0],cy:c[1],rx:15,ry:8,fill:'rgba(31,29,43,.14)'}),box(x-11,y-5.5,2,22,11,7,shade(col)),box(x-5,y-5,9,11,10,6,{t:lt(col,.35),l:'#E3F0FF',r:'#C3D6EE'})];
    const L=night?(dir>0?LAMP:{t:'rgb(255,96,112)',l:'rgb(255,96,112)',r:'rgb(220,70,90)'}):(dir>0?LOFF:{t:'#D98A94',l:'#C9707C',r:'#B35E6A'});
    out.push(box(x+10.6,y-4.6,4,1,2.8,2.4,L),box(x+10.6,y+1.8,4,1,2.8,2.4,L));
    return out;
   };
   const lamp=(x,y)=>{const hd=P(x,y,33);return[box(x-1.3,y-1.3,0,2.6,2.6,30,{t:'#6A6680',l:'#4C4860',r:'#3C3850'}),box(x-3,y-3,30,6,6,4,night?LAMP:LOFF),night&&E('circle',{cx:hd[0],cy:hd[1],r:11,fill:'rgba(255,222,140,.32)'})];};
   const big=30*T,ROAD='#E2DBF0',DASH=night?'rgba(170,170,210,.5)':'#FFFFFF';
   const seg=(a,b,z)=>`M${P(a[0],a[1],z).map(v=>v.toFixed(1)).join(' ')} L${P(b[0],b[1],z).map(v=>v.toFixed(1)).join(' ')}`;
   const ground=[poly([P(-big,-big,0),P(X+big,-big,0),P(X+big,Y+big,0),P(-big,Y+big,0)],'#A6D78C')],marks=[],plots=[],glows=[];
   for(let j=0;j<=R;j++){const y=j*PY;ground.push(poly([P(-big,y,.2),P(X+big,y,.2),P(X+big,y+RD,.2),P(-big,y+RD,.2)],ROAD));marks.push(E('path',{d:seg([-big,y+RD/2],[X+big,y+RD/2],.4),stroke:DASH,strokeWidth:2.4,strokeDasharray:'12 12',fill:'none'}));}
   for(let i=0;i<=C;i++){const x=i*PX;ground.push(poly([P(x,-big,.2),P(x+RD,-big,.2),P(x+RD,Y+big,.2),P(x,Y+big,.2)],ROAD));marks.push(E('path',{d:seg([x+RD/2,-big],[x+RD/2,Y+big],.4),stroke:DASH,strokeWidth:2.4,strokeDasharray:'12 12',fill:'none'}));}
   const inView=(cs,top)=>{const xs=cs.map(p=>p[0]),ys=cs.map(p=>p[1]);return Math.max(...xs)>vx-90&&Math.min(...xs)<vx+VW+90&&Math.max(...ys)>vy-60&&Math.min(...ys)-top<vy+VH+90;};
   const rows=[],spots=[];
   for(let j=0;j<R;j++){
    rows[j]=[];
    for(let i=0;i<C;i++){
     const bx=i*PX+RD,by=j*PY+RD;
     if(!inView([P(bx,by,0),P(bx+BW,by,0),P(bx+BW,by+BD,0),P(bx,by+BD,0)],170))continue;
     plots.push(box(bx,by,0,BW,BD,4,{t:'#C6EBB0',l:'#9FCF88',r:'#8EBF78'}));
     const objs=rows[j];
     [by+BD*.2,by+BD*.8].forEach(ly=>{const lx=bx-7,g=P(lx,ly,0);objs.push({k:lx+ly,b:[lx-1,lx+1,ly-1,ly+1],el:lamp(lx,ly)});if(night)glows.push(E('ellipse',{cx:g[0],cy:g[1],rx:64,ry:37,fill:'url(#lg)'}));});
     if(r()<.15){
      const cx=bx+BW/2,cy=by+BD/2,ell=(rx,ry,z)=>Array.from({length:28},(_,n)=>{const a=n/28*Math.PI*2;return P(cx+Math.cos(a)*rx,cy+Math.sin(a)*ry,z);});
      plots.push(poly(ell(60,42,4.2),'#B4E4F8'),poly(ell(51,34,4.4),'#62BDEB'));
      for(let n=0;n<16;n++){const tx=bx+10+r()*(BW-20),ty=by+10+r()*(BD-20),dx=(tx-cx)/66,dy=(ty-cy)/48;if(dx*dx+dy*dy<1)continue;objs.push({k:tx+ty,b:[tx-1,tx+1,ty-1,ty+1],el:tree(tx,ty,6+r()*4,r()<.3?'pine':'round',pick(TC))});}
      continue;
     }
     const occ=new Set();
     pick(TPL).forEach(([cx,cy,fw,fd])=>{
      for(let a=0;a<fw;a++)for(let b=0;b<fd;b++)occ.add((cx+a)+','+(cy+b));
      const big2=fw*fd>=4,sq=fw===fd;
      const spec={n:'',fp:[fw,fd],fl:big2?2+Math.floor(r()*3):1+Math.floor(r()*2.6),roof:pick(sq?['flat','gable','dome','flat']:['flat','gable']),fa:pick(['windows','band','arches']),i:pick(ICONS)};
      const u=r(),st=u<.64?'active':u<.93?'idle':'construction';
      const b=building(spec,st,bx+cx*T,by+cy*T,{tint:pick(HUES)});
      objs.push({k:b.key,b:[b.x0-2.5,b.x0+b.W+2.5,b.y0-2.5,b.y0+b.D+2.5],el:b.el});
      if(st!=='construction')spots.push({top:b.top,area:fw*fd,st});
      const roll=r();
      if(st!=='construction'&&cy+fd===3&&roll<.45){
       const ax=b.x0+b.W*.26,ay=by+BD+3,ex=pick(['focused','neutral','talking','delighted']),fa=r()<.5?'L':'R',role=pick(ROLES);
       objs.push({k:ax+ay,b:[ax-1,ax+1,ay-1,ay+1],el:using(MM,()=>agent({role,expr:ex,facing:fa},ax,ay,{scale:1.15}))});
      }
     });
     for(let cx=0;cx<4;cx++)for(let cy=0;cy<3;cy++){
      if(occ.has(cx+','+cy))continue;
      const n=r()<.35?2:1;
      for(let q=0;q<n;q++){const tx=bx+cx*T+12+r()*(T-24),ty=by+cy*T+12+r()*(T-24);objs.push({k:tx+ty,b:[tx-1,tx+1,ty-1,ty+1],el:tree(tx,ty,6+r()*3.5,r()<.3?'pine':'round',pick(TC))});}
     }
    }
   }
   const cyc=.56*(k>1?1.4:1),movers=[];
   for(let j=0;j<=R;j++){
    const y=j*PY,yc=y+RD/2,list=[];
    const x0=Math.max(yc+(vx-140)/.866,2*(vy-100)-yc,-RD),x1=Math.min(yc+(vx+VW+140)/.866,2*(vy+VH+140)-yc,X+RD);
    if(x1-x0>80){
     const span=x1-x0,nc=r()<.75?1:0,nw=r()<.7?(r()<.35?2:1):0;
     const place=(dir,ly,speed,vb,make,walk)=>{
      const a=dir>0?x0:x1,b=dir>0?x1:x0,dur=span/speed*k,f=r(),p0=P(a,ly,0),q=toPx(p0),dx=(b-a)*.866*s2,dy=(b-a)*.5*s2;
      const wrap=el=>E('g',{transform:`translate(${(-p0[0]).toFixed(1)} ${(-p0[1]).toFixed(1)})`},el);
      const made=using(MM,()=>make(a));
      list.push({ly,el:walk?walker(q[0],q[1],dx,dy,dur,f,vb,made.map(wrap),still,cyc):mover(q[0],q[1],dx,dy,dur,f,vb,wrap(made),still)});
     };
     for(let n=0;n<nc;n++){const dir=r()<.5?1:-1,ly=y+(dir>0?RD*.72:RD*.28),col=pick(CARS);place(dir,ly,50+r()*20,[-30,-30,60,45,s2],a=>car(a,ly,col,dir),false);}
     for(let n=0;n<nw;n++){const dir=r()<.5?1:-1,ly=y+(dir>0?RD*.9:RD*.1),role=pick(ROLES);place(dir,ly,13+r()*5,[-22,-60,44,70,s2],a=>[false,true].map(step=>agent({role,expr:'walking',facing:'R',back:dir<0,step},a,ly,{scale:1.1})),true);}
    }
    movers.push(list.sort((p,q)=>p.ly-q.ly).map(o=>o.el));
   }
   const vbS=`${vx.toFixed(1)} ${vy.toFixed(1)} ${VW} ${VH.toFixed(1)}`,sv=els=>cover(svgUrl(o.w,o.h,vbS,els));
   const defs=night?E('defs',null,E('radialGradient',{id:'lg'},E('stop',{offset:'0%',stopColor:'rgb(255,214,130)',stopOpacity:.5}),E('stop',{offset:'100%',stopColor:'rgb(255,214,130)',stopOpacity:0}))):null;
   const kids=[sv([defs,ground,marks,plots,glows])];
   for(let j=0;j<=R;j++){kids.push(movers[j]);if(j<R&&rows[j].length)kids.push(sv(depthSort(rows[j]).map(o=>o.el)));}
   return{el:h('div',{style:{position:'absolute',inset:0}},...kids.flat(9).filter(x=>x!=null&&x!==false)),spots:spots.map(c=>{const q=toPx(c.top);return{x:q[0],y:q[1],area:c.area,st:c.st};})};
  }finally{cmap=prev;}
 }
 const ns=s=>s.replace('<svg','<svg xmlns="http://www.w3.org/2000/svg"');
 const dims=s=>{const m=s.match(/^<svg[^>]*?\swidth="([\d.]+)"[^>]*?\sheight="([\d.]+)"/);return m?[+m[1],+m[2]]:[undefined,undefined];};
 const pic=(s,style,size)=>{const t=ns(s);return h('img',{src:blob(t),alt:'',draggable:false,width:size&&size[0],height:size&&size[1],style:Object.assign({display:'block',pointerEvents:'none'},style||{})});};
 function world(plan,o){o=o||{};const s=using(o.night?toward(NAVY,.6,true):null,()=>W.world(plan,{seed:o.seed||3,labels:false,tags:false,anim:false,width:1000,height:640})).s;return pic(s,{position:'absolute',left:0,top:0,width:'100%',height:'100%',objectFit:'contain'});}
 function building(spec,state,d,ht,night){const s=using(night?toward(NAVY,.58,true):null,()=>W.soloBuilding(spec,state,{d,height:ht})).s;return pic(s,{flex:'none'},dims(ns(s)));}
 function agent(a,size,night){const s=using(night?toward(NAVY,.3):null,()=>W.soloAgent(a,size)).s;return pic(s,{flex:'none'},dims(ns(s)));}
 return{scene,world,building,agent};
};
})();

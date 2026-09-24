(function(){
/* Tilo World Player engine: layout JSON + event log JSON -> compiled timeline -> SVG frame at time t */
const GZ=330,ZIG=170,SP={walk:250,run:430,carry:210},LIFTV=460;
const clamp=(v,a,b)=>Math.max(a,Math.min(b,v));
const easeIO=x=>x<.5?2*x*x:1-Math.pow(-2*x+2,2)/2;
const easeBack=x=>{const c=1.6;return 1+(c+1)*Math.pow(x-1,3)+c*Math.pow(x-1,2);};
const last=(list,t)=>{let v=null;for(const x of list){if(x[0]<=t)v=x;else break;}return v;};

window.TiloPlayer=function(h){
const TW=window.TiloWorld(h),{P,T,K0,dk,lt,icon}=TW,G=TW.G,M0=.8*T;
const E=(t,p,...c)=>h(t,p,...c.flat(9).filter(x=>x!=null&&x!==false));

/* ================= geometry ================= */
function geometry(lay){
 const seed=lay.seed||2,pieces={},bIdx={},levels=[],levelIdx={};
 lay.levels.forEach((lv,i)=>{
  const plan={districts:lv.districts,gates:lv.gates||[]},L=TW.layout(plan,seed+i);
  const pc={id:lv.id,kind:'level',i,L,plan,dx:(i%2)*ZIG,dy:-(i%2)*ZIG,z:i*GZ,seed:seed+i};
  const l={...lv,i,pc,islands:[]};pc.lv=l;levels.push(l);pieces[lv.id]=pc;levelIdx[lv.id]=i;
 });
 (lay.islands||[]).forEach(is=>{
  const l=levels.find(v=>v.id===is.level);
  const plan={districts:[{id:is.id,name:is.name,tint:is.tint,icon:is.icon,buildings:is.buildings}]},L=TW.layout(plan,seed+l.i+9);
  const pc={id:is.id,kind:'island',is,lv:l,L,plan,z:l.pc.z,seed:seed+l.i+9,level:l.pc};l.islands.push(pc);pieces[is.id]=pc;
 });
 const bridges={};
 levels.forEach(l=>{
  const m=l.pc,sx=l.islands.filter(s=>s.is.side!=='y'),sy=l.islands.filter(s=>s.is.side==='y');
  sx.forEach((s,k)=>{
   s.dx=m.dx+m.L.Wt+2*M0+110;s.dy=k===0?m.dy+m.L.Dt-s.L.Dt:sx[k-1].dy-2*M0-30-s.L.Dt;
   const yb=clamp(s.dy+s.L.Dt/2,m.dy+G*1.5,m.dy+m.L.Dt-G*1.5);
   s.br={side:'x',a:[m.dx+m.L.Wt+M0,yb],b:[s.dx-M0,yb],mainLoop:[m.L.Wt-G/2,yb-m.dy],islLoop:[G/2,yb-s.dy]};
  });
  sy.forEach((s,k)=>{
   s.dy=m.dy-2*M0-110-s.L.Dt;s.dx=k===0?m.dx+m.L.Wt-s.L.Wt-60:sy[k-1].dx-2*M0-80-s.L.Wt;
   const xb=clamp(s.dx+s.L.Wt/2,m.dx+G*1.5,m.dx+m.L.Wt-G*1.5);
   s.br={side:'y',a:[xb,m.dy-M0],b:[xb,s.dy+s.L.Dt+M0],mainLoop:[xb-m.dx,G/2],islLoop:[xb-s.dx,s.L.Dt-G/2]};
  });
  l.islands.forEach(s=>{const b=s.is.bridge||{};s.br.id=b.id||('br-'+s.id);s.br.type=b.type||'api';s.br.island=s;s.br.level=m;s.br.name=b.name||s.is.name;bridges[s.br.id]=s.br;});
 });
 Object.values(pieces).forEach(pc=>Object.values(pc.L.bmap).forEach(bb=>{bIdx[bb.id]={bb,pc,d:bb.block.d};}));
 const lifts=[];
 for(let i=0;i<levels.length-1;i++){
  const a=levels[i].pc,b=levels[i+1].pc,x=Math.max(a.dx,b.dx)+80,fa=a.dy+a.L.Dt+M0,fb=b.dy+b.L.Dt+M0,yS=Math.max(fa,fb)+34;
  lifts.push({i,x,yS,fa,fb,a,b,loop:{[a.id]:[x-a.dx,a.L.Dt-G/2],[b.id]:[x-b.dx,b.L.Dt-G/2]}});
 }
 const ext=(pc,bx)=>{[[-M0,-M0],[pc.L.Wt+M0,-M0],[pc.L.Wt+M0,pc.L.Dt+M0],[-M0,pc.L.Dt+M0]].forEach(([x,y])=>{const p=P(x+pc.dx,y+pc.dy,pc.z);bx[0]=Math.min(bx[0],p[0]);bx[1]=Math.max(bx[1],p[0]);bx[2]=Math.min(bx[2],p[1]);bx[3]=Math.max(bx[3],p[1]);});};
 const all=[1e9,-1e9,1e9,-1e9];
 levels.forEach(l=>{
  const bx=[1e9,-1e9,1e9,-1e9];[l.pc,...l.islands].forEach(pc=>ext(pc,bx));
  bx[2]-=120;bx[0]-=l.name.length*9.3+90;bx[3]+=20;l.box=bx;l.mainBox=(()=>{const q=[1e9,-1e9,1e9,-1e9];ext(l.pc,q);q[2]-=120;q[0]-=l.name.length*9.3+90;return q;})();
  all[0]=Math.min(all[0],bx[0]);all[1]=Math.max(all[1],bx[1]);all[2]=Math.min(all[2],bx[2]);all[3]=Math.max(all[3],bx[3]);
 });
 return{lay,levels,levelIdx,pieces,bIdx,bridges,lifts,box:all};
}

/* ================= paths ================= */
function locLocal(geo,loc){
 const bi=geo.bIdx[loc.at];const s=TW.standOf(bi.bb);let x=s[0],y=s[1];
 if(loc.seat!=null){const n=loc.of||6,a=Math.PI*2*(loc.seat+.5)/n;x+=18+Math.cos(a)*24;y+=Math.sin(a)*13;}
 else if(loc.q!=null){x-=24+loc.q*24;}
 else if(loc.slot){x+=loc.slot*16;}
 if(loc.dx)x+=loc.dx;if(loc.dy)y+=loc.dy;return[x,y];
}
function seatCenter(geo,at){const bi=geo.bIdx[at];const s=TW.standOf(bi.bb);return[s[0]+18,s[1]];}
function laneOut(geo,loc){const bi=geo.bIdx[loc.at],s=TW.standOf(bi.bb),p=locLocal(geo,loc),o=[p];if(Math.abs(p[1]-s[1])>.5)o.push([p[0],s[1]]);return o;}
function bldToLoop(geo,pc,loc,toward){
 const bi=geo.bIdx[loc.at],bb=bi.bb,b=bb.block,out=laneOut(geo,loc),x=out[out.length-1][0],s=TW.standOf(bb);
 if(bb.front)out.push([x,b.frontRoad]);else out.push([b.leftRoad,s[1]],[b.leftRoad,b.frontRoad]);
 const rx=toward[0]<pc.L.Wt/2?G/2:pc.L.Wt-G/2;out.push([rx,b.frontRoad]);return out;
}
function loopWalk(L,p,q){
 const x0=G/2,x1=L.Wt-G/2,y0=G/2,y1=L.Dt-G/2,W=x1-x0,H=y1-y0,per=2*(W+H);
 const par=pt=>{const d=[Math.abs(pt[1]-y0),Math.abs(pt[0]-x1),Math.abs(pt[1]-y1),Math.abs(pt[0]-x0)],e=d.indexOf(Math.min(...d));
  return e===0?clamp(pt[0],x0,x1)-x0:e===1?W+clamp(pt[1],y0,y1)-y0:e===2?W+H+x1-clamp(pt[0],x0,x1):2*W+H+y1-clamp(pt[1],y0,y1);};
 const cs=[[0,[x0,y0]],[W,[x1,y0]],[W+H,[x1,y1]],[2*W+H,[x0,y1]]];
 const a=par(p),b=par(q),fw=((b-a)%per+per)%per,bw=per-fw,out=[p];
 const pick=cs.map(([pc,pt])=>({pt,d:fw<=bw?((pc-a)%per+per)%per:((a-pc)%per+per)%per})).filter(c=>c.d>0.01&&c.d<Math.min(fw,bw)-0.01).sort((u,v)=>u.d-v.d);
 pick.forEach(c=>out.push(c.pt));out.push(q);return out;
}
function dedupe(pts){const o=[];pts.forEach(p=>{const l=o[o.length-1];if(!l||Math.abs(l[0]-p[0])>.3||Math.abs(l[1]-p[1])>.3||Math.abs(l[2]-p[2])>.3)o.push(p);});return o;}
function path(geo,A,B){
 const a=geo.bIdx[A.at],b=geo.bIdx[B.at];if(!a||!b)return null;
 const G3=(pc,pts)=>pts.map(p=>[p[0]+pc.dx,p[1]+pc.dy,pc.z]);
 if(a.pc===b.pc){
  if(A.at===B.at)return dedupe(G3(a.pc,[...laneOut(geo,A),...laneOut(geo,B).reverse()]));
  let r=TW.route(a.pc.L,A.at,B.at)||[TW.standOf(a.bb),TW.standOf(b.bb)];
  return dedupe(G3(a.pc,[...laneOut(geo,A),...r,...laneOut(geo,B).reverse()]));
 }
 const hops=[];let pc=a.pc;
 if(pc.kind==='island'){const br=pc.br;hops.push({fromLoop:br.islLoop,toLoop:br.mainLoop,mid:[[br.b[0],br.b[1],pc.z],[br.a[0],br.a[1],pc.z]],to:pc.level});pc=pc.level;}
 const tgt=b.pc.kind==='island'?b.pc.level:b.pc;let li=pc.i;const lj=tgt.i;
 while(li!==lj){const up=lj>li,lf=geo.lifts[up?li:li-1],from=geo.levels[li].pc,to=geo.levels[up?li+1:li-1].pc;
  hops.push({fromLoop:lf.loop[from.id],toLoop:lf.loop[to.id],mid:[[lf.x,lf.yS,from.z],[lf.x,lf.yS,to.z]],to});li+=up?1:-1;}
 if(b.pc.kind==='island'){const br=b.pc.br;hops.push({fromLoop:br.mainLoop,toLoop:br.islLoop,mid:[[br.a[0],br.a[1],b.pc.z],[br.b[0],br.b[1],b.pc.z]],to:b.pc});}
 const out=[];const push=(p,pts)=>pts.forEach(q=>out.push([q[0]+p.dx,q[1]+p.dy,p.z]));
 let cur=a.pc;const s0=bldToLoop(geo,cur,A,hops[0].fromLoop);push(cur,s0);let at=s0[s0.length-1];
 hops.forEach(hp=>{push(cur,loopWalk(cur.L,at,hp.fromLoop).slice(1));hp.mid.forEach(m=>out.push(m));cur=hp.to;at=hp.toLoop;push(cur,[at]);});
 const e0=bldToLoop(geo,cur,B,at),ring=e0[e0.length-1];push(cur,loopWalk(cur.L,at,ring).slice(1));push(cur,e0.slice(0,-1).reverse());
 return dedupe(out);
}
function timing(pts,mode){const sp=SP[mode]||SP.walk,ts=[0];let t=0;for(let i=1;i<pts.length;i++){const a=pts[i-1],b=pts[i],dz=Math.abs(b[2]-a[2]);t+=dz>0?dz/LIFTV+.15:Math.hypot(b[0]-a[0],b[1]-a[1])/sp;ts.push(t);}return ts;}
function bridgePts(br){const m=br.level,s=br.island;return[[br.mainLoop[0]+m.dx,br.mainLoop[1]+m.dy],br.a,br.b,[br.islLoop[0]+s.dx,br.islLoop[1]+s.dy]];}

/* ================= compile ================= */
function compile(geo,events,answers,extra){
 answers=answers||{};
 const ok=e=>!e.when||Object.keys(e.when).every(k=>answers[k]===e.when[k]);
 const ev=events.filter(ok).concat(extra||[]).map((e,i)=>({...e,_i:i})).sort((a,b)=>a.ts-b.ts||a._i-b._i);
 const C={geo,ev,A:{},B:{},BR:{},LV:{},DS:{},ISV:{},UNL:{},alerts:[],meet:{},fx:[],meters:[[0,0,0,0]],cam:[],presence:[],comments:[],chains:[],story:[],end:0,decisions:[],heat:{}};
 const bo=id=>C.B[id]||(C.B[id]={st:[],flag:[],tag:[],fl:[],vis:null});
 const br=id=>C.BR[id]||(C.BR[id]={st:[],calls:0,vol:0,last:null});
 const lvOfB=id=>{const bi=geo.bIdx[id];return bi?bi.pc.kind==='island'?bi.pc.level.i:bi.pc.i:null;};
 const bub=(actor,ic,t0,t1)=>C.fx.push({k:'bubble',actor,icon:ic,t0,t1});
 const flag=(id,f,t)=>{if(id&&geo.bIdx[id])bo(id).flag.push([t,f]);};
 let credits=0,saved=0,mins=0;
 const mkAgent=(id,d,t,loc,extra2)=>C.A[id]={id,role:d.role,rank:d.rank||'specialist',name:d.name||id,title:d.title||'',tools:d.tools||[],scope:d.scope||[],budget:d.budget||0,born:t,died:null,segs:[],locs:[[t,loc]],ex:[],items:[],pack:[],badge:[],work:[],credits:0,hits:0,loc,...(extra2||{})};
 for(const e of ev){
  const d=e.data||{},t=e.ts,ag=C.A[e.actor];
  if(e.credits){credits+=e.credits;if(ag)ag.credits+=e.credits;const hb=e.target&&geo.bIdx[e.target]?e.target:ag&&ag.loc&&ag.loc.at;if(hb)(C.heat[hb]=C.heat[hb]||[]).push([t,e.credits]);}
  if(d.saved){saved+=d.saved;}if(d.minutes)mins+=d.minutes;
  if(e.credits||d.saved||d.minutes)C.meters.push([t,credits,saved,mins]);
  let li=e.level!=null?geo.levelIdx[e.level]:null;
  if(li==null&&e.target&&geo.bIdx[e.target])li=lvOfB(e.target);
  if(li==null&&e.target&&geo.bridges[e.target])li=geo.bridges[e.target].level.i;
  if(li==null&&ag&&ag.loc)li=lvOfB(ag.loc.at);
  e._lv=li;
  if(d.cam==='all')C.cam.push([t,'all']);
  else if(li!=null&&!d.nocam&&!['agent.moved','data.transfer','agent.working','memory.saved','agent.idle','user.commented','building.planned'].includes(e.type))C.cam.push([t,li]);
  if(d.tag!=null&&e.target&&geo.bIdx[e.target])bo(e.target).tag.push([t,d.tag,d.tagIcon]);
  if(d.expr&&ag)ag.ex.push([t,d.expr,d.until?t+d.until:null]);
  switch(e.type){
   case 'level.created':C.LV[e.level]=t;break;
   case 'district.created':C.DS[e.district]=t;C.fx.push({k:'dpop',t0:t,t1:t+.5,district:e.district});break;
   case 'building.planned':{const b=bo(e.target);if(b.vis==null)b.vis=t;b.st.push([t,'planned']);const bi=geo.bIdx[e.target];if(bi&&bi.pc.kind==='island'&&C.ISV[bi.pc.id]==null)C.ISV[bi.pc.id]=t;break;}
   case 'building.constructing':{const b=bo(e.target);if(b.vis==null)b.vis=t;b.st.push([t,'construction']);C.fx.push({k:'build',t0:t,t1:t+1.5,at:e.target});break;}
   case 'building.operational':bo(e.target).st.push([t,'idle']);C.fx.push({k:'pop',t0:t,t1:t+.4,at:e.target});break;
   case 'building.scaled':bo(e.target).fl.push([t,d.fl]);C.fx.push({k:'pop',t0:t,t1:t+.4,at:e.target});break;
   case 'building.archived':bo(e.target).st.push([t,'complete']);break;
   case 'agent.spawned':{mkAgent(e.actor,d,t,{at:e.target,...(d.loc||{})});C.A[e.actor].ex.push([t,'delighted',t+1.2]);C.fx.push({k:'spawn',t0:t,t1:t+1.2,actor:e.actor});break;}
   case 'agent.cloned':{const n=(d.ids||[]).length+1;(d.ids||[]).forEach((id,j)=>{const loc={...ag.loc,dx:(ag.loc.dx||0)+(j+1)*15};mkAgent(id,{role:ag.role,rank:'specialist',name:ag.name+' '+(j+2),title:ag.title},t,loc,{parent:e.actor,cloneOf:j+2});C.A[id].badge.push([t,'×'+n]);});ag.badge.push([t,'×'+n]);C.fx.push({k:'clone',t0:t,t1:t+.5,actor:e.actor,ids:d.ids});break;}
   case 'agent.moved':{
    if(!ag)break;const to={at:e.target,...(d.loc||{})},mode=d.mode||(e.item?'carry':'walk');const pts=path(geo,ag.loc,to);
    if(pts&&pts.length>1){const tm=timing(pts,mode),seg={t0:t,t1:t+tm[tm.length-1],pts,tm,mode,item:e.item};ag.segs.push(seg);e._dur=seg.t1-t;ag.locs.push([seg.t1,to]);
     if(d.follow){let lv=null;pts.forEach((p,k)=>{const L2=Math.round(p[2]/GZ);if(L2!==lv){lv=L2;C.cam.push([t+tm[k],L2,'follow']);}});}
    }else ag.locs.push([t,to]);
    ag.loc=to;ag.work.push([t,null]);ag.items.push([t,e.item||null]);if(!d.hold&&e.item&&e._dur!=null)ag.items.push([t+e._dur,null]);break;}
   case 'agent.working':if(ag){ag.ex.push([t,d.expr||'focused']);ag.work.push([t,e.target||ag.loc.at]);if(e.item)ag.items.push([t,e.item]);}break;
   case 'agent.assigned':if(ag){ag.title=d.title||ag.title;}break;
   case 'agent.idle':if(ag){ag.ex.push([t,'sleepy']);ag.work.push([t,null]);}break;
   case 'agent.help_requested':if(ag){ag.ex.push([t,'talking',t+2.2]);bub(e.actor,'help',t,t+2.2);}break;
   case 'agent.escalated':if(ag){ag.ex.push([t,'needs',t+2.2]);bub(e.actor,'up',t,t+2.2);C.chains.push({t,from:e.actor,to:e.target});}break;
   case 'agent.blocked':if(ag){ag.ex.push([t,'puzzled']);flag(e.target||ag.loc.at,'blocked',t);C.fx.push({k:'pulse',t0:t,t1:t+1.2,at:e.target||ag.loc.at});}break;
   case 'agent.recovered':if(ag){ag.ex.push([t,'recovering',t+2.2]);ag.ex.push([t+2.2,'focused']);flag(e.target||ag.loc.at,null,t);bub(e.actor,'swap',t,t+2.2);}break;
   case 'agent.handoff':{const tg=C.A[e.target];if(ag&&tg){C.fx.push({k:'arc',t0:t,t1:t+.7,from:e.actor,to:e.target,item:e.item});ag.items.push([t,null]);tg.items.push([t+.7,e.item]);ag.ex.push([t,'talking',t+.9]);tg.ex.push([t+.7,'delighted',t+1.4]);}break;}
   case 'agent.retired':if(ag){ag.died=t+.6;C.fx.push({k:'retire',t0:t,t1:t+.6,actor:e.actor});}break;
   case 'meeting.called':{C.meet[d.id]={id:d.id,kind:d.kind,at:e.target,called:t,by:e.actor,attendees:d.attendees||[],agenda:d.agenda||[],decisions:[],follow:d.follow||[],title:d.title||e.summary};if(ag)bub(e.actor,'people',t,t+2);break;}
   case 'meeting.started':{const m=C.meet[d.id];if(m){m.t0=t;if(d.attendees)m.attendees=d.attendees;}break;}
   case 'meeting.decision':{const m=C.meet[d.id];if(m){m.decisions.push({t,text:e.summary,by:d.by||'',why:d.why||''});C.fx.push({k:'card',t0:t,t1:t+2.4,at:m.at});}break;}
   case 'meeting.ended':{const m=C.meet[d.id];if(m)m.t1=t;break;}
   case 'connection.requested':br(e.target).st.push([t,'requested']);break;
   case 'connection.consented':br(e.target).st.push([t,'requested']);break;
   case 'connection.established':{const b=br(e.target);b.st.push([t,'building'],[t+1.2,'connected']);const is=geo.bridges[e.target]&&geo.bridges[e.target].island;if(is&&is.is.locked&&d.unlock)C.UNL[is.id]=t;if(is&&C.ISV[is.id]==null)C.ISV[is.id]=t;break;}
   case 'connection.rate_limited':br(e.target).st.push([t,'rate']);break;
   case 'connection.expiring':br(e.target).st.push([t,'expiring']);break;
   case 'connection.expired':br(e.target).st.push([t,'expired']);break;
   case 'connection.revoked':br(e.target).st.push([t,'revoked']);break;
   case 'data.transfer':{const b=br(e.target);b.calls+=d.calls||1;b.vol+=d.mb||0;C.fx.push({k:'cart',t0:t,t1:t+(d.dur||2.6),br:e.target,size:d.size||'cart',dir:d.dir||'in',n:d.n||1});break;}
   case 'app.building':C.fx.push({k:'app',t0:t,t1:t+(d.dur||2.5),at:e.target,step:d.step,wires:d.wires||[]});break;
   case 'artifact.created':if(ag&&e.item&&d.hold)ag.items.push([t,e.item]);C.fx.push({k:'made',t0:t,t1:t+.8,at:e.target||(ag&&ag.loc.at),item:e.item});break;
   case 'artifact.reviewed':C.fx.push({k:'stamp',t0:t,t1:t+1.6,at:e.target||(ag&&ag.loc.at),okay:d.result!=='changes'});if(ag)ag.ex.push([t,d.result==='changes'?'focused':'delighted',t+1.4]);break;
   case 'alert.raised':case 'approval.requested':{
    const al={id:d.id||e.id,t0:t,sev:e.severity||'needs',type:e.type,target:e.target,actor:e.actor,card:d.card||{},decision:d.decision,needBy:d.needBy,def:d.default,defBy:d.defaultBy||'Director',kind:d.kind||(e.type==='approval.requested'?'approval':'needs'),gate:d.gate,anchor:d.anchor,meeting:d.meeting,timer:d.timer||40,batch:d.batch,summary:e.summary,level:li};
    C.alerts.push(al);if(al.decision)C.decisions.push(al);
    if(al.sev!=='nudge')flag(e.target,al.sev==='blocked'?'blocked':al.sev==='fyi'?'fyi':'needs',t);break;}
   case 'alert.resolved':case 'approval.resolved':{const al=C.alerts.find(a=>a.id===d.alert);if(al){al.resolved=t;al.by=d.by;al.choice=d.choice;if(al.sev!=='nudge')flag(al.target,null,t);const aa=C.A[al.actor];if(aa)aa.ex.push([t,'delighted',t+1.4]);}break;}
   case 'budget.requested':if(ag)bub(e.actor,'coin',t,t+2.2);break;
   case 'budget.granted':C.fx.push({k:'pop',t0:t,t1:t+.4,at:e.target});if(ag)ag.ex.push([t,'delighted',t+1.2]);break;
   case 'memory.hit':if(ag){ag.pack.push([t,t+2.2]);ag.hits++;}C.fx.push({k:'mem',t0:t,t1:t+2.2,from:d.from||'vault',to:e.target||(ag&&ag.loc.at)});break;
   case 'memory.saved':C.fx.push({k:'toVault',t0:t,t1:t+1.2,actor:e.actor,from:e.target,to:d.vault||'vault',item:e.item||'scroll'});break;
   case 'user.joined':C.presence.push({t,at:e.target,initials:d.initials||'You',color:d.color||K0.hero,until:d.until!=null?t+d.until:null,meeting:d.meeting});break;
   case 'user.commented':C.comments.push({t,at:e.target,n:d.n||1,text:e.summary,by:d.by||'AM'});break;
  }
  if(e.summary&&e.type!=='agent.moved'&&e.type!=='data.transfer'||d.story)C.story.push(e);
  C.end=Math.max(C.end,t+(e._dur||0)+.5);
 }
 Object.values(C.A).forEach(a=>{['ex','items','work','badge'].forEach(k=>a[k].sort((x,y)=>x[0]-y[0]));});
 Object.values(C.B).forEach(b=>{['st','flag','tag','fl'].forEach(k=>b[k].sort((x,y)=>x[0]-y[0]));});
 Object.values(C.BR).forEach(b=>b.st.sort((x,y)=>x[0]-y[0]));
 // camera keyframes with 3s dwell (follow moves may break dwell)
 const cam=[];C.cam.sort((a,b)=>a[0]-b[0]).forEach(([t,l,f])=>{const lc=cam[cam.length-1];if(lc&&lc[1]===l)return;const tt=lc&&!f?Math.max(t,lc[0]+3):t;cam.push([tt,l]);});C.camK=cam;
 C.markers=ev.filter(e=>['alert.raised','approval.requested','meeting.called','meeting.decision','connection.requested','connection.established','artifact.reviewed','agent.blocked','level.created','app.deployed','alert.resolved','approval.resolved'].includes(e.type)).map(e=>({ts:e.ts,type:e.type,sev:e.severity}));
 return C;
}

/* ================= queries ================= */
function bState(C,id,t){
 const b=C.B[id];if(!b||b.vis==null||t<b.vis)return null;
 const s=last(b.st,t),f=last(b.flag,t),tg=last(b.tag,t),fl=last(b.fl,t);
 return{state:s?s[1]:'planned',flag:f?f[1]:null,tag:tg?tg[1]:null,icon:tg?tg[2]:null,fl:fl?fl[1]:null};
}
function agentAt(C,a,t,reduced){
 if(t<a.born)return null;if(a.died!=null&&t>=a.died)return null;
 const geo=C.geo;let seg=null;for(const s of a.segs){if(t>=s.t0&&t<s.t1){seg=s;break;}}
 let p,dir='L',moving=false,op=1,mode=null;
 const locP=loc=>{const bi=geo.bIdx[loc.at],q=locLocal(geo,loc);return[q[0]+bi.pc.dx,q[1]+bi.pc.dy,bi.pc.z];};
 if(seg&&reduced){const f=(t-seg.t0)/(seg.t1-seg.t0);p=f<.5?seg.pts[0]:seg.pts[seg.pts.length-1];op=f<.5?1-f*2:(f-.5)*2;}
 else if(seg){
  const u=t-seg.t0;let k=1;while(k<seg.tm.length-1&&seg.tm[k]<u)k++;
  const a0=seg.pts[k-1],b0=seg.pts[k],den=seg.tm[k]-seg.tm[k-1],f=den>0?clamp((u-seg.tm[k-1])/den,0,1):1;
  p=[a0[0]+(b0[0]-a0[0])*f,a0[1]+(b0[1]-a0[1])*f,a0[2]+(b0[2]-a0[2])*f];
  const ddx=b0[0]-a0[0],ddy=b0[1]-a0[1];
  dir=Math.abs(b0[2]-a0[2])>0?'L':Math.abs(ddx)>=Math.abs(ddy)?(ddx>=0?'R':'BR'):(ddy>=0?'L':'BL');moving=true;mode=seg.mode;
 }else{
  const l=last(a.locs,t);const loc=l[1];p=locP(loc);
  if(loc.seat!=null){const c=seatCenter(geo,loc.at),bi=geo.bIdx[loc.at],cx=c[0]+bi.pc.dx,cy=c[1]+bi.pc.dy;const ddx=cx-p[0],ddy=cy-p[1];dir=Math.abs(ddx)>=Math.abs(ddy)?(ddx>=0?'R':'BR'):(ddy>=0?'L':'BL');}
  else if(loc.q!=null)dir='R';else if(loc.face)dir=loc.face;
 }
 if(a.died!=null&&t>a.died-.6)op*=clamp((a.died-t)/.6,0,1);
 let ex='neutral';for(let i=a.ex.length-1;i>=0;i--){const x=a.ex[i];if(x[0]>t)continue;if(x[2]!=null&&t>=x[2])continue;ex=x[1];break;}
 const w=last(a.work,t),working=!moving&&w&&w[1]?w[1]:null;
 const waiting=C.alerts.some(al=>al.actor===a.id&&al.sev!=='nudge'&&al.sev!=='fyi'&&t>=al.t0&&!(al.resolved<=t));
 if(waiting&&!moving)ex='needs';
 if(moving)ex=mode==='run'?'walking':'walking';
 const it=last(a.items,t),bd=last(a.badge,t),pk=a.pack.some(([t0,t1])=>t>=t0&&t<t1);
 const loc=last(a.locs,t)[1];
 return{p,dir,moving,ex,item:it?it[1]:null,badge:bd?bd[1]:null,pack:pk,op,working,waiting,mode,loc,seg};
}
function meetingsAt(C,t){return Object.values(C.meet).filter(m=>m.t0!=null&&t>=m.t0&&(m.t1==null||t<m.t1));}
function camLevel(C,t){const k=last(C.camK,t);return k?k[1]:'all';}
function metersAt(C,t){return last(C.meters,t)||[0,0,0,0];}
function openAlerts(C,t){return C.alerts.filter(a=>t>=a.t0&&!(a.resolved<=t));}
function levelProgress(C,l,t){
 const ids=[];(l.plan||l.pc.plan).districts.forEach(d=>d.buildings.forEach(b=>ids.push(b.id)));
 let s=0;ids.forEach(id=>{const b=bState(C,id,t);if(!b)return;s+=b.state==='complete'?1:b.state==='idle'||b.state==='active'?.5:b.state==='construction'?.2:0;});
 return ids.length?s/ids.length:0;
}
function bTop(C,id,t){
 const bi=C.geo.bIdx[id];if(!bi)return null;const st=bState(C,id,t)||{};const s=TW.specOf(bi.bb,bi.pc.seed);if(st.fl)s.fl=st.fl;
 const r=TW.building(s,'idle',bi.bb.cx,bi.bb.cy,{tint:TW.DIST.hall});const p=[r.top[0]+P(bi.pc.dx,bi.pc.dy,bi.pc.z)[0],r.top[1]+P(bi.pc.dx,bi.pc.dy,bi.pc.z)[1]];
 const b0=P(bi.bb.cx+bi.pc.dx,bi.bb.cy+bi.pc.dy,bi.pc.z),b1=P(bi.bb.cx+bi.pc.dx+s.fp[0]*T,bi.bb.cy+bi.pc.dy,bi.pc.z),b2=P(bi.bb.cx+bi.pc.dx,bi.bb.cy+bi.pc.dy+s.fp[1]*T,bi.pc.z),b3=P(bi.bb.cx+bi.pc.dx+s.fp[0]*T,bi.bb.cy+bi.pc.dy+s.fp[1]*T,bi.pc.z);
 return{top:p,rect:[Math.min(b0[0],b2[0]),Math.max(b1[0],b3[0]),p[1]-6,b3[1]],spec:s};
}

/* ================= drawing helpers ================= */
const bubbleEl=(x,y,ic,col)=>{const w=26,hh=22;return E('g',null,
 E('path',{d:`M${x-w/2} ${y-hh} h${w} a5 5 0 0 1 5 5 v${hh-10} a5 5 0 0 1 -5 5 h-${w/2-4} l-4 5 l-4 -5 h-${w/2-4} a5 5 0 0 1 -5 -5 v-${hh-10} a5 5 0 0 1 5 -5 z`,transform:`translate(-2.5 0)`,fill:'#FFFFFF',stroke:K0.ink,strokeWidth:1.6,strokeLinejoin:'round'}),
 ic.length===1?E('text',{x,y:y-hh/2+4.5,textAnchor:'middle',fontFamily:K0.body,fontSize:13,fontWeight:900,fill:col||K0.ink},ic):icon(ic,col||K0.ink,x,y-hh/2+1,.85));};
function itemEl(kind,x,y){
 const o=[];
 if(kind==='scroll'||kind==='doc'){o.push(E('rect',{x:x-6,y:y-5,width:12,height:9,rx:2.5,fill:'#FFF7E6',stroke:K0.kraftD,strokeWidth:1.2}),E('path',{d:`M${x-3} ${y-2} H${x+3} M${x-3} ${y+1} H${x+2}`,stroke:K0.kraftD,strokeWidth:1,strokeLinecap:'round'}));}
 else if(kind==='crate'||kind==='data'){o.push(TW.box(0,0,0,9,9,8,{t:lt(K0.kraft,.18),l:K0.kraft,r:dk(K0.kraft,.2)}));return E('g',{transform:`translate(${x-1} ${y+3})`},o);}
 else if(kind==='blueprint'){o.push(E('rect',{x:x-7,y:y-3,width:14,height:6,rx:3,fill:'#DCE6F5',stroke:'#5B7FA6',strokeWidth:1.2}),E('circle',{cx:x-7,cy:y,r:3,fill:'#C4D4EC',stroke:'#5B7FA6',strokeWidth:1.2}));}
 else if(kind==='parcel'){o.push(E('rect',{x:x-5,y:y-5,width:10,height:9,rx:1.6,fill:K0.kraft,stroke:K0.kraftD,strokeWidth:1}),E('path',{d:`M${x} ${y-5} V${y+4}`,stroke:K0.kraftD,strokeWidth:1.4}));}
 else if(kind==='app'){o.push(TW.box(0,0,0,8,8,8,{t:lt(K0.hero,.45),l:K0.hero,r:K0.heroLip}));return E('g',{transform:`translate(${x-1} ${y+3})`},o);}
 else if(kind==='decision'||kind==='card'){o.push(E('rect',{x:x-5,y:y-6.5,width:10,height:12,rx:1.8,fill:'#FFFFFF',stroke:K0.ink,strokeWidth:1.2}),E('circle',{cx:x,cy:y+1.5,r:2.4,fill:K0.hero}));}
 else if(kind==='key'){o.push(E('rect',{x:x-5,y:y-3.5,width:10,height:7,rx:1.6,fill:'#FFFFFF',stroke:K0.ink,strokeWidth:1.2}),E('rect',{x:x-3,y:y-1.5,width:3,height:3,rx:.8,fill:K0.hero}));}
 return E('g',null,o);
}
const pill=(text,x,y,bg,fg,fs)=>{fs=fs||11;const w=text.length*fs*.58+14,hh=fs+8;return E('g',null,E('rect',{x:x-w/2,y:y-hh/2+1.5,width:w,height:hh,rx:hh/2,fill:dk(bg,.25)}),E('rect',{x:x-w/2,y:y-hh/2,width:w,height:hh,rx:hh/2,fill:bg}),E('text',{x,y:y+fs*.36,textAnchor:'middle',fontFamily:K0.body,fontSize:fs,fontWeight:800,fill:fg||'#FFFFFF'},text));};

function bridgeEl(brd,state,f,o){
 const pts=bridgePts(brd),z=brd.level.z,[,a,b]=pts,ax=brd.side==='x',out=[];
 const len=ax?b[0]-a[0]:a[1]-b[1];const W2=brd.type==='browser'?9:15;
 const rect=(u0,u1,zz,hh,c)=>ax?TW.box(a[0]+u0,a[1]-W2,zz,u1-u0,W2*2,hh,c):TW.box(a[0]-W2,a[1]-u1,zz,W2*2,u1-u0,hh,c);
 const slab={t:brd.type==='browser'?lt(K0.kraft,.35):K0.road,l:dk(brd.type==='browser'?K0.kraft:K0.road,.14),r:dk(brd.type==='browser'?K0.kraft:K0.road,.24)};
 const zb=z-5;
 if(state==='requested'){const c=[[0,-W2],[len,-W2],[len,W2],[0,W2]].map(([u,v])=>ax?P(a[0]+u,a[1]+v,z):P(a[0]+v,a[1]-u,z));out.push(E('polygon',{points:TW.pts(c),fill:'rgba(255,255,255,.55)',stroke:K0.ink2,strokeWidth:1.6,strokeDasharray:'6 5'}));return out;}
 if(state==='revoked'||state==='none'||!state)return out;
 if(state==='building'){const n=10,k=Math.floor(clamp(f,0,1)*n);const c=[[0,-W2],[len,-W2],[len,W2],[0,W2]].map(([u,v])=>ax?P(a[0]+u,a[1]+v,z):P(a[0]+v,a[1]-u,z));out.push(E('polygon',{points:TW.pts(c),fill:'none',stroke:K0.ink2,strokeWidth:1.4,strokeDasharray:'6 5'}));for(let i=0;i<k;i++){const u0=len*i/n,u1=len*(i+1)/n-3;out.push(rect(u0,u1,zb,5,{t:lt(K0.kraft,.2),l:K0.kraft,r:K0.kraftD}));}return out;}
 if(state==='expired'){out.push(rect(0,len*.5,zb,5,slab));const e0=len*.5;const c=[[e0,-W2,0],[e0,W2,0],[e0,W2,len*.45],[e0,-W2,len*.45]].map(([u,v,hh])=>ax?P(a[0]+u,a[1]+v,z+hh):P(a[0]+v,a[1]-u,z+hh));out.push(E('polygon',{points:TW.pts(c),fill:slab.r,stroke:dk(slab.r,.2),strokeWidth:1}));return out;}
 out.push(rect(0,len,zb,5,slab));
 if(brd.type==='mcp'){[-6,6].forEach(v=>{const p0=ax?P(a[0],a[1]+v,z+.4):P(a[0]+v,a[1],z+.4),p1=ax?P(b[0],a[1]+v,z+.4):P(a[0]+v,b[1],z+.4);out.push(E('path',{d:`M${p0[0]} ${p0[1]} L${p1[0]} ${p1[1]}`,stroke:K0.ink2,strokeWidth:2}));});for(let u=6;u<len;u+=14){const p0=ax?P(a[0]+u,a[1]-10,z+.2):P(a[0]-10,a[1]-u,z+.2),p1=ax?P(a[0]+u,a[1]+10,z+.2):P(a[0]+10,a[1]-u,z+.2);out.push(E('path',{d:`M${p0[0]} ${p0[1]} L${p1[0]} ${p1[1]}`,stroke:dk(K0.road,.3),strokeWidth:2.4}));}}
 if(brd.type==='api'){const p0=ax?P(a[0],a[1],z+.3):P(a[0],a[1],z+.3),p1=ax?P(b[0],a[1],z+.3):P(a[0],b[1],z+.3);out.push(E('path',{d:`M${p0[0]} ${p0[1]} L${p1[0]} ${p1[1]}`,stroke:'#FFFFFF',strokeWidth:1.6,strokeDasharray:'8 8'}));}
 if(brd.type==='browser'){const kx=ax?b[0]-10:a[0]+14,ky=ax?a[1]+16:b[1]+10;out.push(TW.box(kx-5,ky-4,z,10,8,16,{t:lt(K0.ink2,.5),l:lt(K0.ink2,.25),r:K0.ink2}));const sp=P(kx,ky+4,z+13);out.push(E('rect',{x:sp[0]-5,y:sp[1]-5,width:9,height:6,rx:1.2,fill:'#FFFFFF'}));}
 if(state==='expiring'){for(let i=1;i<4;i++){const u=len*i/4;const pa=ax?P(a[0]+u-6,a[1]-8,z+.5):P(a[0]-8,a[1]-u+6,z+.5),pb=ax?P(a[0]+u,a[1],z+.5):P(a[0],a[1]-u,z+.5),pc=ax?P(a[0]+u+5,a[1]+8,z+.5):P(a[0]+8,a[1]-u-5,z+.5);out.push(E('path',{d:`M${pa[0]} ${pa[1]} L${pb[0]} ${pb[1]} L${pc[0]} ${pc[1]}`,stroke:K0.amber,strokeWidth:2.4,fill:'none',strokeLinejoin:'round'}));}}
 if(state==='rate'){for(let i=0;i<3;i++){const u=len-14-i*16;const c=ax?[a[0]+u,a[1]+2]:[a[0]+2,a[1]-u];out.push(TW.box(c[0]-6,c[1]-6,z,12,12,10,{t:lt(K0.kraft,.18),l:K0.kraft,r:dk(K0.kraft,.2)}));}}
 return out;
}
function cartEl(brd,f,size,dir){
 const [,a,b]=bridgePts(brd),z=brd.level.z,ax=brd.side==='x';const u=dir==='in'?1-f:f;const len=ax?b[0]-a[0]:a[1]-b[1];const x=ax?a[0]+len*u:a[0],y=ax?a[1]:a[1]-len*u;
 const big=size==='truck';const out=[];
 if(ax){out.push(TW.box(x-(big?14:8),y-(big?8:6),z,big?28:16,big?16:12,big?15:10,{t:lt(K0.kraft,.18),l:K0.kraft,r:dk(K0.kraft,.2)}));out.push(TW.box(dir==='in'?x-(big?24:14):x+(big?14:8),y-(big?7:5),z,big?10:6,big?14:10,big?11:7,{t:lt(K0.ink2,.5),l:lt(K0.ink2,.25),r:K0.ink2}));}
 else{out.push(TW.box(x-(big?8:6),y-(big?14:8),z,big?16:12,big?28:16,big?15:10,{t:lt(K0.kraft,.18),l:K0.kraft,r:dk(K0.kraft,.2)}));}
 return{el:E('g',null,out),k:x+y};
}

/* ================= static memo ================= */
const cache=new Map();
function staticPiece(C,pc,t,v){
 const dv=[],bv=[],sig=[pc.id,v.ls,v.labels?1:0,v.people?1:0];
 pc.plan.districts.forEach(d=>{const dsT=pc.kind==='island'?(pc.is.hidden?C.ISV[pc.id]:0):C.DS[d.id];const on=dsT!=null&&t>=dsT;if(on)dv.push(d.id);sig.push(on?1:0);
  d.buildings.forEach(b=>{const s=bState(C,b.id,t);const work=s&&v.busy.has(b.id);if(s)bv.push(b.id);sig.push(s?[s.state,s.flag,s.tag,s.fl,work?1:0].join(':'):'-');});});
 const locked=pc.kind==='island'&&pc.is.locked&&!(C.UNL[pc.id]<=t);sig.push(locked?'L':'U');(pc.plan.gates||[]).forEach(g=>{const al=C.alerts.find(a=>a.gate===g.before&&t>=a.t0);sig.push(al?(al.resolved<=t?'o':'w'):'c');});
 const pres=v.people?C.presence.filter(q=>t>=q.t&&(q.until==null||t<q.until)&&!q.meeting&&pc.plan.districts.some(d=>d.buildings.some(b=>b.id===q.at))):[];
 const com=v.people?C.comments.filter(q=>t>=q.t&&pc.plan.districts.some(d=>d.buildings.some(b=>b.id===q.at))):[];
 sig.push(pres.map(q=>q.at+q.initials).join(','),com.map(q=>q.at+q.n).join(','));
 const key=sig.join('|');if(cache.has(key))return cache.get(key);
 const plan={gates:(pc.plan.gates||[]).map(g=>{const al=C.alerts.find(a=>a.gate===g.before&&t>=a.t0);return{...g,state:al?(al.resolved<=t?'open':'waiting'):g.state};}),presence:pres.map(q=>({at:q.at,initials:q.initials,color:q.color})),comments:(()=>{const m={};com.forEach(q=>m[q.at]=(m[q.at]||0)+q.n);return Object.keys(m).map(k=>({at:k,n:m[k]}));})(),
  districts:pc.plan.districts.map(d=>({...d,locked,buildings:d.buildings.map(b=>{const s=bState(C,b.id,t)||{state:'planned'};let state=s.state;
   if(state==='idle'&&v.busy.has(b.id))state='active';if(s.flag==='needs'&&state!=='planned')state='needs';if(s.flag==='blocked'&&state!=='planned')state='blocked';
   const tagOn=s.tag&&(state==='active'||state==='idle'||state==='complete');if(tagOn&&state==='idle')state='active';
   const nb={...b,state,event:tagOn&&state==='active'?(s.icon||b.icon||'dot'):undefined,count:tagOn&&state==='active'?s.tag:undefined};
   if(s.fl){if(b.gen)nb.gen={...b.gen,fl:s.fl};else nb.fl=s.fl;}return nb;})}))};
 const r=TW.world(plan,{seed:pc.seed,labels:v.labels,anim:false,parts:true,ls:v.ls,dvis:new Set(dv),bvis:new Set(bv)});
 const tr=P(pc.dx,pc.dy,pc.z),tf=`translate(${tr[0].toFixed(1)} ${tr[1].toFixed(1)})`;
 const out={ground:E('g',{transform:tf,key:'g'+pc.id},r.ground),objs:r.objs.map((o,i)=>({k:o.k+pc.dx+pc.dy,el:E('g',{transform:tf,key:pc.id+'o'+i},o.el)})),cover:E('g',{transform:tf,key:'c'+pc.id},r.cover),top:E('g',{transform:tf,key:'t'+pc.id},r.top)};
 if(cache.size>600)cache.clear();cache.set(key,out);return out;
}

/* ================= frame render ================= */
function render(C,t,v){
 v=Object.assign({lod:'mid',ls:1,focus:null,ghost:true,sel:null,overlays:{},lens:'story',reduced:false,pick:()=>{},hover:null},v||{});
 const geo=C.geo,ov=v.overlays,lod=v.lod,layers=[],fxNow=C.fx.filter(f=>t>=f.t0&&t<f.t1);
 const ags=[];Object.values(C.A).forEach(a=>{const s=agentAt(C,a,t,v.reduced);if(s)ags.push({a,s});});
 const busy=new Set(ags.filter(q=>q.s.working).map(q=>q.s.working));
 const meets=meetingsAt(C,t);
 const talkMap={};meets.forEach(m=>{const at=m.attendees.filter(id=>C.A[id]);if(!at.length)return;const k=Math.floor((t-m.t0)/1.4)%at.length;talkMap[at[k]]=1;});
 const vv={ls:v.ls,labels:lod!=='far',people:ov.people!==false,busy};
 const agById={};ags.forEach(q=>agById[q.a.id]=q);
 const scr=p=>P(p[0],p[1],p[2]);
 const agTop=q=>{const s=scr(q.s.p);return[s[0],s[1]-(q.a.rank==='director'?40:q.a.rank==='lead'?36:33)];};
 geo.levels.forEach((l,li)=>{
  const t0=C.LV[l.id];if(t0==null||t<t0)return;
  if(v.view){const b=l.box,w=v.view;if(b[1]<w[0]||b[0]>w[1]||b[3]<w[2]||b[2]>w[3])return;}
  const ghostL=v.ghost&&v.focus!=null&&v.focus!=='all'&&li>v.focus;
  const age=t-t0,ap=v.reduced?1:easeBack(clamp(age/.7,0,1)),op=v.reduced?clamp(age/.3,0,1):clamp(age/.35,0,1);
  const pcs=[l.pc,...l.islands.filter(s=>!s.is.hidden||(C.ISV[s.id]!=null&&t>=C.ISV[s.id]))];
  const st=pcs.map(pc=>staticPiece(C,pc,t,vv));
  const g=[];
  st.forEach(s=>g.push(s.ground));
  const belowL=v.focus!=null&&v.focus!=='all'&&li<v.focus;
  if(ghostL||belowL){const m0=l.pc,vx0=P(m0.dx-M0,m0.dy+m0.L.Dt+M0,m0.z-10),w0=l.name.length*16*.58+70;layers.push(E('g',{key:'L'+l.id,opacity:ghostL?.16:.45,style:{filter:'saturate(.5)'}},g,E('g',{key:'lp',onClick:e=>{e.stopPropagation();v.pick({kind:'level',id:l.id});},style:{cursor:'pointer'}},E('rect',{x:vx0[0]-w0-18,y:vx0[1]-18,width:w0,height:40,rx:20,fill:K0.ink}),E('text',{x:vx0[0]-w0,y:vx0[1]+7,fontFamily:K0.body,fontSize:16,fontWeight:800,fill:'#FFFFFF'},l.code+'  '+l.name))));if(belowL){const lf=geo.lifts[li];if(lf){const nx=geo.levels[li+1];const L1=TW.liftEl(lf.x,lf.yS,l.pc.z,nx.pc.z,{state:'active',t:0});layers.push(E('g',{key:'lift'+li,opacity:.6},TW.landing(lf.x,lf.fa,lf.yS-12,l.pc.z),L1.el,TW.landing(lf.x,lf.fb,lf.yS-12,nx.pc.z)));}}return;}
  // bridges
  l.islands.forEach(s=>{if(!pcs.includes(s))return;const b=C.BR[s.br.id];const sv=b?last(b.st,t):null;const state=sv?sv[1]:'none';const f=sv&&state==='building'?(t-sv[0])/1.2:1;
   g.push(E('g',{key:'br'+s.br.id,onClick:e=>{e.stopPropagation();v.pick({kind:'bridge',id:s.br.id});},style:{cursor:'pointer'}},bridgeEl(s.br,state,f),ov.conn?(()=>{const [,a,b]=bridgePts(s.br),m=P((a[0]+b[0])/2,(a[1]+b[1])/2,s.br.level.z);return E('polygon',{points:TW.pts([P(a[0],a[1],l.pc.z),P(b[0],b[1],l.pc.z)].map(p=>p)),stroke:K0.hero,strokeWidth:0});})():null));});
  // objects + agents sorted
  const objs=[];st.forEach(s=>objs.push(...s.objs));
  fxNow.filter(f=>f.k==='cart').forEach((f,i)=>{const brd=geo.bridges[f.br];if(!brd||brd.level!==l.pc)return;const c=cartEl(brd,(t-f.t0)/(f.t1-f.t0),f.size,f.dir);objs.push({k:c.k,el:E('g',{key:'cart'+f.t0+i},c.el)});});
  // meeting tables
  meets.forEach(m=>{const bi=geo.bIdx[m.at];if(!bi||bi.pc.lv!==l&&bi.pc.level!==l.pc&&bi.pc!==l.pc)return;if(m.kind==='standup')return;const c=seatCenter(geo,m.at);const gx=c[0]+bi.pc.dx,gy=c[1]+bi.pc.dy;objs.push({k:gx+gy,el:E('g',{key:'tbl'+m.id,onClick:e=>{e.stopPropagation();v.pick({kind:'meeting',id:m.id});},style:{cursor:'pointer'}},TW.box(gx-12,gy-7,bi.pc.z,24,14,7,{t:'#FFFFFF',l:'#E3E0D8',r:'#CFCABF'}))});});
  ags.forEach(q=>{const pz=q.s.p[2];const onL=Math.abs(pz-l.pc.z)<1;if(!onL)return;objs.push({k:q.s.p[0]+q.s.p[1]+.5,el:agentEl(q)});});
  // construction bots
  fxNow.filter(f=>f.k==='build').forEach(f=>{const bi=geo.bIdx[f.at];if(!bi||(bi.pc!==l.pc&&bi.pc.level!==l.pc))return;const s=TW.standOf(bi.bb);[0,1].forEach(j=>{const x=s[0]+bi.pc.dx+(j?bi.bb.s.fp[0]*T-18:-6),y=s[1]+bi.pc.dy-2;const jig=v.reduced?0:Math.abs(Math.sin((t-f.t0)*9+j))*2;objs.push({k:x+y+.4,el:E('g',{key:'bot'+f.at+j,transform:`translate(0 ${-bi.pc.z-jig})`},TW.agent({role:'bot',expr:'focused',facing:j?'L':'R'},x,y,{scale:TW.AS*.85}))});});});
  objs.sort((a,b)=>a.k-b.k);g.push(objs.map(o=>o.el));
  st.forEach(s=>g.push(s.cover));
  // cloud lift animation after unlock
  l.islands.forEach(s=>{const u=C.UNL[s.id];if(u!=null&&t>=u&&t<u+1.4&&!v.reduced){const f=(t-u)/1.4;const tr=P(s.dx,s.dy,s.z);const cb=s.L.blocks[0];g.push(E('g',{key:'cl'+s.id,transform:`translate(${tr[0]} ${tr[1]-f*90})`,opacity:1-f},TW.clouds(cb.x,cb.y,cb.w,cb.h,7)));}});
  st.forEach(s=>g.push(s.top));
  // level pill
  const m=l.pc,vx=P(m.dx-M0,m.dy+m.L.Dt+M0,m.z-10),txt=l.name,w=txt.length*16*.58+70,prog=levelProgress(C,l,t);
  g.push(E('g',{key:'lp',onClick:e=>{e.stopPropagation();v.pick({kind:'level',id:l.id});},style:{cursor:'pointer'}},E('rect',{x:vx[0]-w-18,y:vx[1]-18,width:w,height:40,rx:20,fill:K0.ink}),E('rect',{x:vx[0]-w-14,y:vx[1]-14,width:40,height:32,rx:16,fill:l.color||K0.hero}),E('text',{x:vx[0]-w+6,y:vx[1]+7,textAnchor:'middle',fontFamily:K0.body,fontSize:15,fontWeight:800,fill:'#FFFFFF'},l.code),E('text',{x:vx[0]-w+34,y:vx[1]+7,fontFamily:K0.body,fontSize:16,fontWeight:800,fill:'#FFFFFF'},txt),
   E('rect',{x:vx[0]-w-8,y:vx[1]+26,width:w-12,height:6,rx:3,fill:'#D6D0C0'}),E('rect',{x:vx[0]-w-8,y:vx[1]+26,width:Math.max(6,(w-12)*prog),height:6,rx:3,fill:l.color||K0.hero})));
  // dynamic overlays for this level
  const top=[];
  const onLevel=id=>{const bi=geo.bIdx[id];return bi&&(bi.pc===l.pc||bi.pc.level===l.pc);};
  const bt=id=>bTop(C,id,t);
  // heat
  if(ov.heat)Object.keys(C.heat).forEach(id=>{if(!onLevel(id))return;const s=C.heat[id].filter(x=>x[0]<=t).reduce((a,x)=>a+x[1],0);if(!s)return;const bi=geo.bIdx[id],c=P(bi.bb.cx+bi.pc.dx+bi.bb.s.fp[0]*T/2,bi.bb.cy+bi.pc.dy+bi.bb.s.fp[1]*T/2,bi.pc.z);const r=10+Math.sqrt(s)*7;top.push(E('g',{key:'h'+id},E('ellipse',{cx:c[0],cy:c[1],rx:r*1.6,ry:r*.92,fill:K0.amber,fillOpacity:.22,stroke:K0.amber,strokeWidth:2}),pill(s+' cr',c[0],c[1]+r*.92+10,K0.amberLip,'#FFFFFF',11)));});
  // FYI dots
  Object.keys(C.B).forEach(id=>{if(!onLevel(id))return;const s=bState(C,id,t);if(s&&s.flag==='fyi'){const b=bt(id);top.push(E('g',{key:'fyi'+id},TW.pin('fyi',b.top,{r:8})));}});
  // queues / bottlenecks
  const qs={};ags.forEach(q=>{if(!q.s.moving&&q.s.loc&&q.s.loc.q!=null&&onLevel(q.s.loc.at))qs[q.s.loc.at]=(qs[q.s.loc.at]||0)+1;});
  Object.keys(qs).forEach(id=>{const n=qs[id],bi=geo.bIdx[id],s=TW.standOf(bi.bb),p=P(s[0]+bi.pc.dx-10,s[1]+bi.pc.dy+14,bi.pc.z);top.push(E('g',{key:'q'+id},pill('queue '+n,p[0],p[1]+6,n>3?K0.amber:K0.ink2,n>3?K0.ink:'#FFFFFF',11)));});
  if(ov.bottle)ags.forEach(q=>{if(Math.abs(q.s.p[2]-l.pc.z)>1)return;if(q.s.waiting||(q.s.loc&&q.s.loc.q!=null&&!q.s.moving)){const p=scr(q.s.p);top.push(E('ellipse',{key:'bn'+q.a.id,cx:p[0],cy:p[1],rx:24,ry:13,fill:'none',stroke:K0.amber,strokeWidth:3}));}});
  // connections overlay labels
  if(ov.conn)l.islands.forEach(s=>{if(!pcs.includes(s))return;const b=C.BR[s.br.id];const sv=b?last(b.st,t):null;const [,a,bb]=bridgePts(s.br),mp=P((a[0]+bb[0])/2,(a[1]+bb[1])/2,s.br.level.z);const st2=sv?sv[1]:'not connected';const lab={api:'API',mcp:'MCP',browser:'Browser'}[s.br.type]+' · '+({connected:'connected',building:'building',requested:'requested',rate:'rate-limited',expiring:'expiring',expired:'expired',revoked:'revoked'}[st2]||'not connected');top.push(E('g',{key:'cl'+s.id},pill(lab,mp[0],mp[1]-26,st2==='connected'?K0.ok:st2==='expiring'||st2==='rate'||st2==='expired'?K0.amberLip:K0.ink2,'#FFFFFF',11.5)));});
  // memory routes
  fxNow.filter(f=>f.k==='mem').forEach((f,i)=>{if(!onLevel(f.to))return;const bi=geo.bIdx[f.to];const vb=geo.bIdx[f.from];if(!vb||vb.pc!==bi.pc){return;}const r=TW.route(bi.pc.L,f.from,f.to);if(!r)return;const d=r.map((p,k)=>(k?'L':'M')+P(p[0]+bi.pc.dx,p[1]+bi.pc.dy,bi.pc.z+3.3).map(n=>n.toFixed(1)).join(' ')).join(' ');const fo=Math.min(1,(f.t1-t)/.4,(t-f.t0)/.3);top.push(E('g',{key:'mem'+i,opacity:fo},E('path',{d,stroke:lt(K0.hero,.62),strokeWidth:9,fill:'none',strokeLinecap:'round',strokeLinejoin:'round'}),E('path',{d,stroke:K0.hero,strokeWidth:3,fill:'none',strokeDasharray:'9 7',strokeDashoffset:-(t*18)%16,strokeLinecap:'round',strokeLinejoin:'round'})));});
  // app studio sequence
  fxNow.filter(f=>f.k==='app').forEach((f,i)=>{if(!onLevel(f.at))return;const b=bt(f.at);const pr=clamp((t-f.t0)/(f.t1-f.t0),0,1);const x=b.top[0],y=b.top[1]-58;
   if(f.step==='wireframe'){const n=Math.ceil(pr*5);const L2=[];L2.push(E('path',{d:`M${x-20} ${y+46} L${x-14} ${y+30} M${x+20} ${y+46} L${x+14} ${y+30}`,stroke:K0.ink2,strokeWidth:2}),E('rect',{x:x-40,y:y-8,width:80,height:46,rx:5,fill:'#FFFFFF',stroke:K0.ink,strokeWidth:1.6}));if(n>0)L2.push(E('rect',{x:x-34,y:y-3,width:68,height:7,rx:2,fill:K0.hero}));for(let r=1;r<n;r++)L2.push(E('rect',{x:x-34,y:y+6+r*7,width:r%2?68:52,height:4,rx:2,fill:'#CFCABF'}));top.push(E('g',{key:'wf'+i},L2));}
   if(f.step==='assemble'){const n=Math.floor(pr*9)+1;const L2=[E('rect',{x:x-40,y:y-8,width:80,height:46,rx:5,fill:'#FFFFFF',stroke:K0.ink,strokeWidth:1.6})];for(let k=0;k<n&&k<9;k++){const cx=k%3,cy=Math.floor(k/3);L2.push(E('rect',{x:x-34+cx*23,y:y-3+cy*13,width:20,height:10,rx:2.5,fill:cy===0?K0.hero:lt(K0.hero,.55+cx*.1)}));}top.push(E('g',{key:'as'+i},L2));}
   if(f.step==='wire'){(f.wires||[]).forEach((bid,j)=>{const brd=geo.bridges[bid];if(!brd)return;const pts=bridgePts(brd);const bi=geo.bIdx[f.at];const s0=TW.standOf(bi.bb);const a=[s0[0]+bi.pc.dx,s0[1]+bi.pc.dy],m=pts[0];const d=`M${P(a[0],a[1],l.pc.z+3.5).join(' ')} L${P(a[0],m[1],l.pc.z+3.5).join(' ')} L${P(m[0],m[1],l.pc.z+3.5).join(' ')} L${P(pts[1][0],pts[1][1],l.pc.z+3.5).join(' ')}`;top.push(E('path',{key:'w'+i+j,d,stroke:K0.hero,strokeWidth:2.6,fill:'none',strokeDasharray:'4 6',strokeDashoffset:-(t*20)%10,strokeLinecap:'round',strokeLinejoin:'round',opacity:clamp(pr*3,0,1)}));});}
  });
  // review whiteboard over Meeting Hall
  meets.forEach(m=>{if(!onLevel(m.at)||m.kind!=='review'&&m.kind!=='decision')return;const b=bt(m.at);const x=b.top[0],y=b.top[1]-56;top.push(E('g',{key:'mb'+m.id,onClick:e=>{e.stopPropagation();v.pick({kind:'meeting',id:m.id});},style:{cursor:'pointer'}},E('path',{d:`M${x-18} ${y+44} L${x-12} ${y+30} M${x+18} ${y+44} L${x+12} ${y+30}`,stroke:K0.ink2,strokeWidth:2}),E('rect',{x:x-44,y:y-10,width:88,height:44,rx:5,fill:'#FFFFFF',stroke:K0.ink,strokeWidth:1.6}),m.kind==='decision'?[['A',-26],['B',0],['C',26]].map(([c,dx])=>E('g',{key:c},E('rect',{x:x+dx-10,y:y-2,width:20,height:28,rx:4,fill:c==='B'?lt(K0.hero,.75):'#EFECE4'}),E('text',{x:x+dx,y:y+17,textAnchor:'middle',fontFamily:K0.body,fontSize:13,fontWeight:900,fill:K0.ink},c))):[E('rect',{key:'a',x:x-36,y:y-4,width:30,height:30,rx:3,fill:lt(K0.hero,.7)}),E('rect',{key:'b',x:x,y:y-2,width:34,height:5,rx:2,fill:'#CFCABF'}),E('rect',{key:'c',x:x,y:y+8,width:26,height:5,rx:2,fill:'#CFCABF'})]));});
  // You at the table
  C.presence.filter(q=>q.meeting&&t>=q.t&&(q.until==null||t<q.until)&&onLevel(q.at)).forEach(q=>{const bi=geo.bIdx[q.at],c=seatCenter(geo,q.at),p=P(c[0]+bi.pc.dx+30,c[1]+bi.pc.dy+12,bi.pc.z+18);top.push(E('g',{key:'you'+q.t},TW.presence(p,q.initials,q.color)));});
  // fx: pop, pulse, stamp, card, made, spawn, arc, toVault
  fxNow.forEach((f,i)=>{const pr=clamp((t-f.t0)/(f.t1-f.t0),0,1);
   if((f.k==='pop'||f.k==='pulse'||f.k==='made')&&onLevel(f.at)){const b=bt(f.at);const r=(f.k==='pulse'?14:10)+pr*(f.k==='pulse'?16:20);top.push(E('circle',{key:'fx'+i,cx:b.top[0],cy:b.top[1]-(f.k==='pulse'?26:8),r,fill:'none',stroke:f.k==='pulse'?K0.red:f.k==='made'?K0.hero:K0.ok,strokeWidth:3*(1-pr)+.5,opacity:1-pr}));}
   if(f.k==='stamp'&&onLevel(f.at)){const b=bt(f.at);const sc=v.reduced?1:easeBack(clamp(pr*3,0,1));const x=b.top[0]+26,y=b.top[1]-10,col=f.okay?K0.ok:K0.amber;top.push(E('g',{key:'st'+i,transform:`translate(${x} ${y}) scale(${sc}) rotate(-12)`,opacity:pr>.8?(1-pr)*5:1},E('rect',{x:-20,y:-12,width:40,height:24,rx:6,fill:'#FFFFFF',stroke:col,strokeWidth:3}),icon(f.okay?'check':'swap',col,0,0,1.1)));}
   if(f.k==='card'&&onLevel(f.at)){const b=bt(f.at);const y=b.top[1]-80-pr*10;top.push(E('g',{key:'cd'+i,opacity:pr>.85?(1-pr)/.15:1},itemEl('decision',b.top[0]+60,y),pill('Decision sealed',b.top[0]+60,y-20,K0.hero,'#FFFFFF',11)));}
   if(f.k==='spawn'){const q=agById[f.actor];if(!q||Math.abs(q.s.p[2]-l.pc.z)>1)return;const p=agTop(q);top.push(E('circle',{key:'sp'+i,cx:p[0],cy:p[1]+12,r:12+pr*22,fill:'none',stroke:K0.hero,strokeWidth:2.5*(1-pr)+.4,opacity:1-pr}));if(pr<.9)top.push(E('g',{key:'spl'+i},pill((q.a.name)+' · '+(q.a.title||q.a.role),p[0],p[1]-26,K0.ink,'#FFFFFF',11.5)));}
   if(f.k==='arc'){const A=agById[f.from],B=agById[f.to];if(!A||!B||Math.abs(A.s.p[2]-l.pc.z)>1)return;const a=agTop(A),b=agTop(B),mx=(a[0]+b[0])/2,my=Math.min(a[1],b[1])-26,u=pr;const x=(1-u)*(1-u)*a[0]+2*(1-u)*u*mx+u*u*b[0],y=(1-u)*(1-u)*(a[1]+8)+2*(1-u)*u*my+u*u*(b[1]+8);top.push(E('g',{key:'arc'+i},E('path',{d:`M${a[0]} ${a[1]+8} Q${mx} ${my} ${b[0]} ${b[1]+8}`,stroke:K0.hero,strokeWidth:2,fill:'none',strokeDasharray:'4 4'}),itemEl(f.item||'parcel',x,y)));}
   if(f.k==='toVault'){const vb=geo.bIdx[f.to];if(!vb||!onLevel(f.to))return;const b=bt(f.to);const q=agById[f.actor];let a=null;if(q&&Math.abs(q.s.p[2]-l.pc.z)<1)a=agTop(q);else if(f.from&&onLevel(f.from))a=bt(f.from).top;if(!a)a=[b.top[0]-160,b.top[1]-120];const u=easeIO(pr),mx=(a[0]+b.top[0])/2,my=Math.min(a[1],b.top[1])-60;const x=(1-u)*(1-u)*a[0]+2*(1-u)*u*mx+u*u*b.top[0],y=(1-u)*(1-u)*a[1]+2*(1-u)*u*my+u*u*b.top[1];top.push(E('g',{key:'tv'+i},itemEl(f.item,x,y)));}
   if(f.k==='dpop'){}
  });
  // bubbles
  fxNow.filter(f=>f.k==='bubble').forEach((f,i)=>{const q=agById[f.actor];if(!q||Math.abs(q.s.p[2]-l.pc.z)>1||lod==='far')return;const p=agTop(q);top.push(E('g',{key:'bb'+i},bubbleEl(p[0]+4,p[1]-4,f.icon==='help'?'help':f.icon,f.icon==='coin'?K0.amberLip:K0.ink)));});
  // agent overlays: badge, item, selection, name
  ags.forEach(q=>{if(Math.abs(q.s.p[2]-l.pc.z)>1||lod==='far')return;const p=agTop(q);const o=[];
   if(q.s.item){const s=scr(q.s.p);o.push(itemEl(q.s.item,s[0]-12,s[1]-18));}
   if(q.s.badge)o.push(pill(q.s.badge,p[0]+14,p[1]-2,K0.ink,'#FFFFFF',10));
   const sel=v.sel&&v.sel.kind==='agent'&&v.sel.id===q.a.id,hov=v.hover===q.a.id;
   if(sel||hov||lod==='near'&&q.a.rank!=='specialist'){o.push(pill(q.a.name+(sel&&q.a.title?' · '+q.a.title:''),p[0],p[1]-(q.s.item?30:16),sel?K0.hero:K0.ink,'#FFFFFF',11));}
   if(o.length)top.push(E('g',{key:'ao'+q.a.id,opacity:q.s.op,style:{pointerEvents:'none'}},o));});
  // selection ring for building
  if(v.sel&&v.sel.kind==='building'&&onLevel(v.sel.id)){const bi=geo.bIdx[v.sel.id],W=bi.bb.s.fp[0]*T,D=bi.bb.s.fp[1]*T;top.push(E('polygon',{key:'selb',points:TW.pts([[0,0],[W,0],[W,D],[0,D]].map(([x,y])=>P(bi.bb.cx+bi.pc.dx+x,bi.bb.cy+bi.pc.dy+y,bi.pc.z+3.5))),fill:'none',stroke:K0.hero,strokeWidth:3,strokeDasharray:'8 5',style:{pointerEvents:'none'}}));}
  if(v.kfocus&&onLevel(v.kfocus)){const bi=geo.bIdx[v.kfocus],W=bi.bb.s.fp[0]*T,D=bi.bb.s.fp[1]*T;top.push(E('polygon',{key:'kf',points:TW.pts([[-4,-4],[W+4,-4],[W+4,D+4],[-4,D+4]].map(([x,y])=>P(bi.bb.cx+bi.pc.dx+x,bi.bb.cy+bi.pc.dy+y,bi.pc.z+3.5))),fill:'none',stroke:K0.ink,strokeWidth:3,style:{pointerEvents:'none'}}));}
  // trails
  if(ov.trail&&v.sel&&v.sel.kind==='agent'){const a=C.A[v.sel.id];if(a)a.segs.forEach((s,i)=>{if(s.t0>t)return;const age=t-s.t1;const op=clamp(1-age/30,.15,1);const pts=s.pts.filter(p=>Math.abs(p[2]-l.pc.z)<1);if(pts.length<2)return;const d=pts.map((p,k)=>(k?'L':'M')+P(p[0],p[1],p[2]+2).map(n=>n.toFixed(1)).join(' ')).join(' ');top.push(E('path',{key:'tr'+i,d,stroke:K0.hero,strokeWidth:2.4,fill:'none',strokeDasharray:'2 6',strokeLinecap:'round',opacity:op,style:{pointerEvents:'none'}}));});}
  // escalation chains in Trace lens
  if(v.lens==='trace')C.chains.filter(c=>c.t<=t&&t-c.t<14).forEach((c,i)=>{const A=agById[c.from],B=agById[c.to];if(!A||!B)return;if(Math.abs(A.s.p[2]-l.pc.z)>1&&Math.abs(B.s.p[2]-l.pc.z)>1)return;const a=scr(A.s.p),b=scr(B.s.p);top.push(E('path',{key:'ch'+i,d:`M${a[0]} ${a[1]-12} L${b[0]} ${b[1]-12}`,stroke:K0.red,strokeWidth:1.6,strokeDasharray:'3 4',style:{pointerEvents:'none'}}));});
  // building hit areas (keyboard + click)
  const hits=[];pcs.forEach(pc=>Object.values(pc.L.bmap).forEach(bb=>{const s=bState(C,bb.id,t);if(!s)return;const b=bt(bb.id);const r=b.rect;hits.push(E('rect',{key:'hit'+bb.id,x:r[0],y:r[2],width:r[1]-r[0],height:r[3]-r[2],fill:'transparent',tabIndex:0,'aria-label':b.spec.n,onClick:e=>{e.stopPropagation();v.pick({kind:'building',id:bb.id});},onFocus:()=>v.onKFocus&&v.onKFocus(bb.id),onKeyDown:e=>{if(e.key==='Enter'){v.pick({kind:'building',id:bb.id});}},style:{cursor:'pointer',outline:'none'}}));}));
  const ghost=v.ghost&&v.focus!=null&&v.focus!=='all'&&li>v.focus;
  const done=levelProgress(C,l,t)>=.999;
  const below=v.focus!=null&&v.focus!=='all'&&li<v.focus;
  layers.push(E('g',{key:'L'+l.id,opacity:(ghost?.14:below?.5:1)*op,transform:`translate(0 ${(1-ap)*-70})`,style:{filter:done||below?'saturate(.55)':null,transition:v.reduced?null:'opacity .5s'}},g,E('g',{key:'hits'},hits),top));
  // lifts between l and next
  const lf=geo.lifts[li];if(lf&&C.LV[geo.levels[li+1].id]!=null&&t>=C.LV[geo.levels[li+1].id]){
   const nx=geo.levels[li+1];const riders=ags.filter(q=>Math.abs(q.s.p[0]-lf.x)<2&&Math.abs(q.s.p[1]-lf.yS)<2&&q.s.p[2]>l.pc.z-1&&q.s.p[2]<nx.pc.z+1&&q.s.moving);
   const zc=riders.length?riders[0].s.p[2]:l.pc.z;const planned=levelProgress(C,nx,t)<.01&&!riders.length&&!Object.values(C.A).some(a=>a.segs.some(s=>s.t0<=t&&s.pts.some(p=>Math.abs(p[2]-nx.pc.z)<1)));
   const L1=TW.liftEl(lf.x,lf.yS,l.pc.z,nx.pc.z,{state:planned?'planned':'active',t:(zc-l.pc.z)/GZ});
   const lg=[TW.landing(lf.x,lf.fa,lf.yS-12,l.pc.z),L1.el];if(!planned)lg.push(TW.landing(lf.x,lf.fb,lf.yS-12,nx.pc.z));
   riders.forEach(q=>lg.push(agentEl(q)));
   if(riders.length&&L1.cab){const dest=riders[0].s.seg.pts[riders[0].s.seg.pts.length-1][2]>riders[0].s.p[2]?'up':'down';const tgtLv=geo.levels[Math.round(riders[0].s.seg.pts.filter(p=>Math.abs(p[0]-lf.x)<2&&Math.abs(p[1]-lf.yS)<2).map(p=>p[2]).reduce((a,b)=>dest==='up'?Math.max(a,b):Math.min(a,b))/GZ)];lg.push(pill('to '+(tgtLv?tgtLv.code:''),L1.cab[0]+34,L1.cab[1]-6,K0.hero,'#FFFFFF',12));}
   layers.push(E('g',{key:'lift'+li,opacity:(v.ghost&&v.focus!=null&&v.focus!=='all'&&li>=v.focus+1?.14:1)},lg));
  }
 });
 function agentEl(q){
  const {a,s}=q;const pz=s.p[2];
  if(lod==='far'){const p=scr(s.p);return E('circle',{key:'ag'+a.id,cx:p[0],cy:p[1]-8,r:a.rank==='director'?9:a.rank==='lead'?7.5:6,fill:a.rank==='director'?K0.hero:TW.ROLE[a.role]||K0.hero,stroke:'#FFFFFF',strokeWidth:2,opacity:s.op,onClick:e=>{e.stopPropagation();v.pick({kind:'agent',id:a.id});},style:{cursor:'pointer'}});}
  let ex=s.ex;if(talkMap[a.id]&&!s.moving)ex='talking';
  const back=s.dir==='BR'||s.dir==='BL',facing=s.dir==='R'||s.dir==='BR'?'R':'L';
  const ph=v.reduced?0:(t*(s.mode==='run'?7:4.6));const step=s.moving?Math.floor(ph*2)%2:0;const bob=s.moving&&!v.reduced?Math.abs(Math.sin(ph*Math.PI))*2.2:(ex==='neutral'||ex==='sleepy')&&!v.reduced?Math.sin(t*2.1+a.id.length)*.5:0;
  let sc=TW.AS,dy=0;const born=t-a.born;if(born<.5&&!v.reduced){sc*=easeBack(clamp(born/.5,0,1));dy=-(1-clamp(born/.35,0,1))*26;}
  const el=TW.agent({role:a.role,rank:a.rank,expr:ex,facing,back,step,pack:s.pack,ring:s.waiting},s.p[0],s.p[1],{scale:Math.max(.01,sc)});
  return E('g',{key:'ag'+a.id,transform:`translate(0 ${-pz-bob+dy})`,opacity:s.op,onClick:e=>{e.stopPropagation();v.pick({kind:'agent',id:a.id});},onMouseEnter:()=>v.onHover&&v.onHover(a.id),onMouseLeave:()=>v.onHover&&v.onHover(null),style:{cursor:'pointer'}},el);
 }
 const defs=E('defs',{key:'defs'},E('pattern',{id:'tiloHatch',width:8,height:8,patternUnits:'userSpaceOnUse',patternTransform:'rotate(30)'},E('rect',{width:8,height:8,fill:'#F4EFE2'}),E('rect',{width:3,height:8,fill:'#E4D9BE'})));
 return[defs,...layers];
}

/* ================= card anchors ================= */
function anchorOf(C,target,t){
 if(!target)return null;if(C.geo.bIdx[target]){const b=bTop(C,target,t);return b?[b.top[0],b.top[1]-30]:null;}
 const brd=C.geo.bridges[target];if(brd){const [,a,b]=bridgePts(brd);return P((a[0]+b[0])/2,(a[1]+b[1])/2,brd.level.z+10);}
 const a=C.A[target];if(a){const s=agentAt(C,a,t);if(s)return P(s.p[0],s.p[1],s.p[2]+40);}return null;
}
function travel(geo,A,B,mode){const p=path(geo,A,B);if(!p)return 0;const tm=timing(p,mode||'walk');return tm[tm.length-1];}

return{geometry,compile,render,agentAt,bState,meetingsAt,camLevel,metersAt,openAlerts,levelProgress,anchorOf,bTop,travel,path,GZ,TW,last};
};
})();

/* Generates worlds/k1.layout.json + worlds/k1.events.json. Timing uses the engine's own travel(), so every move lands where the log says. */
function K1(TP){
const g=(id,name,fp,i,x)=>({id,gen:{name,fp,i,...(x||{})}});
const k=(id,kit,x)=>({id,kit,...(x||{})});
const D=(id,name,tint,icon,buildings,x)=>({id,name,tint,icon,buildings,...(x||{})});
const layout={world:'K1 electric scooter',seed:2,tier:'City',levels:[
 {id:'concept',code:'L1',name:'Concept & requirements',color:'#21748A',districts:[
  D('hq','Town Hall','hall','hall',[k('townhall','townhall'),k('desk','desk')],{hall:true}),
  D('market','Market research','research','search',[k('library','library'),g('survey','Rider Survey Lab',[2,1],'person')]),
  D('req','Requirements','analysis','doc',[g('reqhall','Requirements Hall',[2,2],'doc',{fl:2,roof:'gable'}),g('costdesk','Cost Target Desk',[1,1],'coin')])]},
 {id:'design',code:'L2',name:'Industrial design',color:'#89466E',districts:[
  D('style','Styling','delivery','make',[g('sketch','Sketch Studio',[2,1],'make'),g('clay','Clay Studio',[2,2],'make',{fl:1,roof:'dome'})]),
  D('cmf','Colour & finish','people','tag',[g('cmflib','CMF Library',[1,1],'tag')]),
  D('ergo','Ergonomics','learning','person',[g('ergolab','Ergonomics Lab',[2,1],'person')])]},
 {id:'eng',code:'L3',name:'Engineering',color:'#A5663C',districts:[
  D('chassis','Chassis','analysis','wheel',[g('frame','Frame Workshop',[2,2],'make',{fl:2,roof:'gable'}),g('susp','Suspension Bay',[1,1],'wheel')]),
  D('battery','Battery & powertrain','research','battery',[g('pack','Battery Pack Lab',[2,1],'battery'),g('motor','Motor Test Bench',[2,1],'cog')]),
  D('commons','Commons','hall','hall',[k('vault','vault'),k('treasury','treasury'),k('connector','connector'),k('meeting','meeting')],{hall:true}),
  D('elec','Electronics & firmware','learning','screen',[g('ctrl','Controller Lab',[2,1],'screen'),g('fw','Firmware Workshop',[1,1],'doc')]),
  D('apps','Parts & apps','mail','screen',[g('bom','BOM Office',[2,1],'doc',{fl:1,roof:'flat'}),k('appstudio','appstudio'),k('testyard','testyard'),g('pwatch','Parts Watch',[1,1],'screen',{fl:1,roof:'flat',fa:'band'})])],
  gates:[{before:'pwatch',state:'closed'}]},
 {id:'valid',code:'L4',name:'Validation',color:'#5F6770',districts:[
  D('proto','Prototype build','analysis','make',[g('garage','Prototype Garage',[2,2],'make',{fl:1,roof:'gable'})]),
  D('track','Test track','people','flask',[k('testtrack','testyard',{name:'Test Track'}),g('drop','Drop Tower',[1,1],'eye',{fl:4,roof:'flat'})]),
  D('safety','Battery safety','research','battery',[g('thermal','Thermal Chamber',[2,1],'flask'),g('samplelab','Sample Lab',[1,1],'flask')]),
  D('cert','Certification','learning','check',[g('homolog','Homologation Office',[2,1],'doc')])],gates:[{before:'homolog',state:'closed'}]},
 {id:'mfg',code:'L5',name:'Manufacturing',color:'#6C7A30',districts:[
  D('plant','Plant','accounts','cog',[g('line','Assembly Line',[3,2],'cog',{fl:1,roof:'gable'}),g('qc','Quality Gate Office',[1,1],'check')]),
  D('tooling','Tooling','analysis','make',[g('toolshop','Tooling Shop',[2,1],'make'),g('fixture','Fixture Bay',[1,1],'make')]),
  D('logistics','Logistics','delivery','parcel',[g('warehouse','Parts Warehouse',[2,2],'parcel',{fl:1,roof:'flat'}),k('dock','dock')])]},
 {id:'launch',code:'L6',name:'Launch & service',color:'#5A3FE0',districts:[
  D('mkt','Marketing','delivery','chart',[g('launchstudio','Launch Studio',[2,1],'chart')]),
  D('dealers','Dealers','accounts','screen',[g('portal','Dealer Portal',[2,1],'screen')]),
  D('service','Service','learning','doc',[g('manual','Service Manual Press',[1,1],'doc'),g('spares','Spare Parts Depot',[2,1],'parcel')])]}
],islands:[
 {id:'cells',level:'eng',name:'Voltacell · cells',tint:'research',icon:'battery',side:'x',bridge:{id:'br-cells',type:'api',name:'Voltacell API'},buildings:[g('cellplant','Cell Plant',[2,1],'battery')]},
 {id:'motors',level:'eng',name:'Northline Motors',tint:'learning',icon:'cog',side:'x',bridge:{id:'br-motors',type:'mcp',name:'Northline agent server (MCP)'},buildings:[g('motorworks','Motor Works',[2,1],'cog')]},
 {id:'pricing',level:'eng',name:'Supplier pricing',tint:'payroll',icon:'lock',side:'y',locked:true,bridge:{id:'br-pricing',type:'browser',name:'Pricing portal (browser)'},buildings:[g('pricebook','Price Book',[2,1],'coin'),g('contracts','Contract Files',[1,1],'doc')]},
 {id:'kelvra',level:'eng',name:'Kelvra Cells',tint:'research',icon:'battery',side:'y',hidden:true,bridge:{id:'br-kelvra',type:'api',name:'Kelvra API'},buildings:[g('kelvrafab','Kelvra Cell Works',[2,1],'battery')]}
]};
const geo=TP.geometry(layout);
const NAME={};Object.values(geo.bIdx).forEach(b=>NAME[b.bb.id]=b.bb.s.n);
let EV=[],N=0,WHEN=null;const LOC={},BUILT=new Set(),AG={};
const clean=o=>{const r={};Object.keys(o||{}).forEach(k=>{if(o[k]!==undefined&&o[k]!==null)r[k]=o[k];});return Object.keys(r).length?r:undefined;};
const E=(ts,type,f)=>{const e={id:'e'+String(++N).padStart(3,'0'),ts:Math.round(ts*100)/100,type,...(f||{})};if(e.data)e.data=clean(e.data);if(WHEN)e.when={...WHEN};EV.push(e);return e;};
const build=(ts,b,s)=>{if(BUILT.has(b))return;BUILT.add(b);E(ts,'building.constructing',{target:b,actor:'bots',summary:s||`Built ${NAME[b]}`});E(ts+1.5,'building.operational',{target:b});};
function go(ts,a,to,o){o=o||{};const L2={at:to,...(o.loc||{})};const mode=o.mode||(o.item?'carry':'walk');const d=TP.travel(geo,LOC[a],L2,mode);
 E(ts,'agent.moved',{actor:a,target:to,item:o.item,data:{loc:o.loc,mode:o.mode,hold:o.hold||undefined,follow:o.follow||undefined},summary:o.summary});LOC[a]=L2;const arr=ts+d;if(o.build)build(arr,to,o.buildSummary);return arr;}
function spawn(ts,a,meta,slot){AG[a]=meta;LOC[a]={at:'townhall',slot:slot||0};E(ts,'agent.spawned',{actor:a,target:'townhall',data:{...meta,loc:{slot:slot||0}},summary:`Director built ${meta.name}, ${meta.title}`});}
const work=(ts,a,b,cr,s,x)=>E(ts,'agent.working',{actor:a,target:b,credits:cr,summary:s,data:x});
const art=(ts,a,b,item,s,x)=>E(ts,'artifact.created',{actor:a,target:b,item,summary:s,data:x});
function branch(when,fn){const L0=JSON.parse(JSON.stringify(LOC)),B0=new Set(BUILT);WHEN=when;fn();WHEN=null;const L1=JSON.parse(JSON.stringify(LOC));Object.keys(LOC).forEach(k=>delete LOC[k]);Object.assign(LOC,L0);BUILT.clear();B0.forEach(b=>BUILT.add(b));return L1;}
const plannedAll=(ts,lv,step)=>{const l=layout.levels.find(v=>v.id===lv);let t=ts;l.districts.forEach(d=>{E(t,'district.created',{level:lv,district:d.id,data:{nocam:true},summary:undefined});d.buildings.forEach(b=>{E(t+.05,'building.planned',{target:b.id,data:{nocam:true}});});t+=step;});
 layout.islands.filter(i=>i.level===lv&&!i.hidden).forEach(i=>i.buildings.forEach(b=>E(t,'building.planned',{target:b.id,data:{nocam:true}})));};

/* ---------- 0 · Director builds the world ---------- */
E(0,'world.created',{actor:'director',data:{cam:'all',title:'Take the K1 electric scooter from concept to launch'},summary:'New task: take the K1 electric scooter from concept to launch.'});
E(.3,'level.created',{level:'concept',data:{nocam:true},summary:'Planned Level 1 · Concept & requirements'});plannedAll(.5,'concept',.15);
build(.9,'townhall','Built the Town Hall');build(1.2,'desk','Built Your Desk. Requests for you arrive here.');
spawn(2.6,'director',{role:'director',rank:'director',name:'Director',title:'Director',tools:['Planner','Every district'],scope:['All bridges'],budget:2400},0);
LOC.director={at:'townhall',slot:0};
[['design',3.2,'Level 2 · Industrial design'],['eng',3.8,'Level 3 · Engineering, 5 workstreams, 3 supplier islands'],['valid',4.4,'Level 4 · Validation'],['mfg',5.0,'Level 5 · Manufacturing'],['launch',5.6,'Level 6 · Launch & service']].forEach(([lv,t,s])=>{E(t,'level.created',{level:lv,actor:'director',data:{nocam:true},summary:'Planned '+s});plannedAll(t+.2,lv,.1);});
E(6.4,'alert.raised',{actor:'director',target:'townhall',severity:'nudge',data:{id:'a-plan',kind:'nudge'},summary:'Plan ready: 6 levels, 21 workstreams, 3 suppliers. Starting with Concept.',credits:6});

/* ---------- L1 · Concept ---------- */
spawn(6.8,'ivo',{role:'research',rank:'lead',name:'Ivo',title:'Research Lead',tools:['Browser','Library'],scope:['Public web'],budget:40},1);
spawn(7.2,'pim',{role:'research',name:'Pim',title:'Survey Analyst',tools:['Survey tool'],scope:['Survey panel'],budget:20},2);
spawn(7.6,'tess',{role:'tester',name:'Tess',title:'Reviewer',tools:['Checklist'],scope:[],budget:10},3);
let a=go(7.4,'ivo','library',{build:true,buildSummary:'Built the Library for rider and market research'});
let b=go(7.8,'pim','survey',{build:true});
let c=go(8.2,'tess','costdesk',{build:true});
work(a+.2,'ivo','library',8,'Ivo is reading 212 rider interviews and 9 market reports');
E(a+.6,'memory.hit',{actor:'ivo',target:'library',data:{saved:22,from:'library'},summary:'Reused S1 rider research from memory. 22 credits saved.'});
work(b+.2,'pim','survey',6,'Pim is running the rider survey (1,140 replies)');
work(c+.2,'tess','costdesk',3,'Tess is setting the cost target: €1,450 bill of materials');
art(a+3.2,'ivo','library','scroll','Market brief: commuters want 40 km range and a 14 kg frame',{minutes:25,hold:true});
a=go(a+3.4,'ivo','reqhall',{item:'scroll',hold:true,build:true});
work(a+.2,'ivo','reqhall',9,'Ivo is drafting requirements');
art(a+2.4,'ivo','reqhall','doc','Requirements v1: 64 requirements',{minutes:30,hold:true,tag:'64 reqs',tagIcon:'doc'});
a=go(a+2.6,'ivo','costdesk',{item:'doc',hold:true,loc:{slot:1}});
E(a+.2,'artifact.reviewed',{actor:'tess',target:'costdesk',item:'doc',data:{result:'changes'},summary:'Tess sent requirements back: 3 conflict with the cost target',credits:2});
E(a+1.8,'agent.working',{actor:'ivo',target:'costdesk',credits:3,summary:'Ivo reconciled the 3 conflicting requirements'});
E(a+3.2,'artifact.reviewed',{actor:'tess',target:'costdesk',item:'doc',data:{result:'approved'},summary:'Tess approved Requirements v1.1',credits:2});
const l1done=a+3.6;
['library','survey','reqhall','costdesk'].forEach((id,i)=>E(l1done+.6+i*.15,'building.archived',{target:id,data:{nocam:true}}));
E(l1done+.4,'agent.idle',{actor:'pim',summary:'Pim is idle: survey closed'});
// Tess retires
c=go(l1done+1,'tess','townhall',{loc:{slot:3}});
E(c+.1,'memory.saved',{actor:'tess',target:'townhall',item:'scroll',summary:'Tess filed her review learnings to the Memory Vault'});
E(c+.4,'agent.retired',{actor:'tess',summary:'Tess handed in her key-card and retired'});

/* ---------- Foundry wave for Engineering (walk up while L1/L2 run) ---------- */
const crew=[
 ['fenn',{role:'builder',rank:'lead',name:'Fenn',title:'Chassis Lead',tools:['CAD','FEA'],scope:['PLM'],budget:60},'frame',{}],
 ['bo',{role:'builder',name:'Bo',title:'Frame Engineer',tools:['CAD'],scope:['PLM'],budget:30},'frame',{slot:1}],
 ['cy',{role:'tester',name:'Cy',title:'Fatigue Tester',tools:['Test rig'],scope:[],budget:20},'susp',{}],
 ['rue',{role:'research',rank:'lead',name:'Rue',title:'Battery Lead',tools:['Cell models','Parts Watch'],scope:['Voltacell','Kelvra'],budget:60},'pack',{}],
 ['sol',{role:'research',name:'Sol',title:'Cell Specialist',tools:['Cell models'],scope:['Voltacell'],budget:30},'pack',{slot:1}],
 ['dex',{role:'builder',name:'Dex',title:'Motor Engineer',tools:['Dyno'],scope:['Northline'],budget:30},'motor',{}],
 ['lark',{role:'browser',rank:'lead',name:'Lark',title:'Electronics Lead',tools:['EMC scanner','Browser'],scope:['Lab portal'],budget:50},'ctrl',{}],
 ['nell',{role:'builder',name:'Nell',title:'Firmware Engineer',tools:['Compiler'],scope:[],budget:30},'fw',{}],
 ['wren',{role:'delivery',rank:'lead',name:'Wren',title:'BOM Lead',tools:['PLM','ERP'],scope:['PLM','ERP'],budget:50},'bom',{}],
 ['mae',{role:'designer',name:'Mae',title:'App Designer',tools:['App Studio'],scope:[],budget:30},'appstudio',{}],
 ['taz',{role:'builder',name:'Taz',title:'App Builder',tools:['App Studio'],scope:['Voltacell','Northline'],budget:40},'appstudio',{slot:1}],
 ['kip',{role:'tester',name:'Kip',title:'App Tester',tools:['Test Yard'],scope:[],budget:20},'testyard',{}],
 ['lu',{role:'connector',rank:'lead',name:'Lu',title:'Connections Lead',tools:['Connector Post'],scope:['Voltacell','Northline'],budget:40},'connector',{}],
 ['pip',{role:'delivery',name:'Pip',title:'Courier',tools:['Satchel'],scope:[],budget:10},'connector',{slot:1}]
];
const ARR={};
crew.forEach(([id,meta,post,loc],i)=>{const t=9.2+i*.55;spawn(t,id,meta,i%4);ARR[id]=go(t+.5,id,post,{loc:Object.keys(loc).length?loc:undefined,build:true,mode:'walk'});});
E(9.2,'agent.assigned',{actor:'director',data:{nocam:true},summary:'Director assigned 14 agents to Engineering. They are walking up now.'});
// Director moves up to oversee Engineering at the Meeting Hall
let dA=go(15.5,'director','meeting',{loc:{slot:0}});

/* ---------- L2 · Design ---------- */
spawn(10,'juno',{role:'designer',rank:'lead',name:'Juno',title:'Design Lead',tools:['Sketch','Clay','CAD'],scope:['PLM'],budget:60},0);
let j=go(10.3,'juno','sketch',{build:true});
spawn(10.6,'oren',{role:'research',name:'Oren',title:'Ergonomist',tools:['Fit rig'],scope:[],budget:20},1);
let o=go(10.9,'oren','ergolab',{build:true});
work(o+.2,'oren','ergolab',7,'Oren is fitting 5th to 95th percentile riders',{tag:'rider fit v3',tagIcon:'person'});
// Ivo carries requirements up to Design
a=go(l1done+.3,'ivo','sketch',{item:'doc',hold:true,follow:true,loc:{slot:1},summary:'Ivo is taking Requirements v1.1 up to Design'});
const hand1=Math.max(a,j)+.2;
E(hand1,'agent.handoff',{actor:'ivo',target:'juno',item:'doc',summary:'Ivo handed Requirements v1.1 to Juno (Design)'});
E(hand1+.9,'agent.cloned',{actor:'juno',data:{ids:['juno2','juno3']},summary:'Juno split into 3 to sketch, sculpt and pick finishes in parallel'});
LOC.juno2={at:'sketch',dx:15};LOC.juno3={at:'sketch',dx:30};
let j2=go(hand1+1.4,'juno2','clay',{build:true}),j3=go(hand1+1.5,'juno3','cmflib',{build:true});
work(hand1+1.2,'juno','sketch',8,'Juno is sketching 3 surface directions');
work(j2+.2,'juno2','clay',8,'Clay model of direction B');
work(j3+.2,'juno3','cmflib',5,'Picking colours and finishes');
const conv=Math.max(j2,j3)+3;
art(conv-.4,'juno2','clay','blueprint','Surface CAD v2.4 frozen',{minutes:40});
let r2=go(conv,'juno2','sketch',{loc:{dx:15}}),r3=go(conv+.1,'juno3','sketch',{loc:{dx:30}});
const merge=Math.max(r2,r3)+.2;
E(merge,'agent.retired',{actor:'juno2',data:{merge:true},summary:'Juno\'s clones merged back'});E(merge,'agent.retired',{actor:'juno3',data:{merge:true}});
art(merge+.3,'juno','sketch','blueprint','Surface CAD v2.4 released to Engineering',{hold:true,minutes:15});
// Ivo retires back at Town Hall
a=go(hand1+1,'ivo','townhall',{loc:{slot:1}});E(a+.1,'memory.saved',{actor:'ivo',target:'townhall',item:'scroll',summary:'Ivo filed rider research to memory'});E(a+.4,'agent.retired',{actor:'ivo',summary:'Ivo retired. Research is done.'});
// Juno takes CAD up the lift
j=go(merge+.6,'juno','frame',{item:'blueprint',hold:true,follow:true,loc:{slot:2},summary:'Juno is riding the lift to Engineering with Surface CAD v2.4'});
['sketch','clay','cmflib','ergolab'].forEach((id,i)=>E(merge+2+i*.15,'building.archived',{target:id,data:{nocam:true}}));
E(merge+1.5,'agent.idle',{actor:'oren',summary:'Oren is idle: fit study signed off'});

/* ---------- L3 · Engineering ---------- */
const e0=Math.max(j,ARR.fenn,ARR.bo,ARR.cy)+.3;
E(e0,'agent.handoff',{actor:'juno',target:'fenn',item:'blueprint',summary:'Juno handed Surface CAD v2.4 to Fenn (Chassis)'});
work(e0+.8,'fenn','frame',10,'Fenn is revising the frame to rev C',{tag:'rev C',tagIcon:'make'});
work(ARR.bo+.1,'bo','frame',6,'Bo is modelling the steering head');work(ARR.cy+.1,'cy','susp',4,'Cy is preparing the fatigue rig');
work(ARR.rue+.1,'rue','pack',8,'Rue is sizing the battery pack: 48 V, 15 Ah');work(ARR.sol+.1,'sol','pack',5,'Sol is comparing cell datasheets');
work(ARR.dex+.1,'dex','motor',6,'Dex is running the motor on the dyno');work(ARR.lark+.1,'lark','ctrl',8,'Lark is running the EMC pre-scan');
work(ARR.nell+.1,'nell','fw',6,'Nell is writing the battery-management firmware');
work(ARR.wren+.1,'wren','bom',6,'Wren is assembling the bill of materials',{tag:'412 parts',tagIcon:'doc'});
E(ARR.wren+.8,'memory.hit',{actor:'wren',target:'bom',data:{saved:38,from:'vault'},summary:'Reused 318 parts from the S1 BOM in memory. 38 credits saved.'});
work(ARR.lu+.1,'lu','connector',3,'Lu is checking supplier connections');
E(ARR.lu+.6,'connection.requested',{actor:'lu',target:'br-cells',summary:'Lu asked for the Voltacell API connection (pre-approved by Kestrel IT)'});
E(ARR.lu+1.2,'connection.established',{actor:'lu',target:'br-cells',summary:'Connected to Voltacell over API (read-only)'});
E(ARR.lu+3,'data.transfer',{target:'br-cells',data:{dir:'in',size:'cart',mb:2},summary:'Pulled Voltacell catalogue: 48 cell parts'});
// stand-up
const su=e0+2.4;
E(su,'meeting.called',{actor:'fenn',target:'frame',data:{id:'m-standup',kind:'standup',title:'Chassis stand-up',attendees:['fenn','bo','cy','juno'],agenda:['Rev C status','Fatigue rig','CAD v2.4 impact']},summary:'Fenn called the Chassis stand-up'});
let sArr=su;['fenn','bo','cy','juno'].forEach((id,i)=>{sArr=Math.max(sArr,go(su+.1,id,'frame',{loc:{seat:i,of:4}}));});
E(sArr+.1,'meeting.started',{target:'frame',data:{id:'m-standup'},summary:'Stand-up started: 4 agents'});
E(sArr+5.8,'meeting.decision',{target:'frame',data:{id:'m-standup',by:'Fenn',why:'CAD v2.4 moved the deck 12 mm'},summary:'Decided: keep rev C mounting points; Suspension Bay runs fatigue after the frame is released',credits:4});
E(sArr+6.2,'meeting.ended',{target:'frame',data:{id:'m-standup'}});
E(sArr+6.3,'memory.saved',{actor:'fenn',target:'frame',item:'scroll',summary:'Stand-up minutes filed to the Memory Vault'});
go(sArr+6.4,'fenn','frame');go(sArr+6.4,'bo','frame',{loc:{slot:1}});let cyb=go(sArr+6.5,'cy','susp');
work(sArr+7,'fenn','frame',6);work(sArr+7,'bo','frame',4);
E(cyb+.3,'agent.idle',{actor:'cy',summary:'Cy is idle: fatigue rig waits for the frame release'});
// juno retires to L2 (walks back down, fades)
let jb=go(sArr+6.6,'juno','sketch');E(jb+.2,'agent.retired',{actor:'juno',summary:'Juno retired. Design is complete.'});
// controller recovery
const cr=ARR.lark+3;
E(cr,'agent.blocked',{actor:'lark',target:'ctrl',summary:'Controller fails the EMC pre-scan at 150 MHz',severity:'blocked',credits:3});
E(cr+2.4,'memory.hit',{actor:'lark',target:'ctrl',data:{saved:16,from:'vault'},summary:'Found the S1 ferrite fix in memory. 16 credits saved.'});
E(cr+2.6,'agent.recovered',{actor:'lark',target:'ctrl',summary:'Lark is trying another way: a ferrite filter on the motor lead',credits:4});
E(cr+7,'artifact.reviewed',{actor:'lark',target:'ctrl',data:{result:'approved'},summary:'EMC pre-scan passes with 6 dB margin',credits:2});
work(ARR.lark+.1+7,'lark','ctrl',0);
// BOM queue -> scale up
const q0=Math.max(ARR.wren,ARR.dex,ARR.sol,ARR.nell,ARR.bo)+4.5;
const Q=['dex','nell','sol','bo'];Q.forEach((id,i)=>{E(q0+i*.25,'agent.help_requested',{actor:id,target:'wren',summary:i===0?'4 part-change requests are queueing at the BOM Office':undefined});go(q0+i*.25,id,'bom',{loc:{q:i},item:'doc',hold:true});});
const qFull=q0+4.5;
E(qFull,'building.scaled',{target:'bom',data:{fl:2,tag:'412 parts · queue 4',tagIcon:'doc'},summary:'BOM Office added a floor to clear the queue'});
E(qFull+.4,'agent.cloned',{actor:'wren',data:{ids:['wren2']},summary:'Wren cloned to review part changes in parallel'});LOC.wren2={at:'bom',dx:15};
Q.forEach((id,i)=>{const tt=qFull+1.2+i*.9;E(tt,'agent.handoff',{actor:id,target:i%2?'wren2':'wren',item:'doc',summary:i===3?'All 4 part changes reviewed':undefined});});
const posts={dex:['motor'],nell:['fw'],sol:['pack',{slot:1}],bo:['frame',{slot:1}]};
Q.forEach((id,i)=>{const tt=qFull+1.9+i*.9;const pa=go(tt,id,posts[id][0],{loc:posts[id][1]});work(pa+.1,id,posts[id][0],3);});
E(qFull+5.4,'agent.retired',{actor:'wren2',data:{merge:true},summary:'Wren\'s clone merged back. Queue cleared.'});
E(qFull+5.5,'building.scaled',{target:'bom',data:{fl:1,tag:'412 parts',tagIcon:'doc'},summary:'BOM Office scaled back down'});
// budget request
const bq=ARR.sol+2;let sb=go(bq,'sol','treasury');E(sb+.1,'budget.requested',{actor:'sol',target:'treasury',data:{amount:30},summary:'Sol asked the Treasury for 30 credits to order sample cells'});E(sb+1.6,'budget.granted',{actor:'sol',target:'treasury',data:{amount:30},summary:'Granted automatically (under the 50-credit limit)',credits:30});
go(sb+2,'sol','pack',{loc:{slot:1}});

/* ---------- Parts Watch ---------- */
const pw0=Math.max(ARR.wren+3,ARR.mae,ARR.taz)+1;
let wa=go(pw0,'wren','appstudio',{item:'crate',hold:true,loc:{slot:2},summary:'Wren is carrying the 412-part list to App Studio'});
E(wa+.1,'agent.handoff',{actor:'wren',target:'mae',item:'crate',summary:'Wren handed the 412-part list to App Studio'});
E(wa+.3,'app.spec',{actor:'wren',target:'appstudio',item:'scroll',summary:'App spec: track lead time, price, stock and certification for 412 vendor parts. Flag anything that lands after the build date.',credits:4});
go(wa+.8,'wren','bom');
E(wa+.9,'app.building',{actor:'mae',target:'appstudio',data:{step:'wireframe',dur:3},summary:'Mae is sketching the Parts Watch wireframe',credits:6});
// motor consent
E(wa+1.2,'connection.requested',{actor:'lu',target:'br-motors',summary:'Lu requested read-only access to Northline Motors'});
const pipOut=wa+1.4;let pd=go(pipOut,'pip','desk',{mode:'run',item:'key',hold:true,summary:'Pip is running the access request to Your Desk'});
E(pd+.1,'alert.raised',{actor:'pip',target:'desk',severity:'needs',data:{id:'a-motor',kind:'consent',decision:'motor',needBy:pd+9,default:'notnow',defaultBy:'Director',timer:40,anchor:'connector',
 card:{title:'Parts Watch needs read-only access to Northline Motors',why:'64 motor parts would have no lead-time data. You can still build Proto 3 without it.',service:'Northline Motors',method:'Agent protocol (MCP)',
  perms:[['Read part numbers, lead times and stock','So Parts Watch can flag late motor parts'],['Read certification status','To catch parts missing UN 38.3 or CE marks']],
  duration:'90 days, then Tilo asks again',never:'No write access and no pricing. Tilo never sees your password: you sign in with Northline directly.',
  options:[{id:'allow',label:'Allow read-only access',suggested:true,reason:'Motor parts are 16% of the BOM'},{id:'notnow',label:'Not now',detail:'Parts Watch shows motor rows as "no data"'}]}},summary:'Needs you: allow read-only access to Northline Motors?'});
const mNeed=pd+9;
E(wa+4,'app.building',{actor:'taz',target:'appstudio',data:{step:'assemble',dur:4},summary:'Taz is assembling Parts Watch from 9 components',credits:10});
E(wa+4.4,'agent.cloned',{actor:'taz',data:{ids:['taz2']},summary:'Taz cloned to build the table and the trend charts at the same time'});LOC.taz2={at:'appstudio',dx:15};
E(wa+8.4,'agent.retired',{actor:'taz2',data:{merge:true}});
// AM presence + comment
E(wa+3,'user.joined',{actor:'am',target:'pack',data:{initials:'AM',color:'#5A3FE0',who:'Anita M. (Approver)'},summary:'Anita M. joined and is looking at the Battery Pack Lab'});
E(wa+5,'user.commented',{actor:'am',target:'frame',data:{n:1,by:'Anita M.'},summary:'Anita M. on Frame Workshop: "Keep the rev C mounting points. Tooling is already quoted."'});
// pip returns (branch-agnostic)
const pipBack=mNeed+.3;go(pipBack,'pip','connector',{loc:{slot:1},mode:'run'});
const wire=mNeed+.6;
branch({motor:'allow'},()=>{E(mNeed+.2,'connection.consented',{actor:'you',target:'br-motors',summary:'Northline access granted (read-only, 90 days)'});E(mNeed+.4,'connection.established',{actor:'lu',target:'br-motors',summary:'Bridge to Northline Motors built (MCP)'});
 E(wire,'app.building',{actor:'taz',target:'appstudio',data:{step:'wire',dur:3,wires:['br-cells','br-motors']},summary:'Wiring Parts Watch to Voltacell and Northline',credits:6});
 E(wire+1.8,'data.transfer',{target:'br-motors',data:{dir:'in',size:'cart',mb:1},summary:'Pulled 64 motor parts from Northline'});});
branch({motor:'notnow'},()=>{E(wire,'app.building',{actor:'taz',target:'appstudio',data:{step:'wire',dur:3,wires:['br-cells']},summary:'Wiring Parts Watch to Voltacell only. Motor rows show no data.',credits:5});});
E(wire+1,'data.transfer',{target:'br-cells',data:{dir:'in',size:'truck',mb:6},summary:'Synced 348 cell and pack parts from Voltacell'});
// test
let tz=go(wire+3.2,'taz','testyard',{item:'app',hold:true,loc:{slot:1},summary:'Taz is taking Parts Watch to the Test Yard'});
E(tz+.1,'agent.handoff',{actor:'taz',target:'kip',item:'app'});
work(tz+.6,'kip','testyard',6,'Kip is testing Parts Watch with 3 months of history');
E(tz+3.6,'app.tested',{actor:'kip',target:'testyard',summary:'Parts Watch passed 22 of 22 checks',data:{minutes:20}});
E(tz+3.7,'artifact.reviewed',{actor:'kip',target:'testyard',data:{result:'approved'},summary:'Kip approved Parts Watch'});
go(tz+4,'taz','appstudio',{loc:{slot:1}});
// share approval: Kip carries it to Your Desk; Anita can answer
let kd=go(tz+4.2,'kip','desk',{mode:'run',item:'card',hold:true,loc:{slot:1},summary:'Kip is taking the sharing approval to Your Desk'});
E(tz+4.3,'approval.requested',{actor:'kip',target:'pwatch',severity:'needs',data:{id:'a-share',kind:'approval',decision:'share',gate:'pwatch',needBy:kd+8,default:'ops',defaultBy:'Anita M.',timer:14,anchor:'appstudio',
 card:{title:'Share Parts Watch beyond the Engineering team?',why:'Kestrel ops (14 people) would see supplier lead times and stock. Nothing is sent outside Kestrel.',
  options:[{id:'ops',label:'Share with Kestrel ops',suggested:true,reason:'Ops plans the Proto 3 build and needs the lead times'},{id:'team',label:'Keep it to Engineering',detail:'You can share it later'}]}},summary:'Approval: share Parts Watch with Kestrel ops? Anita M. can also answer.'});
const shNeed=kd+8;
go(shNeed+.4,'kip','testyard',{mode:'run'});
const dep=shNeed+.8;
E(dep,'app.deployed',{actor:'taz',target:'pwatch',summary:'Parts Watch is live in Parts & apps'});
build(dep,'pwatch','Built the Parts Watch kiosk');
branch({share:'ops'},()=>E(dep+1.6,'app.refreshed',{target:'pwatch',data:{tag:'412 parts · ops',tagIcon:'screen'},summary:'Parts Watch shared with Kestrel ops'}));
branch({share:'team'},()=>E(dep+1.6,'app.refreshed',{target:'pwatch',data:{tag:'412 parts · team',tagIcon:'screen'},summary:'Parts Watch shared with Engineering only'}));
// pricing request
const prq=dep+1;E(prq,'connection.requested',{actor:'lu',target:'br-pricing',summary:'Lu asked for access to Supplier pricing so Parts Watch can show negotiated prices'});
let pp=go(prq+.2,'pip','desk',{mode:'run',item:'key',hold:true,summary:'Pip is running the pricing access request to Your Desk'});
/* ---------- the slip ---------- */
const slip=dep+3.2;
E(slip,'data.transfer',{target:'br-cells',data:{dir:'in',size:'truck',mb:4},summary:'Scheduled Voltacell sync'});
E(slip+2.4,'app.refreshed',{target:'pwatch',data:{tag:'3 at risk',tagIcon:'flag'},summary:'Parts Watch: Voltacell cell lead time slipped from 6 to 11 weeks'});
E(slip+2.5,'alert.raised',{actor:'sol',target:'pack',severity:'fyi',data:{id:'a-slip',kind:'fyi'},summary:'Voltacell cells now land in week 25. Proto 3 builds in week 22.',credits:3});
E(slip+2.8,'alert.batched',{target:'pwatch',data:{count:3},summary:'3 at-risk parts merged into one issue: all are Voltacell cells'});
E(pp+.1,'alert.raised',{actor:'pip',target:'desk',severity:'needs',data:{id:'a-pricing',kind:'consent',decision:'pricing',needBy:0,default:'decline',defaultBy:'Director',timer:45,anchor:'connector',
 card:{title:'Allow Tilo to read Supplier pricing?',why:'Parts Watch would show negotiated prices, not list prices. Cost decisions get more accurate.',service:'Kestrel supplier pricing portal',method:'Browser, signed in by you',
  perms:[['Read negotiated unit prices for 412 parts','So price changes show up in Parts Watch'],['Read contract end dates','To warn before a price agreement expires']],
  duration:'Until the end of Manufacturing (week 40)',never:'Read-only. Tilo never stores or shows your sign-in; you sign in on the portal itself.',
  options:[{id:'grant',label:'Allow read-only access',suggested:true,reason:'The expedite and switch costs depend on negotiated prices'},{id:'decline',label:'Keep pricing private',detail:'Agents use list prices and route around the island'}]}},summary:'Needs you: allow Tilo to read Supplier pricing?'});
/* disagreement + escalation */
const dg=slip+3.4;
E(dg,'agent.help_requested',{actor:'sol',target:'rue',summary:'Sol asked Rue what to do about the Voltacell slip'});
E(dg+.2,'agent.escalated',{actor:'sol',target:'rue',summary:'Sol escalated to Rue (Battery Lead)'});
spawn(dg-14,'mo',{role:'connector',rank:'lead',name:'Mo',title:'Manufacturing Lead',tools:['ERP','Supplier terms'],scope:['Voltacell','ERP'],budget:60},2);
go(dg-13.6,'mo','pack',{loc:{dx:-34,face:'R'},follow:false});
E(dg+1.4,'agent.working',{actor:'rue',target:'pack',data:{expr:'talking',until:2.6},summary:'Rue: switch to the Kelvra cell validated in the Sample Lab'});
E(dg+1.4,'agent.working',{actor:'mo',target:'pack',data:{expr:'talking',until:2.6},summary:'Mo: expedite Voltacell. Changing cells means new tooling.'});
E(dg+1.5,'budget.requested',{actor:'mo',target:'pack',data:{nocam:true}});
E(dg+4.2,'agent.escalated',{actor:'rue',target:'director',summary:'Rue and Mo disagree. Rue escalated to the Director.'});
const mc=dg+4.8;
E(mc,'meeting.called',{actor:'director',target:'meeting',data:{id:'m-supplier',kind:'decision',title:'Cell supply decision',attendees:['director','rue','mo','wren'],agenda:['Voltacell slip: 6 to 11 weeks','Options and costs','Impact on Proto 3']},summary:'Director called a decision meeting and invited you'});
let mArr=mc;[['director',0],['rue',1],['mo',2],['wren',3]].forEach(([id,s])=>{mArr=Math.max(mArr,go(mc+.2,id,'meeting',{loc:{seat:s,of:4}}));});
E(mArr+.1,'meeting.started',{target:'meeting',data:{id:'m-supplier'},summary:'Decision meeting started in the Meeting Hall'});
E(mArr+.3,'agent.handoff',{actor:'director',target:'pip',item:'card'});
// pip is at desk with pricing; a second courier path: Director hands invite to Pip only if back. Use Wren's seat; Pip runs from desk? Pip is at Your Desk already -> invite raised directly by Director via Pip already there.
const inv=mArr+.4;
E(inv,'alert.raised',{actor:'director',target:'meeting',severity:'needs',data:{id:'a-supplier',kind:'invite',decision:'supplier',meeting:'m-supplier',needBy:inv+10,default:'move',defaultBy:'Director',timer:45,anchor:'meeting',
 card:{title:'Voltacell cells slipped from 6 to 11 weeks. Proto 3 is at risk.',why:'Proto 3 builds in week 22 and the cells now land in week 25. Rue and Mo disagree on the fix.',
  options:[{id:'expedite',label:'Expedite Voltacell at a premium',detail:'€18,400 premium. Cells in 7 weeks. Keeps the date, uses 9% of the contingency.',irreversible:true,approve:{button:'Approve and pay €18,400',what:['Tilo sends a signed expedite order to Voltacell','€18,400 is charged to the K1 contingency budget','Voltacell commits to week 21 delivery']}},
   {id:'switch',label:'Switch to the Kelvra alternate cell',detail:'Same price. Passed Sample Lab tests in week 14. Needs one retest.',suggested:true,reason:'Keeps the Proto 3 date with no premium, and the cell is already validated'},
   {id:'move',label:'Move the Proto 3 date',detail:'Proto 3 moves 5 weeks and launch moves 3. No cost.'}]}},summary:'Meeting invite: cell supply decision. Join, answer async, or delegate.'});
const sNeed=inv+10,pNeed=sNeed+13;
EV.forEach(e=>{if(e.data&&e.data.id==='a-pricing'){e.data.needBy=pNeed;}});
E(inv+1,'meeting.decision',{target:'meeting',data:{id:'m-supplier',by:'Director',nocam:true},summary:'Director laid out 3 options for you'});

/* ---------- branch: supplier ---------- */
const B0=sNeed+.4;
const endPosts=()=>{};
branch({supplier:'expedite'},()=>{
 E(B0,'meeting.decision',{target:'meeting',data:{id:'m-supplier',by:'You',why:'Protect the Proto 3 date'},summary:'Decided: expedite Voltacell at a €18,400 premium'});
 E(B0+.6,'meeting.ended',{target:'meeting',data:{id:'m-supplier'}});
 E(B0+.7,'memory.saved',{actor:'director',target:'meeting',item:'decision',summary:'Decision card filed to the Memory Vault'});
 let m1=go(B0+.8,'mo','treasury');E(m1+.1,'budget.requested',{actor:'mo',target:'treasury',data:{amount:18400},summary:'Mo took the €18,400 expedite to the Treasury'});E(m1+1.4,'budget.granted',{actor:'mo',target:'treasury',summary:'Treasury released €18,400 from contingency (you approved)',credits:4});
 E(B0+2,'data.transfer',{target:'br-cells',data:{dir:'out',size:'cart'},summary:'Signed expedite order sent to Voltacell'});
 E(B0+5,'data.transfer',{target:'br-cells',data:{dir:'in',size:'truck',mb:3},summary:'Voltacell confirmed week 21 delivery'});
 E(B0+7.6,'app.refreshed',{target:'pwatch',data:{tag:'cells 7 wks',tagIcon:'check'},summary:'Parts Watch: cells back on time for Proto 3'});
 go(m1+2,'mo','pack',{loc:{dx:-34,face:'R'}});
 go(B0+.8,'rue','pack');go(B0+.9,'wren','bom');go(B0+1,'director','meeting',{loc:{slot:0}});
 work(B0+9,'rue','pack',6,'Rue is locking the pack design on Voltacell cells');
});
branch({supplier:'switch'},()=>{
 E(B0,'meeting.decision',{target:'meeting',data:{id:'m-supplier',by:'You',why:'Validated cell, no premium'},summary:'Decided: switch to the Kelvra alternate cell'});
 E(B0+.6,'meeting.ended',{target:'meeting',data:{id:'m-supplier'}});
 E(B0+.7,'memory.saved',{actor:'director',target:'meeting',item:'decision',summary:'Decision card filed to the Memory Vault'});
 E(B0+1,'building.planned',{target:'kelvrafab',summary:'Kelvra Cells island is now in the plan'});
 E(B0+1.4,'connection.requested',{actor:'lu',target:'br-kelvra',summary:'Lu requested the Kelvra API (covered by your decision)'});
 E(B0+2.2,'connection.established',{actor:'lu',target:'br-kelvra',summary:'Bridge to Kelvra Cells built'});
 let s1=go(B0+3.4,'sol','kelvrafab',{summary:'Sol is crossing to Kelvra to collect sample cells'});
 E(s1+.2,'agent.working',{actor:'sol',target:'kelvrafab',credits:3,summary:'Sol collected 12 Kelvra sample cells'});
 let s2=go(s1+1,'sol','pack',{item:'crate',hold:true,loc:{slot:1}});
 E(s2+.1,'artifact.reviewed',{actor:'rue',target:'pack',data:{result:'approved'},summary:'Rue retested the Kelvra cell: 1C discharge passes',credits:6});
 E(s2+.4,'app.refreshed',{target:'pwatch',data:{tag:'Kelvra · 6 wks',tagIcon:'check'},summary:'Parts Watch now tracks Kelvra cells: 6 weeks, on time'});
 E(s2+.5,'data.transfer',{target:'br-kelvra',data:{dir:'in',size:'truck',mb:3},summary:'Synced Kelvra catalogue'});
 go(s2+.8,'sol','pack',{loc:{slot:1}});
 go(B0+.8,'rue','pack');go(B0+.9,'wren','bom');go(B0+1,'director','meeting',{loc:{slot:0}});
 let m1=go(B0+.8,'mo','pack',{loc:{dx:-34,face:'R'}});E(m1+.4,'agent.working',{actor:'mo',target:'pack',summary:'Mo is re-quoting tooling for the Kelvra cell holder',credits:4,data:{tag:undefined}});
});
branch({supplier:'move'},()=>{
 E(B0,'meeting.decision',{target:'meeting',data:{id:'m-supplier',by:'You',why:'No cost, launch slips 3 weeks'},summary:'Decided: move Proto 3 by 5 weeks'});
 E(B0+.6,'meeting.ended',{target:'meeting',data:{id:'m-supplier'}});
 E(B0+.7,'memory.saved',{actor:'director',target:'meeting',item:'decision',summary:'Decision card filed to the Memory Vault'});
 E(B0+1.2,'alert.raised',{actor:'director',target:'meeting',severity:'nudge',data:{id:'a-move',kind:'nudge'},summary:'Plan updated: Proto 3 moves to week 27; launch moves 3 weeks.'});
 go(B0+.8,'rue','pack');go(B0+.9,'wren','bom');go(B0+1,'director','meeting',{loc:{slot:0}});go(B0+.8,'mo','pack',{loc:{dx:-34,face:'R'}});
 E(B0+4,'agent.idle',{actor:'dex',summary:'Dex is idle until the new build date'});
 E(B0+4.4,'app.refreshed',{target:'pwatch',data:{tag:'on new date',tagIcon:'check'},summary:'Parts Watch re-baselined to the week 27 build'});
});
/* ---------- pricing branch (needBy pNeed) ---------- */
go(pNeed+.3,'pip','connector',{loc:{slot:1},mode:'run'});
branch({pricing:'grant'},()=>{
 E(pNeed+.2,'connection.consented',{actor:'you',target:'br-pricing',summary:'You allowed read-only access to Supplier pricing'});
 E(pNeed+.5,'connection.established',{actor:'lu',target:'br-pricing',data:{unlock:true},summary:'Cloud lifted: Supplier pricing is visible. Footpath and browser kiosk built.'});
 E(pNeed+2.4,'data.transfer',{target:'br-pricing',data:{dir:'in',size:'cart',mb:1},summary:'Read 412 negotiated prices'});
 let l1=go(pNeed+1,'lu','pricebook',{summary:'Lu is crossing to the Price Book'});E(l1+.2,'agent.working',{actor:'lu',target:'pricebook',credits:4,summary:'Lu is reading negotiated prices'});
 E(l1+2.6,'app.refreshed',{target:'pwatch',data:{tag:'+ prices',tagIcon:'coin'},summary:'Parts Watch now shows negotiated prices'});go(l1+3,'lu','connector');
});
branch({pricing:'decline'},()=>{
 E(pNeed+.4,'agent.recovered',{actor:'lu',target:'connector',summary:'Pricing stays private. Lu is routing around it with list prices from public catalogues.'});
 E(pNeed+2.6,'app.refreshed',{target:'pwatch',data:{tag:'list prices',tagIcon:'coin'},summary:'Parts Watch uses list prices (marked as estimates)'});
});
/* ---------- L4 · Validation ---------- */
const v0=pNeed+1;
[['gus',{role:'builder',rank:'lead',name:'Gus',title:'Prototype Lead',tools:['Garage'],scope:[],budget:50},'garage',{}],['tia',{role:'tester',rank:'lead',name:'Tia',title:'Validation Lead',tools:['Test Track','Drop Tower'],scope:[],budget:50},'testtrack',{}],['sam',{role:'tester',name:'Sam',title:'Safety Tester',tools:['Thermal Chamber'],scope:[],budget:30},'thermal',{}]].forEach(([id,m,post,loc],i)=>{const t=sNeed-16+i*.6;spawn(t,id,m,i%4);ARR[id]=go(t+.4,id,post,{build:true});});
let fp=go(v0,'fenn','garage',{item:'parcel',hold:true,follow:true,loc:{slot:1},summary:'Fenn is riding the lift to Validation with the Proto 3 build pack'});
E(fp+.1,'agent.handoff',{actor:'fenn',target:'gus',item:'parcel',summary:'Fenn handed the Proto 3 build pack to Gus'});
work(fp+.6,'gus','garage',8,'Gus is building Proto 3',{tag:'proto 3 of 5',tagIcon:'make'});
work(ARR.tia+.2,'tia','testtrack',4,'Tia is preparing the Test Track');work(ARR.sam+.2,'sam','thermal',4,'Sam is running thermal soak at 45 °C');
build(fp+.8,'drop','Built the Drop Tower');
let tr=go(fp+4,'gus','testtrack',{item:'parcel',hold:true,loc:{slot:1},summary:'Gus rolled Proto 3 onto the Test Track'});
E(tr+.1,'agent.handoff',{actor:'gus',target:'tia',item:'parcel'});
work(tr+.4,'tia','testtrack',8,'Test Track: braking, range and hill-start runs');
E(tr+4,'artifact.reviewed',{actor:'tia',target:'testtrack',data:{result:'approved',minutes:30},summary:'Test Track signed off Proto 3: braking, 41 km range and hill starts pass'});
go(tr+4.3,'gus','garage');go(fp+1,'fenn','frame');
['frame','susp','ctrl','fw','motor'].forEach((id,i)=>E(tr+4.6+i*.15,'building.archived',{target:id,data:{nocam:true}}));
/* ---------- L5 reached ---------- */
spawn(tr-12,'hal',{role:'builder',rank:'lead',name:'Hal',title:'Plant Lead',tools:['Line planner'],scope:['ERP'],budget:60},1);
let ha=go(tr-11.6,'hal','line',{build:true});
work(ha+1.6,'hal','line',6,'Hal is planning the line build-out',{tag:'line build-out',tagIcon:'cog'});
const end=Math.max(tr+5.4,ha+2.4);
E(end,'alert.raised',{actor:'director',target:'line',severity:'nudge',data:{id:'a-end',kind:'nudge'},summary:'The run reached Manufacturing. Every decision is in the Story.',credits:2});

EV.sort((x,y)=>x.ts-y.ts);
// scale credits so the total by the supplier decision is 214, and saved stays 96
const pre=EV.filter(e=>e.ts<=sNeed&&e.credits).reduce((s,e)=>s+e.credits,0);const f=214/pre;
EV.forEach(e=>{if(e.credits)e.credits=Math.max(1,Math.round(e.credits*(e.ts<=sNeed?f:f)));});
// minutes: scale to 190 at end
const mn=EV.reduce((s,e)=>s+((e.data&&e.data.minutes)||0),0);EV.forEach(e=>{if(e.data&&e.data.minutes)e.data.minutes=Math.round(e.data.minutes*190/mn);});
return{layout,events:{world:'k1',version:1,events:EV},info:{end,sNeed,pNeed,mNeed,shNeed,n:EV.length}};
}
if(typeof module!=='undefined')module.exports=K1;else window.K1=K1;

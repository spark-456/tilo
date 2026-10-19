(function(){
/* Tilo app: shared data model + render kit. Pages read window.TiloApp.data; art comes from TiloApp.kit(h). */
const gbp=v=>'£'+(v<100&&v%1?v.toFixed(2):Math.round(v).toLocaleString('en-GB'));
const LEVELS=['Off','Read','Draft','Act'];
const D={gbp,LEVELS};

D.user={first:'Alex',name:'Alex Morgan',initials:'AM',email:'alex@northwind.co',title:'Operations lead',org:'Northwind Ops',plan:'Team',tz:'Europe/London (GMT+1)',lang:'English (UK)',hours:'08:30 – 17:30, Monday to Friday'};
D.today={long:'Thursday 24 September',short:'Thu 24 Sep',time:'09:12'};

D.decisions=[
 {k:'depot',world:'k1',title:'Laptop Depot · budget sign-off',body:'6 test laptops for firmware, £3,420. Above the £2,500 district limit.',yes:'Approve £3,420',icon:'coin',done:'Approved · just now'},
 {k:'mail',world:'k1',title:'Mail Room gate · supplier brief',body:'Brief ready for 3 battery suppliers outside the company. Nothing sent yet.',yes:'Send brief',icon:'mail',done:'Sent to 3 suppliers · just now'}
];
D.needsLeft=dec=>D.decisions.filter(d=>!(dec&&dec[d.k])).length;

D.plans=dec=>{dec=dec||{};return{
 k1:{districts:[
  {id:'hall',name:'Town Hall',hall:true,icon:'hall',buildings:[{id:'townhall',kit:'townhall',state:'active'},{id:'treasury',kit:'treasury'},{id:'watch',kit:'watchtower',state:'active'}]},
  {id:'fw',name:'Firmware',icon:'laptop',buildings:[{id:'office',kit:'workshop',state:'active'},{id:'depot',gen:{name:'Laptop Depot',fp:[2,1],i:'laptop'},state:dec.depot?'active':'needs'}]},
  {id:'research',name:'Research',icon:'search',buildings:[{id:'browser',kit:'browser',state:'active'},{id:'lib',kit:'library',state:'complete'}]},
  {id:'mail',name:'Suppliers',icon:'mail',buildings:[{id:'mailroom',gen:{name:'Mail Room',fp:[2,1],i:'mail'},state:dec.mail?'active':'needs'},{id:'yard',kit:'testyard',state:'active'}]},
  {id:'delivery',name:'Launch',icon:'parcel',buildings:[{id:'pack',gen:{name:'Launch Kit',fp:[1,1],i:'doc'},state:'planned'},{id:'dock',kit:'dock',state:'planned'}]}
 ],gates:[{before:'mailroom',state:dec.mail?'open':'waiting'}],
 agents:[{rank:'director',at:'townhall'},{role:'tester',at:'watch',expr:'focused'},{role:'builder',rank:'lead',at:'office',expr:'focused'},{role:'builder',at:'depot',expr:dec.depot?'focused':'needs',ring:!dec.depot},{role:'browser',rank:'lead',at:'browser',expr:'focused'},{role:'research',at:'lib',expr:'delighted'},{role:'delivery',rank:'lead',at:'mailroom',expr:dec.mail?'walking':'needs'}]},
 hires:{districts:[
  {id:'hall',name:'Town Hall',hall:true,icon:'hall',buildings:[{id:'townhall',kit:'townhall',state:'active'},{id:'clock',kit:'clock',state:'active'}]},
  {id:'accounts',name:'Accounts',icon:'laptop',buildings:[{id:'office',gen:{name:'Account Setup',fp:[2,1],i:'person'},state:'active'},{id:'laptops',gen:{name:'Laptops',fp:[1,1],i:'laptop'},state:'complete'}]},
  {id:'people',name:'HR',icon:'doc',buildings:[{id:'browser',kit:'browser',state:'active'},{id:'records',gen:{name:'HR Records',fp:[1,1],i:'doc'},state:'complete'}]},
  {id:'learning',name:'Training',icon:'cap',buildings:[{id:'training',gen:{name:'Training Hall',fp:[2,2],i:'cap'},state:'construction'}]}
 ],agents:[{rank:'director',at:'townhall'},{role:'connector',rank:'lead',at:'office',expr:'focused'},{role:'browser',at:'browser',expr:'focused'},{role:'research',at:'records',expr:'delighted'},{role:'builder',at:'training',expr:'focused'}]},
 audit:{districts:[
  {id:'hall',name:'Town Hall',hall:true,icon:'hall',buildings:[{id:'townhall',kit:'townhall',state:'complete'},{id:'treasury',kit:'treasury',state:'complete'}]},
  {id:'accounts',name:'Evidence',icon:'doc',buildings:[{id:'vault',kit:'vault',state:'complete'},{id:'lib',kit:'library',state:'complete'}]},
  {id:'delivery',name:'Sign-off',icon:'parcel',buildings:[{id:'dock',kit:'dock',state:'complete'}]}
 ],agents:[{rank:'director',at:'townhall',expr:'delighted'},{role:'finance',at:'vault',expr:'delighted'},{role:'research',at:'lib',expr:'sleepy'}]},
 fresh:{districts:[
  {id:'hall',name:'Town Hall',hall:true,icon:'hall',buildings:[{id:'townhall',kit:'townhall',state:'construction'}]},
  {id:'research',name:'Research',icon:'search',buildings:[{id:'lib',kit:'library',state:'planned'}]}
 ],agents:[{rank:'director',at:'townhall',expr:'focused'}]}
};};

D.worlds=(dec,added)=>{
 dec=dec||{};const n=D.needsLeft(dec);
 const k1Act=[
  {t:'11:52',role:'builder',who:'Builder',text:'Paused Laptop Depot. £3,420 is above the £2,500 district limit.',kind:'needs'},
  {t:'11:40',role:'delivery',who:'Courier lead',text:'Drafted a brief for 3 battery suppliers. Waiting at the Mail Room gate.',kind:'needs'},
  {t:'11:18',role:'research',who:'Researcher',text:'Finished the battery cell comparison from 14 sources.',kind:'done'},
  {t:'10:05',role:'tester',who:'Tester',text:'Firmware 0.4.2 passed 31 of 32 checks. One retry queued.',kind:'info'},
  {t:'09:30',rank:'director',who:'Director',text:'Opened Level 3: prototypes and suppliers.',kind:'info'}];
 if(dec.mail)k1Act.unshift({t:'Just now',you:true,who:'You',text:'Sent the supplier brief to 3 battery suppliers.',kind:'done'});
 if(dec.depot)k1Act.unshift({t:'Just now',you:true,who:'You',text:'Approved £3,420 for Laptop Depot.',kind:'done'});
 const list=[
  {id:'k1',name:'K1 electric scooter',short:'K1 electric scooter',tier:'City',tool:'Workspace',st:n?'needs':'running',meta:'Concept to launch · Level 3 of 6',agents:38,prog:46,spend:'£1,386',of:'of £4,000',spendV:1386,budget:4000,nextL:'Launch',nextV:'14 Nov',owner:'Alex Morgan',started:'2 Sep',plan:'k1',
   districts:[
    {name:'Town Hall',icon:'hall',done:3,total:3,agents:4,st:'running',note:'Director and tester on watch'},
    {name:'Firmware',icon:'laptop',done:dec.depot?2:1,total:2,agents:12,st:dec.depot?'running':'needs',note:dec.depot?'Laptop Depot is building':'Laptop Depot waiting on budget'},
    {name:'Research',icon:'search',done:2,total:2,agents:9,st:'finished',note:'Cell comparison finished'},
    {name:'Suppliers',icon:'mail',done:dec.mail?2:1,total:2,agents:8,st:dec.mail?'running':'needs',note:dec.mail?'Brief out with 3 suppliers':'Mail Room gate waiting'},
    {name:'Launch',icon:'parcel',done:0,total:2,agents:5,st:'scheduled',note:'Opens at Level 5'}],
   activity:k1Act},
  {id:'hires',name:'Onboard 12 new hires',short:'Onboard 12 new hires',tier:'City',tool:'Workspace',st:'running',meta:'Accounts, HR and training',agents:14,prog:58,spend:'£228',of:'of £600',spendV:228,budget:600,nextL:'Due',nextV:'Fri 2 Oct',owner:'Alex Morgan',started:'14 Sep',plan:'hires',
   districts:[
    {name:'Town Hall',icon:'hall',done:2,total:2,agents:2,st:'running',note:'Tracking 12 starters'},
    {name:'Accounts',icon:'laptop',done:2,total:2,agents:5,st:'finished',note:'12 of 12 accounts ready'},
    {name:'HR',icon:'doc',done:1,total:2,agents:4,st:'running',note:'Contracts 9 of 12 signed'},
    {name:'Training',icon:'cap',done:0,total:1,agents:3,st:'running',note:'Course plan being built'}],
   activity:[
    {t:'10:44',role:'connector',who:'Connector lead',text:'Created Slack and email accounts for the last 3 starters.',kind:'done'},
    {t:'09:58',role:'browser',who:'Browser',text:'Sent contract reminders to 3 starters.',kind:'info'},
    {t:'Yesterday',role:'research',who:'Researcher',text:'Filed 12 HR records.',kind:'done'}]},
  {id:'audit',name:'Q3 audit prep',short:'Q3 audit prep',tier:'City',tool:'Workspace',st:'finished',meta:'Evidence pack signed off',agents:22,prog:100,spend:'£2,140',of:'of £2,500',spendV:2140,budget:2500,nextL:'Finished',nextV:'12 Sep',owner:'Priya Shah',started:'18 Aug',plan:'audit',
   districts:[
    {name:'Town Hall',icon:'hall',done:2,total:2,agents:3,st:'finished',note:'Closed 12 Sep'},
    {name:'Evidence',icon:'doc',done:2,total:2,agents:14,st:'finished',note:'412 documents filed'},
    {name:'Sign-off',icon:'parcel',done:1,total:1,agents:5,st:'finished',note:'Signed by Priya'}],
   activity:[{t:'12 Sep',rank:'director',who:'Director',text:'Handed the evidence pack to the auditors.',kind:'done'}]},
  {id:'northline',name:'Supplier onboarding · Northline',short:'Northline onboarding',tier:'Town',tool:'Workspace',st:'running',meta:'Contracts and portal access',agents:7,prog:72,spend:'£342',of:'of £500',spendV:342,budget:500,nextL:'Due',nextV:'Wed 30 Sep',owner:'Jin Park',started:'16 Sep',row:[['connector','active','mail'],['dock','active','delivery']],skill:'brief',
   runs:[{when:'Today 08:10',what:'Portal access requested',ok:true,cost:'£1.20'},{when:'Tue 22 Sep',what:'Contract sent for signature',ok:true,cost:'£0.80'},{when:'Mon 21 Sep',what:'Supplier details checked',ok:true,cost:'£2.10'}]},
  {id:'invoice',name:'Weekly invoice match',short:'Invoice match',tier:'Town',tool:'Routine',st:'scheduled',meta:'Last run 142 matched, 3 flagged',agents:5,spend:'£0.60',of:'per run',spendV:.6,nextL:'Next run',nextV:'Mon 09:00',owner:'Priya Shah',started:'June',row:[['clock','idle','hall'],['vault','idle','analysis']],skill:'invoice',
   runs:[{when:'Mon 21 Sep 09:00',what:'142 matched · 3 flagged',ok:false,cost:'£0.60'},{when:'Mon 14 Sep 09:00',what:'131 matched · 0 flagged',ok:true,cost:'£0.58'},{when:'Mon 7 Sep 09:00',what:'127 matched · 1 flagged',ok:true,cost:'£0.55'}]},
  {id:'inbox',name:'Daily inbox triage',short:'Inbox triage',tier:'Town',tool:'Routine',st:'scheduled',meta:'Sorts, drafts, flags urgent',agents:4,spend:'£0.30',of:'per run',spendV:.3,nextL:'Next run',nextV:'Tomorrow 07:30',owner:'Alex Morgan',started:'May',row:[[{fp:[2,1],fl:1,roof:'flat',fa:'windows',i:'mail'},'idle','mail'],['desk','idle','mail']],skill:'triage',
   runs:[{when:'Today 07:30',what:'48 sorted · 6 drafts · 1 urgent',ok:true,cost:'£0.30'},{when:'Wed 07:30',what:'52 sorted · 4 drafts',ok:true,cost:'£0.31'},{when:'Tue 07:30',what:'61 sorted · 9 drafts',ok:true,cost:'£0.34'}]},
  {id:'pricing',name:'Pricing check before leadership',short:'Pricing check',tier:'Town',tool:'Routine',st:'scheduled',meta:'14 competitor sites',agents:6,spend:'£3.10',of:'per run',spendV:3.1,nextL:'Next run',nextV:'Thu 08:30',owner:'Tom Reyes',started:'July',row:[['watchtower','idle','research'],['library','idle','research']],skill:'price',
   runs:[{when:'Today 08:30',what:'14 sites · 2 price drops',ok:true,cost:'£3.10'},{when:'Thu 17 Sep 08:30',what:'14 sites · no change',ok:true,cost:'£2.90'}]},
  {id:'calls',name:'Summarise yesterday’s calls',short:'Call summary',tier:'Village',tool:'Quick task',st:'running',agents:1,prog:80,spend:'£0.40',spendV:.4,nextL:'Ends',nextV:'in 3 min',when:'About 3 min left',single:['desk','active','research'],owner:'Alex Morgan',started:'09:04',out:'Summary of 7 calls, with actions per owner'},
  {id:'venues',name:'Offsite venue options',short:'Venue options',tier:'Village',tool:'Quick task',st:'running',agents:2,prog:62,spend:'£0.90',spendV:.9,nextL:'Ends',nextV:'in 6 min',when:'5 of 8 venues checked',single:['browser','active','research'],owner:'Alex Morgan',started:'09:01',out:'Shortlist of 3 venues for 20 people, under £4k'},
  {id:'comp',name:'Competitor pricing',short:'Competitor pricing',tier:'Village',tool:'Quick task',st:'finished',agents:1,prog:100,spend:'£0.70',spendV:.7,nextL:'Ready',nextV:'11:18',when:'Report · today 11:18',single:['library','complete','research'],owner:'Tom Reyes',started:'10:52',out:'Report: 2 rivals cut prices by 6–8% this week'},
  {id:'reply',name:'Reply to Northline',short:'Northline reply',tier:'Village',tool:'Quick task',st:'finished',agents:1,prog:100,spend:'£0.20',spendV:.2,nextL:'Ready',nextV:'09:40',when:'Draft · today 09:40',single:['meeting','complete','delivery'],owner:'Jin Park',started:'09:31',out:'Draft reply confirming NDA wording, ready to send'}
 ];
 return (added||[]).concat(list);
};
D.TIERS={quick:{tier:'Village',tool:'Quick task',word:'village',agents:2,cost:'about £0.60',eta:'about 6 min',ph:'Summarise this week’s customer feedback',start:'Start task',hint:'You see the plan and the cost before any agent starts.',chips:['Compare three suppliers','Draft a reply to Northline','Summarise yesterday’s calls']},
 routine:{tier:'Town',tool:'Routine',word:'town',agents:4,cost:'about £0.40 a run',eta:'first run tomorrow 08:00',ph:'Every Monday, match invoices to purchase orders',start:'Set up routine',hint:'You approve the first run. After that it runs on its own.',chips:['Weekly invoice match','Monday pricing check','Daily inbox triage']},
 workspace:{tier:'City',tool:'Workspace',word:'city',agents:18,cost:'£400 budget to start',eta:'plan in about 2 min',ph:'Onboard 12 new hires across email, HR and laptops',start:'Plan project',hint:'Tilo drafts districts, teams and gates for your sign-off.',chips:['Product launch','Supplier onboarding','Quarterly audit prep']}};
D.makeWorld=(mode,q,i)=>{const T=D.TIERS[mode],name=q||T.ph;return{id:'new'+i,name,short:name.length>26?name.slice(0,24)+'…':name,tier:T.tier,tool:T.tool,st:'running',isNew:true,meta:'Started just now',agents:T.agents,prog:4,spend:'£0.00',of:T.tier==='City'?'of £400':'',spendV:0,budget:T.tier==='City'?400:0,nextL:'Status',nextV:'Starting',when:'Starting now',owner:'Alex Morgan',started:'Just now',plan:T.tier==='City'?'fresh':null,single:T.tier==='Village'?['desk','active','research']:null,row:T.tier==='Town'?[['clock','active','hall'],['desk','idle','mail']]:null,
 districts:T.tier==='City'?[{name:'Town Hall',icon:'hall',done:0,total:1,agents:1,st:'running',note:'Director is drafting the plan'}]:null,
 runs:T.tier==='Town'?[]:null,out:T.tier==='Village'?'Working on it. You’ll get a notification when it’s ready.':null,
 activity:[{t:'Just now',rank:'director',who:'Director',text:'Read your brief and started planning.',kind:'info'}]};};

D.skills=[
 {id:'invoice',name:'Match invoices to purchase orders',team:'Finance',owner:'Priya Shah',role:'finance',runs:142,rate:98,last:'Mon 09:00',improved:'18 Sep',status:'live',tools:[['Gmail',1],['Xero',2],['Google Sheets',2]],used:['invoice'],
  steps:['Collect new invoices from the Accounts inbox','Find the matching purchase order in Xero','Check supplier, amount and line items','Mark matched invoices as ready to pay','Flag anything that doesn’t match for Priya'],
  ask:{q:'3 invoices had no PO number. What should agents do next time?',a:['Email the supplier for it','Flag them to Priya']}},
 {id:'triage',name:'Triage the Accounts inbox',team:'Operations',owner:'Alex Morgan',role:'connector',runs:212,rate:96,last:'Today 07:30',improved:'2 Sep',status:'live',tools:[['Gmail',3],['Slack',2]],used:['inbox'],
  steps:['Read new mail since the last run','Sort into Invoices, Suppliers, Customers and Other','Draft replies to routine questions','Post anything urgent to #ops']},
 {id:'brief',name:'Draft a supplier brief',team:'Supply chain',owner:'Jin Park',role:'delivery',runs:9,rate:100,last:'Today 11:40',improved:'14 Sep',status:'live',tools:[['Google Drive',1],['Gmail',2]],used:['k1','northline'],
  steps:['Read the spec and volumes from Drive','Pull past terms for this supplier','Write the brief in our template','Hold at the gate until someone approves sending'],
  ask:{q:'Should briefs include our target unit price?',a:['Yes, always','Only for repeat suppliers']}},
 {id:'price',name:'Scan competitor prices',team:'Sales',owner:'Tom Reyes',role:'browser',runs:38,rate:92,last:'Today 08:30',improved:'10 Sep',status:'live',tools:[['Web',1],['Google Sheets',2]],used:['pricing','comp'],
  steps:['Open the 14 competitor product pages','Read list price, discounts and stock','Compare with last week in the pricing sheet','Write a short summary of what changed'],
  ask:{q:'2 sites blocked the browser. Skip them or ask a person?',a:['Skip and note it','Ask Tom to check']}},
 {id:'starter',name:'Set up a new starter',team:'People',owner:'Alex Morgan',role:'connector',runs:12,rate:100,last:'Yesterday',improved:'21 Sep',status:'live',tools:[['Google Workspace',3],['BambooHR',1],['Slack',3]],used:['hires'],
  steps:['Read the starter’s record in BambooHR','Create their email and calendar','Add them to the right Slack channels','Send a welcome note with day-one details']},
 {id:'log',name:'Log new supplier invoices',team:'Finance',owner:'Alex Morgan',role:'builder',runs:0,rate:null,last:'Not run yet',improved:'Draft',status:'draft',tools:[['Gmail',2],['Google Sheets',2]],used:[],
  steps:['Watch the Accounts inbox for invoice emails','Open the PDF and read supplier, amount and due date','Add a row to the “Invoices 2026” sheet','Label the email “Logged”']}
];

D.ledger={budget:8000,spent:2412,forecast:6300,
 daily:[38,52,61,44,22,18,71,66,58,49,74,140,20,16,63,57,48,69,72,28,1216,64,35,31],
 by:{world:{head:'K1 electric scooter is 57% of this month',rows:[['K1 electric scooter',1386],['Northline onboarding',342],['Quick tasks (11)',312],['Onboard 12 new hires',228],['Routines (3)',144]]},
  tool:{head:'Workspaces carry most of the spend',rows:[['Workspaces',1956],['Quick tasks',312],['Routines',144]]},
  role:{head:'Builders spend most, mainly on parts',rows:[['Builders',1580],['Researchers',290],['Couriers',176],['Connectors',148],['Testers',122],['Browsers',96]]}},
 tx:[
  {id:'t1',d:'Today 11:52',world:'k1',wn:'K1 electric scooter',item:'6 test laptops · Laptop Depot',type:'Purchase',amt:3420,st:'waiting',dec:'depot'},
  {id:'t2',d:'Today 10:12',world:'k1',wn:'K1 electric scooter',item:'Battery cell samples ×4',type:'Purchase',amt:186,st:'paid'},
  {id:'t3',d:'Today 08:30',world:'pricing',wn:'Pricing check',item:'Routine run · 14 sites',type:'Compute',amt:3.1,st:'paid'},
  {id:'t4',d:'Wed 23 Sep',world:'hires',wn:'Onboard 12 new hires',item:'Training platform · 12 seats',type:'Subscription',amt:96,st:'paid'},
  {id:'t5',d:'Tue 22 Sep',world:'northline',wn:'Northline onboarding',item:'Supplier portal licence',type:'Subscription',amt:120,st:'paid'},
  {id:'t6',d:'Mon 21 Sep',world:'k1',wn:'K1 electric scooter',item:'Motor controller dev kit',type:'Purchase',amt:1140,st:'paid'},
  {id:'t7',d:'Mon 21 Sep',world:'invoice',wn:'Weekly invoice match',item:'Routine run · 145 invoices',type:'Compute',amt:.6,st:'paid'},
  {id:'t8',d:'Fri 18 Sep',world:'k1',wn:'K1 electric scooter',item:'Agent time · Research district',type:'Compute',amt:64,st:'paid'}
 ]};

D.agenda={days:['Mon 21','Tue 22','Wed 23','Thu 24','Fri 25'],wkend:['Sat 26','Sun 27'],today:3,start:8,end:18,now:9.2,
 events:[
  {id:'su1',d:0,s:9,e:9.5,t:'Team stand-up',cal:'work',joins:true,past:true},{id:'dr',d:0,s:10,e:11,t:'K1 design review',cal:'work',joins:true,past:true},{id:'lunch',d:0,s:13,e:13.75,t:'Lunch with Sam',cal:'personal',past:true},
  {id:'su2',d:1,s:9,e:9.5,t:'Team stand-up',cal:'work',joins:true,past:true},{id:'nl',d:1,s:11,e:12,t:'Northline call',cal:'work',joins:true,past:true},{id:'cc',d:1,s:15,e:15.5,t:'Priya · cost centres',cal:'work',past:true},
  {id:'su3',d:2,s:9,e:9.5,t:'Team stand-up',cal:'work',joins:true,past:true},{id:'gym',d:2,s:12.5,e:13.5,t:'Gym',cal:'personal',past:true},{id:'dent',d:2,s:16,e:17,t:'Dentist',cal:'personal',past:true},
  {id:'price',d:3,s:8.5,e:8.75,t:'Pricing check runs',cal:'tilo',tiloOnly:true,past:true},{id:'su4',d:3,s:9,e:9.5,t:'Team stand-up',cal:'work',joins:true},{id:'q4',d:3,s:10.5,e:12,t:'Focus · Q4 plan',cal:'work'},{id:'sync',d:3,s:14,e:14.75,t:'Supplier sync · Northline',cal:'work',brief:true,joins:true},{id:'read',d:3,s:13.5,e:13.75,t:'Read Tilo’s brief',cal:'tilo'},
  {id:'su5',d:4,s:9,e:9.5,t:'Team stand-up',cal:'work',joins:true},{id:'jin',d:4,s:11,e:11.5,t:'1:1 with Jin',cal:'work'},{id:'lap',d:4,s:12,e:12.5,t:'Laptops arrive · desk 3',cal:'tilo',tiloOnly:true},{id:'lead',d:4,s:15.5,e:16.5,t:'Leadership pricing review',cal:'work',joins:true},
  {id:'run',d:5,s:9,e:11,t:'Parkrun and brunch',cal:'personal'}],
 slots:[{d:3,s:16,e:16.5,l:'Thu 16:00'},{d:4,s:9.5,e:10,l:'Fri 09:30'},{d:4,s:14,e:14.5,l:'Fri 14:00'}],
 details:{
  sync:{people:['AM','JP','PS','NL'],brief:['Northline wants 60-day payment terms. Your policy is 30.','Portal access for their 3 staff is ready to send.','Still open: delivery dates for the Q4 battery batch.'],briefMeta:'From 14 emails · 08:10'},
  lead:{people:['AM','PS','TR','SO'],brief:['Competitor report attached from this morning’s quick task.','2 rivals cut prices 6–8% this week.','Decision needed: hold or match on K1 accessories.'],briefMeta:'Report attached · 11:18'},
  nl:{people:['AM','JP','NL'],notes:['Agreed the NDA wording, pending Jin’s final read.','Portal access approved for 3 Northline staff.','Payment terms still open. Revisit Thursday.'],actions:[['Jin confirms NDA wording','JP','Pinned to Team board · due Fri'],['Draft portal invite emails','tilo','Done by Tilo · Tue 14:20']]},
  dr:{people:['AM','JP','SO'],notes:['Level 2 passed with 12 of 12 checks.','Battery housing needs a second supplier quote.'],actions:[['Get a second housing quote','tilo','Running in K1 · Research'],['Book Level 3 gate review','tilo','Suggested on Team board']]},
  gate:{people:['AM','JP','PS','TR'],brief:['Level 3 covers prototype test results and parts spend.','Laptop Depot budget is still waiting for sign-off.','Tilo will bring the firmware test summary.'],briefMeta:'Drafting now'},
  su:{people:['AM','PS','JP','TR','SO'],notes:['Everyone on track. Laptops arrive Friday.','Priya flagged the Depot budget for Alex.'],actions:[['Approve Laptop Depot budget','AM','Pinned to Team board']]}},
 pins:[
  {id:'t0',board:'team',title:'Book the K1 Level 3 gate review',note:'Alex, Jin, Priya and Tom all need to be there. Tilo can find 30 minutes this week.',by:'tilo',role:'research',suggested:true,kind:'find',color:'white'},
  {id:'t1',board:'team',title:'Approve Laptop Depot budget',note:'£3,420 for 6 test laptops · K1 electric scooter',by:'tilo',role:'builder',due:'Tilo · today',group:'waiting',dec:'depot',color:'amber'},
  {id:'t2',board:'team',title:'Supplier sync with Northline',note:'14:00 today. Tilo wrote a brief and will take notes.',by:'tilo',role:'director',due:'Tilo · 14:00',group:'week',color:'blue'},
  {id:'t3',board:'team',title:'Q4 supplier review deck',note:'First draft for leadership. Include the Northline terms.',by:'PS',due:'Priya · Thu 1 Oct',group:'week',color:'pink'},
  {id:'t4',board:'team',title:'Laptops for new hires arrive',note:'12 units to desk 3. Accounts are ready.',by:'tilo',role:'connector',due:'Tilo · Fri 25 Sep',group:'week',color:'green'},
  {id:'t7',board:'team',title:'Jin confirms NDA wording',note:'From Tuesday’s Northline call',by:'tilo',role:'delivery',due:'From meeting notes · Fri',group:'week',color:'yellow'},
  {id:'t5',board:'team',title:'Send new price list',note:'Hold until leadership decides on Friday.',by:'TR',due:'Tom · waiting on leadership',group:'waiting',color:'lilac'},
  {id:'t6',board:'team',title:'Design review sign-off',note:'K1 Level 2 passed, 12 of 12 checks',by:'AM',due:'Alex and Jin',group:'done',done:true,color:'green'},
  {id:'m0',board:'me',title:'Block 2 hours of focus time on Monday',note:'Your week has no gap longer than 45 minutes.',by:'tilo',role:'research',suggested:true,kind:'focus',color:'white'},
  {id:'m1',board:'me',title:'Read Tilo’s brief before the supplier sync',note:'2 minute read · 3 open questions',by:'tilo',role:'director',due:'Tilo · 13:45',group:'week',color:'yellow'},
  {id:'m2',board:'me',title:'Check 3 flagged invoices',note:'From Monday’s invoice match',by:'tilo',role:'builder',due:'Tilo · today',group:'waiting',go:'invoice',color:'amber'},
  {id:'m3',board:'me',title:'1:1 with Jin',note:'Career goals and the Q4 plan',by:'AM',due:'Fri 11:00',group:'week',color:'blue'},
  {id:'m4',board:'me',title:'Answer Priya on cost centres',note:'Sent Tuesday',by:'AM',due:'Done Tue',group:'done',done:true,color:'lilac'}
 ]};

D.team={people:[
  {id:'am',name:'Alex Morgan',email:'alex@northwind.co',dept:'Operations lead',role:'Owner',active:'Now',you:true,c:'#E6E1F8'},
  {id:'ps',name:'Priya Shah',email:'priya@northwind.co',dept:'Finance',role:'Approver',limit:'£2,500',active:'2h ago',c:'#D9F0EE'},
  {id:'jp',name:'Jin Park',email:'jin@northwind.co',dept:'Supply chain',role:'Approver',limit:'£1,000',active:'Yesterday',c:'#FBE4EE'},
  {id:'tr',name:'Tom Reyes',email:'tom@northwind.co',dept:'Sales',role:'Member',active:'Mon',c:'#FDEBDD'},
  {id:'so',name:'Sam Ode',email:'sam@northwind.co',dept:'Design',role:'Viewer',active:'Last week',c:'#E2ECFB'}],
 rules:[['spend','Spending over £250','An approver signs off, within their limit',true],['share','Sharing anything outside the company','The owner or an approver signs off',true],['undo','Actions that can’t be undone','Deleting, paying or mass emails need two people',true],['tools','Giving a skill more access to a tool','Only the owner can change tool access',true],['weekend','Routines that fall on a weekend','Hold until Monday morning',false]],
 matrix:[['Start quick tasks',7],['Build routines',7],['Open workspaces',3],['Approve spend up to their limit',3],['Approve sharing outside',3],['Change tool access',1],['Invite people',1],['See the ledger',15]],
 roles:['Owner','Approver','Member','Viewer']};

D.connectors=[
 {id:'gmail',name:'Gmail',cat:'Email',mono:'G',col:'#D2463A',st:'connected',acct:'alex@northwind.co',sync:'2 min ago',scopes:[['Read mail',1],['Write drafts',2],['Send and label',3]],level:3,used:['Triage the Accounts inbox','Draft a supplier brief','Match invoices to purchase orders']},
 {id:'gcal',name:'Google Calendar',cat:'Calendar',mono:'C',col:'#2F6FD8',st:'connected',acct:'alex@northwind.co',sync:'Live',scopes:[['See events',1],['Suggest times',2],['Book and move events',3]],level:3,used:['Agenda','Find a time']},
 {id:'gdrive',name:'Google Drive',cat:'Files',mono:'D',col:'#1C8F5E',st:'connected',acct:'Northwind shared drive',sync:'8 min ago',scopes:[['Read files',1],['Create files',2],['Share outside',3]],level:1,used:['Draft a supplier brief','Q3 audit prep']},
 {id:'slack',name:'Slack',cat:'Chat',mono:'S',col:'#6B3A86',st:'connected',acct:'northwind.slack.com',sync:'Live',scopes:[['Read channels',1],['Post as Tilo',2],['Invite people',3]],level:2,used:['Triage the Accounts inbox','Set up a new starter']},
 {id:'xero',name:'Xero',cat:'Accounting',mono:'X',col:'#0E85B0',st:'connected',acct:'Northwind Ltd',sync:'1h ago',scopes:[['Read bills and POs',1],['Draft bills',2],['Approve payments',3]],level:2,used:['Match invoices to purchase orders','Ledger export']},
 {id:'hubspot',name:'HubSpot',cat:'CRM',mono:'H',col:'#D9622B',st:'attention',acct:'Northwind sales',sync:'Sign-in expires in 3 days',scopes:[['Read contacts',1],['Update deals',2],['Email contacts',3]],level:1,used:['Scan competitor prices']},
 {id:'notion',name:'Notion',cat:'Docs',mono:'N',col:'#1F1D2B',st:'available',blurb:'Read and write team docs and wikis'},
 {id:'m365',name:'Microsoft 365',cat:'Email and files',mono:'M',col:'#C9472A',st:'available',blurb:'Outlook mail, calendar, OneDrive'},
 {id:'jira',name:'Jira',cat:'Projects',mono:'J',col:'#2659C9',st:'available',blurb:'Create and update issues'},
 {id:'github',name:'GitHub',cat:'Code',mono:'GH',col:'#2B2A33',st:'available',blurb:'Read repos, open issues and PRs'},
 {id:'stripe',name:'Stripe',cat:'Payments',mono:'S',col:'#5A4FD8',st:'available',blurb:'Read payments and refunds'},
 {id:'bamboo',name:'BambooHR',cat:'HR',mono:'B',col:'#5E9E2E',st:'available',blurb:'Read people records and time off'}
];

D.notifications=[
 {id:'n1',t:'11:52',title:'Laptop Depot needs budget sign-off',sub:'K1 electric scooter · £3,420',kind:'needs',go:['world','k1'],dec:'depot'},
 {id:'n2',t:'11:40',title:'Supplier brief is waiting at the gate',sub:'K1 electric scooter · 3 suppliers',kind:'needs',go:['world','k1'],dec:'mail'},
 {id:'n3',t:'11:18',title:'Competitor pricing is ready',sub:'Quick task · report',kind:'done',go:['world','comp']},
 {id:'n4',t:'09:40',title:'Draft reply to Northline is ready',sub:'Quick task · draft',kind:'done',go:['world','reply']},
 {id:'n5',t:'Yesterday',title:'HubSpot sign-in expires in 3 days',sub:'Connectors · reconnect to keep syncing',kind:'warn',go:['connectors']}
];

/* learning, ledger and team extras (merged from the v3 sheets) */
const SX={
 invoice:{first:2.8,now:.6,st:'trusted',from:'Weekly invoice match',ask:{q:'Voltcell lists shipping as a separate line. Should it count toward the PO total?',a:['Yes, include shipping','No, items only']}},
 triage:{first:.7,now:.3,st:'trusted',from:'Daily inbox triage'},
 brief:{first:1.4,now:.9,st:'learning',from:'Northline onboarding',ask:{q:'Northline asked for 60-day payment terms. Your past briefs said 30. Which should I use?',a:['Keep 30 days','Offer 45 days','Ask me each time']}},
 price:{first:6.1,now:3.1,st:'trusted',from:'Pricing check',ask:{q:'2 sites blocked the browser. Skip them or ask a person?',a:['Skip and note it','Ask Tom to check']}},
 starter:{first:4.2,now:2.6,st:'review',from:'Onboard 12 new hires',ask:{q:'BambooHR now needs a cost centre for each starter. Where should I find it?',a:['In the offer letter','Ask the hiring manager','Use OPS-01']}},
 log:{st:'draft',from:'Taught by you'}};
D.skills.forEach(s=>Object.assign(s,SX[s.id]||{}));
D.skills.splice(4,0,
 {id:'calls',name:'Summarise call notes',team:'Sales',owner:'Tom Reyes',role:'research',runs:61,rate:97,last:'Today 09:04',improved:'15 Sep',status:'live',st:'trusted',first:.9,now:.2,from:'Summarise yesterday’s calls',tools:[['Google Drive',1],['Slack',2]],used:['calls'],
  steps:['Pull yesterday’s call recordings','Pick out decisions and numbers','List follow-ups for each owner','Save the notes to the shared drive']},
 {id:'fw',name:'Check firmware test results',team:'Engineering',owner:'Jin Park',role:'tester',runs:6,rate:100,last:'Today 10:05',improved:'22 Sep',status:'live',st:'learning',first:3,now:2.4,from:'K1 electric scooter',tools:[['Google Drive',1],['Slack',2]],used:['k1'],
  steps:['Collect the overnight test logs','Compare with the last passing build','Retry any flaky check once','Post a pass or fail summary to #k1-firmware']});
D.learn={
 rates:[{id:'r1',name:'Triage the Accounts inbox',meta:'Today 07:30 · 48 sorted · 6 drafts',steps:['Sort mail','Draft replies','Flag urgent']},
  {id:'r2',name:'Scan competitor prices',meta:'Today 08:30 · 14 sites · 2 changes',steps:['Visit pages','Record prices','Compare','Summarise']},
  {id:'r3',name:'Summarise call notes',meta:'Today 09:04 · 7 calls · 12 follow-ups',steps:['Pull recordings','Pick out decisions','List follow-ups','Save notes']},
  {id:'r4',name:'Match invoices to purchase orders',meta:'Mon 09:00 · 142 matched · 3 flagged',steps:['Collect invoices','Match to PO','Flag differences','Mark ready to pay']}],
 reviews:[{id:'brief',meta:'12 runs · 11 good · last fix 8 runs ago',bars:[1,1,0,1,1,1,1,1,1,1,1,1]},{id:'fw',meta:'6 runs · all good · no fixes needed',bars:[1,1,1,1,1,1]}],
 helpers:[{id:'am',name:'Alex Morgan',you:true,init:'AM',c:'#E6E1F8',impact:'6 fixes · 22 ratings · invoice flags halved',n:28},{id:'ps',name:'Priya Shah',init:'PS',c:'#D9F0EE',impact:'14 answers · invoice matching right 99% of runs',n:17},{id:'jp',name:'Jin Park',init:'JP',c:'#FBE4EE',impact:'9 answers · supplier briefs need fewer edits',n:14},{id:'tr',name:'Tom Reyes',init:'TR',c:'#FDEBDD',impact:'4 ratings on price scans',n:4}],
 tools:[
  ['email','Email','mail','Gmail · used by 4 skills',3,['Can’t see your mail.','Reads mail. Never sends or deletes.','Writes drafts. You press send.','Sends within limits. Asks before emailing outside the company.']],
  ['calendar','Calendar','clock','Google Calendar · used by Agenda',3,['Can’t see your calendar.','Sees free and busy times and titles.','Proposes meetings for you to accept.','Books meetings. Asks before inviting outside guests.']],
  ['files','Files','doc','Google Drive · used by 4 skills',1,['Can’t open files.','Opens shared files. Never edits.','Creates new files. Never edits yours.','Edits and moves files. Asks before deleting.']],
  ['sheets','Spreadsheets','chart','Google Sheets · used by 3 skills',2,['Can’t open sheets.','Reads sheets it’s shared on.','Adds rows for you to check.','Adds and edits rows. Asks before deleting.']],
  ['accounts','Accounting','coin','Xero · used by 1 skill',2,['No access to the books.','Reads invoices, POs and ledgers.','Prepares entries for you to post.','Posts entries under £250. Asks above that.']],
  ['hr','HR system','person','BambooHR · used by 1 skill',1,['No access to people records.','Reads names, roles and start dates.','Prepares changes for HR to approve.','Updates records. Asks before pay or contract changes.']],
  ['web','Web browser','screen','Tilo browser · used by 2 skills',1,['Can’t browse.','Reads public pages only.','Fills in forms, stops before submit.','Browses and submits forms. Asks before paying.']],
  ['chat','Team chat','people','Slack · used by 3 skills',2,['Can’t see chat.','Reads channels it’s added to.','Drafts messages for you.','Posts in channels it’s added to.']]]};
Object.assign(D.ledger,{
 runs:[['Match invoices to POs',[2.8,2.1,1.6,1.3,1.05,.9,.8,.7,.65,.6],142,'invoice'],['Triage the inbox',[.7,.62,.55,.48,.44,.4,.36,.33,.31,.3],212,'triage'],['Competitor price scan',[6.1,5.4,4.9,4.3,3.9,3.6,3.4,3.25,3.15,3.1],38,'price'],['New starter setup',[4.2,3.9,3.5,3.2,2.95,2.8,2.7,2.6],12,'starter']],
 waits:{buckets:[['< 5 min',18],['5–15 min',11],['15–60 min',6],['1–4 hours',3],['> 4 hours',1]],types:[['Spend within limits','6 min','ok'],['Spend above limits','14 min',''],['Gate sign-offs','38 min',''],['Sharing outside the company','2 h 10 min','amber']]},
 memory:[120,150,170,200],
 hours:[['Finance',19,'#5A3FE0','Invoice matching and audit prep'],['Operations',14,'#0E7C79','Inbox triage and onboarding'],['Sales',9,'#F0A500','Call notes and price scans'],['Supply chain',4,'#D9588C','Supplier briefs and research']],
 activity:[
  {day:'Today · Thu 24 Sep',t:'11:52',k:'waiting',dec:'depot',world:'k1',what:'Laptop Depot asked for sign-off',sub:'K1 electric scooter · Builder agent',amt:'£3,420',detail:[['Why it asked','Above the £2,500 district limit'],['Can approve','Alex or Priya'],['Paused','1 building']]},
  {day:'Today · Thu 24 Sep',t:'11:40',k:'waitshare',dec:'mail',world:'k1',what:'Supplier brief waiting at the Mail Room gate',sub:'K1 electric scooter · Courier lead',amt:'—',detail:[['Recipients','3 battery suppliers'],['Files','Brief, spec sheet'],['Rule','Sharing outside needs sign-off']]},
  {day:'Today · Thu 24 Sep',t:'10:12',k:'spend',world:'k1',what:'Battery cell samples ×4',sub:'K1 electric scooter · Builder agent',amt:'£186',detail:[['Budget','Firmware district'],['Supplier','Voltcell'],['Receipt','Attached']]},
  {day:'Today · Thu 24 Sep',t:'08:30',k:'spend',world:'pricing',what:'Routine run · 14 competitor sites',sub:'Pricing check · Browser agent',amt:'£3.10',detail:[['Per run','£3.10, down from £6.10'],['Changes found','2 price drops'],['Next run','Thu 1 Oct 08:30']]},
  {day:'Wed 23 Sep',t:'16:02',k:'spend',world:'hires',what:'Training platform · 12 seats',sub:'Onboard 12 new hires · Builder agent',amt:'£96',detail:[['Approved by','Within Member limit'],['Billing','Monthly'],['Seats','12']]},
  {day:'Tue 22 Sep',t:'10:20',k:'spend',world:'northline',what:'Supplier portal licence',sub:'Northline onboarding · approved by Jin',amt:'£120',detail:[['Approved by','Jin Park'],['Waited','9 min'],['Renews','22 Oct']]},
  {day:'Mon 21 Sep',t:'16:31',k:'spend',world:'k1',what:'Motor controller dev kit',sub:'K1 electric scooter · Builder agent',amt:'£1,140',detail:[['Approved by','Priya Shah'],['Order','Dev kit ×2'],['Delivery','Fri 25 Sep']]},
  {day:'Mon 21 Sep',t:'16:30',k:'approval',world:'k1',what:'Approved the motor controller order',sub:'K1 electric scooter · Priya Shah',amt:'£1,140',detail:[['Her limit','£2,500'],['Asked by','Builder agent'],['Waited','14 min']]},
  {day:'Mon 21 Sep',t:'09:00',k:'saved',world:'invoice',what:'Reused invoice layouts from memory',sub:'Weekly invoice match · Memory Vault',amt:'+£2.20',detail:[['First run cost','£2.80'],['This run','£0.60'],['Runs so far','142']]},
  {day:'Sat 19 Sep',t:'11:04',k:'share',world:'northline',what:'Sent NDA and brief to Northline',sub:'Northline onboarding · approved by Jin',amt:'—',detail:[['Recipient','ops@northline.com'],['Files','Brief, NDA'],['Waited','2 h 40 min']]},
  {day:'Fri 18 Sep',t:'17:20',k:'gate',world:'k1',what:'Level 2 · Design review passed',sub:'K1 electric scooter · Alex and Jin',amt:'—',detail:[['Checks','12 of 12 passed'],['Signed off','Alex Morgan, Jin Park'],['Next','Level 3 · Prototypes']]},
  {day:'Fri 18 Sep',t:'14:00',k:'spend',world:'k1',what:'Agent time · Research district',sub:'K1 electric scooter · 9 agents',amt:'£64',detail:[['Hours','31 agent hours'],['Sources read','214'],['Output','Cell comparison']]},
  {day:'Thu 17 Sep',t:'08:40',k:'declined',world:'pricing',what:'Send new price list to all customers',sub:'Pricing check · Tom Reyes',amt:'—',detail:[['Reason','“Wait for leadership”'],['Recipients','1,240 customers'],['Rule','Can’t be undone']]}]});
D.team.coverage=[{id:'small',what:'Spend up to £1,000',who:['ps','jp'],wait:'6 min'},{id:'big',what:'Spend up to £2,500',who:['ps'],wait:'14 min'},{id:'share',what:'Sharing outside the company',who:['jp'],wait:'2 h 10 min',slow:true},{id:'gate',what:'Gate sign-offs',who:['jp'],wait:'38 min'}];

/* render kit (memoised; one per document) */
let K=null;
const ready=()=>!!(window.TiloWorld&&window.TiloPark);
function kit(h){
 if(K)return K;
 const W=window.TiloWorld(h),TP=window.TiloPark(h),C={};
 const ck=(k,f)=>(k in C)?C[k]:(C[k]=f());
 const sw={stroke:'currentColor',strokeWidth:2,strokeLinecap:'round',strokeLinejoin:'round',fill:'none'};
 const p=(d,o)=>h('path',Object.assign({d},sw,o||{}));
 const X={
  home:()=>p('M-7 -0.5 L0 -6.5 L7 -0.5 M-5 -2 V6.5 H5 V-2'),
  grid:()=>[h('rect',Object.assign({x:-7,y:-7,width:5.5,height:5.5,rx:1.5},sw)),h('rect',Object.assign({x:1.5,y:-7,width:5.5,height:5.5,rx:1.5},sw)),h('rect',Object.assign({x:-7,y:1.5,width:5.5,height:5.5,rx:1.5},sw)),h('rect',Object.assign({x:1.5,y:1.5,width:5.5,height:5.5,rx:1.5},sw))],
  calendar:()=>[h('rect',Object.assign({x:-7,y:-5.5,width:14,height:12.5,rx:2.5},sw)),p('M-7 -1.5 H7 M-3.5 -8 V-4 M3.5 -8 V-4')],
  bell:()=>[p('M-5.5 3.5 V-1 Q-5.5 -6.5 0 -6.5 Q5.5 -6.5 5.5 -1 V3.5 L7 5.5 H-7 Z'),p('M-2 7.5 H2')],
  plus:()=>p('M0 -6 V6 M-6 0 H6',{strokeWidth:2.4}),
  chevR:()=>p('M-2 -5 L3 0 L-2 5',{strokeWidth:2.4}),
  chevL:()=>p('M2 -5 L-3 0 L2 5',{strokeWidth:2.4}),
  chevD:()=>p('M-5 -2 L0 3 L5 -2',{strokeWidth:2.4}),
  x:()=>p('M-5 -5 L5 5 M5 -5 L-5 5',{strokeWidth:2.4}),
  plug:()=>[p('M-3 -8 V-4 M3 -8 V-4 M0 4.5 V8'),p('M-6 -4 H6 V-0.5 Q6 4.5 0 4.5 Q-6 4.5 -6 -0.5 Z')],
  arrowR:()=>p('M-6 0 H6 M2 -4 L6 0 L2 4'),
  arrowL:()=>p('M6 0 H-6 M-2 -4 L-6 0 L-2 4'),
  more:()=>[-5,0,5].map(x=>h('circle',{key:x,cx:x,cy:0,r:1.6,fill:'currentColor'})),
  shield:()=>p('M0 -7.5 L6.5 -5 V0 Q6.5 5 0 7.5 Q-6.5 5 -6.5 0 V-5 Z'),
  card:()=>[h('rect',Object.assign({x:-8,y:-5.5,width:16,height:11,rx:2},sw)),p('M-8 -1.5 H8 M-5 2.5 H-1')],
  sun:()=>[h('circle',Object.assign({cx:0,cy:0,r:3.2},sw)),p('M0 -7.5 V-6 M0 6 V7.5 M-7.5 0 H-6 M6 0 H7.5 M-5.3 -5.3 L-4.3 -4.3 M4.3 4.3 L5.3 5.3 M-5.3 5.3 L-4.3 4.3 M4.3 -4.3 L5.3 -5.3')],
  moon:()=>p('M2.5 -6.8 A6.8 6.8 0 1 0 6.8 2.5 A5.2 5.2 0 0 1 2.5 -6.8 Z'),
  pause:()=>p('M-2.5 -5 V5 M2.5 -5 V5',{strokeWidth:2.6}),
  play:()=>h('path',{d:'M-3 -5.5 L5 0 L-3 5.5 Z',fill:'currentColor'}),
  share:()=>p('M1.5 -6.5 H6.5 V-1.5 M6.5 -6.5 L-0.5 0.5 M3.5 2 V6.5 H-6.5 V-3.5 H-2'),
  download:()=>p('M0 -7 V3 M-4 -1 L0 3 L4 -1 M-6.5 6.5 H6.5'),
  logout:()=>p('M-1.5 -6.5 H-6.5 V6.5 H-1.5 M1.5 -3.5 L5 0 L1.5 3.5 M5 0 H-2.5'),
  bolt:()=>h('path',{d:'M1.5 -8 L-5 1 H-0.5 L-1.5 8 L5 -1 H0.5 Z',fill:'currentColor'}),
  refresh:()=>[p('M5.8 -1.5 A6 6 0 1 0 5 3.4'),p('M6.2 -6 V-1.2 H1.5')],
  phone:()=>[h('rect',Object.assign({x:-4.5,y:-7.5,width:9,height:15,rx:2.2},sw)),p('M-1 5 H1')],
  sparkle:()=>h('path',{d:'M0 -7.5 Q1 -1 7.5 0 Q1 1 0 7.5 Q-1 1 -7.5 0 Q-1 -1 0 -7.5 Z',fill:'currentColor'}),
  record:()=>[h('circle',Object.assign({cx:0,cy:0,r:6.5},sw)),h('circle',{cx:0,cy:0,r:3,fill:'currentColor'})],
  upload:()=>p('M0 4 V-6 M-4 -2 L0 -6 L4 -2 M-6.5 6.5 H6.5'),
  pen:()=>p('M-6 6 L-5 2 L3 -6 L6 -3 L-2 5 Z M1 -4 L4 -1'),
  globe:()=>[h('circle',Object.assign({cx:0,cy:0,r:7},sw)),p('M-7 0 H7 M0 -7 Q-4 0 0 7 Q4 0 0 -7')]
 };
 const icon=(n,s)=>h('svg',{width:s||16,height:s||16,viewBox:'-10 -10 20 20',style:{display:'block',flex:'none'},'aria-hidden':true},...[].concat(X[n]?X[n]():W.icon(n,'currentColor',0,0,.9,'#FFFFFF')));
 const agent=(a,s,night)=>ck('a|'+JSON.stringify(a)+'|'+s+'|'+!!night,()=>TP.agent(a,s,night));
 const building=(spec,st,dist,ht,night)=>ck('b|'+JSON.stringify(spec)+st+dist+ht+!!night,()=>TP.building(spec,st,dist,ht,night));
 const world=(planId,dec,night)=>{const key=planId==='k1'?'k1'+(dec&&dec.depot?1:0)+(dec&&dec.mail?1:0):planId;return ck('w|'+key+'|'+!!night,()=>TP.world(D.plans(dec)[planId],{night}));};
 const art=(w,ht,night)=>{const src=w.single||(w.row&&w.row[0]);return src?building(src[0],src[1],src[2],ht,night):null;};
 const strip=(w,ht,night)=>w.row?w.row.map((b,i)=>h('div',{key:i,style:{marginLeft:i?-14:0}},building(b[0],b[1],b[2],ht,night))):null;
 return K={W,TP,ck,icon,agent,building,world,art,strip};
}
window.TiloApp={data:D,kit,ready};
})();

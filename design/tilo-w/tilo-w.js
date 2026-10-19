/* Tilo W — fixture data for the World page. Every array maps 1:1 to a real API shape (agents, steps, events, messages, artifacts). */
(function(){
const AG={
 director:{id:'director',n:'Nova',role:'Director',col:'#E8643F',cname:'Coral',tok:'--ag1',kind:'director',home:'plan',job:'Plans the work and checks it'},
 lead:{id:'lead',n:'Kai',role:'Lead',col:'#3F7FE0',cname:'Blue',tok:'--ag2',kind:'lead',home:'budget',job:'Runs the team and owns the budget'},
 research:{id:'research',n:'Remy',role:'Specialist · Venues',col:'#2BA3B8',cname:'Teal',tok:'--ag3',kind:'agent',home:'venue',job:'Finds and checks venues'},
 travel:{id:'travel',n:'Juno',role:'Specialist · Travel',col:'#3E9A7C',cname:'Green',tok:'--ag4',kind:'agent',home:'flights',job:'Searches flights on the web'},
 writer:{id:'writer',n:'Wren',role:'Writer',col:'#A45DB8',cname:'Violet',tok:'--ag5',kind:'agent',home:'doc',job:'Writes the plan and the invite'},
 designer:{id:'designer',n:'Pia',role:'Designer',col:'#D9588C',cname:'Pink',tok:'--ag6',kind:'agent',home:'design',job:'Makes the slides and the site'},
 verifier:{id:'verifier',n:'Vale',role:'Verifier',col:'#C9982A',cname:'Ochre',tok:'--ag7',kind:'agent',home:'review',job:'Checks everything against your request'}
};
const ORDER=['director','lead','research','travel','writer','designer','verifier'];
const STEPS={
 plan:{n:'Plan',kit:'townhall',d:'hall',at:[3,.3],fp:[3,2],ic:'pen',by:'director',makes:'The plan in 7 steps'},
 venue:{n:'Venue research',kit:'library',d:'research',at:[6.4,.2],fp:[2,2],ic:'search',by:'research',makes:'Shortlist: 4 venues by the river'},
 flights:{n:'Flights',kit:'browser',d:'learning',at:[.4,3.4],fp:[2,1],ic:'plane',by:'travel',makes:'12 options from 3 cities'},
 budget:{n:'Budget sheet',kit:'appstudio',d:'accounts',at:[5.6,4],fp:[2,1],ic:'sheet',by:'lead',makes:'€14,280 of €16,000'},
 doc:{n:'Plan & invite',kit:'workshop',d:'analysis',at:[2.6,5.4],fp:[2,2],ic:'file',by:'writer',makes:'Offsite plan (PDF) and the invite email'},
 design:{n:'Slides & site',kit:'appstudio',d:'delivery',at:[.4,6.6],fp:[2,1],ic:'palette',by:'designer',makes:'Kickoff deck and event site'},
 review:{n:'Review',kit:'watchtower',d:'people',at:[3,3.6],fp:[1,1],ic:'eye',by:'verifier',makes:'Checked against your request'}
};
const SO=['plan','venue','flights','budget','doc','design','review'];
const PLACES={
 meeting:{n:'Meeting Hall',kit:'meeting',d:'people',at:[.4,.6],fp:[2,1],ic:'people'},
 dock:{n:'Delivery Dock',kit:'dock',d:'delivery',at:[6,7.2],fp:[2,1],ic:'parcel'}
};
const ISL={
 web:{n:'Web',ic:'globe',at:[-1.9,3.9],step:'flights'},
 drive:{n:'Google Drive',ic:'file',at:[7.4,-1.9],step:'venue'},
 gmail:{n:'Gmail',ic:'mail',at:[3.6,10.5],step:'doc'},
 canva:{n:'Canva',ic:'palette',at:[.8,10.5],step:'design'},
 lovable:{n:'Lovable',ic:'code',at:[-1.9,7.4],step:'design'}
};
/* [time, event, agent, to, where, plain story, trace detail, credits] */
const E=[
 ['3:54','agent.spawned','director',null,'plan','Nova picked up your request.','director#1 · planner',1],
 ['3:54','memory.hit','director',null,'plan','Nova remembered your last offsite: walkable venues, no flights before 8 am.','offsite-2025 prefs · 2 hits',1],
 ['3:55','world.planned','director',null,'plan','Nova drew up a plan in 7 steps.','plan v1 · 7 buildings · est. 90 cr',3],
 ['3:56','agent.spawned','director',null,'plan','Six helpers joined. Kai leads Remy, Juno, Wren, Pia and Vale.','6 agents · lead=kai',2],
 ['3:57','building.constructing','research',null,'venue','Remy started looking for venues by the river.','venue · tool=web.search',5],
 ['3:58','building.constructing','travel',null,'flights','Juno is checking flights from London, Berlin and Lisbon.','flights · tool=browser',6],
 ['4:00','artifact.created','research',null,'venue','Remy shortlisted 4 venues under €180 a night.','venue-shortlist.md',7],
 ['4:01','question.routed','travel','director','plan','Juno asked Nova if the direct Berlin flight is worth €40 more.','travel → director',1],
 ['4:03','artifact.created','travel',null,'flights','Juno found 12 flights. Best: TAP direct at €142 return.','flights-12-options.csv · 12 rows',10],
 ['4:04','agent.handoff','research','lead','budget','Remy handed the venue shortlist to Kai.','research → lead · shortlist',1],
 ['4:04','building.constructing','lead',null,'budget','Kai started the budget sheet.','budget · tool=sheets',5],
 ['4:05','agent.moved','travel','lead','budget','Juno is walking over to Kai with the flights.','travel: flights → budget',0],
 ['4:06','agent.handoff','travel','lead','budget','Juno handed 12 flights to Kai.','travel → lead · flights',1],
 ['4:07','building.completed','lead',null,'budget','Budget done: €14,280 of €16,000.','offsite-budget.xlsx ✓',6],
 ['4:07','building.constructing','writer',null,'doc','Wren is writing the plan and the invite.','doc · tool=docs',5],
 ['4:08','building.constructing','designer',null,'design','Pia started the kickoff deck in Canva.','design · tool=canva',4],
 ['4:10','approval.requested','writer',null,'doc','Wren needs your yes to email the invite to 12 people.','gmail.send × 12 · risk=medium',1],
 ['4:11','approval.resolved','writer',null,'doc','You approved. The invite went out from your Gmail.','approved by Maya',2],
 ['4:13','artifact.created','designer',null,'design','Pia finished the deck and published the event site with Lovable.','kickoff-deck · porto-offsite.lovable.app',9],
 ['4:13','building.completed','writer',null,'doc','Wren finished the plan: 6 pages.','porto-offsite-plan.pdf ✓',4],
 ['4:14','building.constructing','verifier',null,'review','Vale is checking everything against your request.','review · 5 pieces',4],
 ['4:15','artifact.reviewed','verifier',null,'review','Vale found nothing to fix.','review · 0 issues',3],
 ['4:16','artifact.delivered','director',null,'dock','Your offsite pack arrived at the Delivery Dock.','offsite-pack · 5 pieces',1],
 ['4:16','world.completed','director',null,'dock','Done in 22 minutes, using 82 of 120 credits.','world ✓ · 22 min',0]
];
const EF=[
 ['4:02','agent.blocked','travel',null,'flights','The airline site blocked Juno after 3 tries.','browser · HTTP 429 ×3',2],
 ['4:02','world.failed','director',null,'flights','The run stopped at Flights. Nothing was sent or paid.','world ✗ · reason=site_blocked',0]
];
const EM=[
 ['4:06','meeting.called','me',null,'meeting','You called a team meeting with Kai, Wren and Pia.','meeting · 3 agents',0],
 ['4:06','agent.moved','lead',null,'meeting','Kai, Wren and Pia walked to the Meeting Hall.','3 agents → meeting',0]
];
const CUT={planning:1,working:10,working1:11,working2:12,workingX:12,needs:16,done:23,meeting:12};
function evs(fr){ if(fr==='failed') return E.slice(0,8).concat(EF); const c=CUT[fr]==null?10:CUT[fr]; let a=E.slice(0,c+1); if(fr==='meeting') a=a.concat(EM); return a; }
const all=v=>({plan:v,venue:v,flights:v,budget:v,doc:v,design:v,review:v});
const SS={
 planning:Object.assign(all('planned'),{plan:'working'}),
 working:{plan:'done',venue:'done',flights:'done',budget:'working',doc:'waiting',design:'waiting',review:'waiting'},
 needs:{plan:'done',venue:'done',flights:'done',budget:'done',doc:'needs',design:'working',review:'waiting'},
 done:all('done'),
 failed:{plan:'done',venue:'done',flights:'failed',budget:'notStarted',doc:'notStarted',design:'notStarted',review:'notStarted'}
};
const grp=fr=>fr==='meeting'||String(fr).indexOf('working')===0?'working':fr;
function stepSt(fr){ return SS[grp(fr)]||SS.working; }
function status(fr){ return grp(fr); }
function credits(fr){ return evs(fr).reduce((a,e)=>a+e[7],0); }
function agentCr(fr,id){ return evs(fr).filter(e=>e[2]===id).reduce((a,e)=>a+e[7],0); }
function total(fr){ return fr==='failed'?evs('failed').length:E.length; }
const CHAT=[
 {at:3,t:'3:56',from:'director',to:'team',text:'Plan is set: venue, flights, budget, then the plan and invite, slides and site, and a final review. Kai, you lead.'},
 {at:3,t:'3:56',from:'lead',to:'director',text:'On it. I’ll keep us under €16,000.'},
 {at:7,t:'4:01',from:'travel',to:'director',text:'Two people fly from Berlin. The direct flight is €40 more each. Worth it?'},
 {at:7,t:'4:01',from:'director',to:'travel',text:'Yes. Maya asked for no early starts, and the direct one leaves at 10:20.'},
 {at:9,t:'4:04',from:'research',to:'lead',hand:{title:'Venue shortlist',note:'4 venues under €180 a night, all walkable to the river. Casa do Rio is my pick.',file:'venue-shortlist.md'}},
 {at:10,t:'4:04',from:'lead',to:'research',text:'Thanks Remy. Costing all four for 12 people, 2 nights.'},
 {at:10,t:'4:05',from:'me',to:'lead',text:'Kai, can we keep Saturday morning free?'},
 {at:10,t:'4:05',from:'lead',to:'me',text:'Yes. I’ll ask Wren to leave it out of the agenda.'},
 {at:12,t:'4:06',from:'travel',to:'lead',hand:{title:'Flights, 12 options',note:'All 12 people come to €2,140, with the direct Berlin flight.',file:'flights-12-options.csv'}},
 {at:16,t:'4:10',from:'writer',to:'me',ask:'Can I email the invite to 12 people from your Gmail?'},
 {at:17,t:'4:11',from:'me',to:'writer',text:'Approved. Send it.'},
 {at:21,t:'4:15',from:'verifier',to:'director',text:'Checked all 5 pieces against the request. Nothing to fix.'},
 {at:22,t:'4:16',from:'director',to:'me',text:'Your offsite pack is at the Dock. Open the plan PDF first.'}
];
const MEET=[
 {sys:'Team meeting · Kai, Wren, Pia · 4:06 pm'},
 {t:'4:06',from:'me',to:'meeting',text:'Change of plan: swap the Saturday workshop for a boat trip on the Douro. Same budget.'},
 {t:'4:06',from:'lead',to:'meeting',text:'Got it. I’ll move the money from the workshop space line.'},
 {t:'4:07',from:'writer',to:'meeting',text:'I’ll rewrite day 2 of the agenda and the invite.'},
 {t:'4:07',from:'designer',to:'meeting',text:'Slide 5 becomes the boat trip.'}
];
const INFO={
 director:{units:'Plan of 7 steps',tools:['Memory','Planner'],before:['The team liked walkable venues last time','No flights before 8 am'],now:['The Berlin pair takes the direct flight']},
 lead:{units:'6 of 14 budget lines',tools:['Sheets'],before:['Team budget cap is €16,000'],now:['Saturday morning stays free']},
 research:{units:'4 venues checked',tools:['Web search','Google Drive'],before:['The team liked walkable venues last time'],now:['Ribeira hotels fill up fast in May','Casa do Rio holds rooms for 48 hours']},
 travel:{units:'12 flights compared',tools:['Browser','Web search'],before:['No flights before 8 am'],now:['TAP direct from Berlin leaves at 10:20']},
 writer:{units:'2 drafts',tools:['Docs','Gmail'],before:['Maya signs off emails with just “M”'],now:['Saturday morning is free']},
 designer:{units:'1 of 2 pieces',tools:['Canva','Lovable'],before:['Team Rao brand kit in Canva'],now:['Slide 5 is the river walk']},
 verifier:{units:'Waiting for 5 pieces',tools:['Checklist'],before:['Check every cost against the cap'],now:[]}
};
const APR={by:'writer',t:'4:10 pm',q:'Send the invite email to 12 people from your Gmail?',exact:'Email “Porto, 14–16 May: you’re in” from maya@rao.studio to 12 people on Team Rao.',risk:'Medium. People will see it and it can’t be unsent.',cost:'1 credit'};
const FAIL={step:'Flights',t:'4:02 pm',what:'The airline site blocked automated search after 3 tries.',done:['Plan','Venue shortlist (kept)'],notDone:['Flights','Budget sheet','Plan & invite','Slides & site','Review'],safe:'Nothing was sent or paid.',cr:'28 of 120 credits used.'};
const RES={
 main:{title:'Porto offsite plan',type:'PDF',meta:'6 pages · 1.2 MB',by:'writer',made:'Tilo',summary:'Venue, flights, budget and a 3-day agenda for 12 people, 14–16 May. €1,720 under budget.'},
 sheet:{title:'Offsite budget.xlsx',meta:'Sheet · 5 lines',by:'lead',made:'Tilo',rows:[['Casa do Rio, 2 nights','12 rooms × €168','€4,032'],['Flights','12 people, 3 cities','€2,140'],['Food and dinners','3 days','€3,960'],['Workshop space','Friday','€1,850'],['Local transport and activities','Boats, trams, tickets','€2,298']],total:'€14,280'},
 slides:{title:'Kickoff deck',meta:'8 slides',by:'designer',made:'Canva',thumbs:['Porto · 14–16 May','Why Porto','Where we stay','Getting there']},
 web:{title:'Event site',meta:'Live · 3 pages',by:'designer',made:'Lovable',url:'porto-offsite.lovable.app'},
 text:{title:'Invite email',meta:'Sent from Gmail · 4:11 pm',by:'writer',made:'Tilo',to:'12 people on Team Rao',subj:'Porto, 14–16 May: you’re in',body:['Hi all, we’re off to Porto. Rooms are booked at Casa do Rio and flights are held until Friday.'],list:['Thu 14: arrive, dinner by the river at 8','Fri 15: workshop day','Sat 16: free morning, flights home after 3 pm'],sign:'Reply with any food needs by Wednesday. M'},
 files:[['venue-shortlist.md','research','4 KB'],['flights-12-options.csv','travel','9 KB'],['casa-do-rio-quote.pdf','research','210 KB'],['budget-draft-v1.xlsx','lead','18 KB'],['agenda-draft.docx','writer','26 KB'],['invite-email.md','writer','2 KB'],['review-notes.md','verifier','3 KB'],['plan-v1.json','director','6 KB']],
 made:[['Tilo','Plan PDF, budget sheet, invite email','sparkle'],['Canva','Kickoff deck','palette'],['Lovable','Event site','code']]
};
const MORE={
 skill:{t:'Save “Plan a team offsite” as a skill?',d:'Next time Tilo starts from this plan: walkable venues, no flights before 8 am, under €16,000.'},
 items:[['Book a dinner for Friday night','Maya','Open'],['Collect food needs by Wednesday','Kai','In progress'],['Share the event site in #porto','Pia','Done']]
};
window.TiloW={AG,ORDER,STEPS,SO,PLACES,ISL,E,EF,EM,CUT,evs,stepSt,status,credits,agentCr,total,CHAT,MEET,INFO,APR,FAIL,RES,MORE};
})();

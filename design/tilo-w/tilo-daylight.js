(function(){
const PLANS={
 trip:{districts:[
  {id:'hall',name:'Town Hall',hall:true,icon:'hall',buildings:[{id:'th',kit:'townhall',state:'active'},{id:'clock',kit:'clock',state:'complete'}]},
  {id:'research',name:'Beaches',icon:'search',buildings:[{id:'lib',kit:'library',state:'complete'},{id:'web',kit:'browser',state:'active'}]},
  {id:'analysis',name:'Route',icon:'swap',buildings:[{id:'map',gen:{name:'Map Room',fp:[2,1],i:'swap'},state:'active'},{id:'fuel',gen:{name:'Fuel & Tolls',fp:[1,1],i:'coin'},state:'complete'}]},
  {id:'delivery',name:'Stays',icon:'person',buildings:[{id:'stays',gen:{name:'Guesthouses',fp:[2,1],i:'person'},state:'needs'},{id:'food',gen:{name:'Food Stops',fp:[1,1],i:'dot'},state:'construction'}]}
 ],routes:[{id:'r1',from:'lib',to:'map'},{id:'r2',from:'web',to:'th'},{id:'r3',from:'fuel',to:'stays'}],
 agents:[{rank:'director',at:'th',expr:'focused'},{role:'research',at:'lib',expr:'delighted'},{role:'browser',route:'r2',t:.5,expr:'walking'},{role:'designer',at:'map',expr:'focused'},{role:'research',route:'r1',t:.55,expr:'walking'},{role:'finance',at:'fuel',expr:'delighted'},{role:'connector',at:'stays',expr:'needs'}]},
 suppliers:{districts:[
  {id:'hall',name:'Town Hall',hall:true,icon:'hall',buildings:[{id:'th',kit:'townhall',state:'active'}]},
  {id:'research',name:'Suppliers',icon:'search',buildings:[{id:'a',gen:{name:'Brightcell',fp:[1,1],i:'screen'},state:'complete'},{id:'b',gen:{name:'Voltway',fp:[1,1],i:'battery'},state:'needs'},{id:'c',gen:{name:'Nordpack',fp:[1,1],i:'parcel'},state:'active'}]},
  {id:'analysis',name:'Compare',icon:'chart',buildings:[{id:'cmp',gen:{name:'Scorecard',fp:[2,1],i:'chart'},state:'construction'}]}
 ],routes:[{id:'r1',from:'a',to:'cmp'}],
 agents:[{rank:'director',at:'th',expr:'focused'},{role:'research',at:'a',expr:'delighted'},{role:'finance',at:'b',expr:'needs'},{role:'research',route:'r1',t:.5,expr:'walking'}]},
 email:{districts:[
  {id:'hall',name:'Town Hall',hall:true,icon:'hall',buildings:[{id:'th',kit:'townhall',state:'complete'}]},
  {id:'mail',name:'Reply',icon:'mail',buildings:[{id:'post',gen:{name:'Post Office',fp:[2,1],i:'mail'},state:'complete'}]}
 ],agents:[{rank:'director',at:'th',expr:'delighted'},{role:'connector',at:'post',expr:'delighted'}]},
 launch:{districts:[
  {id:'hall',name:'Town Hall',hall:true,icon:'hall',buildings:[{id:'th',kit:'townhall',state:'active'},{id:'watch',kit:'watchtower',state:'idle'}]},
  {id:'delivery',name:'Launch page',icon:'screen',buildings:[{id:'studio',kit:'appstudio',state:'active'}]},
  {id:'analysis',name:'Pricing',icon:'tag',buildings:[{id:'price',gen:{name:'Price Lab',fp:[1,1],i:'tag'},state:'construction'}]},
  {id:'research',name:'Press',icon:'search',locked:true,buildings:[{id:'lib',kit:'library',state:'planned'}]}
 ],agents:[{rank:'director',at:'th',expr:'focused'},{role:'designer',at:'studio',expr:'focused'},{role:'builder',at:'price',expr:'focused'}]},
 calls:{districts:[
  {id:'hall',name:'Town Hall',hall:true,icon:'hall',buildings:[{id:'th',kit:'townhall',state:'complete'}]},
  {id:'research',name:'Calls',icon:'people',buildings:[{id:'lib',kit:'library',state:'complete'},{id:'vault',kit:'vault',state:'complete'}]},
  {id:'learning',name:'Summary',icon:'doc',buildings:[{id:'desk',kit:'desk',state:'complete'}]}
 ],agents:[{rank:'director',at:'th',expr:'delighted'},{role:'research',at:'lib',expr:'delighted'},{role:'designer',at:'desk',expr:'delighted'}]},
 town:{districts:[
  {id:'hall',name:'Your desk',hall:true,icon:'person',buildings:[{id:'th',kit:'townhall',state:'active'},{id:'desk',kit:'desk',state:'idle'}]},
  {id:'research',name:'Road trip',icon:'flag',buildings:[{id:'lib',kit:'library',state:'complete'},{id:'map',gen:{name:'Map Room',fp:[2,1],i:'swap'},state:'active'}]},
  {id:'analysis',name:'Suppliers',icon:'chart',buildings:[{id:'b',gen:{name:'Voltway',fp:[1,1],i:'battery'},state:'needs'},{id:'cmp',gen:{name:'Scorecard',fp:[2,1],i:'chart'},state:'construction'}]},
  {id:'mail',name:'Northline reply',icon:'mail',buildings:[{id:'post',gen:{name:'Post Office',fp:[2,1],i:'mail'},state:'complete'}]},
  {id:'delivery',name:'Spring launch',icon:'screen',buildings:[{id:'studio',kit:'appstudio',state:'active'},{id:'price',gen:{name:'Price Lab',fp:[1,1],i:'tag'},state:'construction'}]},
  {id:'accounts',name:'Invoices',icon:'coin',buildings:[{id:'tre',kit:'treasury',state:'complete'},{id:'v',kit:'vault',state:'active'}]}
 ],routes:[{id:'r1',from:'lib',to:'th'},{id:'r2',from:'post',to:'v'},{id:'r3',from:'studio',to:'cmp'}],
 agents:[{rank:'director',at:'th',expr:'delighted'},{role:'research',route:'r1',t:.5,expr:'walking'},{role:'designer',at:'map',expr:'focused'},{role:'finance',at:'b',expr:'needs'},{role:'connector',at:'post',expr:'delighted'},{role:'builder',route:'r3',t:.4,expr:'walking'},{role:'designer',at:'studio',expr:'focused'},{role:'finance',at:'v',expr:'focused'}]},
 invoices:{districts:[
  {id:'hall',name:'Town Hall',hall:true,icon:'hall',buildings:[{id:'th',kit:'townhall',state:'active'}]},
  {id:'accounts',name:'Invoices',icon:'coin',buildings:[{id:'tre',kit:'treasury',state:'complete'},{id:'v',kit:'vault',state:'active'}]},
  {id:'mail',name:'Inbox',icon:'mail',buildings:[{id:'post',gen:{name:'Inbox',fp:[1,1],i:'mail'},state:'complete'}]}
 ],routes:[{id:'r1',from:'post',to:'v'}],agents:[{rank:'director',at:'th',expr:'focused'},{role:'finance',at:'v',expr:'focused'},{role:'connector',route:'r1',t:.5,expr:'walking'}]}
};
const cache={};
PLANS.tripDone=JSON.parse(JSON.stringify(PLANS.trip));PLANS.tripDone.districts.forEach(d=>d.buildings.forEach(b=>b.state='complete'));PLANS.tripDone.agents=PLANS.tripDone.agents.filter(a=>!a.route).map(a=>({...a,expr:'delighted'}));
const KEEP={viewBox:1,preserveAspectRatio:1,patternUnits:1,patternTransform:1,gradientUnits:1,gradientTransform:1};
const kb=k=>k.replace(/[A-Z]/g,m=>'-'+m.toLowerCase());
const esc=v=>String(v).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
function S(t,p,...c){let a='';if(p)for(const k in p){const v=p[k];if(v==null||v===false||k==='key')continue;if(k==='style'){const css=Object.keys(v).filter(q=>v[q]!=null).map(q=>kb(q)+':'+v[q]).join(';');if(css)a+=' style="'+esc(css)+'"';continue;}a+=' '+(KEEP[k]?k:kb(k))+'="'+esc(v)+'"';}
 const kids=c.flat(12).filter(x=>x!=null&&x!==false).map(x=>x&&x.__s!=null?x.__s:esc(x)).join('');return{__s:'<'+t+a+'>'+kids+'</'+t+'>'};}
const ANIM='<style>@keyframes tiloBob{0%,100%{transform:translateY(0)}50%{transform:translateY(-3px)}}@keyframes tiloDash{to{stroke-dashoffset:-28}}@media (prefers-reduced-motion:reduce){*{animation:none!important}}</style>';
window.TiloR=function(h){
 if(!window.TiloCity)return null;
 const W=cache.W||(cache.W=window.TiloCity(h));
 const ck=(k,f)=>cache[k]||(cache[k]=f());
 const still=!!(window.matchMedia&&matchMedia('(prefers-reduced-motion: reduce)').matches);
 return{
  city:(key,o)=>ck('c|'+key+'|'+JSON.stringify(o||{}),()=>{
   const WS=cache.WS||(cache.WS=window.TiloCity(S));
   const oo=Object.assign({seed:3,anim:false},o||{});if(oo.show)oo.dvis=new Set(oo.show);
   let s=WS.world(PLANS[key],oo).__s;
   s=s.replace('<svg','<svg xmlns="http://www.w3.org/2000/svg"').replace(/<defs>/,'<defs>'+ANIM);
   const vb=(s.match(/viewBox="([^"]+)"/)||[])[1];if(vb){const q=vb.split(' ');s=s.replace('width="100%" height="100%"','width="'+q[2]+'" height="'+q[3]+'"');}
   const src='data:image/svg+xml;charset=utf-8,'+encodeURIComponent(s);
   return h('img',{src,alt:'',draggable:false,style:{display:'block',width:'100%',height:'100%',objectFit:'contain'}});}),
  agent:(role,expr,size,rank)=>ck(['a',role,expr,size,rank].join('|'),()=>W.soloAgent({role,expr,rank,facing:'R'},size)),
  bld:(kit,state,height,d)=>ck(['b',kit,state,height,d].join('|'),()=>W.soloBuilding(kit,state,{height,d,pin:state==='complete'||state==='needs'})),
  ic:(n,size)=>ck(['i',n,size].join('|'),()=>h('svg',{width:size,height:size,viewBox:'-10 -10 20 20','aria-hidden':true,style:{display:'block',overflow:'visible'}},W.icon(n,'currentColor',0,0,.92,'#FFFFFF')))
 };
};
})();

/** Keep model HTML inside a unique-origin sandbox. Only this injected script crosses the frame boundary. */
export function captureHtml(html: string): string {
  const script = `<script>(function(){document.addEventListener('submit',function(event){
    if(!(event.target instanceof HTMLFormElement))return;
    event.preventDefault();var fields={};new FormData(event.target).forEach(function(value,key){
      if(typeof value==='string'&&key!=='__proto__')fields[key]=value;
    });window.parent.postMessage({type:'tilo-form-submit',fields:fields},'*');
  },true)})()<\/script>`;
  return /<\/body\s*>/i.test(html)
    ? html.replace(/<\/body\s*>/i, `${script}</body>`)
    : html + script;
}

/** Only this exact first-party script is permitted by the Hosting CSP hash inside the opaque-origin frame. */
export const CAPTURE_SCRIPT =
  "document.addEventListener('submit',function(event){if(!(event.target instanceof HTMLFormElement))return;event.preventDefault();var fields=Object.create(null);new FormData(event.target).forEach(function(value,key){if(typeof value==='string'&&key!=='__proto__')fields[key]=value});window.parent.postMessage({type:'tilo-form-submit',fields:fields},'*')},true);";

export function captureHtml(html: string): string {
  const script = `<script>${CAPTURE_SCRIPT}</script>`;
  return /<\/body\s*>/i.test(html)
    ? html.replace(/<\/body\s*>/i, `${script}</body>`)
    : html + script;
}

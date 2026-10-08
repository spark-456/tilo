"""A self-contained playback page: the recording plus the transcript, click a line to hear that moment.

Stdlib only. Written to out/<run>/playback.html; open it in any browser (it needs audio.wav in the same folder).
"""

from __future__ import annotations

import html
import json
from pathlib import Path

CAPTION_LEAD_S = 4.0  # captions appear a moment after the words are spoken, so start playback a little earlier


def write_playback(run_dir: Path) -> Path | None:
    tpath = run_dir / "transcript.jsonl"
    if not tpath.is_file():
        return None
    rows = [json.loads(ln) for ln in tpath.read_text(encoding="utf-8").splitlines() if ln.strip()]
    has_audio = (run_dir / "audio.wav").is_file()
    items = []
    for r in rows:
        t = float(r.get("t", 0))
        start = max(0.0, t - CAPTION_LEAD_S)
        items.append(
            f'<li data-t="{start:.1f}"><span class="t">{int(t) // 60:02d}:{int(t) % 60:02d}</span> '
            f"<b>{html.escape(r['speaker'])}</b> {html.escape(r['text'])}</li>"
        )
    audio = (
        '<audio id="a" controls src="audio.wav"></audio>'
        if has_audio
        else "<p><b>No audio.wav here.</b> Run with <code>--record-audio</code> to record the meeting audio.</p>"
    )
    page = f"""<!doctype html><meta charset="utf-8"><title>Meeting playback</title>
<style>
body{{font:16px/1.5 system-ui,sans-serif;max-width:860px;margin:2rem auto;padding:0 1rem;background:#111;color:#eee}}
audio{{width:100%;position:sticky;top:0;background:#111}} li{{list-style:none;padding:.5rem .6rem;border-radius:.4rem;cursor:pointer}}
li:hover,li.on{{background:#25304a}} .t{{color:#8ab4ff;font-variant-numeric:tabular-nums;margin-right:.4rem}} ul{{padding:0}}
small{{color:#999}}
</style>
<h1>Meeting playback</h1>
<p><small>Click a line to jump to that moment (a few seconds early, because captions lag the speech).
Compare what you hear with what the caption says.</small></p>
{audio}
<ul>{"".join(items)}</ul>
<script>
const a=document.getElementById('a'), lis=[...document.querySelectorAll('li')];
lis.forEach(li=>li.onclick=()=>{{ if(a){{a.currentTime=+li.dataset.t; a.play();}} }});
if(a) a.ontimeupdate=()=>{{ let cur=null; lis.forEach(li=>{{ if(+li.dataset.t<=a.currentTime+{CAPTION_LEAD_S}) cur=li; li.classList.remove('on'); }}); if(cur) cur.classList.add('on'); }};
</script>"""
    out = run_dir / "playback.html"
    out.write_text(page, encoding="utf-8")
    return out

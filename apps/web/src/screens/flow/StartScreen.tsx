// S-01 Start (PRD 18.3, FR-INT-01): task box with a counter and a hard 4,000 character limit, a
// file drop and picker, three suggested tasks. Limits are checked before submit with the server's
// wording (intakeRules.ts). A suggested task fills the box; it never submits.
import { type ChangeEvent, type DragEvent, useEffect, useRef, useState } from "react";
import { useClient } from "../../api/ClientProvider";
import { SUGGESTED_TASKS } from "../../api/fixtures/suggestedTasks";
// A circular import with FlowShell (which renders this): both are only used at render time.
import { Primary, Summary } from "../FlowShell";
import { useAction } from "../remote";
import { rememberIntake } from "../s02/Understanding";
import {
  ACCEPTED,
  ACCEPT_ATTR,
  MAX_BYTES,
  MAX_FILES,
  MAX_TEXT,
  checkFiles,
  checkLength,
  clipText,
  codePoints,
  fileStatuses,
  formatSize,
} from "./intakeRules";

export function StartScreen() {
  const client = useClient();
  const [text, setText] = useState("");
  const [clipped, setClipped] = useState<number | null>(null); // code points the box was offered
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const action = useAction("start the task", async () => {
    const result = await client.submitIntake(text, files);
    rememberIntake(result); // S-02 shows this brief; the client has no "get intake" call
    return `/task/${encodeURIComponent(result.task_id)}/understanding`;
  });

  // A file dropped outside the zone must not make the browser open it and leave the page.
  useEffect(() => {
    const stop = (e: Event) => e.preventDefault();
    window.addEventListener("dragover", stop);
    window.addEventListener("drop", stop);
    return () => {
      window.removeEventListener("dragover", stop);
      window.removeEventListener("drop", stop);
    };
  }, []);

  const edit = (value: string) => {
    // Hard limit, counted in code points like the server: the box keeps the first 4,000 and
    // says so. The notice goes with the next edit; the kept text is valid, so it never blocks.
    const length = codePoints(value);
    setClipped(length > MAX_TEXT ? length : null);
    setText(clipText(value));
  };
  const add = (list: FileList | null) => {
    // Copied now: the browser empties the live FileList when the input is reset.
    const picked = list ? Array.from(list) : [];
    if (picked.length) setFiles((current) => [...current, ...picked]);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    add(e.dataTransfer.files);
  };
  const onPick = (e: ChangeEvent<HTMLInputElement>) => {
    add(e.target.files);
    e.target.value = ""; // the same file can be picked again after removing it
  };

  const problem = checkFiles(files);
  const notice =
    clipped === null ? null : `${checkLength(clipped)} Kept the first ${MAX_TEXT} characters.`;
  const message = action.busy ? null : (problem ?? notice);
  const statuses = fileStatuses(files);
  return (
    <>
      <div className="flow-body">
        <Summary>Describe what you want Tilo to handle.</Summary>
        <div className="task-box">
          <textarea
            ref={box}
            aria-label="Describe your task"
            aria-describedby="task-count"
            placeholder="e.g. Summarise this week's customer feedback"
            rows={5}
            value={text}
            onChange={(e) => edit(e.target.value)}
          />
          <p id="task-count" className="task-count">
            {`${codePoints(text).toLocaleString("en-US")} / ${MAX_TEXT.toLocaleString("en-US")}`}
          </p>
        </div>
        <fieldset className="task-chips" aria-label="Suggested tasks">
          {SUGGESTED_TASKS.map((task) => (
            <button
              type="button"
              key={task}
              className="task-chip"
              onClick={() => {
                edit(task);
                box.current?.focus();
              }}
            >
              {task}
            </button>
          ))}
        </fieldset>
        <section
          className="file-drop"
          aria-label="Files"
          data-over={dragging || undefined}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <div>
            <p>Drop files here, or choose them.</p>
            <p className="hint">
              {ACCEPTED}. Up to {MAX_FILES} files, {MAX_BYTES / (1024 * 1024)} MB in total.
            </p>
          </div>
          <button type="button" className="secondary" onClick={() => picker.current?.click()}>
            Choose files
          </button>
          <input ref={picker} type="file" hidden multiple accept={ACCEPT_ATTR} onChange={onPick} />
        </section>
        {files.length > 0 && (
          <ul className="file-list" aria-label="Attached files">
            {files.map((file, i) => (
              <li key={`${i}:${file.name}`}>
                <span className="file-name">{file.name}</span>
                <span className="file-meta">
                  {formatSize(file.size)} · {action.busy ? "Sending" : statuses[i]}
                </span>
                <button
                  type="button"
                  className="secondary small"
                  aria-label={`Remove ${file.name}`}
                  disabled={action.busy}
                  onClick={() => setFiles((current) => current.filter((_, j) => j !== i))}
                >
                  Remove
                </button>
              </li>
            ))}
          </ul>
        )}
        <div className="flow-msg">
          {message && <p role="alert">{message}</p>}
          <output>{action.busy ? "Sending your task…" : ""}</output>
        </div>
      </div>
      <div className="flow-actions">
        <p className="start-hint">You see the plan and the cost before any agent starts.</p>
        <Primary label="Start task" action={action} disabled={!text.trim() || problem !== null} />
      </div>
    </>
  );
}

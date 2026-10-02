// S-01 Start (PRD 18.3, FR-INT-01): task box with a counter and a hard 4,000 character limit, a
// file drop and picker, three suggested tasks. Limits are checked before submit with the server's
// wording (intakeRules.ts). A suggested task fills the box; it never submits.
import { type ChangeEvent, type DragEvent, useRef, useState } from "react";
import { useClient } from "../../api/ClientProvider";
import { SUGGESTED_TASKS } from "../../api/fixtures/suggestedTasks";
// A circular import with FlowShell (which renders this): both are only used at render time.
import { Primary, Summary } from "../FlowShell";
import { useAction } from "../remote";
import {
  ACCEPTED,
  ACCEPT_ATTR,
  MAX_BYTES,
  MAX_FILES,
  MAX_TEXT,
  checkFiles,
  checkLength,
  formatSize,
  isAccepted,
} from "./intakeRules";

export function StartScreen() {
  const client = useClient();
  const [text, setText] = useState("");
  const [over, setOver] = useState<number | null>(null); // length of text the box refused
  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const action = useAction("start the task", async () => {
    const result = await client.submitIntake(text, files);
    return `/task/${encodeURIComponent(result.task_id)}/understanding`;
  });

  const edit = (value: string) => {
    // Hard limit: the box keeps 4,000 characters and says so in the server's words.
    setOver(value.length > MAX_TEXT ? value.length : null);
    setText(value.slice(0, MAX_TEXT));
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

  const problem = (over !== null ? checkLength(over) : null) ?? checkFiles(files);
  const message = action.busy ? null : problem;
  return (
    <>
      <div className="flow-body">
        <Summary>Describe what you want Tilo to handle.</Summary>
        <div className="task-box">
          <textarea
            ref={box}
            aria-label="Describe your task"
            aria-describedby="task-count"
            rows={5}
            value={text}
            onChange={(e) => edit(e.target.value)}
          />
          <p id="task-count" className="task-count">
            {text.length.toLocaleString("en-US")} / {MAX_TEXT.toLocaleString("en-US")}
          </p>
        </div>
        <fieldset className="chips" aria-label="Suggested tasks">
          {SUGGESTED_TASKS.map((task) => (
            <button
              type="button"
              key={task}
              className="chip"
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
                  {formatSize(file.size)} ·{" "}
                  {action.busy
                    ? "Sending"
                    : isAccepted(file.name)
                      ? "Ready to send"
                      : "Not accepted"}
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
        <Primary label="Start" action={action} disabled={!text.trim() || problem !== null} />
      </div>
    </>
  );
}

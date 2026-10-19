// JUDGE-FIRST-RUN F2: the one real thing a first visit offers. Three example tasks fill the task box (nothing starts
// until the person presses Start and approves the plan) and one button opens the recorded sample project to watch.
// The recorded project is labelled Sample; the three tasks are real and are not.
import { Button } from "../components";
import { FIRST_TASKS } from "./firstTask";
import "./firstTask.css";

export function FirstTaskCard({
  onPick,
  onWatch,
}: {
  /** Puts the task's text in the task box and focuses it; starts nothing. */
  onPick: (prompt: string) => void;
  /** Opens the recorded sample project. */
  onWatch: () => void;
}) {
  return (
    <section className="park-first-task" aria-labelledby="park-first-task-title">
      <h2 id="park-first-task-title">Start your first task</h2>
      <p>
        Pick one to fill the task box, then press Start. Tilo shows the plan and the cost first, and
        nothing runs until you approve it.
      </p>
      <ul className="park-first-task__list">
        {FIRST_TASKS.map((task) => (
          <li key={task.id}>
            <button
              type="button"
              className="park-first-task__pick"
              onClick={() => onPick(task.prompt)}
            >
              {task.label}
            </button>
          </li>
        ))}
      </ul>
      <div className="park-first-task__watch">
        <Button variant="secondary" size="sm" onClick={onWatch}>
          Watch a recorded project
        </Button>
        <span>A finished example you can replay. It is not your work.</span>
      </div>
    </section>
  );
}

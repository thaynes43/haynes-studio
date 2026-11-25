import { Fragment } from "react";

import type { RunProblem } from "./run-data";
import { boardPosition } from "./storyboard-timeline";

export function RunProblemList({ problems, order = [] }: { problems: RunProblem[]; order?: readonly string[] }) {
  if (!problems.length) return null;
  const groups = new Map<string | undefined, RunProblem[]>();
  for (const problem of problems) {
    const group = groups.get(problem.board);
    if (group) group.push(problem);
    else groups.set(problem.board, [problem]);
  }
  return <div className="run-problems">{[...groups].map(([board, items]) => {
    const index = board ? order.indexOf(board) : -1;
    return <Fragment key={board ?? ""}>
      {board && <p><strong>{index >= 0 ? boardPosition(index) : "Board"}</strong> <code>{board}</code></p>}
      <ul>{items.map(({ code, message, field }, index) => <li key={index}>
        {message}{code && <> <code>{code}</code></>}{field && <> <code>{field}</code></>}
      </li>)}</ul>
    </Fragment>;
  })}</div>;
}

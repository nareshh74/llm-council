import './Activity.css';

const STAGES = {
  memory: 'Memory and wiki',
  stage1: 'Stage 1: individual responses',
  stage2: 'Stage 2: peer rankings',
  stage3: 'Stage 3: final synthesis',
  title: 'Title',
};

function mergeById(events) {
  const rows = [];
  const index = new Map();
  for (const e of events) {
    if (e.id && index.has(e.id)) {
      rows[index.get(e.id)] = { ...rows[index.get(e.id)], ...e };
    } else {
      if (e.id) index.set(e.id, rows.length);
      rows.push(e);
    }
  }
  return rows;
}

function seconds(ms) {
  return `${(ms / 1000).toFixed(1)}s`;
}

function Row({ e, t0 }) {
  const at = `+${(e.at - t0).toFixed(1)}s`;
  const state = e.status === 'running' ? 'running' : e.status === 'error' ? 'error' : 'done';
  const mark = state === 'running' ? '…' : state === 'error' ? '✗' : '✓';

  let text = '';
  if (e.kind === 'llm') {
    text = `${e.model} · LLM call ${e.round}`;
    if (e.status === 'done') {
      text += ` · ${seconds(e.ms)} · ${e.chars} chars${e.tool_calls ? ` · ${e.tool_calls} tool call${e.tool_calls > 1 ? 's' : ''}` : ''}`;
    }
    if (e.status === 'error') text += ` · failed after ${seconds(e.ms)}: ${e.error}`;
  } else if (e.kind === 'tool') {
    text = `${e.model} · ${e.name} ${e.args}`;
    if (e.status !== 'running') text += ` · ${e.ms}ms · ${e.chars} chars`;
  } else if (e.kind === 'memory') {
    text = e.status === 'done' ? `Recalled wiki and memory (${e.chars} chars added)` : 'Recalling wiki and memory';
  } else if (e.kind === 'memory_save') {
    text = e.status === 'done' ? 'Saved the verdict to wiki and memory' : 'Saving the verdict to wiki and memory';
  } else if (e.kind === 'workspace') {
    text = `Opened folder ${e.folder} · ${e.tools} MCP tools · ${e.skills} skills`;
  } else if (e.kind === 'title') {
    text = `Title: ${e.title}`;
  } else {
    text = e.kind;
  }

  const body = (
    <>
      <span className={`activity-mark ${state}`}>{mark}</span>
      <span className="activity-text">{text}</span>
      <span className="activity-at">{at}</span>
    </>
  );

  if (e.kind === 'tool' && e.preview) {
    return (
      <details className={`activity-row tool ${state}`}>
        <summary>{body}</summary>
        <pre className="activity-preview">{e.preview}</pre>
      </details>
    );
  }
  return <div className={`activity-row ${e.kind} ${state}`}>{body}</div>;
}

export default function Activity({ events, live }) {
  if (!events || events.length === 0) return null;
  const rows = mergeById(events);
  const t0 = events[0].at;
  const order = [];
  const groups = {};
  for (const r of rows) {
    const key = r.stage || 'other';
    if (!groups[key]) {
      groups[key] = [];
      order.push(key);
    }
    groups[key].push(r);
  }
  const running = rows.filter((r) => r.status === 'running').length;

  return (
    <details className="activity" open={live || undefined}>
      <summary className="activity-summary">
        Activity · {rows.length} steps{live && running ? ` · ${running} running` : ''}
      </summary>
      {order.map((key) => (
        <div key={key} className="activity-group">
          <div className="activity-group-title">{STAGES[key] || key}</div>
          {groups[key].map((r, i) => (
            <Row key={r.id || `${key}-${i}`} e={r} t0={t0} />
          ))}
        </div>
      ))}
    </details>
  );
}

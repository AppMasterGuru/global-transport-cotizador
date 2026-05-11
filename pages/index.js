import { useState, useEffect } from 'react';
import Head from 'next/head';
import { SECTIONS } from '../data/tasks';

const TAG_CONFIG = {
  ready: { label: 'ready to build', bg: '#e6f4ea', color: '#1e7e34' },
  client: { label: 'needs client', bg: '#e8f0fe', color: '#1a56db' },
  blocked: { label: 'blocked', bg: '#fdecea', color: '#b91c1c' },
};

function Tag({ tag }) {
  const cfg = TAG_CONFIG[tag];
  if (!cfg) return null;
  return (
    <span style={{
      display: 'inline-block', fontSize: '10px', fontWeight: 600,
      letterSpacing: '.04em', textTransform: 'uppercase',
      padding: '2px 7px', borderRadius: '20px',
      background: cfg.bg, color: cfg.color,
      marginLeft: '8px', verticalAlign: 'middle', whiteSpace: 'nowrap',
    }}>{cfg.label}</span>
  );
}

export default function Dashboard() {
  const [state, setState] = useState({});
  const [collapsed, setCollapsed] = useState({});
  const [expanded, setExpanded] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);

  useEffect(() => {
    fetch('/api/tasks')
      .then(r => r.json())
      .then(({ state }) => { setState(state); setLoading(false); });
  }, []);

  const allTasks = SECTIONS.flatMap(s => s.tasks);
  const doneCount = allTasks.filter(t => state[t.id]).length;
  const total = allTasks.length;
  const pct = total ? Math.round((doneCount / total) * 100) : 0;
  const blockedCount = allTasks.filter(t => t.tags?.includes('blocked') && !state[t.id]).length;
  const readyCount = allTasks.filter(t => t.tags?.includes('ready') && !state[t.id]).length;

  async function toggle(id, current) {
    const next = !current;
    setState(prev => ({ ...prev, [id]: next }));
    setSaving(id);
    try {
      await fetch('/api/tasks', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, done: next }),
      });
      setLastUpdated(new Date());
    } catch {}
    setSaving(null);
  }

  function toggleSection(id) {
    setCollapsed(prev => ({ ...prev, [id]: !prev[id] }));
  }

  function toggleExpanded(id) {
    setExpanded(prev => prev === id ? null : id);
  }

  if (loading) return (
    <div style={{ minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#f8f7f4' }}>
      <div style={{ fontSize: '13px', color: '#6b7280', letterSpacing: '.06em', textTransform: 'uppercase' }}>Loading checklist…</div>
    </div>
  );

  return (
    <>
      <Head>
        <title>GT × TimeBack AI — Pipeline #1</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=Sora:wght@400;500;600&display=swap" rel="stylesheet" />
        <style>{`
          *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
          :root { --font: 'Sora', sans-serif; --mono: 'IBM Plex Mono', monospace; }
          body { background: #f8f7f4; font-family: var(--font); color: #111; -webkit-font-smoothing: antialiased; }
          input[type=checkbox] { accent-color: #1B3A6B; cursor: pointer; flex-shrink: 0; }
          .section-hdr:hover { background: #f0ede8 !important; }
          .task-body-click:hover { background: #f5f3ef !important; }
          @keyframes slideDown { from { opacity:0; transform:translateY(-4px); } to { opacity:1; transform:translateY(0); } }
          .detail-panel { animation: slideDown .18s ease both; }
          ol { padding-left: 1.2rem; }
          ol li { margin-bottom: 6px; font-size: 13px; line-height: 1.6; color: #374151; }
        `}</style>
      </Head>

      <div style={{ minHeight: '100vh', background: '#f8f7f4' }}>
        {/* Top bar */}
        <div style={{ background: '#1B3A6B', padding: '0 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', height: '52px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <div style={{ width: '8px', height: '8px', borderRadius: '50%', background: '#E8471C' }} />
            <span style={{ fontFamily: 'var(--mono)', fontSize: '12px', color: 'rgba(255,255,255,.7)', letterSpacing: '.06em' }}>
              GLOBAL TRANSPORT × TIMEBACK AI
            </span>
          </div>
          <span style={{ fontFamily: 'var(--mono)', fontSize: '11px', color: 'rgba(255,255,255,.45)' }}>
            {lastUpdated ? `saved ${lastUpdated.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}` : 'pipeline #1'}
          </span>
        </div>

        <div style={{ maxWidth: '780px', margin: '0 auto', padding: '32px 24px 64px' }}>
          {/* Header */}
          <div style={{ marginBottom: '32px' }}>
            <h1 style={{ fontSize: '28px', fontWeight: 600, color: '#111', lineHeight: 1.2, marginBottom: '6px' }}>
              Cotizador — master checklist
            </h1>
            <p style={{ fontSize: '14px', color: '#6b7280' }}>
              Pipeline #1 · Click a task row to see why it matters and how to do it
            </p>
          </div>

          {/* Stats */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '12px', marginBottom: '32px' }}>
            {[
              { label: 'Done', value: doneCount, accent: '#1B3A6B' },
              { label: 'Total', value: total, accent: '#374151' },
              { label: 'Complete', value: `${pct}%`, accent: pct === 100 ? '#16a34a' : '#1B3A6B' },
              { label: 'Blocked', value: blockedCount, accent: '#b91c1c' },
            ].map(({ label, value, accent }) => (
              <div key={label} style={{ background: '#fff', border: '1px solid #e5e7eb', borderRadius: '10px', padding: '16px', textAlign: 'center' }}>
                <div style={{ fontSize: '26px', fontWeight: 600, color: accent, fontFamily: 'var(--mono)', lineHeight: 1 }}>{value}</div>
                <div style={{ fontSize: '11px', color: '#9ca3af', marginTop: '4px', textTransform: 'uppercase', letterSpacing: '.06em' }}>{label}</div>
              </div>
            ))}
          </div>

          {/* Progress bar */}
          <div style={{ background: '#e5e7eb', borderRadius: '4px', height: '5px', marginBottom: '8px' }}>
            <div style={{ background: '#1B3A6B', borderRadius: '4px', height: '5px', width: `${pct}%`, transition: 'width .5s ease' }} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '32px' }}>
            <span style={{ fontSize: '11px', color: '#9ca3af', fontFamily: 'var(--mono)' }}>{readyCount} tasks ready to build now</span>
            <span style={{ fontSize: '11px', color: '#9ca3af', fontFamily: 'var(--mono)' }}>{blockedCount} blocked on client</span>
          </div>

          {/* Sections */}
          {SECTIONS.map((sec, sIdx) => {
            const tasks = sec.tasks;
            const secDone = tasks.filter(t => state[t.id]).length;
            const secBlocked = tasks.filter(t => t.tags?.includes('blocked') && !state[t.id]).length;
            const isOpen = !collapsed[sec.id];
            const allDone = secDone === tasks.length;

            return (
              <div key={sec.id} style={{ marginBottom: '12px', background: '#fff', border: '1px solid #e5e7eb', borderRadius: '12px', overflow: 'hidden' }}>
                {/* Section header */}
                <button className="section-hdr" onClick={() => toggleSection(sec.id)} style={{
                  width: '100%', display: 'flex', alignItems: 'center', gap: '12px',
                  padding: '14px 18px', background: 'transparent', border: 'none',
                  cursor: 'pointer', textAlign: 'left', transition: 'background .12s',
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flex: 1, minWidth: 0 }}>
                    <span style={{ fontFamily: 'var(--mono)', fontSize: '10px', fontWeight: 500, letterSpacing: '.08em', textTransform: 'uppercase', color: allDone ? '#16a34a' : '#6b7280' }}>
                      {String(sIdx + 1).padStart(2, '0')}
                    </span>
                    <span style={{ fontSize: '14px', fontWeight: 500, color: '#111' }}>{sec.title}</span>
                  </div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexShrink: 0 }}>
                    <span style={{ fontSize: '11px', fontFamily: 'var(--mono)', fontWeight: 500, color: allDone ? '#16a34a' : secBlocked > 0 ? '#b91c1c' : '#6b7280' }}>
                      {secDone}/{tasks.length}
                    </span>
                    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" style={{ transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'transform .2s', color: '#9ca3af' }}>
                      <path d="M2 5l5 5 5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </div>
                </button>

                {/* Tasks */}
                {isOpen && (
                  <div style={{ borderTop: '1px solid #f3f4f6' }}>
                    {tasks.map((task, tIdx) => {
                      const done = !!state[task.id];
                      const isSaving = saving === task.id;
                      const isExpanded = expanded === task.id;

                      return (
                        <div key={task.id} style={{ borderBottom: tIdx < tasks.length - 1 ? '1px solid #f3f4f6' : 'none' }}>
                          {/* Task row */}
                          <div style={{ display: 'flex', alignItems: 'flex-start' }}>
                            {/* Checkbox area — click to tick */}
                            <div
                              onClick={() => toggle(task.id, done)}
                              style={{ padding: '13px 12px 13px 18px', cursor: 'pointer', display: 'flex', alignItems: 'flex-start', paddingTop: '15px', flexShrink: 0 }}
                            >
                              <input
                                type="checkbox"
                                checked={done}
                                onChange={() => {}}
                                style={{ width: '15px', height: '15px', opacity: isSaving ? .5 : 1, cursor: 'pointer' }}
                              />
                            </div>

                            {/* Task body — click to expand detail */}
                            <div
                              className="task-body-click"
                              onClick={() => toggleExpanded(task.id)}
                              style={{
                                flex: 1, padding: '12px 18px 12px 4px', cursor: 'pointer',
                                background: isExpanded ? '#f8f6f2' : done ? '#fafaf9' : 'transparent',
                                transition: 'background .12s', minWidth: 0,
                              }}
                            >
                              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
                                <div style={{ flex: 1, minWidth: 0 }}>
                                  <div style={{ fontSize: '13.5px', color: done ? '#9ca3af' : '#111', textDecoration: done ? 'line-through' : 'none', lineHeight: 1.5 }}>
                                    {task.name}
                                    {(task.tags || []).map(tag => <Tag key={tag} tag={tag} />)}
                                  </div>
                                  {task.sub && (
                                    <div style={{ fontSize: '11.5px', color: '#9ca3af', marginTop: '3px', lineHeight: 1.5 }}>{task.sub}</div>
                                  )}
                                </div>
                                {/* Expand chevron */}
                                <svg width="12" height="12" viewBox="0 0 12 12" fill="none" style={{ transform: isExpanded ? 'rotate(180deg)' : 'none', transition: 'transform .2s', color: '#d1d5db', flexShrink: 0, marginTop: '4px' }}>
                                  <path d="M2 4l4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                                </svg>
                              </div>
                            </div>
                          </div>

                          {/* Detail panel */}
                          {isExpanded && (
                            <div className="detail-panel" style={{ background: '#f8f6f2', borderTop: '1px solid #ede9e2', padding: '16px 18px 18px 18px' }}>
                              {/* Why it matters */}
                              {task.why && task.why !== 'Completed.' && (
                                <div style={{ marginBottom: '14px' }}>
                                  <div style={{ fontSize: '10px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.07em', color: '#E8471C', marginBottom: '6px', fontFamily: 'var(--mono)' }}>
                                    Why this matters
                                  </div>
                                  <p style={{ fontSize: '13px', color: '#374151', lineHeight: 1.65 }}>{task.why}</p>
                                </div>
                              )}

                              {/* How to do it */}
                              {task.how && task.how.length > 0 && !(task.how.length === 1 && task.how[0].startsWith('Done')) && (
                                <div>
                                  <div style={{ fontSize: '10px', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '.07em', color: '#1B3A6B', marginBottom: '8px', fontFamily: 'var(--mono)' }}>
                                    How to do it
                                  </div>
                                  <ol>
                                    {task.how.map((step, i) => (
                                      <li key={i}>{step}</li>
                                    ))}
                                  </ol>
                                </div>
                              )}

                              {/* Completed state */}
                              {task.why === 'Completed.' && (
                                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                                  <span style={{ fontSize: '18px', color: '#16a34a' }}>✓</span>
                                  <span style={{ fontSize: '13px', color: '#16a34a', fontWeight: 500 }}>{task.how?.[0] || 'Completed'}</span>
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}

          <p style={{ textAlign: 'center', fontSize: '11px', color: '#d1d5db', marginTop: '32px', fontFamily: 'var(--mono)' }}>
            TimeBack AI · Pipeline #1 · {new Date().getFullYear()}
          </p>
        </div>
      </div>
    </>
  );
}

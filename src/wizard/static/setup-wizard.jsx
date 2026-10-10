// setup-wizard.jsx — ARCNODE first-boot setup wizard.
// Served by FastAPI at http://<ip>:8080; runs once, then the URL 404s.
// One page per daemon: its input, apply, and verification rows together —
// Continue unlocks only when every check is green. The hardware check comes
// first everywhere (preflight-page.jsx). Then SSH, on-prem only: paste the
// public half of your own .pem. In the cloud EC2 already set SSH up.

const { useState: useStateW, useEffect: useEffectW } = React;

// ─── Steps definition ────────────────────────────────────────────────
// Each step lists the deployments it exists in — the body filters to this
// box's deployment. SSH is on-prem only: in the cloud EC2 already set it up.
const ALL_STEPS = [
  { id: 'ssh',      n: 1, title: 'SSH access', sub: 'Add + verify your key',    deployments: ['on-prem'] },
  { id: 'docker',   n: 2, title: 'Docker',     sub: 'Container network',         deployments: ['on-prem'] },
  { id: 'postgres', n: 3, title: 'PostgreSQL', sub: 'Password + databases',      deployments: ['on-prem'] },
  { id: 'neo4j',    n: 4, title: 'Neo4j',      sub: 'Password + graph',          deployments: ['on-prem'] },
  { id: 'ollama',   n: 5, title: 'Ollama',     sub: 'AI models',                 deployments: ['on-prem'] },
];

// ─── Inline icons ────────────────────────────────────────────────────
function CheckW({ color, size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 12 L10 17 L19 7"/>
    </svg>
  );
}
function ChevronW({ color, size = 14, dir = 'right' }) {
  const d = dir === 'right' ? 'M9 6 L15 12 L9 18' : 'M15 6 L9 12 L15 18';
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d={d}/>
    </svg>
  );
}
function LockW({ color, size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="11" width="16" height="10" rx="2"/>
      <path d="M8 11 V7 a 4 4 0 0 1 8 0 V11"/>
    </svg>
  );
}
function FailW({ color, size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
      <path d="M6 6 L18 18 M18 6 L6 18"/>
    </svg>
  );
}
function SpinnerW({ color, size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="2.5" strokeLinecap="round"
         style={{ animation: 'wizSpin 0.9s linear infinite' }}>
      <path d="M12 3 a9 9 0 0 1 9 9" />
    </svg>
  );
}
// ─── Step rail (left column) ─────────────────────────────────────────
function StepRailW({ t, steps, current, completed, onJump }) {
  const isSov = t.name === 'sovereign';
  const preflightActive = current === 'preflight';
  const preflightDone = completed.has('preflight');
  return (
    <div style={{
      width: 260, flexShrink: 0,
      padding: `${SPACE[6]}px ${SPACE[5]}px`,
      borderRight: `1px solid ${t.border}`,
      background: t.surface,
      display: 'flex', flexDirection: 'column', gap: SPACE[2],
    }}>
      <div style={{
        fontFamily: t.fontLabel, fontSize: 9, fontWeight: 700,
        letterSpacing: 0.22, color: t.textFaint, textTransform: 'uppercase',
        marginBottom: SPACE[3],
      }}>Setup · {steps.length} {steps.length === 1 ? 'step' : 'steps'}</div>

      {/* preflight chip — above the numbered list, not part of the count */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: SPACE[3],
        padding: `${SPACE[2]}px ${SPACE[3]}px`,
        marginBottom: SPACE[2],
        borderRadius: RADIUS[2],
        background: preflightActive ? t.accent + '12' : 'transparent',
        borderLeft: `2px solid ${preflightActive ? t.accent : 'transparent'}`,
        cursor: preflightDone ? 'pointer' : 'default',
        opacity: (preflightActive || preflightDone) ? 1 : 0.55,
      }}
      onClick={() => preflightDone && onJump && onJump('preflight')}>
        <span style={{
          width: 22, height: 22, borderRadius: 6,
          border: `1px solid ${preflightDone ? t.statusOk : preflightActive ? t.accent : t.borderSoft}`,
          background: preflightDone ? t.statusOk : preflightActive ? t.accent : 'transparent',
          display: 'flex', alignItems: 'center', justifyContent: 'center',
          flexShrink: 0,
        }}>
          {preflightDone
            ? <CheckW color="#fff" size={11}/>
            : <svg width="11" height="11" viewBox="0 0 24 24" fill="none"
                   stroke={preflightActive ? '#fff' : t.textSoft} strokeWidth="2.2"
                   strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2 L4 6 V12 C4 17 8 20 12 22 C16 20 20 17 20 12 V6 Z"/>
              </svg>}
        </span>
        <div style={{ minWidth: 0 }}>
          <div style={{
            fontFamily: t.fontBody, fontSize: 13, fontWeight: 600,
            color: preflightActive ? t.text : t.textMid,
            lineHeight: 1.2,
          }}>Hardware preflight</div>
          <div style={{
            fontFamily: t.fontLabel, fontSize: 10, color: t.textSoft,
            marginTop: 2, letterSpacing: 0.05,
          }}>Before setup begins</div>
        </div>
      </div>

      {steps.map(s => {
        const isActive = current === s.id;
        const isDone   = completed.has(s.id);
        const isUpcoming = !isActive && !isDone;
        const dotBg = isDone ? t.statusOk : isActive ? t.accent : 'transparent';
        const dotBorder = isDone ? t.statusOk : isActive ? t.accent : t.borderSoft;
        const dotFg = isDone || isActive ? '#fff' : t.textSoft;
        return (
          <div key={s.id}
            onClick={() => isDone && onJump && onJump(s.id)}
            style={{
              display: 'flex', alignItems: 'flex-start', gap: SPACE[3],
              padding: `${SPACE[2]}px ${SPACE[3]}px`,
              borderRadius: RADIUS[2],
              background: isActive ? t.accent + '12' : 'transparent',
              borderLeft: `2px solid ${isActive ? t.accent : 'transparent'}`,
              cursor: isDone ? 'pointer' : 'default',
              opacity: isUpcoming ? 0.55 : 1,
            }}>
            <span style={{
              width: 22, height: 22, borderRadius: '50%',
              border: `1px solid ${dotBorder}`,
              background: dotBg,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              flexShrink: 0, marginTop: 1,
              fontFamily: t.fontLabel, fontSize: 10, fontWeight: 700,
              color: dotFg,
            }}>
              {isDone ? <CheckW color="#fff" size={11}/> : s.n}
            </span>
            <div style={{ minWidth: 0 }}>
              <div style={{
                fontFamily: t.fontBody, fontSize: 13, fontWeight: 600,
                color: isActive ? t.text : t.textMid,
                lineHeight: 1.2,
              }}>{s.title}</div>
              <div style={{
                fontFamily: t.fontLabel, fontSize: 10, color: t.textSoft,
                marginTop: 2, letterSpacing: 0.05,
              }}>{s.sub}</div>
            </div>
          </div>
        );
      })}

      <div style={{ flex: 1 }}/>

      {/* address pill (this is the FastAPI bootstrap server) */}
      <div style={{
        padding: `${SPACE[3]}px`,
        background: t.bg,
        border: `1px solid ${t.border}`,
        borderRadius: RADIUS[2],
      }}>
        <div style={{
          display: 'flex', alignItems: 'center', gap: 6,
          fontFamily: t.fontLabel, fontSize: 9, fontWeight: 700,
          letterSpacing: 0.22, color: t.textFaint, textTransform: 'uppercase',
        }}>
          <LockW color={t.statusOk} size={10}/>
          Bootstrap server
        </div>
        <div style={{
          fontFamily: t.fontLabel, fontSize: 11,
          color: t.text, marginTop: 6, lineHeight: 1.4,
          wordBreak: 'break-all',
        }}>http://{window.location.host}</div>
        <div style={{
          fontFamily: t.fontLabel, fontSize: 9, color: t.textSoft,
          marginTop: 4, letterSpacing: 0.05,
        }}>Disappears after apply.</div>
      </div>
    </div>
  );
}

// ─── Shared field primitives ─────────────────────────────────────────
function FieldLabelW({ t, children, optional, required }) {
  return (
    <label style={{
      display: 'flex', alignItems: 'baseline', gap: 6,
      fontFamily: t.fontLabel, fontSize: 10, fontWeight: 700,
      letterSpacing: 0.18, color: t.textSoft, textTransform: 'uppercase',
      marginBottom: 6,
    }}>
      <span>{children}</span>
      {optional && <span style={{ color: t.textFaint, fontWeight: 500 }}>· optional</span>}
      {required && <span style={{ color: t.statusAlarm, fontWeight: 500 }}>· required</span>}
    </label>
  );
}
function HelperW({ t, children, error }) {
  return (
    <div style={{
      fontFamily: t.fontLabel, fontSize: 10,
      color: error ? t.statusAlarm : t.textSoft,
      marginTop: 6, lineHeight: 1.4, letterSpacing: 0.05,
    }}>{children}</div>
  );
}

// ─── Step 1 — SSH access ─────────────────────────────────────────────
// applyState: idle | applying | done (all checks green) | unverified (a
// check failed — retry is safe) | error (the request itself failed)
const WIZARD_LOG_HINT = 'sudo journalctl -u arcnode-wizard';

function StepSsh({ t, setup, sshKey, onKey, page, onApply }) {
  const { state: applyState, error: applyError, result } = page;
  if (!setup) {
    return (
      <StepShellW t={t} title="SSH access" blurb="Loading…">
        <SpinnerW color={t.accent} size={16}/>
      </StepShellW>
    );
  }
  const isApplying = applyState === 'applying';
  const isDone     = applyState === 'done';
  const canApply   = !isApplying && !isDone && sshKey.trim() !== '';
  const buttonLabel = isApplying ? 'Verifying'
    : applyState === 'unverified' ? 'Try again' : 'Install & verify';
  const blurb = `Bring your own key. Paste the public half of your .pem; you'll log in as ${setup.account}, the account you created during the Debian install. Your private key never leaves your machine.`;
  return (
    <StepShellW t={t} title="SSH access" blurb={blurb}>
      <div style={{ marginBottom: SPACE[4] }}>
        <FieldLabelW t={t} required>SSH public key</FieldLabelW>
        <textarea value={sshKey} onChange={e => onKey(e.target.value)} disabled={isApplying || isDone}
          placeholder="ssh-rsa AAAA…" rows={4} spellCheck={false} aria-label="SSH public key"
          style={{
            width: '100%', boxSizing: 'border-box', padding: SPACE[3],
            background: t.bg, color: t.text, resize: 'vertical', outline: 'none',
            border: `1px solid ${t.border}`, borderRadius: RADIUS[2],
            fontFamily: t.fontLabel, fontSize: 12, lineHeight: 1.5,
          }}/>
        <HelperW t={t}>Get it with: ssh-keygen -y -f private-key.pem</HelperW>
      </div>
      {!isDone && (
        <button onClick={canApply ? onApply : undefined} disabled={!canApply}
          style={primaryBtnStyle(t, !canApply)}>
          {isApplying && <SpinnerW color="#fff" size={13}/>}
          {buttonLabel}
        </button>
      )}
      {applyState === 'error' && (
        <div style={{ marginTop: SPACE[4] }}>
          <HelperW t={t} error>Failed: {applyError}</HelperW>
          <HintW t={t} label="See the wizard's own log, on the appliance console" command={WIZARD_LOG_HINT}/>
        </div>
      )}
      {result && !isApplying && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: SPACE[3], marginTop: SPACE[5] }}>
          {result.checks.map(check => <CheckRowW key={check.name} t={t} check={check}/>)}
        </div>
      )}
      {isDone && (
        <div style={{ marginTop: SPACE[5] }}>
          <HintW t={t} label="Log in from your machine"
            command={`ssh -i private-key.pem ${setup.account}@${window.location.hostname}`}/>
          <HelperW t={t}>
            Still refused? Run ssh -v -i private-key.pem {setup.account}@{window.location.hostname} on
            your machine while sudo journalctl -u ssh -f runs on the appliance — it shows why sshd said no.
          </HelperW>
        </div>
      )}
    </StepShellW>
  );
}
function HintW({ t, label, command }) {
  return (
    <div style={{ marginTop: SPACE[3] }}>
      <FieldLabelW t={t}>{label}</FieldLabelW>
      <code style={{
        display: 'block', userSelect: 'all', padding: `${SPACE[3]}px ${SPACE[4]}px`,
        background: t.panel, border: `1px solid ${t.border}`, borderRadius: RADIUS[2],
        fontFamily: t.fontLabel, fontSize: 12, color: t.text, wordBreak: 'break-all',
      }}>{command}</code>
    </div>
  );
}
function CheckRowW({ t, check }) {
  return (
    <div data-check={check.name} data-ok={check.ok} style={{
      padding: `${SPACE[3]}px ${SPACE[4]}px`, background: t.panel,
      border: `1px solid ${check.ok ? t.border : t.statusAlarm}`, borderRadius: RADIUS[2],
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: SPACE[3] }}>
        <span style={{ marginTop: 2 }}>
          {check.ok ? <CheckW color={t.statusOk} size={14}/> : <FailW color={t.statusAlarm} size={14}/>}
        </span>
        <div>
          <div style={{ fontFamily: t.fontBody, fontSize: 13, fontWeight: 600,
                        color: check.ok ? t.text : t.statusAlarm }}>{check.name}</div>
          <div style={{ fontFamily: t.fontLabel, fontSize: 12, color: t.textMid, marginTop: 2,
                        wordBreak: 'break-all' }}>{check.detail}</div>
        </div>
      </div>
      {!check.ok && <HintW t={t} label="On the appliance console, run" command={check.hint}/>}
    </div>
  );
}

// ─── Shared step shell (title + blurb + children) ────────────────────
function StepShellW({ t, title, blurb, children }) {
  const isSov = t.name === 'sovereign';
  return (
    <div>
      <div style={{
        fontFamily: t.fontHeading, fontSize: 32,
        fontWeight: isSov ? 400 : 600,
        letterSpacing: isSov ? 0.8 : -0.3,
        textTransform: isSov ? 'uppercase' : 'none',
        color: t.text, lineHeight: 1.05,
      }}>{title}</div>
      {blurb && (
        <div style={{
          fontFamily: t.fontBody, fontSize: 14, color: t.textMid,
          marginTop: SPACE[3], maxWidth: 640, lineHeight: 1.55,
        }}>{blurb}</div>
      )}
      <div style={{ marginTop: SPACE[5] }}>{children}</div>
    </div>
  );
}

// ─── Theme toggle ───────────────────────────────────────────────────
function ThemeToggleW({ t, isDark, onToggle }) {
  return (
    <button onClick={onToggle}
      title={isDark ? 'Switch to light' : 'Switch to dark'}
      style={{
        appearance: 'none', cursor: 'pointer',
        width: 36, height: 36, padding: 0,
        background: t.surface,
        border: `1px solid ${t.border}`,
        borderRadius: RADIUS[2],
        display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
        color: t.textMid,
      }}>
      {isDark
        ? (
          // Sun
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={t.text}
               strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <circle cx="12" cy="12" r="4"/>
            <path d="M12 2 V4 M12 20 V22 M4.93 4.93 L6.34 6.34 M17.66 17.66 L19.07 19.07 M2 12 H4 M20 12 H22 M4.93 19.07 L6.34 17.66 M17.66 6.34 L19.07 4.93"/>
          </svg>
        ) : (
          // Moon
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke={t.text}
               strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12.8 A9 9 0 1 1 11.2 3 a7 7 0 0 0 9.8 9.8 Z"/>
          </svg>
        )}
    </button>
  );
}

// ─── Top header ─────────────────────────────────────────────────────
function HeaderW({ t, steps, deployment, current, isDark, onToggleTheme }) {
  const isSov = t.name === 'sovereign';
  const idx = steps.findIndex(s => s.id === current);
  const isPreflight = current === 'preflight';
  return (
    <div style={{
      padding: `${SPACE[4]}px ${SPACE[6]}px`,
      borderBottom: `1px solid ${t.border}`,
      display: 'flex', alignItems: 'center', gap: SPACE[4],
      background: t.bg,
    }}>
      <div style={{
        width: 36, height: 36, borderRadius: RADIUS[2],
        background: t.accent,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2.2">
          <path d="M4 18 L12 4 L20 18 M7 14 H17"/>
        </svg>
      </div>
      <div style={{ flex: 1 }}>
        <div style={{
          fontFamily: t.fontHeading, fontSize: 18,
          fontWeight: isSov ? 400 : 600,
          letterSpacing: isSov ? 1.4 : 0,
          textTransform: isSov ? 'uppercase' : 'none',
          color: t.text, lineHeight: 1,
        }}>ARCNODE</div>
        <div style={{
          fontFamily: t.fontLabel, fontSize: 10,
          letterSpacing: 0.22, textTransform: 'uppercase',
          color: t.textSoft, marginTop: 3, fontWeight: 700,
        }}>First-boot setup</div>
      </div>
      {deployment && (
        <span data-deployment={deployment} style={{
          padding: '4px 10px', border: `1px solid ${t.borderSoft}`, borderRadius: 999,
          fontFamily: t.fontLabel, fontSize: 10, fontWeight: 700, letterSpacing: 0.2,
          color: t.textMid, textTransform: 'uppercase',
        }}>{deployment}</span>
      )}
      <div style={{
        fontFamily: t.fontLabel, fontSize: 11, fontWeight: 700, letterSpacing: 0.2,
        color: t.textSoft, textTransform: 'uppercase',
      }}>
        {isPreflight
          ? 'Preflight'
          : steps.length > 0 && <>Step <span style={{ color: t.text }}>{idx + 1}</span> of {steps.length}</>}
      </div>
      {onToggleTheme && (
        <ThemeToggleW t={t} isDark={isDark} onToggle={onToggleTheme}/>
      )}
    </div>
  );
}

// ─── Footer (Back / Continue) ───────────────────────────────────────
function FooterW({ t, steps, current, stepVerified, onBack, onNext }) {
  const idx = steps.findIndex(s => s.id === current);
  const isPreflight = current === 'preflight';
  // Preflight isn't in `steps` (the rail shows it above the count); with no
  // steps after it (cloud, today) it's the last page.
  const isLast = isPreflight ? steps.length === 0 : idx === steps.length - 1;
  const isDone = isLast && stepVerified;
  const nextLabel = isPreflight ? 'Begin setup' : 'Continue';

  const backDisabled = isPreflight || idx === 0 || isDone;

  return (
    <div style={{
      padding: `${SPACE[4]}px ${SPACE[6]}px`,
      borderTop: `1px solid ${t.border}`,
      display: 'flex', alignItems: 'center', gap: SPACE[3],
      background: t.bg,
    }}>
      <button onClick={onBack} disabled={backDisabled}
        style={{
          appearance: 'none',
          cursor: backDisabled ? 'not-allowed' : 'pointer',
          height: 40, padding: '0 16px',
          background: 'transparent',
          border: `1px solid ${t.border}`,
          borderRadius: RADIUS[2],
          fontFamily: t.fontLabel, fontSize: 11, fontWeight: 700, letterSpacing: 0.18,
          color: backDisabled ? t.textFaint : t.text,
          textTransform: 'uppercase',
          display: 'inline-flex', alignItems: 'center', gap: 6,
        }}>
        <ChevronW color={backDisabled ? t.textFaint : t.text} size={12} dir="left"/>
        Back
      </button>
      <span style={{ flex: 1 }}/>

      {/* contextual hint */}
      <span style={{
        fontFamily: t.fontLabel, fontSize: 10, color: t.textSoft, letterSpacing: 0.1,
      }}>
        {isDone      ? 'Setup complete — this page is now turned off.'
         : isPreflight && !stepVerified ? 'Every hardware minimum is required.'
         : !stepVerified ? 'Continue unlocks once every check is green.'
         : isPreflight ? `Next · ${steps[0].title}`
         : `Next · ${steps[idx + 1]?.title}`}
      </span>

      {isDone ? (
        <button disabled style={primaryBtnStyle(t, true)}>
          <CheckW color="#fff" size={13}/>
          Complete
        </button>
      ) : (
        <button onClick={!stepVerified ? undefined : onNext}
          disabled={!stepVerified}
          style={primaryBtnStyle(t, !stepVerified)}>
          {nextLabel}
          <ChevronW color="#fff" size={12}/>
        </button>
      )}
    </div>
  );
}
// FastAPI's 422 body is {detail: [{loc, msg, ...}, ...]} — a plain string
// detail (e.g. the 404 "already applied" case) also reaches here, so
// handle both rather than assuming one shape.
function formatApplyError(detail) {
  if (!detail) return null;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((e) => `${Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : 'field'}: ${e.msg}`)
      .join('; ');
  }
  return null;
}
function primaryBtnStyle(t, disabled) {
  return {
    appearance: 'none', cursor: disabled ? 'not-allowed' : 'pointer',
    height: 40, padding: '0 18px',
    background: disabled ? t.accentDim : t.accent,
    border: `1px solid ${disabled ? t.accentDim : t.accent}`,
    color: '#fff',
    borderRadius: RADIUS[2],
    display: 'inline-flex', alignItems: 'center', gap: 8,
    fontFamily: t.fontLabel, fontSize: 11, fontWeight: 700, letterSpacing: 0.18,
    textTransform: 'uppercase',
    opacity: disabled ? 0.85 : 1,
  };
}

// ─── Main wizard body ───────────────────────────────────────────────
function SetupWizardBody({ t, isDark, onToggleTheme }) {
  // { deployment: 'cloud' | 'on-prem', account, completed } from GET /api/config
  const [setup, setSetup] = useStateW(null);
  const [current, setCurrent] = useStateW(null);
  const [completed, setCompleted] = useStateW(new Set());
  // Per page: { state: idle | applying | done | unverified | error, error, result }
  const [pages, setPages] = useStateW({});
  const [sshKey, setSshKey] = useStateW('');
  const [pgPassword, setPgPassword] = useStateW('');
  const [neo4jPassword, setNeo4jPassword] = useStateW('');
  // { [model]: latest download progress } while the Ollama page streams
  const [downloads, setDownloads] = useStateW({});

  useEffectW(() => {
    fetch('/api/config').then(r => r.json()).then(setSetup);
  }, []);
  const steps = setup ? ALL_STEPS.filter(s => s.deployments.includes(setup.deployment)) : [];
  // Page order: the hardware check, then this deployment's steps.
  const order = ['preflight', ...steps.map(s => s.id)];
  // Resume where setup left off: done pages from the server, first unfinished page current.
  useEffectW(() => {
    if (!setup) return;
    setCompleted(new Set(setup.completed));
    setCurrent(order.find(id => !setup.completed.includes(id)) || order[order.length - 1]);
  }, [setup]);

  const pageOf = (id) => pages[id] || { state: completed.has(id) ? 'done' : 'idle', error: null, result: null };
  const setPage = (id, patch) => setPages(p => ({ ...p, [id]: { ...pageOf(id), ...p[id], ...patch } }));

  const applyStep = (id, url, payload) => {
    setPage(id, { state: 'applying', error: null });
    fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(async (r) => {
        const body = await r.json().catch(() => ({}));
        if (!r.ok) throw new Error(formatApplyError(body.detail) || `HTTP ${r.status}`);
        setPage(id, { state: body.verified ? 'done' : 'unverified', result: body });
        if (body.verified) setCompleted(s => new Set([...s, id]));
      })
      .catch((err) => setPage(id, { state: 'error', error: String(err.message || err) }));
  };

  const applyOllama = () => {
    setPage('ollama', { state: 'applying', error: null });
    setDownloads({});
    streamOllama(progress => setDownloads(d => ({
      ...d, [progress.model]: nextDownload(d[progress.model], progress, Date.now()),
    })))
      .then((body) => {
        setPage('ollama', { state: body.verified ? 'done' : 'unverified', result: body });
        if (body.verified) setCompleted(s => new Set([...s, 'ollama']));
      })
      .catch((err) => setPage('ollama', { state: 'error', error: String(err.message || err) }));
  };

  const onNext = () => {
    const idx = order.indexOf(current);
    if (idx < order.length - 1) setCurrent(order[idx + 1]);
  };
  const onBack = () => {
    const idx = order.indexOf(current);
    if (idx > 0) setCurrent(order[idx - 1]);
  };
  const onJump = (id) => setCurrent(id);

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      background: t.bg,
      fontFamily: t.fontBody, color: t.text,
      minHeight: '100%',
    }}>
      <HeaderW t={t} steps={steps} deployment={setup?.deployment} current={current}
        isDark={isDark} onToggleTheme={onToggleTheme}/>
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <StepRailW t={t} steps={steps} current={current} completed={completed} onJump={onJump}/>
        <div style={{
          flex: 1,
          padding: `${SPACE[6]}px ${SPACE[8]}px ${SPACE[6]}px`,
          overflowY: 'auto',
          maxWidth: 820,
        }}>
          {current === 'preflight' && (
            <StepPreflight t={t} page={pageOf('preflight')}
              onApply={() => applyStep('preflight', '/api/preflight', {})}/>
          )}
          {current === 'ssh' && (
            <StepSsh t={t} setup={setup} sshKey={sshKey} onKey={setSshKey} page={pageOf('ssh')}
              onApply={() => applyStep('ssh', '/api/ssh', { ssh_public_key: sshKey })}/>
          )}
          {current === 'docker' && (
            <StepDocker t={t} page={pageOf('docker')}
              onApply={() => applyStep('docker', '/api/docker', {})}/>
          )}
          {current === 'postgres' && (
            <StepPostgres t={t} page={pageOf('postgres')} password={pgPassword} onPassword={setPgPassword}
              onApply={() => applyStep('postgres', '/api/postgres', { password: pgPassword })}/>
          )}
          {current === 'neo4j' && (
            <StepNeo4j t={t} page={pageOf('neo4j')} password={neo4jPassword} onPassword={setNeo4jPassword}
              onApply={() => applyStep('neo4j', '/api/neo4j', { password: neo4jPassword })}/>
          )}
          {current === 'ollama' && (
            <StepOllama t={t} page={pageOf('ollama')} downloads={downloads} onApply={applyOllama}/>
          )}
        </div>
      </div>
      {setup && (
        <FooterW t={t} steps={steps} current={current} stepVerified={completed.has(current)}
          onBack={onBack} onNext={onNext}/>
      )}
    </div>
  );
}

window.SetupWizardBody = SetupWizardBody;

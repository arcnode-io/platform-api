// daemon-pages.jsx — wizard pages after SSH, one per daemon (Docker,
// PostgreSQL, Neo4j): input + Install & verify + check rows on the same page. Shared pieces
// (StepShellW, FieldLabelW, HelperW, HintW, CheckRowW, SpinnerW,
// primaryBtnStyle, WIZARD_LOG_HINT) live in setup-wizard.jsx.

const { useState: useStateD } = React;

function EyeW({ color, size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12 C 4 5, 20 5, 23 12 C 20 19, 4 19, 1 12 Z"/>
      <circle cx="12" cy="12" r="3"/>
    </svg>
  );
}
function EyeOffW({ color, size = 16 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12 C 4 5, 20 5, 23 12 C 20 19, 4 19, 1 12 Z"/>
      <circle cx="12" cy="12" r="3"/>
      <path d="M3 3 L21 21"/>
    </svg>
  );
}

// Same policy as PasswordRequest in wizard_record.py — the backend is the
// source of truth; this only keeps a non-compliant password from a round trip.
function passwordProblem(pw) {
  if (pw.length < 8) return 'At least 8 characters.';
  if (!/[A-Z]/.test(pw)) return 'Add an uppercase letter.';
  if (!/\d/.test(pw)) return 'Add a number.';
  if (!/[^A-Za-z0-9]/.test(pw)) return 'Add a special character.';
  return null;
}

function PasswordInputW({ t, label, value, onChange, disabled, error }) {
  const [visible, setVisible] = useStateD(false);
  return (
    <div style={{ position: 'relative' }}>
      <input type={visible ? 'text' : 'password'} value={value} disabled={disabled}
        onChange={e => onChange(e.target.value)} aria-label={label}
        style={{
          width: '100%', height: 40, padding: '0 40px 0 12px', boxSizing: 'border-box',
          background: t.bg, color: t.text, outline: 'none',
          border: `1px solid ${error ? t.statusAlarm : t.border}`, borderRadius: RADIUS[2],
          fontFamily: t.fontLabel, fontSize: 13,
        }}/>
      <button type="button" onClick={() => setVisible(v => !v)}
        aria-label={visible ? 'Hide password' : 'Show password'}
        style={{
          position: 'absolute', right: 10, top: 0, height: 40, padding: 0,
          background: 'transparent', border: 'none', cursor: 'pointer',
          display: 'flex', alignItems: 'center',
        }}>
        {visible ? <EyeOffW color={t.textSoft}/> : <EyeW color={t.textSoft}/>}
      </button>
    </div>
  );
}

// ─── Docker ──────────────────────────────────────────────────────────
// No input: the page creates the arcnode network and Docker picks its
// address range. Later pages (PostgreSQL) trust whatever range it reports.
function StepDocker({ t, page, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Install & verify';
  return (
    <StepShellW t={t} title="Docker"
      blurb="ArcNode's services run as containers. This creates the network they share and proves a container can start on it. Docker picks the network's address range; the database only accepts connections from that range.">
      {!isDone && (
        <button onClick={isApplying ? undefined : onApply} disabled={isApplying}
          style={primaryBtnStyle(t, isApplying)}>
          {isApplying && <SpinnerW color="#fff" size={13}/>}
          {buttonLabel}
        </button>
      )}
      {page.state === 'error' && (
        <div style={{ marginTop: SPACE[4] }}>
          <HelperW t={t} error>Failed: {page.error}</HelperW>
          <HintW t={t} label="See the wizard's own log, on the appliance console" command={WIZARD_LOG_HINT}/>
        </div>
      )}
      {page.result && !isApplying && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: SPACE[3], marginTop: SPACE[5] }}>
          {page.result.checks.map(check => <CheckRowW key={check.name} t={t} check={check}/>)}
        </div>
      )}
    </StepShellW>
  );
}

window.StepDocker = StepDocker;

// ─── Password pages (PostgreSQL, Neo4j) ──────────────────────────────
// Same shape: the daemon's admin password, Install & verify, check rows.
function StepPassword({ t, title, blurb, label, page, password, onPassword, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const problem    = password ? passwordProblem(password) : null;
  const canApply   = !isApplying && !isDone && password !== '' && !problem;
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Install & verify';
  return (
    <StepShellW t={t} title={title} blurb={blurb}>
      <div style={{ marginBottom: SPACE[4] }}>
        <FieldLabelW t={t} required>{label}</FieldLabelW>
        <PasswordInputW t={t} label={label} value={password} onChange={onPassword}
          disabled={isApplying || isDone} error={!!problem}/>
        <HelperW t={t} error={!!problem}>
          {problem || 'At least 8 characters with an uppercase letter, a number, and a special character.'}
        </HelperW>
      </div>
      {!isDone && (
        <button onClick={canApply ? onApply : undefined} disabled={!canApply}
          style={primaryBtnStyle(t, !canApply)}>
          {isApplying && <SpinnerW color="#fff" size={13}/>}
          {buttonLabel}
        </button>
      )}
      {page.state === 'error' && (
        <div style={{ marginTop: SPACE[4] }}>
          <HelperW t={t} error>Failed: {page.error}</HelperW>
          <HintW t={t} label="See the wizard's own log, on the appliance console" command={WIZARD_LOG_HINT}/>
        </div>
      )}
      {page.result && !isApplying && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: SPACE[3], marginTop: SPACE[5] }}>
          {page.result.checks.map(check => <CheckRowW key={check.name} t={t} check={check}/>)}
        </div>
      )}
    </StepShellW>
  );
}

function StepPostgres(props) {
  return <StepPassword {...props} title="PostgreSQL" label="Postgres password"
    blurb="Set the password for the postgres admin account. ArcNode's services use it to reach the database, which only accepts connections from this box and its Docker containers."/>;
}

function StepNeo4j(props) {
  return <StepPassword {...props} title="Neo4j" label="Neo4j password"
    blurb="Set the password for the neo4j admin account. ArcNode's services use it to reach the knowledge graph, which only listens on the network shared with its Docker containers. Neo4j gets a fixed 4 GB heap + 4 GB page cache."/>;
}

window.StepPostgres = StepPostgres;
window.StepNeo4j = StepNeo4j;

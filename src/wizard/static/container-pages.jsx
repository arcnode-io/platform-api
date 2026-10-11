// container-pages.jsx — the pages after the daemons: the order's site, then
// one page per EMS container. Shared pieces (StepShellW, HelperW, HintW,
// CheckRowW, SpinnerW, primaryBtnStyle, WIZARD_LOG_HINT) live in
// setup-wizard.jsx.

// ─── Site ────────────────────────────────────────────────────────────
// No input: the per-order ISO carried the order's site + device topology.
// This hands them to the EMS containers; nothing to type, nothing to mistype.
function StepSite({ t, page, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Install & verify';
  return (
    <StepShellW t={t} title="Site"
      blurb="Your site's name, wholesale market and devices came with this box's installer, straight from your order. This saves them for the EMS containers that run next.">
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

window.StepSite = StepSite;

// ─── HiveMQ ──────────────────────────────────────────────────────────
// One password per broker account. The EMS services log in with these, so
// the page takes all six before it starts the broker.
// The four EMS services share one service password; operator and viewer are people.
const BROKER_ACCOUNTS = [
  { key: 'service',  label: 'Service password (gateway, Device API, telemetry, DER control)' },
  { key: 'operator', label: 'Operator' },
  { key: 'viewer',   label: 'Viewer' },
];

function StepHivemq({ t, page, passwords, onPassword, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const allFilled  = BROKER_ACCOUNTS.every(a => passwords[a.key]);
  const anyProblem = BROKER_ACCOUNTS.some(a => passwords[a.key] && passwordProblem(passwords[a.key]));
  const canApply   = !isApplying && !isDone && allFilled && !anyProblem;
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Install & verify';
  return (
    <StepShellW t={t} title="HiveMQ"
      blurb="Set one password for each account that connects to the MQTT broker. The EMS services log in with these, and each account can only do what its job needs.">
      {BROKER_ACCOUNTS.map(a => {
        const value   = passwords[a.key] || '';
        const problem = value ? passwordProblem(value) : null;
        return (
          <div key={a.key} style={{ marginBottom: SPACE[4] }}>
            <FieldLabelW t={t} required>{a.label}</FieldLabelW>
            <PasswordInputW t={t} label={a.label} value={value}
              onChange={v => onPassword(a.key, v)}
              disabled={isApplying || isDone} error={!!problem}/>
            {problem && <HelperW t={t} error>{problem}</HelperW>}
          </div>
        );
      })}
      <HelperW t={t}>At least 8 characters with an uppercase letter, a number, and a special character.</HelperW>
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


// ─── Telemetry writer ────────────────────────────────────────────────
// No input: it reuses the broker password and the database URL the earlier pages saved.
function StepTelemetry({ t, page, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Start & verify';
  return (
    <StepShellW t={t} title="Telemetry writer"
      blurb="Starts the service that saves every measurement from the broker into the timeseries database. It needs the HiveMQ and PostgreSQL pages finished first.">
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


// ─── Prometheus ─────────────────────────────────────────────────────────
// No input: it fetches the same scrape config as the cloud, then starts Prometheus.
function StepPrometheus({ t, page, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Start & verify';
  return (
    <StepShellW t={t} title="Prometheus"
      blurb="it fetches the same scrape config as the cloud, then starts Prometheus.">
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

// ─── MLflow ─────────────────────────────────────────────────────────
// No input: it starts the experiment tracker the analyst model logs its forecasts to.
function StepMlflow({ t, page, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Start & verify';
  return (
    <StepShellW t={t} title="MLflow"
      blurb="it starts the experiment tracker the analyst model logs its forecasts to.">
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


// ─── Device API ──────────────────────────────────────────────────────
// The signing key and the two login passwords the Device API checks against.
function StepDeviceApi({ t, page, secrets, onSecret, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const jwtOk      = secrets.jwt_secret && secrets.jwt_secret.length >= 32;
  const opProblem  = secrets.operator_password ? passwordProblem(secrets.operator_password) : null;
  const viProblem  = secrets.viewer_password ? passwordProblem(secrets.viewer_password) : null;
  const canApply   = !isApplying && !isDone && jwtOk && secrets.operator_password && secrets.viewer_password && !opProblem && !viProblem;
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Install & verify';
  return (
    <StepShellW t={t} title="Device API"
      blurb="The signing key that logs people in to the HMI, plus the operator and viewer passwords. The Device API serves your site's topology and checks these logins.">
      <div style={{ marginBottom: SPACE[4] }}>
        <FieldLabelW t={t} required>JWT signing key</FieldLabelW>
        <PasswordInputW t={t} label="JWT signing key" value={secrets.jwt_secret || ''}
          onChange={v => onSecret('jwt_secret', v)} disabled={isApplying || isDone}
          error={!!secrets.jwt_secret && !jwtOk}/>
        <HelperW t={t} error={!!secrets.jwt_secret && !jwtOk}>At least 32 characters.</HelperW>
      </div>
      <div style={{ marginBottom: SPACE[4] }}>
        <FieldLabelW t={t} required>Operator password</FieldLabelW>
        <PasswordInputW t={t} label="Operator password" value={secrets.operator_password || ''}
          onChange={v => onSecret('operator_password', v)} disabled={isApplying || isDone} error={!!opProblem}/>
        {opProblem && <HelperW t={t} error>{opProblem}</HelperW>}
      </div>
      <div style={{ marginBottom: SPACE[4] }}>
        <FieldLabelW t={t} required>Viewer password</FieldLabelW>
        <PasswordInputW t={t} label="Viewer password" value={secrets.viewer_password || ''}
          onChange={v => onSecret('viewer_password', v)} disabled={isApplying || isDone} error={!!viProblem}/>
        {viProblem && <HelperW t={t} error>{viProblem}</HelperW>}
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

window.StepHivemq = StepHivemq;
window.StepTelemetry = StepTelemetry;
window.StepPrometheus = StepPrometheus;
window.StepMlflow = StepMlflow;
// ─── Analyst model ──────────────────────────────────────────────────────────────
// No input: it starts the model that trains and publishes the daily price forecast to MLflow.
function StepAnalystModel({ t, page, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Start & verify';
  return (
    <StepShellW t={t} title="Analyst model"
      blurb="it starts the model that trains and publishes the daily price forecast to MLflow.">
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
window.StepAnalystModel = StepAnalystModel;
window.StepDeviceApi = StepDeviceApi;

// ─── Industrial gateway ─────────────────────────────────────────────────────────
// No input: it starts the gateway that bridges your devices onto the broker. It fetches the device spec and subscribes to the broker.
function StepIndustrialGateway({ t, page, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Start & verify';
  return (
    <StepShellW t={t} title="Industrial gateway" blurb="it starts the gateway that bridges your devices onto the broker. It fetches the device spec and subscribes to the broker.">
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

// ─── HMI ─────────────────────────────────────────────────────────
// No input: it starts the operator screen on port 80, served to the browsers on this box.
function StepHmi({ t, page, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Start & verify';
  return (
    <StepShellW t={t} title="HMI" blurb="it starts the operator screen on port 80, served to the browsers on this box.">
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

window.StepIndustrialGateway = StepIndustrialGateway;
window.StepHmi = StepHmi;

// ─── Analyst server ─────────────────────────────────────────────────────────────
// Two API keys, then it starts the server the analyst chat talks to.
const ANALYST_SERVER_FIELDS = [
  { key: 'openweathermap_api_key', label: 'OpenWeatherMap API key' },
  { key: 'gridstatus_api_key', label: 'GridStatus API key' },
];

function StepAnalystServer({ t, page, keys, onKey, onApply }) {
  const isApplying = page.state === 'applying';
  // Stage updates arrive on the apply request's stream.
  const stages = page.stages;
  const isDone     = page.state === 'done';
  const allFilled  = ANALYST_SERVER_FIELDS.every(f => (keys[f.key] || '').length >= 8);
  const canApply   = !isApplying && !isDone && allFilled;
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Start & verify';
  return (
    <StepShellW t={t} title="Analyst server"
      blurb="it starts the server the analyst chat talks to. It needs two API keys: one for weather, one for market prices.">
      {ANALYST_SERVER_FIELDS.map(f => (
        <div key={f.key} style={{ marginBottom: SPACE[4] }}>
          <FieldLabelW t={t} required>{f.label}</FieldLabelW>
          <PasswordInputW t={t} label={f.label} value={keys[f.key] || ''}
            onChange={v => onKey(f.key, v)} disabled={isApplying || isDone}/>
        </div>
      ))}
      <HelperW t={t}>At least 8 characters.</HelperW>
      {!isDone && (
        <button onClick={canApply ? onApply : undefined} disabled={!canApply}
          style={primaryBtnStyle(t, !canApply)}>
          {isApplying && <SpinnerW color="#fff" size={13}/>}
          {buttonLabel}
        </button>
      )}
      {isApplying && stages && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: SPACE[2], marginTop: SPACE[4] }}>
          {stages.map(stage => (
            <div key={stage.label} style={{ fontSize: 13, color: stage.done ? t.statusOk : t.textSoft }}>
              {stage.done ? '✓' : '…'} {stage.label}{stage.percent != null ? ` — ${stage.percent}%` : ''}{stage.eta_seconds != null ? ` · about ${Math.max(1, Math.round(stage.eta_seconds / 60))} min left` : ''}
            </div>
          ))}
        </div>
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
window.StepAnalystServer = StepAnalystServer;

// ─── DER control API ────────────────────────────────────────────────────────────
// Optional: the DERMS base URL the utility gives. Blank means the utility isn't connected yet.
const DER_PEM_FIELDS = [
  { key: 'device_cert_pem', label: 'DEVICE CERTIFICATE (PEM, OPTIONAL)' },
  { key: 'device_key_pem', label: 'DEVICE PRIVATE KEY (PEM, OPTIONAL)' },
  { key: 'utility_ca_pem', label: 'UTILITY CA BUNDLE (PEM, OPTIONAL)' },
];

function StepDerControl({ t, page, url, onUrl, lfdis, onLfdis, pems, onPem, onApply, onSkip }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const badUrl     = url !== '' && !url.startsWith('https://');
  const canApply   = !isApplying && !isDone && !badUrl;
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Save & verify';
  return (
    <StepShellW t={t} title="DER control API"
      blurb="it receives the utility's DER controls. Give the utility's base URL if you have it; you can leave it blank and add it later.">
      <FieldLabelW t={t}>UTILITY BASE URL</FieldLabelW>
      <input type="text" value={url} disabled={isApplying || isDone} placeholder="https://derms.utility.example"
        onChange={e => onUrl(e.target.value)} aria-label="Utility base URL"
        style={{
          width: '100%', height: 40, padding: '0 12px', boxSizing: 'border-box',
          background: t.bg, color: t.text, outline: 'none',
          border: `1px solid ${badUrl ? t.statusAlarm : t.border}`, borderRadius: RADIUS[2],
          fontFamily: t.fontLabel, fontSize: 13,
        }}/>
      {badUrl && <HelperW t={t} error>Must start with https://</HelperW>}
      <FieldLabelW t={t}>ALLOWED DEVICE IDS (OPTIONAL)</FieldLabelW>
      <input type="text" value={lfdis} disabled={isApplying || isDone} placeholder="40 hex characters each, comma or space separated"
        onChange={e => onLfdis(e.target.value)} aria-label="Allowed device IDs"
        style={{
          width: '100%', height: 40, padding: '0 12px', boxSizing: 'border-box', marginBottom: SPACE[4],
          background: t.bg, color: t.text, outline: 'none',
          border: `1px solid ${t.border}`, borderRadius: RADIUS[2],
          fontFamily: t.fontLabel, fontSize: 13,
        }}/>
      {DER_PEM_FIELDS.map(f => (
        <div key={f.key} style={{ marginBottom: SPACE[4] }}>
          <FieldLabelW t={t}>{f.label}</FieldLabelW>
          <textarea value={pems[f.key] || ''} disabled={isApplying || isDone} rows={4}
            onChange={e => onPem(f.key, e.target.value)} aria-label={f.label}
            style={{
              width: '100%', boxSizing: 'border-box', padding: 12, background: t.bg, color: t.text,
              border: `1px solid ${t.border}`, borderRadius: RADIUS[2], fontFamily: t.fontLabel, fontSize: 12,
            }}/>
        </div>
      ))}
      {!isDone && (
        <button onClick={canApply ? onApply : undefined} disabled={!canApply}
          style={{ ...primaryBtnStyle(t, !canApply), marginTop: SPACE[4] }}>
          {isApplying && <SpinnerW color="#fff" size={13}/>}
          {buttonLabel}
        </button>
      )}
      {!isDone && !isApplying && (
        <button onClick={onSkip} style={{ ...primaryBtnStyle(t, false), marginTop: SPACE[3], background: 'transparent', color: t.textSoft, border: `1px solid ${t.border}` }}>
          Skip for now
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
window.StepDerControl = StepDerControl;

// ─── Cloud passwords ────────────────────────────────────────────────────────────
// The cloud box's three customer passwords, the same ones on-prem asks for.
const CLOUD_SECRET_FIELDS = [
  { key: 'operator_password', label: 'Operator password' },
  { key: 'viewer_password', label: 'Viewer password' },
  { key: 'grafana_password', label: 'Grafana admin password' },
];

function StepCloudSecrets({ t, page, passwords, onPassword, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const allFilled  = CLOUD_SECRET_FIELDS.every(f => passwords[f.key]);
  const anyProblem = CLOUD_SECRET_FIELDS.some(f => passwords[f.key] && passwordProblem(passwords[f.key]));
  const canApply   = !isApplying && !isDone && allFilled && !anyProblem;
  const buttonLabel = isApplying ? 'Saving'
    : page.state === 'unverified' ? 'Try again' : 'Save & continue';
  return (
    <StepShellW t={t} title="Passwords"
      blurb="Set a password for each of these. The EMS services start once they're saved.">
      {CLOUD_SECRET_FIELDS.map(f => {
        const value   = passwords[f.key] || '';
        const problem = value ? passwordProblem(value) : null;
        return (
          <div key={f.key} style={{ marginBottom: SPACE[4] }}>
            <FieldLabelW t={t} required>{f.label}</FieldLabelW>
            <PasswordInputW t={t} label={f.label} value={value}
              onChange={v => onPassword(f.key, v)}
              disabled={isApplying || isDone} error={!!problem}/>
            {problem && <HelperW t={t} error>{problem}</HelperW>}
          </div>
        );
      })}
      <HelperW t={t}>At least 8 characters with an uppercase letter, a number, and a special character.</HelperW>
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
window.StepCloudSecrets = StepCloudSecrets;

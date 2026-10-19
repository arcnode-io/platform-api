// container-pages.jsx — the order's Site page (right after the hardware
// check) and one page per EMS container. Shared pieces (StepShellW, HelperW,
// HintW, CheckRowW, SpinnerW, primaryBtnStyle, WIZARD_LOG_HINT) live in
// setup-wizard.jsx.

// ─── Site ────────────────────────────────────────────────────────────
// No input: the per-order ISO carried the order's site + device topology.
// Read-only rows say whose order it is, so the customer stops here on the
// wrong ISO. Confirming hands the order to the EMS containers; nothing to
// type, nothing to mistype.
function StepSite({ t, page, info, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const rows = info ? [
    { label: 'Customer', value: info.customer },
    { label: 'Site', value: info.site },
    { label: 'Market', value: info.market },
    { label: 'Configurator order', value: info.order_id, mono: true },
  ] : [];
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'This is my site — confirm';
  return (
    <StepShellW t={t} title="Site"
      blurb="Make sure this is the installer built for your site. If anything below is wrong, stop here and contact your ARCNODE configurator. Confirming saves your site's name, wholesale market and devices for the EMS containers that run next.">
      {!info && !isDone && <SpinnerW color={t.accent} size={16}/>}
      {info && (
        <div style={{ background: t.panel, border: `1px solid ${t.border}`, borderRadius: RADIUS[3], overflow: 'hidden' }}>
          {rows.map((row, i) => (
            <div key={row.label} style={{
              display: 'grid', gridTemplateColumns: '180px 1fr', alignItems: 'center',
              padding: `${SPACE[3]}px ${SPACE[4]}px`,
              borderBottom: i < rows.length - 1 ? `1px solid ${t.border}` : 'none',
            }}>
              <span style={{ fontFamily: t.fontLabel, fontSize: 10, fontWeight: 500, letterSpacing: 0.18,
                color: t.textSoft, textTransform: 'uppercase' }}>{row.label}</span>
              <span style={{ fontFamily: row.mono ? t.fontLabel : t.fontBody, fontSize: 14, color: t.text }}>
                {row.value || '—'}
              </span>
            </div>
          ))}
        </div>
      )}
      {info && !isDone && (
        <button onClick={isApplying ? undefined : onApply} disabled={isApplying}
          style={{ ...primaryBtnStyle(t, isApplying), marginTop: SPACE[5] }}>
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
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
// Three passwords, taken before the broker starts. The four EMS services share
// one service password; operator and viewer are people, and each one's password
// is both their HMI login and their broker account (one password per role), so
// the Device API page asks for neither.
const BROKER_ACCOUNTS = [
  { key: 'service',  label: 'Service password (gateway, Device API, telemetry, DER control)' },
  { key: 'operator', label: 'Operator password (HMI login and broker)' },
  { key: 'viewer',   label: 'Viewer password (HMI login and broker)' },
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
      blurb="Set one password for the EMS services and one each for the operator and viewer. The operator and viewer passwords log them in to the HMI and to the MQTT broker, and each account can only do what its job needs.">
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
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
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
// One input, how long measurements are kept; the broker password and the
// database URL come from the earlier pages.
function StepTelemetry({ t, page, retentionDays, onRetentionDays, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const badDays    = !/^[1-9]\d*$/.test(retentionDays);
  const canApply   = !isApplying && !isDone && !badDays;
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Start & verify';
  return (
    <StepShellW t={t} title="Telemetry writer"
      blurb="Starts the service that saves every measurement from the broker into the timeseries database. It needs the HiveMQ and PostgreSQL pages finished first.">
      <FieldLabelW t={t} required>DAYS OF TELEMETRY TO KEEP</FieldLabelW>
      <input type="text" inputMode="numeric" value={retentionDays} disabled={isApplying || isDone}
        onChange={e => onRetentionDays(e.target.value)} aria-label="Days of telemetry to keep"
        style={{
          width: 120, height: 40, padding: '0 12px', boxSizing: 'border-box',
          background: t.bg, color: t.text, outline: 'none',
          border: `1px solid ${badDays ? t.statusAlarm : t.border}`, borderRadius: RADIUS[2],
          fontFamily: t.fontLabel, fontSize: 13,
        }}/>
      <div style={{ marginBottom: SPACE[4] }}>
        <HelperW t={t} error={badDays}>
          {badDays ? 'A whole number of days, 1 or more.'
            : 'Older measurements are deleted to keep the disk from filling.'}
        </HelperW>
      </div>
      {!isDone && (
        <button onClick={canApply ? onApply : undefined} disabled={!canApply}
          style={primaryBtnStyle(t, !canApply)}>
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
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
      blurb="It fetches the same scrape config as the cloud, then starts Prometheus.">
      {!isDone && (
        <button onClick={isApplying ? undefined : onApply} disabled={isApplying}
          style={primaryBtnStyle(t, isApplying)}>
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
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
      blurb="It starts the experiment tracker the analyst model logs its forecasts to.">
      {!isDone && (
        <button onClick={isApplying ? undefined : onApply} disabled={isApplying}
          style={primaryBtnStyle(t, isApplying)}>
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
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
// The signing key only: the operator and viewer passwords it checks logins
// against were set on the HiveMQ page (one password per role).
function StepDeviceApi({ t, page, secrets, onSecret, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const jwtOk      = secrets.jwt_secret && secrets.jwt_secret.length >= 32;
  const canApply   = !isApplying && !isDone && jwtOk;
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Install & verify';
  return (
    <StepShellW t={t} title="Device API"
      blurb="The key that signs HMI sessions. The Device API serves your site's topology and checks logins against the operator and viewer passwords you set on the HiveMQ page.">
      <div style={{ marginBottom: SPACE[4] }}>
        <FieldLabelW t={t} required>JWT signing key</FieldLabelW>
        <PasswordInputW t={t} label="JWT signing key" value={secrets.jwt_secret || ''}
          onChange={v => onSecret('jwt_secret', v)} disabled={isApplying || isDone}
          error={!!secrets.jwt_secret && !jwtOk}/>
        <HelperW t={t} error={!!secrets.jwt_secret && !jwtOk}>At least 32 characters.</HelperW>
      </div>
      {!isDone && (
        <button onClick={canApply ? onApply : undefined} disabled={!canApply}
          style={primaryBtnStyle(t, !canApply)}>
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
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
      blurb="It starts the model that trains and publishes the daily price forecast to MLflow.">
      {!isDone && (
        <button onClick={isApplying ? undefined : onApply} disabled={isApplying}
          style={primaryBtnStyle(t, isApplying)}>
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
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
    <StepShellW t={t} title="Industrial gateway" blurb="It starts the gateway that bridges your devices onto the broker. It fetches the device spec and subscribes to the broker.">
      {!isDone && (
        <button onClick={isApplying ? undefined : onApply} disabled={isApplying}
          style={primaryBtnStyle(t, isApplying)}>
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
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
// No input: it starts the operator screen on port 80, plain HTTP at this box's address.
function StepHmi({ t, page, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Start & verify';
  return (
    <StepShellW t={t} title="HMI" blurb={`it starts the operator screen at http://${window.location.hostname}/`}>
      {!isDone && (
        <button onClick={isApplying ? undefined : onApply} disabled={isApplying}
          style={primaryBtnStyle(t, isApplying)}>
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
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

// What one analyst stage's row shows. Seeds download a dump, then import it; the
// analyst reports the download, and the import only if it logs `seed import:` lines.
// With no number to quote the bar sweeps and the text says so, rather than sit at 100%.
function seedRow(stage, isCurrent) {
  const left = stage.eta_seconds != null ? ` · about ${formatDuration(stage.eta_seconds)} left` : '';
  if (stage.phase === 'done') return { detail: 'Done', fraction: 1 };
  if (stage.phase === 'downloading') {
    const sizes = stage.mib_total != null ? `${stage.mib_done} of ${stage.mib_total} MB · ` : '';
    return { detail: `Downloading · ${sizes}${stage.percent}%${left}`, fraction: stage.percent / 100 };
  }
  if (stage.phase === 'importing') {
    return stage.percent != null
      ? { detail: `Importing · ${stage.percent}%${left}`, fraction: stage.percent / 100 }
      : { detail: "Importing into the database — progress is not reported, this can take several minutes", fraction: null };
  }
  return isCurrent ? { detail: 'Working…', fraction: null } : { detail: 'Waiting', fraction: 0 };
}

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
      blurb="It starts the server the analyst chat talks to. It needs two API keys: one for weather, one for market prices.">
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
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
          {buttonLabel}
        </button>
      )}
      {isApplying && stages && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: SPACE[3], marginTop: SPACE[5] }}>
          {stages.map((stage, i) => {
            const row = seedRow(stage, i === stages.findIndex(s => !s.done));
            return <ProgressRowW key={stage.label} t={t} id={stage.label} label={stage.label}
              detail={row.detail} fraction={row.fraction} finished={stage.done}/>;
          })}
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
      blurb="It receives the utility's DER controls. Give the utility's base URL if you have it; you can leave it blank and add it later.">
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
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
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

// ─── SSH lockdown ────────────────────────────────────────────────
// The last page. Password SSH stayed on as the recovery path through setup;
// with the key proven, this turns it off. Unchecking is allowed, not recommended.
function StepSshLockdown({ t, page, checked, onChecked, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : (checked ? 'Turn off & verify' : 'Keep & finish');
  return (
    <StepShellW t={t} title="SSH lockdown" blurb="your key works, so password login can go. From here on, SSH to this box is by key only.">
      {!isDone && (
        <label style={{ display: 'flex', alignItems: 'center', gap: SPACE[3], marginBottom: SPACE[5], cursor: 'pointer' }}>
          <input type="checkbox" checked={checked} disabled={isApplying}
            onChange={e => onChecked(e.target.checked)}/>
          <span>Disable SSH password login</span>
          <span style={{ fontSize: 11, fontWeight: 500, letterSpacing: '0.04em', textTransform: 'uppercase',
            padding: '2px 6px', borderRadius: 4, background: t.accent + '12', color: t.accent }}>Recommended</span>
        </label>
      )}
      {!isDone && (
        <button onClick={isApplying ? undefined : onApply} disabled={isApplying}
          style={primaryBtnStyle(t, isApplying)}>
          {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
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


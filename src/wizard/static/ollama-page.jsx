// ollama-page.jsx — the Ollama page: Install & verify streams the model
// downloads (NDJSON from POST /api/ollama), each with a progress bar, speed
// and time left, then the check rows. Shared pieces (StepShellW, HelperW,
// HintW, CheckRowW, SpinnerW, primaryBtnStyle, WIZARD_LOG_HINT) live in
// setup-wizard.jsx.

// POST /api/ollama and feed each NDJSON line to onEvent; resolves with the
// page's final StepResult. Download speed is measured here, per model, from
// the first byte count seen for the layer being pulled.
async function streamOllama(onProgress) {
  const response = await fetch('/api/ollama', { method: 'POST' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(formatApplyError(body.detail) || `HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let result = null;
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split('\n');
    buffer = lines.pop();
    for (const line of lines.filter(Boolean)) {
      const event = JSON.parse(line);
      if (event.progress) onProgress(event.progress);
      if (event.result) result = event.result;
    }
  }
  if (!result) throw new Error('the download stopped before setup finished — Install & verify picks up where it left off');
  return result;
}

// Track one model's download: keeps where the current layer started so
// speed = bytes since then / seconds since then.
function nextDownload(prev, progress, now) {
  const sameLayer = prev && prev.total === progress.total && progress.completed != null;
  const start = sameLayer ? prev.start : { at: now, bytes: progress.completed || 0 };
  return { ...progress, start, now };
}

function formatBytes(n) {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`;
  return `${Math.round(n / 1e6)} MB`;
}

function formatDuration(seconds) {
  if (seconds < 90) return `${Math.max(1, Math.round(seconds))} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

function DownloadRowW({ t, model, download }) {
  const { status, completed, total, start, now } = download;
  const failed = status.startsWith('error');
  const finished = status === 'success';
  const fraction = finished ? 1 : total ? completed / total : 0;
  const seconds = (now - start.at) / 1000;
  const speed = seconds > 1 ? (completed - start.bytes) / seconds : 0;
  const detail = failed ? status
    : finished ? 'Downloaded'
    : total ? `${formatBytes(completed)} of ${formatBytes(total)}`
      + (speed > 0 ? ` · ${formatBytes(speed)}/s · about ${formatDuration((total - completed) / speed)} left` : '')
    : status;
  return (
    <div data-download={model} style={{
      padding: `${SPACE[3]}px ${SPACE[4]}px`, background: t.panel,
      border: `1px solid ${failed ? t.statusAlarm : t.border}`, borderRadius: RADIUS[2],
    }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: SPACE[3] }}>
        <span style={{ fontFamily: t.fontLabel, fontSize: 13, fontWeight: 600, color: t.text }}>{model}</span>
        <span style={{ fontFamily: t.fontLabel, fontSize: 12, color: failed ? t.statusAlarm : t.textMid }}>{detail}</span>
      </div>
      <div style={{ height: 6, marginTop: SPACE[2], background: t.bg, borderRadius: 3, overflow: 'hidden' }}>
        <div style={{
          height: '100%', width: `${Math.round(fraction * 100)}%`,
          background: failed ? t.statusAlarm : finished ? t.statusOk : t.accent,
          transition: 'width 0.3s',
        }}/>
      </div>
    </div>
  );
}

function StepOllama({ t, page, downloads, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const buttonLabel = isApplying ? 'Downloading + verifying'
    : page.state === 'unverified' || page.state === 'error' ? 'Try again' : 'Install & verify';
  const models = Object.keys(downloads);
  return (
    <StepShellW t={t} title="Ollama"
      blurb="Ollama runs ArcNode's AI models on this box, listening only on the network shared with its Docker containers. Install & verify downloads the chat and embedding models — tens of GB, so expect anywhere from several minutes to over an hour depending on this site's connection. Each model shows its speed and time left once it starts. Keep this page open; if the download is interrupted, Try again picks up where it left off.">
      {!isDone && (
        <button onClick={isApplying ? undefined : onApply} disabled={isApplying}
          style={primaryBtnStyle(t, isApplying)}>
          {isApplying && <SpinnerW color="#fff" size={13}/>}
          {buttonLabel}
        </button>
      )}
      {models.length > 0 && !isDone && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: SPACE[3], marginTop: SPACE[5] }}>
          {models.map(model => <DownloadRowW key={model} t={t} model={model} download={downloads[model]}/>)}
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

window.streamOllama = streamOllama;
window.nextDownload = nextDownload;
window.StepOllama = StepOllama;

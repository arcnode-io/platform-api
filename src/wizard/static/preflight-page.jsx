// preflight-page.jsx — the hardware check, the wizard's first page in
// every deployment. Hard block: no "continue anyway". Each failed row
// carries the console command that shows why (from preflight_verify.py).

function StepPreflight({ t, page, onApply }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const blocked    = page.state === 'unverified';
  const buttonLabel = isApplying ? 'Checking' : blocked ? 'Check again' : 'Check hardware';
  return (
    <StepShellW t={t} title="Hardware check"
      blurb="ArcNode runs its AI models on an NVIDIA GPU and keeps its telemetry on NVMe storage, so both are required, along with enough CPU and memory. Each row shows what this box has next to what it needs.">
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
      {blocked && !isApplying && (
        <div style={{ marginTop: SPACE[4] }}>
          <HelperW t={t} error>
            This box doesn't meet the minimums, and setup can't continue on it. Fix the
            red rows, or move to a server or instance that meets them, then check again.
          </HelperW>
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

window.StepPreflight = StepPreflight;

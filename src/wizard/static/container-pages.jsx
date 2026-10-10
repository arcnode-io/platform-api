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

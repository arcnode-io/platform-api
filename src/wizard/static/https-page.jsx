// https-page.jsx — the optional HTTPS certificate page. The box makes its key and a
// signing request; the customer's IT signs it with their own CA; the box installs
// the certificate. Shared pieces (StepShellW, FieldLabelW, HelperW, CheckRowW,
// SpinnerW, primaryBtnStyle) live in setup-wizard.jsx.

const HTTPS_INPUT_STYLE = (t, error) => ({
  width: '100%', boxSizing: 'border-box', background: t.bg, color: t.text, outline: 'none',
  border: `1px solid ${error ? t.statusAlarm : t.border}`, borderRadius: RADIUS[2],
  fontFamily: t.fontLabel, fontSize: 13,
});

// Mirrors SigningRequest's check: dot-separated DNS labels, not an IP address.
function hostnameProblem(name) {
  const labels = name.split('.');
  if (!labels.every(l => /^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/.test(l))) {
    return 'A DNS name like ems.plant.local.';
  }
  if (/^\d+$/.test(labels[labels.length - 1])) return 'A name, not an IP address.';
  return null;
}

function SectionW({ t, n, title, children }) {
  return (
    <div style={{ marginBottom: SPACE[5] }}>
      <div style={{ fontFamily: t.fontLabel, fontSize: 12, color: t.textMid, marginBottom: SPACE[2] }}>
        {n} · {title}
      </div>
      {children}
    </div>
  );
}

function StepHttps({ t, page, address, https, onHttps, onRequest, onApply, onSkip }) {
  const isApplying = page.state === 'applying';
  const isDone     = page.state === 'done';
  const locked     = isApplying || isDone;
  const nameIssue  = https.hostname ? hostnameProblem(https.hostname) : null;
  const canRequest = !locked && https.hostname && !nameIssue && !https.requesting;
  const canApply   = !locked && https.csr && https.certificate.includes('-----BEGIN CERTIFICATE-----');
  const buttonLabel = isApplying ? 'Verifying'
    : page.state === 'unverified' ? 'Try again' : 'Install & verify';
  const download = () => {
    const blob = new Blob([https.csr], { type: 'application/pkcs10' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${https.hostname}.csr`;
    link.click();
  };
  return (
    <StepShellW t={t} title="HTTPS certificate"
      blurb="Optional. Give the HMI a name your laptops already trust, so the browser shows a secure connection. Your IT signs it with your own certificate authority; nothing here contacts ArcNode. The private key is made on this box and never leaves it.">
      <SectionW t={t} n={1} title="BOX NAME ON YOUR NETWORK">
        <input type="text" value={https.hostname} disabled={locked || !!https.csr}
          placeholder="ems.plant.local" aria-label="Box name on your network"
          onChange={e => onHttps({ hostname: e.target.value.trim() })}
          style={{ ...HTTPS_INPUT_STYLE(t, !!nameIssue), height: 40, padding: '0 12px', maxWidth: 360 }}/>
        <HelperW t={t} error={!!nameIssue}>
          {nameIssue || `Your DNS must point this name at ${address || 'this box'}.`}
        </HelperW>
        {!https.csr && (
          <button onClick={canRequest ? onRequest : undefined} disabled={!canRequest}
            style={{ ...primaryBtnStyle(t, !canRequest), marginTop: SPACE[3] }}>
            {https.requesting && <SpinnerW color={t.onPrimary} size={13}/>}
            Create signing request
          </button>
        )}
      </SectionW>
      {https.csr && (
        <SectionW t={t} n={2} title="SIGNING REQUEST — GIVE THIS TO YOUR IT">
          <textarea readOnly value={https.csr} rows={6} aria-label="Signing request"
            style={{ ...HTTPS_INPUT_STYLE(t, false), padding: 12, fontSize: 12 }}/>
          <div style={{ display: 'flex', gap: SPACE[3], marginTop: SPACE[2] }}>
            <button onClick={() => navigator.clipboard.writeText(https.csr)}
              style={{ ...primaryBtnStyle(t, false), background: 'transparent', color: t.text, border: `1px solid ${t.border}` }}>
              Copy
            </button>
            <button onClick={download}
              style={{ ...primaryBtnStyle(t, false), background: 'transparent', color: t.text, border: `1px solid ${t.border}` }}>
              Download
            </button>
          </div>
        </SectionW>
      )}
      {https.csr && (
        <SectionW t={t} n={3} title="SIGNED CERTIFICATE — PASTE WHAT IT SENDS BACK, WITH ANY INTERMEDIATES">
          <textarea value={https.certificate} disabled={locked} rows={6} aria-label="Signed certificate"
            placeholder="-----BEGIN CERTIFICATE-----"
            onChange={e => onHttps({ certificate: e.target.value })}
            style={{ ...HTTPS_INPUT_STYLE(t, false), padding: 12, fontSize: 12 }}/>
          {!isDone && (
            <button onClick={canApply ? onApply : undefined} disabled={!canApply}
              style={{ ...primaryBtnStyle(t, !canApply), marginTop: SPACE[3] }}>
              {isApplying && <SpinnerW color={t.onPrimary} size={13}/>}
              {buttonLabel}
            </button>
          )}
        </SectionW>
      )}
      {!isDone && !isApplying && (
        <button onClick={onSkip} style={{ ...primaryBtnStyle(t, false), background: 'transparent', color: t.textSoft, border: `1px solid ${t.border}` }}>
          Skip for now
        </button>
      )}
      <div style={{ marginTop: SPACE[4] }}>
        <HelperW t={t}>http://{address || '<this box>'}/ keeps working whether or not you do this.</HelperW>
      </div>
      {https.error && <HelperW t={t} error>Failed: {https.error}</HelperW>}
      {page.state === 'error' && <HelperW t={t} error>Failed: {page.error}</HelperW>}
      {page.result && !isApplying && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: SPACE[3], marginTop: SPACE[5] }}>
          {page.result.checks.map(check => <CheckRowW key={check.name} t={t} check={check}/>)}
        </div>
      )}
    </StepShellW>
  );
}

window.StepHttps = StepHttps;

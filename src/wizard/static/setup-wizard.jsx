// setup-wizard.jsx — ARCNODE first-boot setup wizard.
// Served by FastAPI at https://<ip>/setup; runs once, then the URL 404s.
// 5 steps: identity → API keys → TLS → admin → review/apply.

const { useState: useStateW, useEffect: useEffectW } = React;

// ─── Install identity — fetched from GET /setup/api/identity, which reads
// it from /etc/arcnode/install.json. No hardcoded mock data: this step
// exists specifically to confirm the right build landed at the right
// site, so showing a fake fallback value here would defeat its purpose.

// ─── API keys schema (extend here as new integrations land) ──────────
const API_KEYS = [
  {
    id: 'openweathermap',
    label: 'OpenWeatherMap',
    desc: 'Powers the Forecast agent — temperature and irradiance inputs for load and PV prediction.',
    skippedNote: 'Forecast agent will run with site historicals only; no live weather.',
    placeholder: 'a1b2c3d4e5f6…',
  },
  {
    id: 'gridstatus',
    label: 'GridStatus',
    desc: 'Live ISO market data for the bidding agent — LMPs, ancillary services, congestion.',
    skippedNote: 'Bidding agent disabled. Site stays in self-consumption mode.',
    placeholder: 'gs_live_…',
  },
];

// ─── Steps definition ────────────────────────────────────────────────
const STEPS = [
  { id: 'identity', n: 1, title: 'Install identity', sub: 'Confirm the right ISO' },
  { id: 'apikeys',  n: 2, title: 'API keys',         sub: 'Optional agent integrations' },
  { id: 'tls',      n: 3, title: 'TLS for HMI',      sub: 'How operators connect' },
  { id: 'humanauth',n: 4, title: 'Operator & viewer', sub: 'First HMI logins' },
  { id: 'review',   n: 5, title: 'Review & apply',   sub: 'Read back and start' },
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
function SpinnerW({ color, size = 14 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
         strokeWidth="2.5" strokeLinecap="round"
         style={{ animation: 'wizSpin 0.9s linear infinite' }}>
      <path d="M12 3 a9 9 0 0 1 9 9" />
    </svg>
  );
}
function DotW({ color, size = 8 }) {
  return (
    <span style={{
      display: 'inline-block', width: size, height: size, borderRadius: '50%',
      background: color, boxShadow: `0 0 0 3px ${color}30`,
    }}/>
  );
}

// ─── Step rail (left column) ─────────────────────────────────────────
function StepRailW({ t, current, completed, onJump }) {
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
      }}>Setup · 5 steps</div>

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

      {STEPS.map(s => {
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
        }}>https://10.0.1.42/setup</div>
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
function TextInputW({ t, value, onChange, placeholder, type = 'text', disabled, mono, error }) {
  return (
    <input
      type={type} value={value} onChange={e => onChange && onChange(e.target.value)}
      placeholder={placeholder} disabled={disabled}
      style={{
        width: '100%', height: 40, padding: '0 12px',
        boxSizing: 'border-box',
        background: disabled ? t.surface : t.bg,
        border: `1px solid ${error ? t.statusAlarm : t.border}`,
        borderRadius: RADIUS[2],
        fontFamily: mono ? t.fontLabel : t.fontBody, fontSize: 13,
        color: disabled ? t.textSoft : t.text,
        outline: 'none',
      }}
    />
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

// ─── Step 1 — Install identity (read-only) ───────────────────────────
function Step1Identity({ t, identity }) {
  const isSov = t.name === 'sovereign';
  if (!identity) {
    return (
      <StepShellW t={t} title="Confirm install identity" blurb="Loading…">
        <SpinnerW color={t.accent} size={16}/>
      </StepShellW>
    );
  }
  const items = [
    { label: 'Customer',       value: identity.customer },
    { label: 'Site',           value: identity.site },
    { label: 'Market',         value: identity.market },
    { label: 'ISO version',    value: identity.iso_version, mono: true },
    { label: 'Configurator order', value: identity.order_id, mono: true },
  ];
  return (
    <StepShellW t={t} title="Confirm install identity"
      blurb="Make sure this is the ISO that was built for your site. If anything below is wrong, stop and contact your ARCNODE configurator.">
      <div style={{
        background: t.panel,
        border: `1px solid ${t.border}`,
        borderRadius: RADIUS[3],
        overflow: 'hidden',
      }}>
        {items.map((it, i) => (
          <div key={it.label} style={{
            display: 'grid',
            gridTemplateColumns: '180px 1fr',
            padding: `${SPACE[3]}px ${SPACE[4]}px`,
            borderBottom: i < items.length - 1 ? `1px solid ${t.border}` : 'none',
            alignItems: 'center',
          }}>
            <span style={{
              fontFamily: t.fontLabel, fontSize: 10, fontWeight: 700,
              letterSpacing: 0.18, color: t.textSoft, textTransform: 'uppercase',
            }}>{it.label}</span>
            <span style={{
              fontFamily: it.mono ? t.fontLabel : t.fontBody,
              fontSize: it.mono ? 13 : 14,
              color: t.text, fontWeight: it.mono ? 500 : 600,
            }}>{it.value}</span>
          </div>
        ))}
      </div>
      <div style={{
        marginTop: SPACE[4], padding: `${SPACE[3]}px ${SPACE[4]}px`,
        background: t.accent + '12',
        border: `1px solid ${t.accent}30`,
        borderRadius: RADIUS[2],
        fontFamily: t.fontBody, fontSize: 12, color: t.textMid, lineHeight: 1.5,
      }}>
        This wizard captures what Debian's own installer doesn't ask about:
        API keys, TLS, and the first HMI logins. Network, disk, timezone,
        and SSH access were already set up before this ran.
      </div>
    </StepShellW>
  );
}

// ─── Step 2 — API keys ───────────────────────────────────────────────
function Step2APIKeys({ t, values, onChange }) {
  return (
    <StepShellW t={t} title="Connect optional integrations"
      blurb="ARCNODE agents call out to a few third-party services. Provide a key, or skip — skipped integrations disable their agent tool at runtime. You can add keys later from HMI settings.">
      <div style={{ display: 'flex', flexDirection: 'column', gap: SPACE[3] }}>
        {API_KEYS.map(k => {
          const v = values[k.id] || { key: '', skipped: false };
          return (
            <div key={k.id} style={{
              background: t.panel,
              border: `1px solid ${t.border}`,
              borderRadius: RADIUS[3],
              padding: `${SPACE[4]}px`,
            }}>
              <div style={{
                display: 'flex', alignItems: 'baseline', justifyContent: 'space-between',
                gap: SPACE[4], marginBottom: 4,
              }}>
                <div style={{
                  fontFamily: t.fontBody, fontSize: 14, fontWeight: 600,
                  color: t.text,
                }}>{k.label}</div>
                <ToggleW t={t} on={v.skipped}
                  onChange={(on) => onChange(k.id, { ...v, skipped: on, key: on ? '' : v.key })}
                  label="Skip"/>
              </div>
              <div style={{
                fontFamily: t.fontBody, fontSize: 12, color: t.textMid,
                lineHeight: 1.5, marginBottom: SPACE[3],
              }}>{k.desc}</div>
              <TextInputW t={t} value={v.key}
                onChange={(val) => onChange(k.id, { ...v, key: val })}
                placeholder={k.placeholder} disabled={v.skipped} mono/>
              {v.skipped && <HelperW t={t}>{k.skippedNote}</HelperW>}
            </div>
          );
        })}
      </div>
    </StepShellW>
  );
}

function ToggleW({ t, on, onChange, label }) {
  return (
    <div onClick={() => onChange(!on)} style={{
      display: 'inline-flex', alignItems: 'center', gap: 8,
      cursor: 'pointer', userSelect: 'none',
    }}>
      <span style={{
        fontFamily: t.fontLabel, fontSize: 10, fontWeight: 700,
        letterSpacing: 0.2, textTransform: 'uppercase',
        color: on ? t.text : t.textSoft,
      }}>{label}</span>
      <span style={{
        width: 32, height: 18, borderRadius: 999,
        background: on ? t.accent : t.borderSoft,
        position: 'relative', transition: 'background 0.15s',
      }}>
        <span style={{
          position: 'absolute', top: 2, left: on ? 16 : 2,
          width: 14, height: 14, borderRadius: '50%',
          background: '#fff', transition: 'left 0.15s',
          boxShadow: '0 1px 2px rgba(0,0,0,0.2)',
        }}/>
      </span>
    </div>
  );
}

// ─── Step 3 — TLS for HMI ────────────────────────────────────────────
function Step3TLS({ t, mode, onMode, certName, keyName, onCert, onKey }) {
  return (
    <StepShellW t={t} title="TLS for the HMI"
      blurb="Choose how operators' browsers will trust this box. Self-signed is fine for initial install; replace from HMI settings later.">
      <div style={{ display: 'flex', flexDirection: 'column', gap: SPACE[3] }}>
        <RadioCardW t={t} active={mode === 'selfsigned'}
          onClick={() => onMode('selfsigned')}
          title="Generate self-signed certificate"
          sub="ARCNODE creates a 2048-bit RSA cert valid for 10 years. Operators will get a one-time browser warning, then can trust the cert per machine."
          badge="Default"/>
        <RadioCardW t={t} active={mode === 'upload'}
          onClick={() => onMode('upload')}
          title="Upload certificate and key"
          sub="Provide a cert + key issued by your own CA. Written as-is — cert/key parse + match validation is a follow-up, not done yet.">
          {mode === 'upload' && (
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr', gap: SPACE[3],
              marginTop: SPACE[3],
              paddingTop: SPACE[3],
              borderTop: `1px solid ${t.border}`,
            }}>
              <FileFieldW t={t} label="Certificate" ext=".crt,.pem" filename={certName}
                onPick={onCert}/>
              <FileFieldW t={t} label="Private key" ext=".key,.pem" filename={keyName}
                onPick={onKey}/>
            </div>
          )}
        </RadioCardW>
      </div>
    </StepShellW>
  );
}
function RadioCardW({ t, active, onClick, title, sub, badge, children }) {
  return (
    <div onClick={onClick} style={{
      background: t.panel,
      border: `1px solid ${active ? t.accent : t.border}`,
      borderRadius: RADIUS[3],
      padding: `${SPACE[4]}px`,
      cursor: 'pointer',
      boxShadow: active ? `0 0 0 2px ${t.accent}25` : 'none',
    }}>
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: SPACE[3] }}>
        <span style={{
          width: 18, height: 18, borderRadius: '50%',
          border: `1.5px solid ${active ? t.accent : t.borderSoft}`,
          background: t.bg,
          flexShrink: 0, marginTop: 2,
          display: 'flex', alignItems: 'center', justifyContent: 'center',
        }}>
          {active && <span style={{
            width: 8, height: 8, borderRadius: '50%', background: t.accent,
          }}/>}
        </span>
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: SPACE[3] }}>
            <span style={{
              fontFamily: t.fontBody, fontSize: 14, fontWeight: 600, color: t.text,
            }}>{title}</span>
            {badge && (
              <span style={{
                fontFamily: t.fontLabel, fontSize: 9, fontWeight: 700, letterSpacing: 0.22,
                color: t.statusOk,
                background: t.statusOk + '18',
                border: `1px solid ${t.statusOk}40`,
                padding: '1px 6px', borderRadius: RADIUS[1], textTransform: 'uppercase',
              }}>{badge}</span>
            )}
          </div>
          <div style={{
            fontFamily: t.fontBody, fontSize: 12, color: t.textMid,
            marginTop: 4, lineHeight: 1.5,
          }}>{sub}</div>
          {children}
        </div>
      </div>
    </div>
  );
}
function FileFieldW({ t, label, ext, filename, onPick }) {
  const inputRef = React.useRef(null);
  const handleFile = (file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => onPick(file.name, String(reader.result));
    reader.readAsText(file);
  };
  return (
    <div>
      <FieldLabelW t={t}>{label}</FieldLabelW>
      <input ref={inputRef} type="file" accept={ext} style={{ display: 'none' }}
        onChange={(e) => handleFile(e.target.files && e.target.files[0])}/>
      <div style={{
        display: 'flex', alignItems: 'center', gap: SPACE[3],
        height: 40, padding: '0 4px 0 12px',
        background: t.bg,
        border: `1px dashed ${t.borderSoft}`,
        borderRadius: RADIUS[2],
      }}>
        <span style={{
          fontFamily: t.fontLabel, fontSize: 11,
          color: filename ? t.text : t.textSoft,
          flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{filename || `drop or browse · ${ext}`}</span>
        <button onClick={(e) => {
            e.stopPropagation();
            if (filename) { onPick(null, null); } else { inputRef.current?.click(); }
          }} style={{
          appearance: 'none', cursor: 'pointer',
          height: 30, padding: '0 12px',
          background: 'transparent',
          border: `1px solid ${t.border}`,
          borderRadius: RADIUS[1],
          fontFamily: t.fontLabel, fontSize: 10, fontWeight: 700, letterSpacing: 0.18,
          color: t.text, textTransform: 'uppercase',
        }}>{filename ? 'Replace' : 'Browse'}</button>
      </div>
    </div>
  );
}

// ─── Step 4 — HMI operator + viewer logins ────────────────────────────
// Two fixed roles, not a customizable username — matches device-api's
// real auth model exactly (AUTH_OPERATOR_PW/AUTH_VIEWER_PW, bcrypt-hashed
// at boot), not a generic single "admin" account.
function Step4HumanAuth({ t, values, onChange }) {
  return (
    <StepShellW t={t} title="Create the operator and viewer logins"
      blurb="Two fixed HMI roles: operator (dispatch + full access) and viewer (read-only). Separate from the SSH key you already have — these are for the HMI web login only.">
      <div style={{ display: 'flex', flexDirection: 'column', gap: SPACE[4] }}>
        <PasswordPairCard t={t} title="Operator" roleDesc="Dispatch + full HMI access."
          password={values.operatorPassword} confirm={values.operatorConfirm}
          onPassword={(v) => onChange('operatorPassword', v)}
          onConfirm={(v) => onChange('operatorConfirm', v)}/>
        <PasswordPairCard t={t} title="Viewer" roleDesc="Read-only HMI access."
          password={values.viewerPassword} confirm={values.viewerConfirm}
          onPassword={(v) => onChange('viewerPassword', v)}
          onConfirm={(v) => onChange('viewerConfirm', v)}/>
      </div>
    </StepShellW>
  );
}
function PasswordPairCard({ t, title, roleDesc, password, confirm, onPassword, onConfirm }) {
  const strength = passwordStrength(password);
  const policyUnmet = password.length > 0 && !passwordMeetsPolicy(password);
  const mismatch = confirm.length > 0 && confirm !== password;
  return (
    <div style={{
      background: t.panel, border: `1px solid ${t.border}`,
      borderRadius: RADIUS[3], padding: SPACE[5],
      display: 'flex', flexDirection: 'column', gap: SPACE[4],
    }}>
      <div>
        <div style={{ fontFamily: t.fontBody, fontSize: 14, fontWeight: 600, color: t.text }}>{title}</div>
        <div style={{ fontFamily: t.fontBody, fontSize: 12, color: t.textMid, marginTop: 2 }}>{roleDesc}</div>
      </div>
      <div>
        <FieldLabelW t={t} required>Password</FieldLabelW>
        <TextInputW t={t} type="password" value={password} onChange={onPassword} placeholder="8+ chars, 1 upper, 1 number, 1 special" error={policyUnmet}/>
        <PasswordStrengthW t={t} strength={strength} password={password}/>
        {policyUnmet && <HelperW t={t} error>Needs {MIN_PASSWORD_LENGTH}+ characters, one uppercase letter, one number, and one special character.</HelperW>}
      </div>
      <div>
        <FieldLabelW t={t} required>Confirm password</FieldLabelW>
        <TextInputW t={t} type="password" value={confirm} onChange={onConfirm} error={mismatch}/>
        {mismatch && <HelperW t={t} error>Passwords don't match.</HelperW>}
      </div>
    </div>
  );
}
// Must match MIN_HUMAN_PASSWORD_LENGTH + password_meets_complexity in
// wizard_record.py — the backend is the source of truth, this is just the
// client-side mirror of it so a non-compliant password never reaches a
// round trip to find out.
const MIN_PASSWORD_LENGTH = 8;

function passwordStrength(pw) {
  if (!pw) return 0;
  let s = 0;
  if (pw.length >= 8)  s++;
  if (pw.length >= 12) s++;
  if (/[A-Z]/.test(pw) && /[a-z]/.test(pw)) s++;
  if (/\d/.test(pw))   s++;
  if (/[^A-Za-z0-9]/.test(pw)) s++;
  return Math.min(s, 4);
}
function passwordMeetsPolicy(pw) {
  return (
    pw.length >= MIN_PASSWORD_LENGTH &&
    /[A-Z]/.test(pw) &&
    /\d/.test(pw) &&
    /[^A-Za-z0-9]/.test(pw)
  );
}
function isHumanAuthValid(humanAuth) {
  return (
    passwordMeetsPolicy(humanAuth.operatorPassword) &&
    humanAuth.operatorPassword === humanAuth.operatorConfirm &&
    passwordMeetsPolicy(humanAuth.viewerPassword) &&
    humanAuth.viewerPassword === humanAuth.viewerConfirm
  );
}
function PasswordStrengthW({ t, strength, password }) {
  const labels = ['Too short', 'Weak', 'Fair', 'Good', 'Strong'];
  const colors = [t.statusAlarm, t.statusAlarm, t.statusWarn, t.colorBess, t.statusOk];
  const label = password ? labels[strength] : '';
  const c = colors[strength];
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: 'flex', gap: 4 }}>
        {[0,1,2,3].map(i => (
          <div key={i} style={{
            flex: 1, height: 4, borderRadius: 2,
            background: i < strength ? c : t.borderSoft,
          }}/>
        ))}
      </div>
      <div style={{
        fontFamily: t.fontLabel, fontSize: 10,
        color: password ? c : t.textSoft,
        marginTop: 6, letterSpacing: 0.1, fontWeight: 600,
      }}>{password ? label : 'Mix length, case, digits, and a symbol.'}</div>
    </div>
  );
}

// ─── Step 5 — Review + apply ─────────────────────────────────────────
// No fake progress animation — apply() on the backend is a synchronous
// write of secrets.env + a TLS cert, not a multi-service bringup, so this
// just shows a spinner then the real response (success or the actual
// error message), not a scripted log of things that aren't happening.
function Step5Review({ t, identity, values, applyState, applyError, onApply, onJump }) {
  const isApplying = applyState === 'applying';
  const isDone     = applyState === 'done';
  const isIdle     = applyState === 'idle';
  const isError    = applyState === 'error';
  return (
    <StepShellW t={t} title={isIdle || isError ? 'Review and apply' : (isDone ? 'Setup complete' : 'Applying…')}
      blurb={isDone
        ? 'Done. The /setup URL is now disabled.'
        : isError
          ? `Apply failed: ${applyError}`
          : isApplying
            ? 'Writing secrets.env and the TLS cert…'
            : 'Writes secrets.env + TLS cert/key, then disables this /setup URL for good.'}>
      {(isIdle || isError) && <ReviewSummary t={t} identity={identity} values={values} onJump={onJump}/>}
      {isApplying && <SpinnerW color={t.accent} size={20}/>}
      {isDone && <CheckW color={t.statusOk} size={20}/>}
    </StepShellW>
  );
}
function ReviewSummary({ t, identity, values, onJump }) {
  const apiSummary = API_KEYS.map(k => {
    const v = values.apiKeys[k.id] || { key: '', skipped: false };
    return {
      label: k.label,
      value: v.skipped ? <span style={{ color: t.textSoft }}>skipped</span>
            : (v.key ? <span style={{ fontFamily: t.fontLabel, color: t.text }}>{maskKey(v.key)}</span>
                     : <span style={{ color: t.textSoft }}>not provided</span>),
    };
  });
  const tlsSummary = values.tls.mode === 'selfsigned'
    ? 'Self-signed (auto-generated, 10-year)'
    : `Uploaded · ${values.tls.cert || '?'} + ${values.tls.key || '?'}`;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: SPACE[3] }}>
      <ReviewCard t={t} title="Install identity" onEdit={() => onJump('identity')}
        rows={[
          ['Customer', identity?.customer ?? '?'],
          ['Site',     identity?.site ?? '?'],
          ['Market',   identity?.market ?? '?'],
          ['Order',    identity?.order_id ?? '?'],
        ]}/>
      <ReviewCard t={t} title="API keys" onEdit={() => onJump('apikeys')}
        rows={apiSummary.map(s => [s.label, s.value])}/>
      <ReviewCard t={t} title="TLS" onEdit={() => onJump('tls')}
        rows={[ ['Mode', tlsSummary] ]}/>
      <ReviewCard t={t} title="Operator & viewer" onEdit={() => onJump('humanauth')}
        rows={[
          ['Operator password', values.humanAuth.operatorPassword ? '•••••••••• (set)' : 'not set'],
          ['Viewer password',   values.humanAuth.viewerPassword ? '•••••••••• (set)' : 'not set'],
        ]}/>
    </div>
  );
}
function maskKey(k) {
  if (k.length <= 6) return '•'.repeat(k.length);
  return k.slice(0, 3) + '…' + k.slice(-3);
}
function ReviewCard({ t, title, rows, onEdit }) {
  return (
    <div style={{
      background: t.panel,
      border: `1px solid ${t.border}`,
      borderRadius: RADIUS[3],
      overflow: 'hidden',
    }}>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        padding: `${SPACE[3]}px ${SPACE[4]}px`,
        background: t.surface,
        borderBottom: `1px solid ${t.border}`,
      }}>
        <span style={{
          fontFamily: t.fontLabel, fontSize: 10, fontWeight: 700,
          letterSpacing: 0.22, color: t.textSoft, textTransform: 'uppercase',
        }}>{title}</span>
        <button onClick={onEdit} style={{
          appearance: 'none', cursor: 'pointer',
          padding: '4px 10px', background: 'transparent',
          border: `1px solid ${t.border}`, borderRadius: RADIUS[1],
          fontFamily: t.fontLabel, fontSize: 9, fontWeight: 700, letterSpacing: 0.18,
          color: t.text, textTransform: 'uppercase',
        }}>Edit</button>
      </div>
      {rows.map((r, i) => (
        <div key={i} style={{
          display: 'grid', gridTemplateColumns: '140px 1fr',
          padding: `${SPACE[2]}px ${SPACE[4]}px`,
          borderBottom: i < rows.length - 1 ? `1px solid ${t.border}` : 'none',
          alignItems: 'center',
        }}>
          <span style={{
            fontFamily: t.fontLabel, fontSize: 10, fontWeight: 700,
            letterSpacing: 0.18, color: t.textFaint, textTransform: 'uppercase',
          }}>{r[0]}</span>
          <span style={{ fontFamily: t.fontBody, fontSize: 12, color: t.text }}>{r[1]}</span>
        </div>
      ))}
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
function HeaderW({ t, current, isDark, onToggleTheme }) {
  const isSov = t.name === 'sovereign';
  const idx = STEPS.findIndex(s => s.id === current);
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
      <div style={{
        fontFamily: t.fontLabel, fontSize: 11, fontWeight: 700, letterSpacing: 0.2,
        color: t.textSoft, textTransform: 'uppercase',
      }}>
        {isPreflight
          ? 'Preflight'
          : <>Step <span style={{ color: t.text }}>{idx + 1}</span> of {STEPS.length}</>}
      </div>
      {onToggleTheme && (
        <ThemeToggleW t={t} isDark={isDark} onToggle={onToggleTheme}/>
      )}
    </div>
  );
}

// ─── Footer (Back / Continue) ───────────────────────────────────────
function FooterW({ t, current, applyState, hwScenario, canApply, onBack, onNext, onApply }) {
  const idx = STEPS.findIndex(s => s.id === current);
  const isLast = current === 'review';
  const isPreflight = current === 'preflight';
  const isApplying = applyState === 'applying';
  const isDone = applyState === 'done';

  const hwData = (typeof HW_SCENARIOS !== 'undefined') ? HW_SCENARIOS[hwScenario] : null;
  const hwStatus = hwData?.overallStatus || 'ok';
  const hwBlocked = isPreflight && hwStatus === 'fail';
  const hwWarn    = isPreflight && hwStatus === 'warn';

  let nextLabel;
  if (isPreflight)              nextLabel = hwWarn ? 'Continue anyway' : 'Begin setup';
  else if (current === 'identity') nextLabel = 'Continue';
  else                          nextLabel = 'Continue';

  const backDisabled = isPreflight || idx === 0 || isApplying || isDone;

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
        {isApplying  ? 'Do not refresh the page.'
         : isDone    ? 'Redirecting to HMI…'
         : isLast    ? 'Applies all changes in a single transaction.'
         : isPreflight && hwBlocked
                     ? 'Move the ISO to hardware that meets the minimums.'
         : isPreflight && hwWarn
                     ? 'Below recommended — the system will run but may struggle under load.'
         : isPreflight ? 'Next · Install identity'
         : `Next · ${STEPS[idx + 1]?.title}`}
      </span>

      {isLast ? (
        <button onClick={onApply} disabled={isApplying || isDone || !canApply}
          style={primaryBtnStyle(t, isApplying || isDone || !canApply)}>
          {isApplying && <SpinnerW color="#fff" size={13}/>}
          {isDone && <CheckW color="#fff" size={13}/>}
          {isApplying ? 'Applying' : isDone ? 'Complete'
            : !canApply ? 'Fix passwords to continue' : 'Apply & start ARCNODE'}
        </button>
      ) : (
        <button onClick={hwBlocked ? undefined : onNext}
          disabled={hwBlocked}
          style={hwWarn
            ? secondaryBtnStyle(t, false)
            : primaryBtnStyle(t, hwBlocked)}>
          {nextLabel}
          <ChevronW color={hwWarn ? t.text : '#fff'} size={12}/>
        </button>
      )}
    </div>
  );
}
function secondaryBtnStyle(t, disabled) {
  return {
    appearance: 'none', cursor: disabled ? 'not-allowed' : 'pointer',
    height: 40, padding: '0 18px',
    background: 'transparent',
    border: `1px solid ${t.statusWarn}`,
    color: t.text,
    borderRadius: RADIUS[2],
    display: 'inline-flex', alignItems: 'center', gap: 8,
    fontFamily: t.fontLabel, fontSize: 11, fontWeight: 700, letterSpacing: 0.18,
    textTransform: 'uppercase',
  };
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
// No hardware-preflight step yet — its source (hardware-check.jsx) isn't
// built; 'identity' is the real first step. Re-add preflight as its own
// increment later rather than fake it here.
function SetupWizardBody({ t, initialStep, initialApply, isDark, onToggleTheme }) {
  const [current, setCurrent] = useStateW(initialStep || 'identity');
  const [completed, setCompleted] = useStateW(new Set());
  const [applyState, setApplyState] = useStateW(initialApply || 'idle');
  const [applyError, setApplyError] = useStateW(null);
  const [identity, setIdentity] = useStateW(null);

  // form values
  const [values, setValues] = useStateW({
    apiKeys: {
      openweathermap: { key: '', skipped: false },
      gridstatus:     { key: '', skipped: false },
    },
    tls: { mode: 'selfsigned', cert: null, certPem: null, key: null, keyPem: null },
    humanAuth: { operatorPassword: '', operatorConfirm: '', viewerPassword: '', viewerConfirm: '' },
  });

  // GET /setup/api/identity once on mount — real data, no mock fallback.
  useEffectW(() => {
    fetch('/setup/api/identity')
      .then(r => r.json())
      .then(setIdentity)
      .catch(() => setIdentity(null));
  }, []);

  useEffectW(() => {
    if (initialStep && initialStep !== current) setCurrent(initialStep);
  }, [initialStep]);
  useEffectW(() => {
    if (initialApply && initialApply !== applyState) {
      setApplyState(initialApply);
      if (initialApply !== 'idle') setCurrent('review');
    }
  }, [initialApply]);

  const advance = (nextId) => {
    setCompleted(s => new Set([...s, current]));
    setCurrent(nextId);
  };
  const onNext = () => {
    const idx = STEPS.findIndex(s => s.id === current);
    if (idx < STEPS.length - 1) advance(STEPS[idx + 1].id);
  };
  const onBack = () => {
    const idx = STEPS.findIndex(s => s.id === current);
    if (idx > 0) setCurrent(STEPS[idx - 1].id);
  };
  const onApply = () => {
    setApplyState('applying');
    setApplyError(null);
    fetch('/setup/api/apply', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        api_keys: values.apiKeys,
        tls: { mode: values.tls.mode, cert_pem: values.tls.certPem, key_pem: values.tls.keyPem },
        human_auth: {
          operator_password: values.humanAuth.operatorPassword,
          operator_confirm:  values.humanAuth.operatorConfirm,
          viewer_password:   values.humanAuth.viewerPassword,
          viewer_confirm:    values.humanAuth.viewerConfirm,
        },
      }),
    })
      .then(async (r) => {
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          throw new Error(formatApplyError(body.detail) || `HTTP ${r.status}`);
        }
        setApplyState('done');
        // Real navigation, not fake progress — the footer already promises
        // this ("Redirecting to HMI…"); this was the missing half of that.
        // Brief delay so "Setup complete" is actually readable before the
        // page leaves, not simulating work that isn't happening.
        setTimeout(() => {
          window.location.href = `${window.location.protocol}//${window.location.hostname}/`;
        }, 1500);
      })
      .catch((err) => {
        setApplyError(String(err.message || err));
        setApplyState('error');
      });
  };
  const onJump = (id) => setCurrent(id);

  const setAPIKey      = (id, v) => setValues(s => ({ ...s, apiKeys: { ...s.apiKeys, [id]: v } }));
  const setTLSMode     = (m)     => setValues(s => ({ ...s, tls: { ...s.tls, mode: m } }));
  const setCert   = (name, content) => setValues(s => ({ ...s, tls: { ...s.tls, cert: name, certPem: content } }));
  const setTLSKey = (name, content) => setValues(s => ({ ...s, tls: { ...s.tls, key: name, keyPem: content } }));
  const setHumanAuth   = (field, v) => setValues(s => ({ ...s, humanAuth: { ...s.humanAuth, [field]: v } }));

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      background: t.bg,
      fontFamily: t.fontBody, color: t.text,
      minHeight: '100%',
    }}>
      <HeaderW t={t} current={current} isDark={isDark} onToggleTheme={onToggleTheme}/>
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        <StepRailW t={t} current={current} completed={completed} onJump={onJump}/>
        <div style={{
          flex: 1,
          padding: `${SPACE[6]}px ${SPACE[8]}px ${SPACE[6]}px`,
          overflowY: 'auto',
          maxWidth: 820,
        }}>
          {current === 'identity'  && <Step1Identity   t={t} identity={identity}/>}
          {current === 'apikeys'   && <Step2APIKeys    t={t} values={values.apiKeys} onChange={setAPIKey}/>}
          {current === 'tls'       && <Step3TLS        t={t} mode={values.tls.mode} onMode={setTLSMode}
                                                        certName={values.tls.cert} keyName={values.tls.key}
                                                        onCert={setCert} onKey={setTLSKey}/>}
          {current === 'humanauth' && <Step4HumanAuth  t={t} values={values.humanAuth} onChange={setHumanAuth}/>}
          {current === 'review'    && <Step5Review     t={t} identity={identity} values={values}
                                                        applyState={applyState} applyError={applyError}
                                                        onApply={onApply} onJump={onJump}/>}
        </div>
      </div>
      <FooterW t={t} current={current} applyState={applyState}
        hwScenario="ok" canApply={isHumanAuthValid(values.humanAuth)}
        onBack={onBack} onNext={onNext} onApply={onApply}/>
    </div>
  );
}

window.SetupWizardBody = SetupWizardBody;

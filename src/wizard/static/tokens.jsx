// tokens.jsx — minimal design tokens for the wizard.
// The designer's original tokens.jsx wasn't available (only
// setup-wizard.jsx was handed off) — this is a plain, workable
// replacement, not an attempt to match a design system we don't have.

const SPACE = [0, 4, 8, 12, 16, 24, 32, 40, 48];
const RADIUS = [0, 4, 8, 12, 16];

const SOVEREIGN = {
  name: 'sovereign',
  bg: '#14161a',
  surface: '#1b1e24',
  panel: '#20242b',
  border: '#2c313a',
  borderSoft: '#3a4049',
  text: '#eef0f3',
  textMid: '#aab0ba',
  textSoft: '#7b828d',
  textFaint: '#565c66',
  accent: '#4f8ef7',
  accentDim: '#3a6bc2',
  colorBess: '#4f8ef7',
  statusOk: '#2fb380',
  statusWarn: '#d9a528',
  statusAlarm: '#e35b5b',
  fontHeading: "'Bebas Neue', system-ui, sans-serif",
  fontBody: "'Plus Jakarta Sans', system-ui, sans-serif",
  fontLabel: "'DM Mono', monospace",
};

const SOLARPUNK = {
  ...SOVEREIGN,
  name: 'solarpunk',
  bg: '#f7f5ef',
  surface: '#efebe0',
  panel: '#ffffff',
  border: '#ddd6c4',
  borderSoft: '#cfc6ac',
  text: '#2a2620',
  textMid: '#5a5248',
  textSoft: '#8a8278',
  textFaint: '#a89f90',
  accent: '#2f8f5b',
  accentDim: '#246b45',
  colorBess: '#2f8f5b',
};

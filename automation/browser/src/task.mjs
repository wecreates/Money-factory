const ALLOWED_TYPES = new Set(['inspect','qa','multi-inspect']);
const ALLOWED_ACTIONS = new Set(['click','fill','wait','extract','links','screenshot']);
const SENSITIVE_LABEL = /(password|passcode|otp|one[- ]?time|verification code|security code|2fa|mfa|recovery code|cookie|session|token|secret)/i;

export function sanitizeUrl(input) {
  const u = new URL(input);
  if (!['http:','https:'].includes(u.protocol)) throw new Error('Only http(s) URLs are allowed');
  return u.toString();
}

export function compileActions(actions = []) {
  if (!Array.isArray(actions)) throw new Error('actions must be an array');
  if (actions.length > 25) throw new Error('too many actions');
  return actions.map((a, i) => {
    if (!a || !ALLOWED_ACTIONS.has(a.type)) throw new Error(`unsupported action at ${i}`);
    if (a.type === 'fill') {
      if (!a.label || typeof a.value !== 'string') throw new Error('fill requires label and value');
      if (SENSITIVE_LABEL.test(a.label)) throw new Error('credential-like fields are not allowed in cloud tasks');
      if (a.value.length > 4000) throw new Error('fill value too large');
    }
    if (a.type === 'click' && !a.text) throw new Error('click requires text');
    if (a.type === 'wait') {
      if (!Number.isInteger(a.ms) || a.ms < 0 || a.ms > 15000) throw new Error('wait out of range');
    }
    if ((a.type === 'extract' || a.type === 'links') && (!a.selector || a.selector.length > 200)) throw new Error('invalid selector');
    return structuredClone(a);
  });
}

export function validateTask(raw) {
  if (!raw || typeof raw !== 'object') throw new Error('task must be an object');
  const id = String(raw.id || '').trim();
  if (!/^[a-z0-9][a-z0-9._-]{0,80}$/i.test(id)) throw new Error('invalid task id');
  const type = raw.type || 'inspect';
  if (!ALLOWED_TYPES.has(type)) throw new Error('unsupported task type');
  if (type === 'multi-inspect') {
    if (!Array.isArray(raw.pages) || raw.pages.length < 1 || raw.pages.length > 50) throw new Error('multi-inspect requires 1-50 pages');
    const pages = raw.pages.map((p, i) => {
      const pid = String(p?.id || '').trim();
      if (!/^[a-z0-9][a-z0-9._-]{0,80}$/i.test(pid)) throw new Error(`invalid page id at ${i}`);
      return { id: pid, url: sanitizeUrl(p.url) };
    });
    return { id, type, pages, screenshot: raw.screenshot !== false };
  }
  const url = sanitizeUrl(raw.url);
  const actions = compileActions(raw.actions || []);
  return { id, type, url, actions, screenshot: raw.screenshot !== false };
}

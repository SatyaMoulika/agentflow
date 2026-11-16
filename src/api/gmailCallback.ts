type CallbackLocation = Pick<Location, 'pathname' | 'search'>;
type CallbackHistory = Pick<History, 'replaceState'>;

export function captureGmailCallback(location: CallbackLocation, history: CallbackHistory) {
  if (location.pathname !== '/integrations/gmail/callback') return null;
  const parameters = new URLSearchParams(location.search);
  const codes = parameters.getAll('code');
  const states = parameters.getAll('state');
  history.replaceState(null, '', location.pathname);
  return {
    code: codes.length === 1 ? codes[0] : null,
    state: states.length === 1 ? states[0] : null,
  };
}

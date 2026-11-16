import { describe, expect, it, vi } from 'vitest';
import { captureGmailCallback } from '../src/api/gmailCallback';

describe('Gmail callback', () => {
  it('clears the authorization code from the browser URL before returning it', () => {
    const replaceState = vi.fn();
    const data = captureGmailCallback(
      {
        pathname: '/integrations/gmail/callback',
        search: '?code=private-code&state=private-state',
      },
      { replaceState },
    );
    expect(data).toEqual({ code: 'private-code', state: 'private-state' });
    expect(replaceState).toHaveBeenCalledWith(null, '', '/integrations/gmail/callback');
  });

  it('rejects duplicate callback values and does not touch unrelated routes', () => {
    const replaceState = vi.fn();
    expect(
      captureGmailCallback(
        { pathname: '/integrations/gmail/callback', search: '?code=a&code=b&state=s' },
        { replaceState },
      ),
    ).toEqual({ code: null, state: 's' });
    replaceState.mockClear();
    expect(
      captureGmailCallback({ pathname: '/workflows', search: '?code=a' }, { replaceState }),
    ).toBeNull();
    expect(replaceState).not.toHaveBeenCalled();
  });
});

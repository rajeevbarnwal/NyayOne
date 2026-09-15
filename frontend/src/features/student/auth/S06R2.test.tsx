import { renderToStaticMarkup } from 'react-dom/server';
import { readFileSync } from 'node:fs';
import { describe, expect, it, vi } from 'vitest';
import { S06R2, type S06R2Props } from './S06R2';

const base: S06R2Props = {
  state: 'entry', mobile: '', code: '', destinationMasked: null,
  expiresInSeconds: null, resendInSeconds: null, attemptsLeft: null,
  lockedForSeconds: null, busy: false, authorityReady: true, resendAllowed: false,
  onMobileChange: vi.fn(), onCodeChange: vi.fn(), onSend: vi.fn(), onVerify: vi.fn(),
  onResend: vi.fn(), onChangeNumber: vi.fn(), onBack: vi.fn(), onRetry: vi.fn(),
};
const html = (props: Partial<S06R2Props> = {}) => renderToStaticMarkup(<S06R2 {...base} {...props}/>);
const button = (markup: string, label: string) => [...markup.matchAll(/<button\b[^>]*>[\s\S]*?<\/button>/g)]
  .map(match => match[0]).find(node => node.replace(/<[^>]*>/g, '').includes(label));
const challenge = { state: 'challenge' as const, authorityReady: true, expiresInSeconds: 97, resendInSeconds: 12, attemptsLeft: 4, destinationMasked: '+91 ••••• ••321' };

describe('S-06 approved R2 controlled recovery presentation', () => {
  it('preserves the R2 mobile logo line-box gap without shifting desktop composition', () => {
    const css = readFileSync(new URL('./S06R2.css', import.meta.url), 'utf8');
    expect(css).toContain('.s06-r2__brandcopy { margin-top: 9px; }');
    expect(css).toContain('.s06-r2__brandcopy { margin-top: auto; max-width: 360px; }');
  });
  it('preserves the reference icon shrink behavior when the recovery button label wraps', () => {
    const css = readFileSync(new URL('./S06R2.css', import.meta.url), 'utf8');
    expect(css).toContain('.s06-r2__buttonrow .v321-revl-icon { flex: 0 1 auto; }');
    expect(css).toContain('.s06-r2__buttonrow .s06-r2__button { flex: 1; min-width: 0; padding: 0 10px; text-align: center; }');
    expect(css).toContain('.s06-r2__icon, .s06-r2 .v321-revl-icon { display: inline-flex; width: 20px; height: 20px; align-items: center; justify-content: center; }');
    const change = button(html({ ...challenge, state: 'wrong', code: '123456' }), 'Change number');
    expect(change).toContain('class="v321-revl-icon"');
    expect(change).not.toContain('disabled');
  });
  it('renders mobile-only recovery and the approved brand copy with no invented identity', () => {
    const markup = html();
    for (const copy of ['Recover your account.', 'Registered mobile number', 'Keep your law-school record in one place.', 'Learn the law.', 'Build your path.', 'If this number matches an account, we will send a code. The response looks the same either way.']) expect(markup).toContain(copy);
    expect(markup).not.toContain('98765');
    expect(markup).not.toContain('419037');
    expect(markup).not.toContain('type="email"');
    expect(markup).not.toMatch(/<a\b[^>]*>Privacy Notice|<a\b[^>]*>Terms/);
  });
  it.each(['', '   '])('keeps Send disabled for blank mobile %j', mobile => {
    expect(button(html({ mobile }), 'Send recovery code')).toContain('disabled');
  });
  it.each(['12345', 'abcdefghij', '12345678901'])('lets the controller show inline validation for nonempty invalid mobile %j', mobile => {
    expect(button(html({ mobile }), 'Send recovery code')).not.toContain('disabled');
  });
  it('enables Send for nonempty entry and disables it while busy', () => {
    expect(button(html({ mobile: '9876543210' }), 'Send recovery code')).not.toContain('disabled');
    expect(button(html({ mobile: '9876543210', busy: true }), 'Send recovery code')).toContain('disabled');
    expect(button(html({ mobile: '9876543210', state: 'submitting' }), 'Sending')).toContain('disabled');
  });
  it('refuses Send before the server authority read completes', () => {
    expect(button(html({ mobile: '9876543210', authorityReady: false }), 'Send recovery code')).toContain('disabled');
  });
  it('exposes validation summary, linked input and inline error', () => {
    const markup = html({ state: 'invalidnum', mobile: '12345' });
    expect(markup).toContain('href="#v34-reset-mobile"');
    expect(markup).toContain('aria-invalid="true"');
    expect(markup).toContain('aria-describedby="s06-mobile-error"');
    expect(markup).toContain('Enter all 10 digits of your registered mobile number.');
  });
  it('uses one accessible OTP input over six decorative digit boxes', () => {
    const markup = html({ ...challenge, code: '123456' });
    expect(markup.match(/<input\b/g)).toHaveLength(1);
    expect(markup).toContain('id="v34-recovery-code"');
    expect(markup).toContain('aria-label="Six-digit recovery code"');
    expect(markup).toContain('autoComplete="one-time-code"');
    expect(markup).toContain('inputMode="numeric"');
    expect(markup.match(/<i class="s06-r2__digit"/g)).toHaveLength(6);
    expect(markup).toContain('class="s06-r2__otpboxes" aria-hidden="true"');
  });
  it.each(['', '1', '12345', '1234567', 'ABCDEF'])('disables Verify without exactly six digits: %j', code => {
    expect(button(html({ ...challenge, code }), 'Verify and continue')).toContain('disabled');
  });
  it('requires server authority, remaining attempts and a live code even with six digits', () => {
    expect(button(html({ ...challenge, code: '123456' }), 'Verify and continue')).not.toContain('disabled');
    for (const override of [{ authorityReady: false }, { busy: true }, { expiresInSeconds: 0 }, { expiresInSeconds: null }, { attemptsLeft: 0 }, { attemptsLeft: null }, { state: 'expired' as const }]) {
      expect(button(html({ ...challenge, code: '123456', ...override }), 'Verify and continue')).toContain('disabled');
    }
  });
  it('renders server-derived metadata without substituting prototype sample values', () => {
    const markup = html(challenge);
    expect(markup).toContain('<b>1:37</b>');
    expect(markup).toContain('<b>in 0:12</b>');
    expect(markup).toContain('<b>4</b>');
    expect(markup).toContain('+91 ••••• ••321');
    expect(markup).not.toContain('4:32');
    expect(markup).not.toContain('340');
  });
  it('does not fabricate server metadata or show an unmasked entered identifier', () => {
    const markup = html({ state: 'challenge', mobile: '9876543210', code: '123456' });
    expect(markup).not.toContain('9876543210');
    expect(markup).toContain('Unavailable');
    expect(markup).not.toContain('Sent to');
    expect(button(markup, 'Verify and continue')).toContain('disabled');
  });
  it('never grants resend based only on a locally elapsed countdown', () => {
    expect(button(html({ ...challenge, resendInSeconds: 0 }), 'Resend code')).toContain('disabled');
    expect(button(html({ ...challenge, resendInSeconds: 0, resendAllowed: true }), 'Resend code')).not.toContain('disabled');
    expect(button(html({ ...challenge, resendInSeconds: 0, resendAllowed: true, busy: true }), 'Resend code')).toContain('disabled');
    expect(button(html({ ...challenge, resendInSeconds: 0, resendAllowed: true, authorityReady: false }), 'Resend code')).toContain('disabled');
  });
  it('renders wrong/expired states and the code error association', () => {
    const wrong = html({ ...challenge, state: 'wrong', code: '123456' });
    expect(wrong).toContain('Incorrect code');
    expect(wrong).toContain('aria-describedby="s06-code-error"');
    expect(wrong).toContain('That code is not correct. Check the last six digits you received.');
    const expired = html({ ...challenge, state: 'expired' });
    expect(expired).toContain('Code expired');
    expect(button(expired, 'Verify and continue')).toContain('disabled');
  });
  it('does not fabricate a lockout duration and has no verification action while locked', () => {
    const markup = html({ state: 'locked' });
    expect(markup).toContain('Recovery is paused.');
    expect(markup).not.toContain('30 minutes');
    expect(markup).not.toContain('Verify and continue');
    expect(html({ state: 'locked', lockedForSeconds: 81 })).toContain('You can try again in 1:21.');
    expect(html({ state: 'locked', lockedForSeconds: 1800 })).toContain('You can try again in 30 minutes.');
  });
  it('uses truthful non-enumerating network failure copy rather than claiming no code was sent', () => {
    const markup = html({ state: 'neterr' });
    expect(markup).toContain('We could not confirm whether your code was sent. Check your connection and try again.');
    expect(markup).not.toContain('Your code was not sent');
    expect(button(markup, 'Try again')).toBeDefined();
  });
  it('states recovery does not sign in and exposes only the explicit sign-in return', () => {
    const markup = html({ state: 'success' });
    expect(markup).toContain('Your account is ready.');
    expect(markup).toContain('You are not signed in yet.');
    expect(button(markup, 'Back to sign in')).toBeDefined();
    expect(markup).not.toContain('/s-07');
  });
  it('disables Change number during an in-flight recovery operation', () => {
    expect(button(html({ ...challenge, busy: true }), 'Change number')).toContain('disabled');
    expect(button(html(challenge), 'Change number')).not.toContain('disabled');
  });
  it('groups only a complete numeric mobile for display', () => {
    expect(html({ mobile: '9876543210' })).toContain('value="98765 43210"');
    expect(html({ mobile: '12345' })).toContain('value="12345"');
  });
});

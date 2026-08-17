/**
 * LegalSaathi stakeholder walkthrough recorder.
 *
 * Records the implemented Wave 1–3 journeys against a running local stack.
 * It uses only deterministic demo actors, the deterministic payment adapter
 * and fake Chromium media devices. Raw OTPs, PANs, CVVs and LiveKit join
 * credentials are never rendered or written to the artifact directory.
 */
import { createHash, createHmac } from 'node:crypto';
import { mkdir, rename, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { chromium } from 'playwright';

const WEB = (process.env.DEMO_WEB_URL ?? 'http://127.0.0.1:1055').replace(/\/$/, '');
const API = (process.env.DEMO_API_URL ?? 'http://127.0.0.1:1053').replace(/\/$/, '');
const OUT = path.resolve(process.env.DEMO_OUTPUT_DIR ?? 'test-results/stakeholder-demo');
const STUDENT = '00000000-0000-4000-8000-0000000000de';
const TUTOR_PROFILE = '29f9ffa5-1be7-51dc-b64c-d416f3de10df';
const TUTOR_USER = '50d0a8e4-082c-54ec-8d3c-99378f384af4';
const ISSUER = '00000000-0000-4000-8000-000000000253';
const PAY_KEY = Buffer.from('nyayone-deterministic-payment-test-key');
const PAY_SIG_HEADER = 'X-Payment-Signature';
const studentClaims = JSON.stringify({ sub: STUDENT, roles: ['student'] });
const tutorClaims = JSON.stringify({ sub: TUTOR_USER, roles: ['tutor'] });
const report = {
  startedAt: new Date().toISOString(),
  webUrl: WEB,
  apiUrl: API,
  chapters: [],
  consoleErrors: [],
  pageErrors: [],
  failedRequests: [],
};

await mkdir(path.join(OUT, 'screenshots'), { recursive: true });
await mkdir(path.join(OUT, 'raw-video'), { recursive: true });

function headersFor(claims = studentClaims) {
  return { Accept: 'application/json', 'Content-Type': 'application/json', 'X-Actor-Claims': claims };
}

async function api(method, route, body, headers = headersFor()) {
  const response = await fetch(`${API}${route}`, {
    method,
    headers,
    body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
  });
  const text = await response.text();
  let json;
  try { json = text ? JSON.parse(text) : null; } catch { json = { unparsed: text.slice(0, 200) }; }
  if (!response.ok) throw new Error(`${method} ${route} -> ${response.status} ${text.slice(0, 300)}`);
  return json;
}

async function postPaymentWebhook(orderRef) {
  const eventId = `stakeholder_evt_${createHash('sha256').update(`${orderRef}:${Date.now()}`).digest('hex').slice(0, 18)}`;
  const payload = {
    amount_paise: 250000,
    brand: 'TESTCARD',
    currency: 'INR',
    event_id: eventId,
    event_type: 'paid',
    expiry_month: 12,
    expiry_year: 2030,
    masked_last4: '4242',
    order_ref: orderRef,
    provider: 'deterministic',
    token: 'tok_test_success',
  };
  const raw = JSON.stringify(payload, Object.keys(payload).sort());
  const signature = createHmac('sha256', PAY_KEY).update(Buffer.from(raw, 'utf8')).digest('hex');
  return api('POST', '/api/v1/payments/webhook', raw, {
    Accept: 'application/json',
    'Content-Type': 'application/json',
    [PAY_SIG_HEADER]: signature,
  });
}

const schools = await api('GET', '/api/v1/law-schools?page=1&page_size=6');
const schoolIds = schools.items.slice(0, 4).map((item) => item.id);
const availability = await api('GET', `/api/v1/tutors/${TUTOR_PROFILE}/availability?timezone=Asia%2FKolkata`);
const demoSlot = availability.slots.find((slot) => slot.status === 'available');
if (!demoSlot) throw new Error('No available deterministic slot for the stakeholder booking');

const browser = await chromium.launch({
  headless: true,
  args: [
    '--use-fake-device-for-media-stream',
    '--use-fake-ui-for-media-stream',
    '--autoplay-policy=no-user-gesture-required',
  ],
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  colorScheme: 'light',
  permissions: ['camera', 'microphone'],
  recordVideo: { dir: path.join(OUT, 'raw-video'), size: { width: 1280, height: 720 } },
});
const page = await context.newPage();
const video = page.video();

page.on('console', (message) => {
  if (message.type() === 'error') report.consoleErrors.push(message.text().replace(/[A-Za-z0-9_-]{80,}/g, '[REDACTED]'));
});
page.on('pageerror', (error) => report.pageErrors.push(String(error).replace(/[A-Za-z0-9_-]{80,}/g, '[REDACTED]')));
page.on('requestfailed', (request) => report.failedRequests.push({ method: request.method(), path: new URL(request.url()).pathname }));

async function pause(ms = 1300) {
  await page.waitForTimeout(ms);
}

async function chapter(number, label, route, ready) {
  await page.goto(`${WEB}${route}`, { waitUntil: 'domcontentloaded' });
  if (ready) await page.locator(ready).first().waitFor({ timeout: 20_000 });
  await page.evaluate(({ number: n, label: text }) => {
    document.querySelector('[data-stakeholder-chapter]')?.remove();
    const el = document.createElement('div');
    el.dataset.stakeholderChapter = '1';
    el.textContent = `${n} · ${text}`;
    Object.assign(el.style, {
      position: 'fixed', top: '18px', right: '22px', zIndex: '2147483647',
      padding: '11px 16px', borderRadius: '999px', color: '#fff',
      background: 'linear-gradient(135deg,#1f5d48,#5b55c9)',
      boxShadow: '0 10px 30px rgba(20,35,30,.25)', font: '700 15px system-ui',
      letterSpacing: '.01em', pointerEvents: 'none',
    });
    document.body.appendChild(el);
  }, { number, label });
  await pause(900);
  const filename = `${String(number).padStart(2, '0')}_${label.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '')}.png`;
  await page.screenshot({ path: path.join(OUT, 'screenshots', filename), fullPage: false });
  report.chapters.push({ number, label, route, screenshot: `screenshots/${filename}` });
  await pause(1000);
  await page.evaluate(() => document.querySelector('[data-stakeholder-chapter]')?.remove());
}

// Wave 1 — registration, validation, profile and privacy.
await chapter(1, 'Login and registration', '/s-03', 'text=LegalSaathi');
await page.getByRole('tab', { name: 'Register as student' }).click();
await page.getByLabel('First name').fill('Aarav');
await page.getByLabel('Middle name').fill('Demo');
await page.getByLabel('Last name').fill('Sharma');
await page.getByLabel('Mobile number').fill('9000000007');
await page.getByLabel('Date of birth').fill('2002-06-15');
await page.getByLabel('Information about name and guardian consent').hover();
await pause(1200);
await page.screenshot({ path: path.join(OUT, 'screenshots', '02_registration_form_and_privacy_tooltip.png') });
report.chapters.push({ number: 2, label: 'Registration form and privacy tooltip', route: '/s-05', screenshot: 'screenshots/02_registration_form_and_privacy_tooltip.png' });
await chapter(3, 'Profile onboarding', '/s-09', 'h1');
await chapter(4, 'Student dashboard', '/s-14', 'h1');
await chapter(5, 'Profile and verification', '/s-17', 'h1');
await chapter(6, 'Privacy preferences', '/s-19', 'h1');

// Law-school discovery and comparison.
await chapter(7, 'Law school discovery', '/s-27', 'h1');
const schoolSearch = page.locator('input[type="search"]').first();
if (await schoolSearch.count()) {
  await schoolSearch.fill('National');
  await pause(900);
  await schoolSearch.fill('');
}
await chapter(8, 'Verified school detail', `/s-28?id=${schoolIds[0]}`, 'h1');
await chapter(9, 'Four-school comparison', `/s-29?ids=${schoolIds.join(',')}`, 'text=Your 4 picks, side by side.');
await page.mouse.wheel(0, 520);
await pause(1000);
await chapter(10, 'Saved and followed schools', '/s-30', 'h1');

// Wave 2 — real tutor discovery, booking, payment and session.
await chapter(11, 'Find a mentor', '/s-31', 'article');
await chapter(12, 'Mentor profile and availability', `/s-32?tutor=${TUTOR_PROFILE}`, 'h1');
await chapter(13, 'Ten-minute booking hold', `/s-33?slot=${demoSlot.slot_id}&tutor=${TUTOR_PROFILE}`, 'div.tt-hold[role="timer"]');

const orderResponse = page.waitForResponse(
  (response) => response.url().includes('/api/v1/payments/orders') && response.request().method() === 'POST',
);
await page.locator('button.tt-btn--jade', { hasText: /securely/i }).click();
const order = await (await orderResponse).json();
await page.getByText(/Order reference|Waiting for the provider/).first().waitFor({ timeout: 20_000 });
await pause(1000);
await page.screenshot({ path: path.join(OUT, 'screenshots', '14_payment_order_and_masked_card.png') });
report.chapters.push({ number: 14, label: 'Payment order and masked test card', route: '/s-33', screenshot: 'screenshots/14_payment_order_and_masked_card.png' });

await postPaymentWebhook(order.provider_order_ref);
const sessionResponse = page.waitForResponse(
  (response) => response.url().includes('/api/v1/tutoring/sessions') && response.request().method() === 'POST',
);
await page.locator('button.tt-btn--jade', { hasText: /Check payment and confirm/i }).click();
const session = await (await sessionResponse).json();
await page.getByRole('link', { name: 'View your confirmed session' }).waitFor({ timeout: 20_000 });
await pause(1100);
await page.screenshot({ path: path.join(OUT, 'screenshots', '15_payment_approved.png') });
report.chapters.push({ number: 15, label: 'Payment approved and session created', route: '/s-33', screenshot: 'screenshots/15_payment_approved.png' });

await chapter(16, 'Booking receipt', `/s-34?session=${session.id}`, 'h1');
await chapter(17, 'Session management', `/s-35?session=${session.id}&view=manage`, 'h1');
await chapter(18, 'Camera and microphone check', `/s-35?session=${session.id}&view=prejoin`, 'div.tt-preview');
await page.getByRole('button', { name: /Test camera and microphone/i }).click();
await page.getByRole('button', { name: /Enter the room/i }).waitFor({ timeout: 20_000 });
await pause(1200);

// A second real browser context joins as the owning mentor. Its API headers are
// rewritten at the network boundary; no production component is replaced.
const tutorContext = await browser.newContext({
  viewport: { width: 1280, height: 800 },
  permissions: ['camera', 'microphone'],
});
await tutorContext.route(`${API}/api/v1/**`, async (route) => {
  const original = route.request().headers();
  await route.continue({ headers: { ...original, 'x-actor-claims': tutorClaims } });
});
const tutorPage = await tutorContext.newPage();
await tutorPage.goto(`${WEB}/s-35?session=${session.id}&view=room`, { waitUntil: 'domcontentloaded' });
await tutorPage.getByText('In the room', { exact: true }).waitFor({ timeout: 30_000 });

await page.getByRole('button', { name: /Enter the room/i }).click();
await page.getByText('In the room', { exact: true }).waitFor({ timeout: 30_000 });
await page.locator('video[aria-label^="Video from participant"]').waitFor({ timeout: 30_000 });
await pause(2200);
await page.screenshot({ path: path.join(OUT, 'screenshots', '19_livekit_two_participant_video_room.png') });
report.chapters.push({ number: 19, label: 'LiveKit two-participant video room', route: `/s-35?session=${session.id}&view=room`, screenshot: 'screenshots/19_livekit_two_participant_video_room.png' });

await page.getByRole('button', { name: 'Session, connection and privacy details' }).click();
await pause(1000);
await page.screenshot({ path: path.join(OUT, 'screenshots', '20_video_privacy_and_connection_details.png') });
report.chapters.push({ number: 20, label: 'Video privacy and connection details', route: `/s-35?session=${session.id}&view=room`, screenshot: 'screenshots/20_video_privacy_and_connection_details.png' });
await page.keyboard.press('Escape');
await page.getByRole('button', { name: 'Mute microphone' }).click();
await page.getByRole('button', { name: 'Turn camera off' }).click();
await pause(1000);
await page.getByRole('button', { name: 'Unmute microphone' }).click();
await page.getByRole('button', { name: 'Turn camera on' }).click();
await pause(1500);

await tutorContext.close();
await chapter(21, 'Cancellation and refund policy', `/s-35?session=${session.id}&view=policy`, 'h2');
await chapter(22, 'Attendance confirmation', `/s-35?session=${session.id}&view=attendance`, '.tt-banner');
await chapter(23, 'Review eligibility and moderation', `/s-35?session=${session.id}&view=review`, '.tt-banner');

// Wave 3 — private credential evidence, issuer verification and public share.
await chapter(24, 'Credential wallet', '/s-82', 'h1');
await chapter(25, 'Add a private credential', '/s-83', 'h1');
await page.getByLabel('Credential title').fill(`Stakeholder Moot Court Certificate ${Date.now().toString().slice(-5)}`);
await page.getByLabel('Credential type').selectOption('moot_achievement');
await page.getByLabel('Issue date').fill('2026-01-15');
await page.getByLabel('Expiry date').fill('2028-01-15');
await page.getByLabel('Issuer').selectOption(ISSUER);
await page.getByLabel('Credential identifier').fill(`DEMO-${Date.now().toString().slice(-8)}`);
await page.getByLabel('Choose evidence').setInputFiles({
  name: 'stakeholder-demo-certificate.pdf',
  mimeType: 'application/pdf',
  buffer: Buffer.from('%PDF-1.7\nLegalSaathi stakeholder demo evidence'),
});
await page.getByRole('button', { name: 'Save credential' }).click();
await page.waitForURL(/\/s-84\?credential=/, { timeout: 30_000 });
const credentialId = new URL(page.url()).searchParams.get('credential');
await page.getByText('pending verification', { exact: true }).waitFor();
await pause(1200);
await page.screenshot({ path: path.join(OUT, 'screenshots', '26_credential_pending_verification.png') });
report.chapters.push({ number: 26, label: 'Credential pending verification', route: `/s-84?credential=${credentialId}`, screenshot: 'screenshots/26_credential_pending_verification.png' });
await page.getByRole('button', { name: 'Verify credential' }).click();
await page.getByText('verified', { exact: true }).waitFor({ timeout: 20_000 });
await page.getByRole('link', { name: 'Create share link' }).click();
await page.waitForURL(/\/s-85\?credential=/);
await page.getByLabel('Include my name (explicit consent)').check();
await page.getByRole('button', { name: 'Create QR & secure link' }).click();
await page.getByRole('img', { name: /QR code for https:/ }).waitFor({ timeout: 20_000 });
await pause(1500);
await page.screenshot({ path: path.join(OUT, 'screenshots', '27_credential_qr_and_secure_share.png') });
report.chapters.push({ number: 27, label: 'Credential QR and secure share', route: `/s-85?credential=${credentialId}`, screenshot: 'screenshots/27_credential_qr_and_secure_share.png' });

await page.evaluate(() => {
  const el = document.createElement('div');
  el.textContent = 'LegalSaathi · verified journeys from registration to trusted collaboration';
  Object.assign(el.style, {
    position: 'fixed', inset: '0', zIndex: '2147483647', display: 'grid', placeItems: 'center',
    color: '#fff', background: 'linear-gradient(135deg,#142e25,#38346d)',
    font: '700 30px/1.35 system-ui', textAlign: 'center', padding: '15vw',
  });
  document.body.appendChild(el);
});
await pause(2600);

report.completedAt = new Date().toISOString();
report.sessionId = session.id;
report.credentialId = credentialId;
await writeFile(path.join(OUT, 'walkthrough-report.json'), `${JSON.stringify(report, null, 2)}\n`, 'utf8');
await context.close();
const rawVideo = await video.path();
const finalVideo = path.join(OUT, 'LegalSaathi_End_to_End_Stakeholder_Demo.webm');
await rename(rawVideo, finalVideo);
await browser.close();
console.log(JSON.stringify({
  video: finalVideo,
  screenshots: report.chapters.length,
  sessionId: session.id,
  credentialId,
  consoleErrors: report.consoleErrors.length,
  pageErrors: report.pageErrors.length,
  failedRequests: report.failedRequests.length,
}, null, 2));

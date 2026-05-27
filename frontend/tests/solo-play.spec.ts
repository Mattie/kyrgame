import { expect, test, type Page } from '@playwright/test';

import { adminToken, apiBaseUrl } from './e2eConfig';

const consolePane = (page: Page) => page.locator('.crt');
const consoleLines = (page: Page) => consolePane(page).locator('.crt-line');
const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

const patchPlayer = async (page: Page, playerId: string, data: Record<string, unknown>) => {
  const response = await page.request.patch(`${apiBaseUrl}/admin/players/${playerId}`, {
    data,
    headers: {
      Authorization: `Bearer ${adminToken}`,
      'Content-Type': 'application/json',
    },
  });
  if (!response.ok()) {
    throw new Error(
      `Admin player update failed for ${playerId}: ${response.status()} ${await response.text()}`
    );
  }
};

const startSession = async (page: Page, playerId: string, roomId?: string) => {
  const sessionResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === 'POST' &&
      new URL(response.url()).pathname === '/auth/session'
  );
  const websocketPromise = page.waitForEvent('websocket');

  await page.getByLabel('Player ID').fill(playerId);
  await page.getByLabel('Room ID (optional)').fill(roomId ?? '');
  await page.getByRole('button', { name: /start session/i }).click();

  const response = await sessionResponsePromise;
  if (!response.ok()) {
    throw new Error(`Session start failed: ${response.status()} ${await response.text()}`);
  }
  const websocket = await websocketPromise;
  await websocket.waitForEvent('framereceived', { timeout: 10000 });
  await expect(page.locator('.connection-pill.connected')).toBeVisible({ timeout: 10000 });
};

const runCommand = async (
  page: Page,
  command: string,
  expectedText: string | RegExp
) => {
  const crt = consolePane(page);
  const lines = consoleLines(page);
  const input = page.getByLabel('command input');
  const commandEcho = new RegExp(`>\\s*${escapeRegExp(command.split(/\s+/)[0])}`, 'i');
  const commandEchoCount = await lines.filter({ hasText: commandEcho }).count();

  await input.fill(command);
  await input.press('Enter');
  await expect
    .poll(() => lines.filter({ hasText: commandEcho }).count(), { timeout: 10000 })
    .toBeGreaterThan(commandEchoCount);
  await expect(crt).toContainText(expectedText, { timeout: 10000 });

  if (typeof expectedText === 'string' && /^(at|in|near|on)\s/i.test(expectedText)) {
    await expect(page.locator('.mud-header h2')).toContainText(expectedText, { timeout: 10000 });
  }
};

test('solo player can start, run core adventure commands, and resume persisted room state', async ({ page }) => {
  const playerId = `solo${String(Date.now()).slice(-6)}`;
  const crt = consolePane(page);

  await page.goto('/');
  await page.evaluate(() => localStorage.clear());

  await startSession(page, playerId, '12');
  await expect(crt).toContainText('at a bubbling brook');
  await expect(crt).toContainText('garnet');
  await expect(crt).toContainText('pearl');
  await expect(page.locator('.hud-panel')).toHaveCount(0);

  await patchPlayer(page, playerId, {
    grant_all_spells: true,
    gold: 7,
    gpobjs: ['emerald', 'elixir', 'potion', 'dagger', 'sword'],
  });

  await startSession(page, playerId, '12');
  await runCommand(page, 'look', 'at a bubbling brook');
  await runCommand(page, 'west', 'in a dark forest');
  await runCommand(page, 'east', 'at a bubbling brook');
  await runCommand(page, 'north', 'in a dark forest');
  await runCommand(page, 'south', 'at a bubbling brook');
  await runCommand(page, 'get garnet', /garnet/i);
  await runCommand(page, 'inv', /garnet/i);
  await runCommand(page, 'drop garnet', /garnet/i);
  await runCommand(page, 'help', /Help is available/i);
  await runCommand(page, 'brief', /brief/i);
  await runCommand(page, 'unbrief', /full/i);
  await runCommand(page, 'check', /But what/i);
  await runCommand(page, 'what?', /WHAT\?\?/i);
  await runCommand(page, 'count gold', /gold piece/i);
  await runCommand(page, 'gold', /7 gold pieces/i);
  await runCommand(page, 'hits', /hit points/i);
  await runCommand(page, 'pray', /Goddess Tashanna/i);
  await runCommand(page, 'rub emerald', /Ooooookay/i);
  await runCommand(page, 'drink elixir', /Tastes great/i);
  await runCommand(page, 'swallow potion', /Tastes great/i);
  await runCommand(page, 'aim dagger', /At who/i);
  await runCommand(page, 'point sword', /At who/i);
  await runCommand(page, 'fly', /power of flight/i);
  await runCommand(page, 'blink', /Blink!/i);
  await runCommand(page, 'cheer for Tashanna', /for Tashanna/i);
  await runCommand(page, 'comfort', /Comfort who or what/i);
  await runCommand(page, 'think', /Okay, if you say so/i);
  await runCommand(page, 'say hello', 'hello');
  await runCommand(page, 'read spellbook', /whereami/i);
  await runCommand(page, 'memorize whereami', /master.*whereami/i);
  await runCommand(page, 'spells', /"whereami" memorized/i);
  await runCommand(page, 'cast whereami', /coordinate 12/i);
  await runCommand(page, 'frobnicate', /Huh\?/i);
  await runCommand(page, 'north', 'in a dark forest');
  await runCommand(page, 'memorize whereami', /master.*whereami/i);
  await runCommand(page, 'cast whereami', /coordinate 75/i);

  await page.getByLabel('Room ID (optional)').fill('');
  await page.reload();
  await startSession(page, playerId);
  await expect(crt).toContainText('in a dark forest');
  await expect(page.locator('.hud-panel')).toHaveCount(0);
});

test('multiplayer command fan-out renders direct target room and nearby output', async ({ page, context }) => {
  const suffix = String(Date.now()).slice(-6);
  const heroId = `hero${suffix}`;
  const seerId = `seer${suffix}`;
  const observerId = `watch${suffix}`;
  const nearbyId = `near${suffix}`;
  const hero = page;
  const seer = await context.newPage();
  const observer = await context.newPage();
  const nearby = await context.newPage();

  for (const targetPage of [hero, seer, observer, nearby]) {
    await targetPage.goto('/');
    await targetPage.evaluate(() => localStorage.clear());
  }

  await startSession(hero, heroId, '0');
  await patchPlayer(hero, heroId, {
    gold: 5,
    gpobjs: ['ruby', 'emerald', 'garnet'],
  });
  await startSession(hero, heroId, '0');
  await startSession(seer, seerId, '0');
  await startSession(observer, observerId, '0');
  await startSession(nearby, nearbyId, '1');

  await runCommand(hero, `give 2 gold to ${seerId}`, /Ok, done/i);
  await expect(consolePane(seer)).toContainText(/given you 2 gold pieces/i, { timeout: 10000 });
  await expect(consolePane(observer)).toContainText(/given .* 2 gold pieces/i, { timeout: 10000 });

  await runCommand(hero, `hand ${seerId} emerald`, /Ok, done/i);
  await expect(consolePane(seer)).toContainText(/handed you an .*emerald/i, { timeout: 10000 });
  await expect(consolePane(observer)).toContainText(/handed .* an .*emerald/i, { timeout: 10000 });

  await runCommand(hero, `pass ${seerId} garnet`, /Ok, done/i);
  await expect(consolePane(seer)).toContainText(/passed you a .*garnet/i, { timeout: 10000 });
  await expect(consolePane(observer)).toContainText(/passed .* a .*garnet/i, { timeout: 10000 });

  await runCommand(hero, `toss ${seerId} ruby`, /Ok, done/i);
  await expect(consolePane(seer)).toContainText(/tossed you a .*ruby/i, { timeout: 10000 });
  await expect(consolePane(observer)).toContainText(/tossed .* a .*ruby/i, { timeout: 10000 });

  await runCommand(hero, `whisper ${seerId} hush`, /hears you/i);
  await expect(consolePane(seer)).toContainText(/whispers to you: hush/i, { timeout: 10000 });

  await runCommand(hero, `wink ${seerId}`, /wink slyly/i);
  await expect(consolePane(seer)).toContainText(/winked slyly at you/i, { timeout: 10000 });

  await runCommand(hero, `kiss ${seerId}`, /Consider it done/i);
  await expect(consolePane(seer)).toContainText(/has just given you a kiss/i, { timeout: 10000 });
  await expect(consolePane(observer)).toContainText(/just given .* a kiss/i, { timeout: 10000 });

  await runCommand(hero, 'yell parity', /loud about it/i);
  await expect(consolePane(nearby)).toContainText(/PARITY/i, { timeout: 10000 });

  await runCommand(hero, `shove ${seerId} north`, /caught/i);
  await expect(consolePane(seer)).toContainText(/has just shoved you north/i, { timeout: 10000 });
  await expect(consolePane(nearby)).toContainText(/been shoved from the south/i, { timeout: 10000 });
});

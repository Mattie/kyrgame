import { expect, test, type Page } from '@playwright/test';

import { adminToken, apiBaseUrl } from './e2eConfig';

const consolePane = (page: Page) => page.locator('.crt');
const consoleLines = (page: Page) => consolePane(page).locator('.crt-line');
const escapeRegExp = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

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

  const grantResponse = await page.request.patch(`${apiBaseUrl}/admin/players/${playerId}`, {
    data: { grant_all_spells: true },
    headers: {
      Authorization: `Bearer ${adminToken}`,
      'Content-Type': 'application/json',
    },
  });
  if (!grantResponse.ok()) {
    throw new Error(`Grant-all admin update failed: ${grantResponse.status()} ${await grantResponse.text()}`);
  }

  await startSession(page, playerId, '12');
  await runCommand(page, 'look', 'at a bubbling brook');
  await runCommand(page, 'west', 'in a dark forest');
  await runCommand(page, 'east', 'at a bubbling brook');
  await runCommand(page, 'north', 'in a dark forest');
  await runCommand(page, 'south', 'at a bubbling brook');
  await runCommand(page, 'get garnet', /garnet/i);
  await runCommand(page, 'inv', /garnet/i);
  await runCommand(page, 'drop garnet', /garnet/i);
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

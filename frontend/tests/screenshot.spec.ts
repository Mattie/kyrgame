import { expect, test } from '@playwright/test';

test('capture MudConsole screenshot', async ({ page }) => {
  const playerId = `shot${String(Date.now()).slice(-4)}`;

  await page.goto('/');
  await page.evaluate(() => localStorage.clear());

  await page.getByLabel('Player ID').fill(playerId);
  await page.getByLabel('Room ID (optional)').fill('12');
  await page.getByRole('button', { name: /start session/i }).click();

  await expect(page.locator('.connection-pill.connected')).toBeVisible({ timeout: 10000 });
  await expect(page.locator('.crt')).toContainText('at a bubbling brook');
  await expect(page.locator('.hud-panel')).toHaveCount(0);

  await page.screenshot({ 
    path: 'screenshots/mudconsole-ui.png',
    fullPage: true 
  });
});

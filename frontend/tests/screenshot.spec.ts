import { expect, test } from '@playwright/test';

test('capture public site and MudConsole screenshots', async ({ page }) => {
  const playerId = 'hero';

  await page.goto('/');
  await page.evaluate(() => localStorage.clear());
  await expect(page.getByRole('heading', { name: 'Kyrandia' })).toBeVisible();
  await expect(page.getByRole('link', { name: /start playing/i })).toBeVisible();
  await page.screenshot({
    path: 'screenshots/landing-page.png',
    fullPage: true,
  });

  await page.goto('/leaderboard');
  await expect(page.getByRole('heading', { name: /leaderboard/i })).toBeVisible();
  await page.screenshot({
    path: 'screenshots/leaderboard-page.png',
    fullPage: true,
  });

  await page.goto('/enter');
  await page.getByLabel('Player ID').fill(playerId);
  await page.getByRole('button', { name: /start session/i }).click();

  await expect(page).toHaveURL(/\/play$/);
  await expect(page.locator('.connection-pill.connected')).toBeVisible({ timeout: 10000 });
  await expect(page.locator('.crt')).not.toBeEmpty({ timeout: 10000 });
  await expect(page.locator('.hud-panel')).toHaveCount(0);
  await expect(page.getByTestId('game-panel-fire-border')).toBeVisible();

  const readFireBorderStats = () =>
    page.getByTestId('game-panel-fire-border').evaluate((node) => {
      const canvas = node as HTMLCanvasElement;
      const context = canvas.getContext('2d');
      if (!context || canvas.width === 0 || canvas.height === 0) {
        return {
          borderAlpha: 0,
          centerAlpha: 0,
          cornerAlpha: 0,
          width: canvas.width,
          height: canvas.height,
        };
      }

      const { width, height } = canvas;
      const pixels = context.getImageData(0, 0, width, height).data;
      const border = Math.floor(Math.min(width, height) * 0.1);
      const centerLeft = Math.floor(width * 0.36);
      const centerRight = Math.floor(width * 0.64);
      const centerTop = Math.floor(height * 0.36);
      const centerBottom = Math.floor(height * 0.64);
      let borderAlpha = 0;
      let centerAlpha = 0;
      let cornerAlpha = 0;

      for (let y = 0; y < height; y += 4) {
        for (let x = 0; x < width; x += 4) {
          const alpha = pixels[(y * width + x) * 4 + 3];
          const isCorner =
            (x < border && y < border) ||
            (x >= width - border && y < border) ||
            (x < border && y >= height - border) ||
            (x >= width - border && y >= height - border);

          if (alpha >= 12) {
            if (x < border || x >= width - border || y < border || y >= height - border) {
              borderAlpha += 1;
            }
            if (x >= centerLeft && x <= centerRight && y >= centerTop && y <= centerBottom) {
              centerAlpha += 1;
            }
          }
          if (isCorner && alpha >= 12) {
            cornerAlpha += 1;
          }
        }
      }

      return { borderAlpha, centerAlpha, cornerAlpha, width, height };
    });

  await expect.poll(async () => (await readFireBorderStats()).borderAlpha, {
    timeout: 10000,
  }).toBeGreaterThan(80);

  const fireStats = await readFireBorderStats();
  expect(fireStats.centerAlpha).toBeGreaterThan(120);
  expect(fireStats.cornerAlpha).toBeLessThan(fireStats.borderAlpha * 0.35);

  await page.screenshot({ 
    path: 'screenshots/player-console.png',
    fullPage: true 
  });
});

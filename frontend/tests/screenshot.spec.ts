import { test } from '@playwright/test';

test('capture MudConsole screenshot', async ({ page }) => {
  // Navigate to the app
  await page.goto('/');
  
  // Wait for the page to load
  await page.waitForLoadState('networkidle');
  
  // Wait a bit for any animations or content to settle
  await page.waitForTimeout(1000);
  
  // Take a full-page screenshot
  await page.screenshot({ 
    path: 'screenshots/mudconsole-ui.png',
    fullPage: true 
  });
});

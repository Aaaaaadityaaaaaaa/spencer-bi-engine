import { test, expect } from '@playwright/test';
import path from 'path';

test.describe.configure({ mode: 'serial' });

test.describe('7. Canvas & Dashboard System', () => {
  const userEmail = `canvas_test_${Date.now()}@example.com`;
  const password = 'TestPassword123!';

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await page.goto('http://localhost:5173/login');
    await page.getByRole('button', { name: 'Register', exact: true }).first().click();
    await page.fill('input[type="email"]', userEmail);
    await page.fill('input[type="password"]', password);

    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/.*\/table/, { timeout: 10000 });

    // Upload dirty data
    const filePath = path.join(process.cwd(), 'e2e', 'fixtures', 'dirty_data.csv');
    await page.setInputFiles('input[type="file"]', filePath);
    await expect(page.getByText('dirty_data.csv', { exact: false })).toBeVisible({ timeout: 15000 });
  
    
    
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: 'Sign in', exact: true }).first().click();
    await page.fill('input[type="email"]', userEmail);
    await page.fill('input[type="password"]', password);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/.*\/table/, { timeout: 10000 });
    
    // Navigate to Canvas
    await page.getByRole('link', { name: 'Canvas' }).click();
    await expect(page).toHaveURL(/.*\/canvas/);
  });

  test('7.1 Chart Creation', async ({ page }) => {
    // There might be auto-seeded charts
    
    // Click Add Chart
    await page.getByRole('button', { name: 'Add chart' }).click();
    
    // Click Add KPI
    await page.getByRole('button', { name: 'Add KPI' }).click();
    
    // At least 2 tiles should be on the canvas
    await expect(page.locator('.grid-item')).toHaveCount(2);
  });

  test('7.2 Chart Settings Drawer', async ({ page }) => {
    // Click the first tile to open settings drawer
    await page.locator('.grid-item').first().click();
    
    // Wait for drawer
    await expect(page.locator('text=Data & Mapping')).toBeVisible();
    
    // Change Chart Type
    await page.locator('select').first().selectOption('pie');
    
    // Drawer should still be open
    await expect(page.locator('text=Data & Mapping')).toBeVisible();
  });

  test('7.7 Multi-Page Dashboards', async ({ page }) => {
    // Add page
    await page.getByRole('button', { name: '+' }).click(); // The plus button for tabs
    
    // Check new tab exists
    await expect(page.locator('text=Page 2')).toBeVisible();
  });
});

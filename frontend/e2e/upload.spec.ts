import { test, expect } from '@playwright/test';
import path from 'path';

test.describe.configure({ mode: 'serial' });

test.describe('2. Data Ingestion & Upload', () => {
  const userEmail = `upload_test_${Date.now()}@example.com`;
  const password = 'TestPassword123!';

  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await page.goto('http://localhost:5173/login');
    await page.getByRole('button', { name: 'Register', exact: true }).first().click();
    await page.fill('input[type="email"]', userEmail);
    await page.fill('input[type="password"]', password);

    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/.*\/table/, { timeout: 10000 });
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: 'Sign in', exact: true }).first().click();
    await page.fill('input[type="email"]', userEmail);
    await page.fill('input[type="password"]', password);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/.*\/table/, { timeout: 10000 });
  });

  test('2.1 File Upload - Happy Path (CSV)', async ({ page }) => {
    // Wait for dropzone to be visible
    await expect(page.locator('text=Drag & drop a file here')).toBeVisible();
    
    // Upload file
    const filePath = path.join(__dirname, 'fixtures', 'test_data.csv');
    // Using setInputFiles on the hidden file input
    await page.setInputFiles('input[type="file"]', filePath);
    
    // Expect the file to upload and the grid to render
    // The data grid should eventually show "Alice", "Bob", "Charlie"
    await expect(page.locator('text=Alice')).toBeVisible({ timeout: 15000 });
    await expect(page.locator('text=Bob')).toBeVisible();
    
    // The dataset name should be visible in the table switcher or bar
    await expect(page.locator('text=test_data.csv')).toBeVisible();
  });
});

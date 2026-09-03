import { test, expect } from '@playwright/test';
import path from 'path';

test.describe.configure({ mode: 'serial' });

test.describe('2. Data Ingestion & Upload', () => {
  const userEmail = `upload_test_${Date.now()}@example.com`;
  const password = 'TestPassword123!';

  let page: any;
  test.beforeAll(async ({ browser }) => {
    page = await browser.newPage();
    await page.goto('http://localhost:5173/login');
    await page.getByRole('button', { name: 'Register', exact: true }).first().click();
    await page.fill('input[type="email"]', userEmail);
    await page.fill('input[type="password"]', password);

    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/.*\/table/, { timeout: 10000 });
  });


  test('2.1 File Upload - Happy Path (CSV)', async () => {
    // Wait for dropzone to be visible
    await expect(page.getByText('Drag and drop, or click to browse', { exact: false })).toBeVisible();
    
    // Upload file
    const filePath = path.join(process.cwd(), 'e2e', 'fixtures', 'test_data.csv');
    // Using setInputFiles on the hidden file input
    await page.setInputFiles('input[type="file"]', filePath);
    
    // Expect the file to upload and the grid to render
    // The data grid should eventually show "Alice", "Bob", "Charlie"
    await expect(page.getByText('Alice', { exact: false })).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('Bob', { exact: false })).toBeVisible();
    
    // The dataset name should be visible in the table switcher or bar
    await expect(page.locator('text=test_data.csv')).toBeVisible();
  });
});

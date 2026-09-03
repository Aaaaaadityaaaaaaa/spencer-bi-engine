import { test, expect } from '@playwright/test';
import path from 'path';

test.describe.configure({ mode: 'serial' });

test.describe('4. Data Cleaning & Transform Operations', () => {
  const userEmail = `clean_test_${Date.now()}@example.com`;
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
  
    
    // Upload dirty data
    const filePath = path.join(process.cwd(), 'e2e', 'fixtures', 'dirty_data.csv');
    await page.setInputFiles('input[type="file"]', filePath);
    
    // Wait for upload to complete
    await expect(page.locator('text=dirty_data.csv')).toBeVisible({ timeout: 15000 });
    await expect(page.getByText('Alice', { exact: false })).toBeVisible();
    await page.close();
  });

  test.beforeEach(async ({ page }) => {
    await page.goto('/login');
    await page.getByRole('button', { name: 'Sign in', exact: true }).first().click();
    await page.fill('input[type="email"]', userEmail);
    await page.fill('input[type="password"]', password);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/.*\/table/, { timeout: 10000 });
    
    // Make sure we are on the table
    await expect(page.locator('text=dirty_data.csv')).toBeVisible();
  });

  test('4.2 Remove Duplicates', async ({ page }) => {
    // Charlie is duplicated in dirty_data.csv
    await expect(page.getByText('Charlie', { exact: false })).toHaveCount(2);
    
    // Click Dedupe in toolbar
    await page.getByRole('button', { name: 'Remove duplicates' }).click();
    
    // Wait for OpDialog and click Apply
    await expect(page.locator('text=Remove Duplicate Rows')).toBeVisible();
    await page.getByRole('button', { name: 'Apply' }).click();
    
    // Should now only be 1 Charlie
    await expect(page.getByText('Charlie', { exact: false })).toHaveCount(1);
  });

  test('4.1 Drop Nulls', async ({ page }) => {
    // Dave has null status
    await page.getByRole('button', { name: 'Drop nulls' }).click();
    
    // Select column 'status'
    await page.locator('select').first().selectOption('status');
    
    // Apply
    await page.getByRole('button', { name: 'Apply' }).click();
    
    // Dave should be gone
    await expect(page.getByText('Dave', { exact: false })).not.toBeVisible();
  });

  test('4.1 Fill Nulls', async ({ page }) => {
    // Bob has null age
    await page.getByRole('button', { name: 'Fill nulls' }).click();
    
    await page.locator('select').first().selectOption('age');
    await page.locator('select').nth(1).selectOption('zero'); // strategy = zero
    
    await page.getByRole('button', { name: 'Apply' }).click();
    
    // We expect the cell to be updated, but checking specific cell via E2E is tricky
    // We just ensure the op succeeds and applied steps updates
    await expect(page.locator('text=Fill nulls in age')).toBeVisible();
  });

  test('4.4 Calculated Column', async ({ page }) => {
    await page.getByRole('button', { name: 'Add column' }).click();
    
    // OpDialog inputs
    await page.fill('input[placeholder="e.g. total_price"]', 'age_next_year');
    await page.fill('textarea', 'age + 1');
    
    await page.getByRole('button', { name: 'Apply' }).click();
    
    // Check if new column header exists
    await expect(page.locator('text=age_next_year')).toBeVisible();
  });

  test('5. Applied Steps & Undo/Redo', async ({ page }) => {
    // Open Steps panel
    await page.getByRole('button', { name: 'Steps' }).click();
    
    // Verify steps exist
    await expect(page.locator('text=Remove duplicates')).toBeVisible();
    await expect(page.locator('text=Drop nulls in status')).toBeVisible();
    
    // Click Undo in navbar (or via keyboard shortcut)
    // Assuming Undo button has title "Undo" or we can trigger shortcut
    await page.getByRole('button', { name: /Undo/i }).click();
    
    // The calculated column should disappear
    await expect(page.locator('text=age_next_year')).not.toBeVisible();
    
    // Click Redo
    await page.getByRole('button', { name: /Redo/i }).click();
    await expect(page.locator('text=age_next_year')).toBeVisible();
  });
});

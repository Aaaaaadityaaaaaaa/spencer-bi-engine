import { test, expect } from '@playwright/test';

test.describe.configure({ mode: 'serial' });

test.describe('1. Authentication & Security', () => {
  const userEmail = `test_${Date.now()}@example.com`;
  const password = 'TestPassword123!';

  test('1.1 Registration - Happy Path', async ({ page }) => {
    await page.goto('/login');
    
    // Switch to register tab
    await page.getByRole('button', { name: 'Register', exact: true }).first().click();
    
    // Fill out form
    await page.fill('input[type="email"]', userEmail);
    await page.fill('input[type="password"]', password);

    
    // Submit form
    await page.locator('button[type="submit"]').click();
    
    // Expect to be redirected to /table
    await expect(page).toHaveURL(/.*\/table/, { timeout: 10000 });
  });

  test('1.1 Registration - Duplicate Email', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => localStorage.clear());
    await page.goto('/login');
    
    await page.getByRole('button', { name: 'Register', exact: true }).first().click();
    
    await page.fill('input[type="email"]', userEmail);
    await page.fill('input[type="password"]', password);

    
    await page.locator('button[type="submit"]').click();
    
    // Expect error message
    await expect(page.locator('text=already registered')).toBeVisible();
  });

  test('1.2 Login - Wrong Password', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => localStorage.clear());
    await page.goto('/login');
    
    await page.getByRole('button', { name: 'Sign in', exact: true }).first().click();
    
    await page.fill('input[type="email"]', userEmail);
    await page.fill('input[type="password"]', 'WrongPassword123!');
    
    await page.locator('button[type="submit"]').click();
    
    await expect(page.locator('text=Incorrect email or password')).toBeVisible();
  });
  
  test('1.2 Login - Happy Path', async ({ page }) => {
    await page.goto('/');
    await page.evaluate(() => localStorage.clear());
    await page.goto('/login');
    
    await page.getByRole('button', { name: 'Sign in', exact: true }).first().click();
    
    await page.fill('input[type="email"]', userEmail);
    await page.fill('input[type="password"]', password);
    
    await page.locator('button[type="submit"]').click();
    
    // Expect to be redirected to /table
    await expect(page).toHaveURL(/.*\/table/, { timeout: 10000 });
  });
});

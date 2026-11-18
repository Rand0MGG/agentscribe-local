// Exercise real caption controls and IPC with the existing no-audio fixture.
const assert = require('node:assert/strict');

module.exports = async function captionAccessibility(page, passed) {
  const buttons = page.locator('.caption-seek');
  assert.equal(await buttons.count(), 650);
  assert.equal(await page.locator('.caption-seek[tabindex="0"]').count(), 1);
  await buttons.first().focus();
  await page.keyboard.press('ArrowDown');
  assert.equal(await buttons.nth(1).evaluate(el => document.activeElement === el), true);
  await page.keyboard.press('Enter');
  await page.locator('[data-caption="2"].playing').waitFor();
  await page.getByRole('button', { name: '暂停回听', exact: true }).waitFor();
  await page.keyboard.press('End');
  assert.equal(await buttons.last().evaluate(el => document.activeElement === el), true);
  await page.keyboard.press('Space');
  await page.locator('[data-caption="650"].playing').waitFor();
  await page.keyboard.press('Home');
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.classList.contains('caption-seek')), false);
  assert.equal(await page.locator('[data-caption="1"] .source').getAttribute('lang'), 'en');
  assert.equal(await page.locator('[data-caption="1"] .translation').getAttribute('lang'), 'zh-Hans');
  passed.push('Caption replay supports one Tab entry, arrows/Home/End, Enter/Space and recording language tags');
};

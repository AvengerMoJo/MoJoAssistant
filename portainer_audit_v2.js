const { chromium } = require('playwright');

async function main() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();
  
  try {
    console.log('Navigating to Portainer...');
    await page.goto('https://docker.eclipsogate.org/', { waitUntil: 'networkidle' });

    // Fill credentials
    await page.fill("input[name='Username']", 'ahman');
    await page.fill("input[name='Password']", '0A1CEE11-AB1C-47BD-9F18-51874903C67E');
    
    // Click login button
    const submitBtn = await page.$('button[type="submit"]');
    if (submitBtn) {
      await Promise.all([
        page.waitForNavigation({ waitUntil: 'networkidle' }),
        submitBtn.click()
      ]);
    }

    console.log(`Logged in. URL: ${page.url()}`);
    
    const results = {
      loginStatus: 'success',
      containers: [],
      volumes: [],
      errors: [],
      warnings: []
    };

    // Container extraction with better selectors for Portainer 2.x
    console.log('Extracting container data...');
    await page.goto(`${page.url().split('#')[0]}#!/containers`);
    
    // Wait for containers to load and take screenshot
    await page.waitForTimeout(3000);
    await page.screenshot({ path: '/tmp/portainer_containers.png' });

    // Get all table rows from container list
    const containerRows = await page.$$('table tbody tr');
    console.log(`Found ${containerRows.length} container rows`);
    
    for (const row of containerRows) {
      try {
        let name, status;
        
        // Extract name - typically in column 2 or has specific class
        const nameEl = await row.$('.name');
        if (!nameEl) {
          const cols = await row.$$('td');
          if (cols[1]) name = await cols[1].textContent().trim();
        } else {
          name = await nameEl.textContent().trim();
        }

        // Extract status from cell or CSS class
        const statusCell = await row.$('.status-cell, .running');
        if (statusCell) {
          status = 'running';
        } else {
          const statusText = await row.evaluate(el => 
            Array.from(el.classList).find(c => c.includes('stopped') || c.includes('paused') || c.includes('restarting'))
          );
          status = statusText === 'stopped' ? 'stopped' : 
                   statusText === 'paused' ? 'paused' :
                   statusText === 'restarting' ? 'restarting' : 'unknown';
        }

        if (name) results.containers.push({ name, status });
      } catch (e) {
        console.log('Row error:', e.message);
      }
    }

    // Volume extraction
    console.log('Extracting volume data...');
    await page.goto(`${page.url().split('#')[0]}#!/volumes`);
    await page.waitForTimeout(3000);
    await page.screenshot({ path: '/tmp/portainer_volumes.png' });

    const volumeRows = await page.$$('table tbody tr');
    console.log(`Found ${volumeRows.length} volume rows`);
    
    for (const row of volumeRows) {
      try {
        let name, status;
        
        const nameEl = await row.$('.name');
        if (!nameEl) {
          const cols = await row.$$('td');
          if (cols[1]) name = await cols[1].textContent().trim();
        } else {
          name = await nameEl.textContent().trim();
        }

        // Check for in-use or unused status
        const html = await row.innerHTML();
        status = html.includes('unused') ? 'unused' : 
                 html.includes('in use') || html.includes('active') ? 'active' : 'unknown';

        if (name) results.volumes.push({ name, status });
      } catch (e) {
        console.log('Volume row error:', e.message);
      }
    }

  } catch (error) {
    console.error('Error:', error.message);
    results.error = error.message;
    await page.screenshot({ path: '/tmp/portainer_error.png' });
  }

  await browser.close();
  
  console.log('\n=== PORTAINER AUDIT RESULTS ===');
  console.log(JSON.stringify(results, null, 2));
}

main().catch(console.error);

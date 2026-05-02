const { chromium } = require('playwright');

async function main() {
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  const page = await context.newPage();

  try {
    // Navigate to Portainer login
    console.log('Navigating to Portainer...');
    await page.goto('https://docker.eclipsogate.org/', { waitUntil: 'networkidle' });

    // Fill in credentials and submit login form
    console.log('Logging in...');
    
    // Common selectors for Portainer login - try multiple approaches
    const usernameSelectors = ['#username', "input[name='Username']", "[name='Username']", "#form_username", ".loginForm input[type='text']"];
    const passwordSelectors = ['#password', "input[name='Password']", "[name='Password']", "#form_password", ".loginForm input[type='password']"];

    let usernameFieldFound = false;
    for (const selector of usernameSelectors) {
      if (await page.$(selector)) {
        await page.fill(selector, 'ahman');
        console.log('Username filled successfully');
        usernameFieldFound = true;
        break;
      }
    }

    let passwordFieldFound = false;
    for (const selector of passwordSelectors) {
      if (await page.$(selector)) {
        await page.fill(selector, '0A1CEE11-AB1C-47BD-9F18-51874903C67E');
        console.log('Password filled successfully');
        passwordFieldFound = true;
        break;
      }
    }

    if (!usernameFieldFound || !passwordFieldFound) {
      throw new Error(`Could not find login fields - username: ${usernameFieldFound}, password: ${passwordFieldFound}`);
    }

    // Submit the form
    const submitSelectors = ['#login-button', "input[type='submit']", ".btn-primary", "button[type='submit']"];
    
    let submitBtnClicked = false;
    for (const selector of submitSelectors) {
      if (await page.$(selector)) {
        await Promise.all([
          page.waitForNavigation({ waitUntil: 'networkidle' }),
          page.click(selector)
        ]);
        console.log('Login button clicked, waiting for navigation...');
        submitBtnClicked = true;
        break;
      }
    }

    if (!submitBtnClicked) {
      throw new Error('Could not find login button');
    }

    // Wait a moment and check if we're logged in by looking for dashboard elements
    await page.waitForTimeout(3000);
    
    const currentUrl = page.url();
    console.log(`Current URL: ${currentUrl}`);

    if (currentUrl.includes('login') || currentUrl.includes('error')) {
      throw new Error('Login failed - still on login page or error page');
    }

    // Now navigate to containers and volumes pages
    const results = {
      url: currentUrl,
      status: 'logged_in',
      containers: [],
      volumes: [],
      issues: [],
      warnings: []
    };

    try {
      console.log('Navigating to Containers page...');
      await page.goto(`${currentUrl.split('/')[0]}/${currentUrl.split('/')[2]}/containers`);
      await page.waitForTimeout(3000);

      // Extract container information
      const containers = [];
      
      // Try various selectors for container tables/lists
      const containerSelectors = [
        'table tbody tr',
        '.container-list table tbody tr',
        '[data-testid="container-row"]',
        '.card-container'
      ];

      let foundContainers = false;
      for (const selector of containerSelectors) {
        const rows = await page.$$(selector);
        if (rows.length > 0) {
          console.log(`Found ${rows.length} container elements via selector: ${selector}`);
          
          for (let i = 0; i < Math.min(rows.length, 50); i++) {
            try {
              const rowHtml = await rows[i].innerHTML();
              
              // Try to extract status and name from each row
              let status = 'unknown';
              if (rowHtml.includes('running') || rowHtml.match(/status="?running"?\s*$/)) {
                status = 'running';
              } else if (rowHtml.includes('stopped')) {
                status = 'stopped';
              } else if (rowHtml.includes('paused')) {
                status = 'paused';
              } else if (rowHtml.includes('restarting')) {
                status = 'restarting';
              }

              // Try to extract container name - common patterns in Portainer
              let name = 'unknown';
              const nameSelectors = [
                '[class*="container-name"]',
                '.name-column',
                '[data-testid="container-name"]',
                'td:nth-child(2) span'
              ];

              for (const nameSel of nameSelectors) {
                const nameEl = await rows[i].$(nameSel);
                if (nameEl && await nameEl.isVisible()) {
                  name = await nameEl.textContent().trim();
                  break;
                }
              }

              if (name !== 'unknown' || status === 'running') {
                containers.push({ name, status });
              }
            } catch (err) {
              console.log(`Error processing container row ${i}:`, err.message);
            }
          }
          
          foundContainers = true;
          break;
        }
      }

      if (!foundContainers && containers.length === 0) {
        // Take a screenshot and dump the page structure for debugging
        console.log('Could not find container elements, taking full page screenshot...');
        await page.screenshot({ path: '/tmp/portainer_containers.png' });
        
        // Try to get all text content
        const allText = await page.evaluate(() => document.body.innerText);
        results.containerTextDump = allText.substring(0, 5000);
      }

      results.containers = containers;

    } catch (containerError) {
      console.error('Container navigation error:', containerError.message);
      results.containerError = containerError.message;
    }

    try {
      console.log('Navigating to Volumes page...');
      await page.goto(`${currentUrl.split('/')[0]}/${currentUrl.split('/')[2]}/volumes`);
      await page.waitForTimeout(3000);

      const volumes = [];
      
      const volumeSelectors = [
        'table tbody tr',
        '.volume-list table tbody tr',
        '[data-testid="volume-row"]'
      ];

      let foundVolumes = false;
      for (const selector of volumeSelectors) {
        const rows = await page.$$(selector);
        if (rows.length > 0) {
          console.log(`Found ${rows.length} volume elements via selector: ${selector}`);
          
          for (let i = 0; i < Math.min(rows.length, 50); i++) {
            try {
              const rowHtml = await rows[i].innerHTML();
              
              let name = 'unknown';
              const nameSelectors = [
                '[class*="volume-name"]',
                '.name-column',
                '[data-testid="volume-name"]'
              ];

              for (const nameSel of nameSelectors) {
                const nameEl = await rows[i].$(nameSel);
                if (nameEl && await nameEl.isVisible()) {
                  name = await nameEl.textContent().trim();
                  break;
                }
              }

              let status = 'unknown';
              if (rowHtml.includes('in use') || rowHtml.match(/status="?active"?\s*$/)) {
                status = 'active';
              } else if (rowHtml.includes('unused')) {
                status = 'unused';
              }

              if (name !== 'unknown' || status === 'active') {
                volumes.push({ name, status });
              }
            } catch (err) {
              console.log(`Error processing volume row ${i}:`, err.message);
            }
          }
          
          foundVolumes = true;
          break;
        }
      }

      if (!foundVolumes && volumes.length === 0) {
        console.log('Could not find volume elements, taking screenshot...');
        await page.screenshot({ path: '/tmp/portainer_volumes.png' });
        
        const allText = await page.evaluate(() => document.body.innerText);
        results.volumeTextDump = allText.substring(0, 5000);
      }

      results.volumes = volumes;

    } catch (volumeError) {
      console.error('Volume navigation error:', volumeError.message);
      results.volumeError = volumeError.message;
    }

    // Check for errors/warnings on the dashboard
    try {
      await page.goto(`${currentUrl.split('/')[0]}/${currentUrl.split('/')[2]}`);
      await page.waitForTimeout(2000);
      
      const warningSelectors = [
        '.alert-warning',
        '[class*="warning"]',
        '[class*="error"]',
        '[data-testid="alert-error"]'
      ];

      for (const selector of warningSelectors) {
        const alerts = await page.$$(selector);
        if (alerts.length > 0) {
          console.log(`Found ${alerts.length} alert elements`);
          
          for (const alert of alerts) {
            try {
              const text = await alert.textContent().trim();
              if (text && text.length > 0) {
                if (text.toLowerCase().includes('error') || text.toLowerCase().includes('critical')) {
                  results.issues.push(text);
                } else if (text.toLowerCase().includes('warning') || text.toLowerCase().includes('degraded')) {
                  results.warnings.push(text);
                }
              }
            } catch (err) {
              console.log('Error reading alert:', err.message);
            }
          }
        }
      }

    } catch (alertError) {
      console.error('Alert checking error:', alertError.message);
    }

  } catch (error) {
    console.error('Automation error:', error.message);
    results.error = error.message;
    
    // Take screenshot on error
    try {
      await page.screenshot({ path: '/tmp/portainer_error.png' });
    } catch (err) {
      console.log('Screenshot failed:', err.message);
    }
  }

  await browser.close();

  // Output results as JSON
  console.log('\n=== PORTAINER AUDIT RESULTS ===');
  console.log(JSON.stringify(results, null, 2));
}

main().catch(console.error);

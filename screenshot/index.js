const Cdp = require('chrome-remote-interface');
const express = require('express');
const browserReady = require('./browser-ready');
const {spawn} = require('node:child_process');

spawn('/usr/bin/chromium-browser', ["--headless", "--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu", "--disable-software-rasterizer",
  "--disable-extensions", "--disable-component-extensions-with-background-pages",
  "--disable-background-networking", "--no-first-run", "--no-default-browser-check",
  "--user-data-dir=/tmp/edcom-chromium", "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=9222",
  "about:blank"], {
  detached: true,
  stdio: ["ignore", "ignore", "inherit"]
});

function sleep (miliseconds = 100) {
  return new Promise(resolve => setTimeout(() => resolve(), miliseconds))
}

async function captureScreenshotOfUrl (url, mobile = false, width = 580) {
  const LOAD_TIMEOUT = process.env.PAGE_LOAD_TIMEOUT || 1000 * 60

  let result
  let loaded = false

  const loading = async (startTime = Date.now()) => {
    if (!loaded && Date.now() - startTime < LOAD_TIMEOUT) {
      await sleep(100)
      await loading(startTime)
    }
  }

  const [tab] = await browserReady(() => Cdp.List({host: '127.0.0.1'}))
  const client = await Cdp({ host: '127.0.0.1', target: tab })

  const {
    Network, Page, Runtime, Emulation,
  } = client

  Network.requestWillBeSent((params) => {
    console.log('Chrome is sending request for:', params.request.url)
  })

  Page.loadEventFired(() => {
    loaded = true
  })

  try {
    await Promise.all([Network.enable(), Page.enable()])

    if (mobile) {
      await Network.setUserAgentOverride({
        userAgent:
          'Mozilla/5.0 (iPhone; CPU iPhone OS 10_0_1 like Mac OS X) AppleWebKit/602.1.50 (KHTML, like Gecko) Version/10.0 Mobile/14A403 Safari/602.1',
      })
    }

    await Emulation.setDeviceMetricsOverride({
      mobile: !!mobile,
      deviceScaleFactor: 0,
      scale: 1, // mobile ? 2 : 1,
      width: width,
      height: 0,
    })

    function delay(t) {
      return new Promise(function(resolve) {
        setTimeout(function() {
          resolve();
        }, t);
      });
    }

    await Page.navigate({ url })
    await Page.loadEventFired()
    await loading()

    await delay(3000);

    const {
      result: {
        value: { height },
      },
    } = await Runtime.evaluate({
      expression: `(
        () => ({ height: document.body.scrollHeight })
      )();
      `,
      returnByValue: true,
    })

    await Emulation.setDeviceMetricsOverride({
      mobile: !!mobile,
      deviceScaleFactor: 0,
      scale: 1, // mobile ? 2 : 1,
      width: width,
      height,
    })

    const screenshot = await Page.captureScreenshot({ format: 'png' })

    result = screenshot.data
  } catch (error) {
    console.error(error)
  }

  await client.close()

  return result
}

const app = express();
app.use(express.json());
const port = 4000;

app.post('/', (req, res) => {
  res.setHeader('content-type', 'text/plain');

  if (!req.body.url) {
    res.status(400).send("Missing url parameter");
    return;
  }
  captureScreenshotOfUrl(req.body.url, req.body.mobile || false, req.body.width || 580)
    .then(data => {
      res.status(200).send(data);
    })
    .catch(err => {
      res.status(500).send(err.toString());
    });
});

// Do not advertise HTTP readiness while the browser is still starting.
// Startup gets a bounded allowance; ordinary requests retain the short wait.
browserReady(() => Cdp.List({host: '127.0.0.1'}), {timeout: 120000})
  .then(() => app.listen(port, () => console.log(`Listening on port ${port}`)))
  .catch(error => { console.error('Chromium startup failed:', error); process.exit(1); });

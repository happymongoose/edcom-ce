// A bounded local readiness wait; do not turn a failed browser into a hung job.
module.exports = async function browserReady(list, options = {}) {
  const now = options.now || Date.now;
  const sleep = options.sleep || (ms => new Promise(resolve => setTimeout(resolve, ms)));
  const timeout = options.timeout === undefined ? 5000 : options.timeout;
  const deadline = now() + timeout;
  let lastError;
  do {
    try {
      // Chromium also exposes extension and browser-UI targets; those are not pages.
      const tabs = (await list()).filter(tab => tab.type === 'page');
      if (tabs.length) return tabs;
    } catch (error) {
      lastError = error;
    }
    if (now() >= deadline) break;
    await sleep(100);
  } while (now() <= deadline);
  throw lastError || new Error('Chromium did not become ready within ' + timeout / 1000 + ' seconds');
};

// Run inside the screenshot container. Uses an ephemeral loopback fixture only.
const assert = require('assert');
const http = require('http');
const fixture = http.createServer((req, res) => res.end('<html><body><h1>Screenshot acceptance</h1></body></html>'));
fixture.listen(0, '127.0.0.1', () => {
  const request = http.request({host: '127.0.0.1', port: 4000, method: 'POST',
    headers: {'Content-Type': 'application/json'}, timeout: 20000}, response => {
    let body = '';
    response.on('data', part => { body += part; });
    response.on('end', () => {
      fixture.closeAllConnections();
      fixture.close();
      assert.strictEqual(response.statusCode, 200, body);
      const png = Buffer.from(body, 'base64');
      assert.strictEqual(png.subarray(0, 8).toString('hex'), '89504e470d0a1a0a');
      console.log('Screenshot PNG verified:', png.length, 'bytes');
    });
  });
  request.on('timeout', () => request.destroy(new Error('Screenshot timed out')));
  request.on('error', error => { fixture.closeAllConnections(); fixture.close(); console.error(error); process.exitCode = 1; });
  request.end(JSON.stringify({url: 'http://127.0.0.1:' + fixture.address().port, width: 580}));
});

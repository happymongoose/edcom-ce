const rewire = require('rewire');
const defaults = rewire('react-scripts/scripts/start.js');
const webpackConfig = require('react-scripts/config/webpackDevServer.config.js');

defaults.__set__('createDevServerConfig', (proxy, allowedHost) => {
  let config = webpackConfig(proxy, allowedHost, {hot: false});

  config.watchOptions.watch = false;

  return config;
});

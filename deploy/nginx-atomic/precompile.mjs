/**
 * Pre-compile the inline text/babel block from new_frontend/app.html for production.
 * Skips in-browser Babel (slow on TV browsers).
 */
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import * as babel from '@babel/standalone';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const htmlPath = path.resolve(process.argv[2] || path.join(__dirname, '../../new_frontend/app.html'));
const html = fs.readFileSync(htmlPath, 'utf8');

const babelRe = /<script type="text\/babel"[^>]*>([\s\S]*?)<\/script>/i;
const match = html.match(babelRe);
const outDir = path.dirname(htmlPath);
const bundlePath = path.join(outDir, 'app.bundle.js');
if (!match) {
  if (!fs.existsSync(bundlePath)) {
    console.error('precompile: no babel block and missing', bundlePath);
    process.exit(1);
  }
  console.log('precompile: no babel block, keeping', bundlePath);
} else {
  const { code } = babel.transform(match[1], {
    presets: ['react'],
    filename: 'app.jsx',
  });
  fs.writeFileSync(bundlePath, code, 'utf8');
  console.log('precompile: compiled bundle (' + Math.round(code.length / 1024) + ' KB)');
}
const buildStamp = process.env.NF_BUILD_STAMP || String(Date.now());

const prodScripts = `  (function () {
    var p = window.location.pathname || '';
    var prefix = (p === '/accounts-stats' || p.indexOf('/accounts-stats/') === 0) ? '/accounts-stats' : '';
    window.__NF_STATIC_PREFIX = prefix;
    window.__NF_PRECOMPILED = true;
    var base = prefix + '/vendor/';
    ['react.production.min.js', 'react-dom.production.min.js'].forEach(function (f) {
      document.write('<script src="' + base + f + '"><\\/script>');
    });
    document.write('<script src="' + prefix + '/app.bundle.js?v=${buildStamp}"><\\/script>');
  })();`;

let out = match ? html.replace(babelRe, '') : html;
const loaderRe = /<script>\s*\(function \(\) \{\s*var p = window\.location\.pathname[\s\S]*?\}\)\(\);\s*<\/script>/;
if (!loaderRe.test(out)) {
  console.error('precompile: vendor loader block not found');
  process.exit(1);
}
out = out.replace(loaderRe, '<script>\n' + prodScripts.trim() + '\n</script>');

// Маркер __NF_PRECOMPILED в prod выставляется в loader выше (babel-блок уходит в app.bundle.js).
fs.writeFileSync(htmlPath, out, 'utf8');

// В bundle тоже нужен флаг до boot (document.write грузит bundle после loader).
const bundleRaw = fs.readFileSync(bundlePath, 'utf8');
if (!bundleRaw.startsWith('window.__NF_PRECOMPILED=true;')) {
  fs.writeFileSync(
    bundlePath,
    'window.__NF_PRECOMPILED=true;\n' + bundleRaw.replace(
      /window\.__NF_PRECOMPILED\s*=\s*true;\s*\n\s*window\.__nfAppMounted/g,
      'window.__nfAppMounted',
    ),
    'utf8',
  );
}
console.log('precompile: wrote', htmlPath);

// このドライバーが読む CommonJS の実ファイルとパッケージ解決だけを記録・照合する。
const Module = require('node:module');
const { createHash } = require('node:crypto');
const { existsSync, readFileSync, realpathSync, writeFileSync } = require('node:fs');
const { dirname, join, resolve } = require('node:path');

const fingerprint = path => {
  const bytes = readFileSync(path);
  return { path, bytes: bytes.length, sha256: createHash('sha256').update(bytes).digest('hex') };
};

function record(library) {
  const parent = join(library, 'package.json');
  const files = new Set();
  const resolutions = new Map();
  const originalLoad = Module._load;
  Module._load = function (request, caller, isMain) {
    const path = Module._resolveFilename(request, caller, isMain);
    if (!Module.isBuiltin(path)) {
      files.add(path);
      const from = caller.filename;
      resolutions.set(JSON.stringify([from, request]), { parent: from, request, path });
    }
    return originalLoad.apply(this, arguments);
  };
  try {
    const local = Module.createRequire(parent);
    local(library);
    const { DynamoDBClient } = local('@aws-sdk/client-dynamodb');
    const client = new DynamoDBClient({ endpoint: 'http://127.0.0.1:1', region: 'us-east-1',
      credentials: { accessKeyId: 'local', secretAccessKey: 'local' } });
    client.destroy();
  } finally {
    Module._load = originalLoad;
  }
  const scopes = new Map();
  for (const path of [...files, parent]) {
    for (let directory = dirname(path); ; directory = dirname(directory)) {
      const metadata = join(directory, 'package.json');
      const exists = existsSync(metadata);
      scopes.set(metadata, { path: metadata, exists });
      if (exists) files.add(realpathSync(metadata));
      if (dirname(directory) === directory) break;
    }
  }
  return { library, resolved_library: realpathSync(library), parent,
    files: [...files].sort().map(fingerprint), resolutions: [...resolutions.values()],
    package_scopes: [...scopes.values()] };
}

function verify(inputs, library = inputs.library) {
  if (library !== inputs.library || realpathSync(library) !== inputs.resolved_library) {
    throw new Error(`JavaScript library alias changed: ${library}`);
  }
  for (const expected of inputs.files) {
    const actual = fingerprint(expected.path);
    if (actual.bytes !== expected.bytes || actual.sha256 !== expected.sha256) {
      throw new Error(`JavaScript runtime file changed: ${expected.path}`);
    }
  }
  for (const scope of inputs.package_scopes) {
    if (existsSync(scope.path) !== scope.exists) {
      throw new Error(`JavaScript package scope changed: ${scope.path}`);
    }
  }
  for (const edge of inputs.resolutions) {
    if (Module.createRequire(edge.parent).resolve(edge.request) !== edge.path) {
      throw new Error(`JavaScript resolution changed: ${edge.parent} -> ${edge.request}`);
    }
  }
}

exports.verifiedRequire = (manifest, library) => {
  const inputs = JSON.parse(readFileSync(manifest, 'utf8'));
  verify(inputs, library);
  const files = new Set(inputs.files.map(file => file.path));
  const originalLoad = Module._load;
  Module._load = function (request, parent, isMain) {
    const path = Module._resolveFilename(request, parent, isMain);
    if (!Module.isBuiltin(path) && !files.has(path)) {
      throw new Error(`Unrecorded JavaScript runtime file: ${path}`);
    }
    return originalLoad.apply(this, arguments);
  };
  return Module.createRequire(inputs.parent);
};

if (require.main === module) {
  const [mode, path, output] = process.argv.slice(2);
  if (mode === '--record') {
    writeFileSync(output, JSON.stringify(record(resolve(path)), null, 2) + '\n');
  } else if (mode === '--verify') {
    verify(JSON.parse(readFileSync(path, 'utf8')));
  } else {
    throw new Error('Use --record <library> <output> or --verify <manifest>');
  }
}

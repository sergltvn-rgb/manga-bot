import { readdirSync, statSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const webappRoot = path.resolve(scriptDir, '..');

function walkJsFiles(dir) {
    const result = [];
    for (const entry of readdirSync(dir)) {
        const fullPath = path.join(dir, entry);
        const stats = statSync(fullPath);
        if (stats.isDirectory()) {
            result.push(...walkJsFiles(fullPath));
            continue;
        }
        if (stats.isFile() && entry.endsWith('.js')) {
            result.push(fullPath);
        }
    }
    return result;
}

const rootFiles = ['reader.js', 'alya_chat.js', 'sw.js']
    .map((name) => path.join(webappRoot, name))
    .filter((fullPath) => existsSync(fullPath));

const moduleFiles = existsSync(path.join(webappRoot, 'modules'))
    ? walkJsFiles(path.join(webappRoot, 'modules'))
    : [];

const files = [...new Set([...rootFiles, ...moduleFiles])].sort();

if (files.length === 0) {
    console.log('No JavaScript files found for syntax check.');
    process.exit(0);
}

let hasErrors = false;

for (const filePath of files) {
    const relativePath = path.relative(webappRoot, filePath);
    try {
        const source = readFileSync(filePath, 'utf8');
        new vm.Script(source, { filename: filePath });
        console.log(`OK  ${relativePath}`);
    } catch (error) {
        hasErrors = true;
        console.error(`FAIL ${relativePath}`);
        if (error && error.message) {
            console.error(error.message);
        }
    }
}

if (hasErrors) {
    process.exit(1);
}

console.log('JavaScript syntax check passed.');

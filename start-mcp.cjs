const { spawn } = require('child_process');
const http = require('http');
const path = require('path');
const os = require('os');

const PORT = 3000;
const PROJECT_PATH = process.argv[2] ? path.resolve(process.argv[2]) : process.cwd();

console.log('\x1b[35m=================================================================\x1b[0m');
console.log('\x1b[1m🚀 Инициализация автоматического MCP-моста для Notion/Claude...\x1b[0m');
console.log('\x1b[35m=================================================================\x1b[0m\n');

// Функция для получения URL туннеля через локальный API ngrok
const getTunnelUrl = () => {
  return new Promise((resolve) => {
    http.get('http://127.0.0.1:4040/api/tunnels', (res) => {
      let data = '';
      res.on('data', (chunk) => data += chunk);
      res.on('end', () => {
        try {
          const json = JSON.parse(data);
          if (json.tunnels && json.tunnels.length > 0) {
            resolve(json.tunnels[0].public_url);
          } else {
            resolve(null);
          }
        } catch (e) {
          resolve(null);
        }
      });
    }).on('error', () => {
      resolve(null);
    });
  });
};

// Функция копирования в буфер обмена на Windows через PowerShell
const copyToClipboard = (text) => {
  const ps = spawn('powershell', ['-NoProfile', '-Command', `Set-Clipboard -Value '${text}'`]);
  ps.on('error', (err) => {
    console.log('⚠️ Не удалось автоматически скопировать ссылку в буфер обмена:', err.message);
  });
};

// Вывод красивой таблицы настроек для Notion
const printNotionSettingsTable = (sseUrl) => {
  console.log('\n\x1b[1m👉 НАСТРОЙКИ ДЛЯ NOTION:\x1b[0m');
  console.log('┌─────────────────┬────────────────────────────────────────────────┐');
  console.log('│ Параметр        │ Значение                                       │');
  console.log('├─────────────────┼────────────────────────────────────────────────┤');
  console.log('│ Name            │ Любое (например, OpenCode)                     │');
  console.log(`│ MCP server URL  │ \x1b[32m${sseUrl.padEnd(46)}\x1b[0m │`);
  console.log('│ Authentication  │ Bearer token                                   │');
  console.log('│ Token           │ Любой токен (например, 12345678)               │');
  console.log('└─────────────────┴────────────────────────────────────────────────┘');
  console.log('\n\x1b[32m🟢 Мост успешно запущен и работает в фоне!\x1b[0m');
  console.log('\x1b[33m💡 Окно терминала закрывать нельзя. Для остановки нажмите Ctrl + C.\x1b[0m\n');
};

let proxyProc = null;
let ngrokProc = null;

const cleanup = () => {
  console.log('\n\n🛑 Завершение работы моста и туннелей...');
  if (proxyProc) proxyProc.kill();
  if (ngrokProc) ngrokProc.kill();
  console.log('👋 Все локальные процессы успешно остановлены. Пока!');
  process.exit();
};

process.on('SIGINT', cleanup);
process.on('SIGTERM', cleanup);

console.log('\n🔌 Шаг 1: Запуск локального MCP-моста (mcp-proxy)...');
console.log(`📂 Рабочая папка: \x1b[36m${PROJECT_PATH}\x1b[0m`);

const wrapperPath = path.join(__dirname, 'bypass-wrapper.cjs');

// Передаем путь к проекту через переменную окружения (это гарантирует, что пути с пробелами и тире не разобьются шеллом)
process.env.GWR_PROJECT_PATH = PROJECT_PATH;

// Функция для кроссплатформенного запуска npx без использования shell: true на Windows
const fs = require('fs');
function spawnNpx(npxArgs, options) {
  if (process.platform === 'win32') {
    try {
      const npxPath = require('child_process').execSync('where npx').toString().trim().split('\r\n')[0];
      const nodeDir = path.dirname(npxPath);
      const npxCliPath = path.join(nodeDir, 'node_modules', 'npm', 'bin', 'npx-cli.js');
      if (fs.existsSync(npxCliPath)) {
        return spawn('node', [npxCliPath, ...npxArgs], { ...options, shell: false });
      }
    } catch (e) {}
    return spawn('npx', npxArgs, { ...options, shell: true });
  } else {
    return spawn('npx', npxArgs, { ...options, shell: false });
  }
}

// Запускаем mcp-proxy через npx, перенаправляя вызовы к нашему обертчику bypass-wrapper.cjs
const proxyArgs = ['node', wrapperPath];

proxyProc = spawnNpx([
  '-y', 'mcp-proxy',
  '--port', String(PORT),
  '--',
  ...proxyArgs
], { cwd: os.tmpdir() });

proxyProc.stdout.on('data', (data) => {
  const line = data.toString().trim();
  if (line.includes('starting server') || line.includes('MCP') || line.includes('Server')) {
    console.log(`\x1b[32m[Proxy] ${line}\x1b[0m`);
  }
});

proxyProc.stderr.on('data', (data) => {
  const line = data.toString().trim();
  if (line) console.log(`[Proxy-Log]: ${line}`);
});

proxyProc.on('error', (err) => {
  console.error('❌ Ошибка запуска mcp-proxy:', err.message);
  cleanup();
});

console.log('\n🌐 Шаг 2: Запуск публичного туннеля через ngrok...');

// Запускаем ngrok
ngrokProc = spawn('ngrok', ['http', String(PORT)], { shell: true });

ngrokProc.stdout.on('data', (data) => {
  // Раскомментируй строку ниже, если захочешь видеть внутренние логи ngrok
  // console.log(`[ngrok]: ${data.toString().trim()}`);
});

ngrokProc.stderr.on('data', (data) => {
  console.log(`\x1b[31m[ngrok-error]: ${data.toString().trim()}\x1b[0m`);
});

ngrokProc.on('error', (err) => {
  console.error('\n❌ Не удалось запустить ngrok!');
  console.log('💡 Убедитесь, что ngrok установлен в вашей системе (winget install ngrok.ngrok).');
  cleanup();
});

// Ожидание получения ссылки от ngrok
console.log('🔄 Ожидание активации туннеля ngrok...');
let attempts = 15;
const pollInterval = setInterval(() => {
  getTunnelUrl().then((url) => {
    if (url) {
      clearInterval(pollInterval);
      const sseUrl = url.endsWith('/') ? `${url}sse` : `${url}/sse`;
      copyToClipboard(sseUrl);
      printNotionSettingsTable(sseUrl);
    } else {
      attempts--;
      if (attempts <= 0) {
        clearInterval(pollInterval);
        console.error('\n❌ Превышено время ожидания ответа от ngrok API (порт 4040).');
        console.log('💡 Скорее всего, ngrok требует токен или не может запуститься. Попробуй открыть другой терминал и вручную выполнить: ngrok http 3000');
        cleanup();
      }
    }
  });
}, 1000);

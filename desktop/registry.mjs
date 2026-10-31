#!/usr/bin/env node
/**
 * 进程登记中心 —— 任何 AI 创建后台进程前先登记，结束时注销。
 *
 * 存储: data/process-registry.json
 *
 * 用法:
 *   node registry.mjs register --owner chatgpt --name "侧边栏" --pid 1234 --desc "说明"
 *   node registry.mjs unregister --id <id>          按 id 注销
 *   node registry.mjs unregister --name "侧边栏"    按名字注销
 *   node registry.mjs list                          列出全部
 *   node registry.mjs clean                         清理已死的 PID
 *   node registry.mjs run --owner chatgpt --desc "说明" -- <命令...>
 *                                                   包装模式：自动登记→等待→自动注销
 */
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import crypto from 'node:crypto';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DATA_DIR = process.env.AUDIO_MEMORY_PROCESS_REGISTRY_DIR || path.join(HERE, 'data');
const REG_PATH = path.join(DATA_DIR, 'process-registry.json');

function ensureDir() {
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
}

function load() {
  ensureDir();
  if (!fs.existsSync(REG_PATH)) return { processes: [] };
  try {
    return JSON.parse(fs.readFileSync(REG_PATH, 'utf8'));
  } catch {
    return { processes: [] };
  }
}

function save(db) {
  ensureDir();
  fs.writeFileSync(REG_PATH, JSON.stringify(db, null, 1), 'utf8');
}

function alive(pid) {
  if (!pid) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === 'EPERM';   // 权限不足也算活着
  }
}

function now() {
  return new Date().toISOString().replace('T', ' ').slice(0, 19);
}

function add({ owner, name, pid, desc }) {
  const db = load();
  // 同名同 owner 的旧记录先标掉，避免重复
  for (const p of db.processes) {
    if (p.owner === owner && p.name === name && p.status === 'running') {
      p.status = 'replaced';
      p.ended = now();
    }
  }
  const rec = {
    id: crypto.randomUUID().slice(0, 8),
    owner: owner || 'unknown',
    name: name || '',
    desc: desc || '',
    pid: pid || null,
    started: now(),
    status: 'running',
  };
  db.processes.push(rec);
  save(db);
  return rec;
}

function unregister({ id, name }) {
  const db = load();
  let n = 0;
  for (const p of db.processes) {
    const hit = (id && p.id === id) || (name && p.name === name);
    if (hit && p.status === 'running') {
      p.status = 'exited';
      p.ended = now();
      n++;
    }
  }
  save(db);
  return n;
}

function list() {
  const db = load();
  if (!db.processes.length) {
    console.log('（没有登记）');
    return;
  }
  const rows = db.processes.map((p) => {
    const isAlive = p.status === 'running' && alive(p.pid);
    const state = p.status === 'running' ? (isAlive ? '运行中' : '已死未注销') : p.status;
    return { ...p, state };
  });
  const running = rows.filter((r) => r.state === '运行中').length;
  const zombie = rows.filter((r) => r.state === '已死未注销').length;
  console.log(`登记 ${rows.length} 条 | 运行中 ${running} | 已死未注销 ${zombie}`);
  console.log('');
  for (const r of rows) {
    console.log(
      `${r.id.padEnd(9)} ${r.owner.padEnd(10)} ${r.name.padEnd(22)} pid=${String(r.pid).padEnd(7)} ${r.state}`
    );
    if (r.desc) console.log(`          ${r.desc}`);
  }
}

function clean() {
  const db = load();
  let n = 0;
  for (const p of db.processes) {
    if (p.status === 'running' && !alive(p.pid)) {
      p.status = 'died';
      p.ended = now();
      n++;
    }
  }
  save(db);
  console.log(`清理 ${n} 条已死记录`);
}

function run(opts) {
  const cmd = opts.cmd;
  if (!cmd || !cmd.length) {
    console.error('缺少命令。用法: run --owner xxx --desc "..." -- <命令...>');
    process.exit(2);
  }
  const child = spawn(cmd[0], cmd.slice(1), { stdio: 'inherit', shell: false, windowsHide: true });
  const rec = add({
    owner: opts.owner,
    name: opts.name || cmd[0],
    pid: child.pid,
    desc: opts.desc,
  });
  console.log(`[reg] 已登记 ${rec.id} pid=${child.pid} (${rec.owner} / ${rec.name})`);
  child.on('exit', (code) => {
    unregister({ id: rec.id });
    console.log(`[reg] 已注销 ${rec.id}，退出码 ${code}`);
    process.exit(code == null ? 0 : code);
  });
  child.on('error', (e) => {
    unregister({ id: rec.id });
    console.error(`[reg] 启动失败: ${e.message}`);
    process.exit(1);
  });
}

// ---------- 参数解析 ----------
const argv = process.argv.slice(2);
const action = argv[0];
const opts = {};
let cmd = [];
let i = 1;
while (i < argv.length) {
  const a = argv[i];
  if (a === '--') { cmd = argv.slice(i + 1); break; }
  if (a.startsWith('--')) {
    const k = a.slice(2);
    const v = argv[i + 1];
    opts[k] = v;
    i += 2;
  } else {
    i++;
  }
}

switch (action) {
  case 'register': {
    const pid = opts.pid ? Number(opts.pid) : null;
    const rec = add({ owner: opts.owner, name: opts.name, pid, desc: opts.desc });
    console.log(`${rec.id} ${rec.owner} ${rec.name} pid=${rec.pid}`);
    break;
  }
  case 'unregister': {
    const n = unregister({ id: opts.id, name: opts.name });
    console.log(`注销 ${n} 条`);
    break;
  }
  case 'list': list(); break;
  case 'clean': clean(); break;
  case 'run': run({ ...opts, cmd }); break;
  default:
    console.log(`进程登记中心

  register   --owner <谁> --name <名字> --pid <PID> [--desc <说明>]
  unregister --id <id> | --name <名字>
  list
  clean
  run        --owner <谁> [--name <名字>] [--desc <说明>] -- <命令...>
`);
}

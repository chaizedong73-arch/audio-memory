const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
async function importVideo(root, source) {
  const extension = path.extname(source).toLowerCase();
  if (!['.mp4','.webm','.mov','.mkv'].includes(extension) || !(await fs.stat(source)).isFile()) throw new Error('请选择支持的录像文件');
  const folder = path.join(root, 'record', 'camera');
  await fs.mkdir(folder, {recursive:true});
  const name = randomUUID();
  const partial = path.join(folder, name + '.partial' + extension);
  const output = path.join(folder, name + extension);
  let linked = false;
  try {
    await fs.copyFile(source, partial, require('node:fs').constants.COPYFILE_EXCL);
    await fs.link(partial, output);
    linked = true;
  } finally {
    try { await fs.unlink(partial); } catch (error) { if (error.code !== 'ENOENT' && !linked) throw error; }
  }
  return {status:'ready',name:path.basename(source),savedAs:path.basename(output)};
}
module.exports = { importVideo };

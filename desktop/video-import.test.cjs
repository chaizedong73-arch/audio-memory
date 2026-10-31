const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
const { importVideo } = require('./video-import.cjs');
const { removeFixture } = require('./test-fixtures.cjs');
test('import preserves source and publishes only complete, unique files', async () => {
  const root = await fs.mkdtemp(path.join(os.tmpdir(),'audio-visual-worker-'));
  try {
    const source=path.join(root,'original.MP4'); await fs.writeFile(source,'sample video');
    const first=await importVideo(root,source), second=await importVideo(root,source);
    assert.notEqual(first.savedAs,second.savedAs);
    assert.equal(await fs.readFile(source,'utf8'),'sample video');
    assert.equal(await fs.readFile(path.join(root,'record','camera',first.savedAs),'utf8'),'sample video');
    assert.equal((await fs.readdir(path.join(root,'record','camera'))).filter(x=>x.includes('.partial.')).length,0);
    await assert.rejects(importVideo(root,path.join(root,'wrong.txt')));
  } finally { await removeFixture(root); }
});

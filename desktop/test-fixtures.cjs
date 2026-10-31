const fs = require('node:fs/promises');
const path = require('node:path');
const os = require('node:os');
async function removeFixture(root) {
  const real = await fs.realpath(root);
  const temp = await fs.realpath(os.tmpdir());
  if (path.dirname(real).toLowerCase() !== temp.toLowerCase() || !/^audio-(gateway|controller|desktop-fixture|real-gateway|gui-start|pages|context-ui|context-worker|context-lifecycle|recording-worker|recording-ui|correction-ui|visual-worker)-/i.test(path.basename(real))) throw new Error('Refusing to delete a non-fixture directory');
  await fs.rm(real, { recursive:true, force:true });
}
module.exports = { removeFixture };

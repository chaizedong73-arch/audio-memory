// Switching drains the current recording before replacing its worker settings.
function createModeSwitcher({controller, getMode, setMode, validate, persist}) {
  let busy = false;
  return async mode => {
    if (busy) return {status:'error',message:'正在切换转写方式，请稍候'};
    const error = validate(mode);
    if (error) return {status:'error',message:error};
    const previous = getMode();
    if (mode === previous) return {status:'ready',mode};
    busy = true;
    const running = controller.isOwned();
    try {
      if (running) {
        const stopped = await controller.stop();
        if (stopped.status !== 'stopped') return stopped;
      }
      setMode(mode);
      try {
        if (running) {
          const started = await controller.start();
          if (started.status !== 'owned') throw new Error(started.message || '新转写服务未能启动');
        }
        persist(mode);
        return {status:'ready',mode};
      } catch (error) {
        if (controller.isOwned()) {
          const stopped = await controller.stop();
          if (stopped.status !== 'stopped') return {status:'error',mode,message:'切换未完成，录音仍在停止，请查看日志'};
        }
        setMode(previous);
        const restored = running ? await controller.start() : null;
        return {status:'error',mode:previous,message:`切换失败：${error.message}。${running ? restored.status === 'owned' ? '已恢复原转写方式并继续录音。' : '录音未恢复，请重新启动；原音频保留。' : '已保留原选择。'}`};
      }
    } finally { busy = false; }
  };
}
module.exports = {createModeSwitcher};

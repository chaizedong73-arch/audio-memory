# -*- coding: utf-8 -*-
"""单实例锁：保证同一服务在本机只跑一份。

为什么需要
----------
    2026-10-21 实测：start_day.cmd 和 启动.cmd 两套入口都被点过，
    结果 recorder/transcriber/extract 各跑了 2 份。两个 recorder 同秒启动
    会生成完全同名的分片文件，互相覆盖 → 录音静默丢失。
    启动脚本层的"已在运行就退出"检查有竞态（两个脚本同时启动都看不到对方），
    所以真正的保证必须落在进程内部的排他文件锁上。

实现
----
    Windows: msvcrt.locking 排他锁，进程退出由 OS 自动释放，无需清理残留文件。
    其它平台: fcntl.flock 同样语义。
"""
import os


def acquire(path):
    """拿到锁返回文件句柄；已被占用返回 None。句柄必须保持存活，锁才有效。"""
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    fh = open(path, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return None
    fh.seek(0)
    fh.truncate()
    fh.write(str(os.getpid()).encode())
    fh.flush()
    return fh

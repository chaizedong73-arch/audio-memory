"""Conservative detection of known historical prompt echoes; never edit originals."""
import re

def suspected_prompt_echo(text):
    text = str(text or '')
    cue = re.search(r'(?:中文口语录音|中文口语录音|窗口语录音|口语录音|常见术语)', text)
    tokens = re.findall(r'STM32|ESP32|EXTI|PWM|寄存器|中断|大模型|上下文窗口', text, re.I)
    return bool(cue and tokens) or len({t.lower() for t in tokens}) >= 4

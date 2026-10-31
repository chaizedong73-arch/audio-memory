import unittest
from transcript_quality import suspected_prompt_echo

class QualityTests(unittest.TestCase):
    def test_known_echo(self):
        self.assertTrue(suspected_prompt_echo('在下文窗口语录音：STM32、EXTI、PWM、寄存器、中断、大模型、'))
        self.assertTrue(suspected_prompt_echo('用一段中文口语录音：STM32'))
    def test_normal_technical_speech(self):
        self.assertFalse(suspected_prompt_echo('STM32 的 EXTI 用于外部中断'))
        self.assertFalse(suspected_prompt_echo('录音里的上下文窗口需要重新处理'))

if __name__ == '__main__': unittest.main()

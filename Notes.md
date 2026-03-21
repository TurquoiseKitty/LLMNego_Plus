# Some quick notes

---

## 03-20
DeepSeek-R1 (and the deepseek-reasoner model) is trained to produce a chain-of-thought block before its final answer. During training, the model learns to wrap its internal reasoning between special tokens — something like <think> and </think>. So the raw model output looks roughly like:
```
<think>
Let me work through this step by step...
[reasoning trace]
</think>

The answer is: A is a Knight, B is a Knight...
```
DeepSeek's serving infrastructure parses the raw model output before sending it to you:
- It scans the generated token stream for the `<think> / </think>` delimiters.
- Everything inside those tags goes into `reasoning_content`.
- Everything after `</think>` goes into the standard content field.
- The response object is then serialized with both fields and returned as JSON.

---
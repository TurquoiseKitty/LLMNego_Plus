# LLMNego Plus Log


---
## Install

```
conda create -n LLMNego python=3.12
conda activate LLMNego
pip install openai

pip install -e .
```

## Keys

Use environment variables instead of hardcoding secrets.

OpenAI
```
export OPENAI_API_KEY="YOUR_OPENAI_API_KEY"
```

DeepSeek
```
export OPENAI_API_KEY="YOUR_DEEPSEEK_API_KEY"
```

Qwen 3.5, China
```
"YOUR_QWEN_API_KEY"
```

Qwen 3.5, International
```
"YOUR_QWEN_INTERNATIONAL_API_KEY"
```

---

## 03-21

Implement some preliminary demos in 0321 of EXP. Looks like Qwen3.5-Flash cannot understand the complex prompt properly! Even without attack, private information keeps leaking out. In comparison, the instruction following ability of deepseek is FAR better!

---

## 03-23

The `negolib_viewer`.

Setup — open a terminal (PowerShell or CMD) and run:

```
npm create vite@latest viewer-template -- --template react
cd viewer-template
npm install
```

Drop in the file — copy the `negolib_viewer.jsx` file into `src/`, then open `src/App.jsx` and replace its entire contents with:

```
export { default } from './negolib_viewer.jsx'
```

Run it

```
npm run dev
```

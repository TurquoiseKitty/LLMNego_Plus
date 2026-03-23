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

OpenAI
```
export OPENAI_API_KEY="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"
```

DeepSeek
```
export OPENAI_API_KEY="sk-7e40f14caf844470968a9cd0cd8b6616"
```

Qwen 3.5, China
```
"sk-0c2cae48581b452082ecd8ad11041993"
```

Qwen 3.5, International
```
"sk-bc76158be7c447cb875a4a0eedb60db9"
```



---

## 03-21

Implement some preliminary demos in 0321 of EXP. Looks like Qwen3.5-Flash cannot understand the complex prompt properly! Even without attack, private information keeps leaking out. In commparison, the instruction following ability of deepseek is FAR better!

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
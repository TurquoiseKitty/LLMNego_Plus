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

Use process environment variables. Do not paste API keys into Python files,
notebook cells, outputs, logs, or tracked configuration files.

The sanitized notebooks read `OPENAI_API_KEY`, `DEEPSEEK_API_KEY`,
`GEMINI_API_KEY`, or `DASHSCOPE_API_KEY`, depending on the provider. Existing
experiment runners use `NEGO_API_KEY`; the two repaired strategic-buyer
configs also accept `DEEPSEEK_API_KEY` when `NEGO_API_KEY` is unset. Set
`NEGO_API_KEY` for compatibility with the other existing experiment configs.

Set only the variables needed for the experiment you are running, before
starting Python or Jupyter. For example, in PowerShell:

```powershell
$env:OPENAI_API_KEY = "YOUR_NEW_OPENAI_API_KEY"
$env:DEEPSEEK_API_KEY = "YOUR_NEW_DEEPSEEK_API_KEY"
$env:NEGO_API_KEY = $env:DEEPSEEK_API_KEY
$env:GEMINI_API_KEY = "YOUR_NEW_GEMINI_API_KEY"
$env:DASHSCOPE_API_KEY = "YOUR_NEW_DASHSCOPE_API_KEY"
```

In Bash or zsh, use `export NAME="value"` instead. Keep real values private:
commands containing credentials may remain in shell history. Environment
variables set in a terminal are inherited by processes launched from that
terminal; restart an already-running Jupyter server from the configured
terminal as needed. Missing required notebook variables raise `KeyError`
rather than silently falling back to a hardcoded credential.

`.env.example` lists the variable names without credentials. `.env` and local
secret files are ignored by Git, but **this project does not automatically
load `.env` files**. Set the process environment explicitly, or use a local
loader before creating the API client. Some untouched older templates still
contain `YOUR_*` placeholders; replace those placeholders with environment
lookups, not literal real keys, when using those templates.

See `SECURITY_CLEANUP.md` for the cleanup scope, file-by-file changes, and
verification results. Deleting a credential from these files does not revoke
it at the provider or remove it from remote Git history.

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

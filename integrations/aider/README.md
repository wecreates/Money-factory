# Isolated Aider runtime

Pinned package: `aider-chat==0.86.2`, official source tag `v0.86.2` at commit
`253f0368b873ba30d8ee26e463718f0c03614ddf`.

This is a reproducible CLI environment, not a daemon or proof of unattended coding quality.
No Content Control code or publishing settings are changed by this integration.

## Install

Use Python 3.12 and `uv`; keep this environment separate from application dependencies:

```bash
uv venv --python python3.12 /path/to/aider-runtime
uv pip sync --require-hashes --python /path/to/aider-runtime/bin/python integrations/aider/requirements.lock
/path/to/aider-runtime/bin/aider --version
uv pip check --python /path/to/aider-runtime/bin/python
```

The lock contains 108 exact package versions and distribution hashes. It was resolved and
installed on Linux with Python 3.12.14. Other Python versions/platforms have not been tested.
Upgrade deliberately by regenerating the lock, then repeating the runtime checks.

## Local Ollama mode

Aider officially supports an already installed, running Ollama service. Ollama is not installed
by these commands, and this session did not run an Ollama server or download an Ollama model.
Replace `YOUR_INSTALLED_MODEL` with an actually available local model:

```bash
export OLLAMA_API_BASE=http://127.0.0.1:11434
/path/to/aider-runtime/bin/aider --model ollama_chat/YOUR_INSTALLED_MODEL \
  --no-analytics --no-check-update --no-auto-commits --no-suggest-shell-commands
```

Use the machine/VPN host's own terminal or SSH session. This workspace's installation does
not establish availability or 24/7 operation on the user's computer.

## One bounded edit

From a disposable checkout, add explicit files and one task:

```bash
/path/to/aider-runtime/bin/aider --model ollama_chat/YOUR_INSTALLED_MODEL \
  --no-analytics --no-check-update --no-auto-commits --no-suggest-shell-commands \
  --message 'Implement the specified change in this file, then stop.' path/to/file.py
```

Review the diff and execute the relevant tests. Exit code 0 alone does not prove an edit was
made or that the result is correct. Do not infer permission to publish, deploy, or spend money
from a successful coding interaction.

## Executed evidence

See `evidence/runtime-validation.json` and `evidence/installed-packages.json` for the exact
installation and local-model smoke results, including failures and unverified scope.

Official references:
- https://aider.chat/docs/install.html
- https://aider.chat/docs/llms/ollama.html
- https://aider.chat/docs/scripting.html
- https://github.com/Aider-AI/aider/tree/253f0368b873ba30d8ee26e463718f0c03614ddf

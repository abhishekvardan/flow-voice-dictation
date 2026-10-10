# Flow — a local Wispr Flow replica for Windows

Hold a shortcut anywhere in Windows, speak, let go, and polished text appears where your cursor is.
Everything runs on your machine: **faster-whisper** turns speech into text and **Ollama** cleans it up.

## Features

- **Push to talk**: hold `Ctrl + Win`, speak, release. The text is pasted into the focused app, and your clipboard is restored afterwards.
- **Hands-free**: double-tap `Ctrl + Win` or press `Ctrl + Win + Space`. Press a shortcut again (or click the red stop button on the bubble) to finish.
- **Command mode**: select text, hold `Ctrl + Win + Alt`, and say an instruction such as "make this more concise" or "translate to Hindi". The selection is replaced with the result. With nothing selected, the result is inserted at the cursor.
- **Esc** cancels a recording.
- **AI cleanup**: removes filler words, fixes punctuation and false starts, and turns spoken commands like "comma" or "new paragraph" into symbols.
- **Styles per app**: casual in Slack, Discord and WhatsApp; formal in Outlook and Gmail; technical in VS Code, Cursor and terminals. Rules and style instructions can be edited.
- **Personal dictionary**: vocabulary hints (for Whisper and the LLM) plus forced replacements.
- **Snippets**: say "my calendar link" to insert your saved text.
- **History**: searchable, with words dictated and words per minute. Recent dictations are also in the tray menu.
- **Floating bubble**: shows a live waveform, processing dots, and errors. It never takes focus away from your app.
- All shortcuts are configurable, including single keys like `F8` or side-specific keys like `Right Alt`.
- **Transcribes while you speak**: pieces of speech between pauses are transcribed in the background, so releasing the shortcut leaves only the tail to do. Measured on a 23 s dictation: the wait after release dropped from **1,329 ms to 247 ms**, with word-identical text.
- **Rules-based cleanup** (no model): fillers, stutters, spacing, capitalization and spoken punctuation are fixed by rules on every dictation. This is also what gets inserted whenever AI cleanup is unavailable, skipped or rejected, so you never get a raw, unpunctuated dump.
- **Last dictation panel** (`Ctrl + Win + E`): review and edit the result, switch between the exact transcript / rules version / AI version, clean it again with a different style, or insert it again.
- **Voice skills**: say a saved name and then speak - "commit message: fixed the login redirect bug" or "bug report: ...". Ships with commit message, bug report, prompt and email reply; add your own.
- **Prompt mode for coding tools** plus spoken code symbols ("flow slash app dot py" -> `flow/app.py`), and a one-click import of identifiers from a project folder into your dictionary.
- **Stats**: dictations, words, minutes spoken, words per minute, average speech and AI timings, and breakdowns by app, style and day.
- **Local only by default**: Flow refuses Ollama entries that are just pointers to cloud models, and non-loopback servers, so dictation cannot leave the machine by accident.
- **Keeps working**: a watchdog reinstalls the keyboard hook if Windows drops it, hands-free can stop itself after silence, and admin windows are detected and explained rather than silently failing.
- **Multi-language**: Whisper transcribes ~99 languages. Pick one from the tray menu (**Language**) or let it detect automatically. Fixing the language is faster (measured: 298 ms vs 822 ms on a short clip) and avoids misdetection.

## Languages and AI cleanup

Transcription is multilingual, but small local cleanup models are not equally good in every language. Measured on qwen2.5:1.5b and llama3.2 3B, Hindi, Tamil and Hinglish were translated into English, rewritten, or took 5-11 seconds.

So cleanup runs only for the languages in **Settings -> Models -> Clean up only** (default `en,es,fr,de,it,pt,nl`). Everything else is inserted exactly as spoken, which is faster and never mistranslates. Set it to `all` to always clean up.

Two safeguards apply in every language:
- Whisper's detected language is named in the prompt ("Reply in Hindi"), which stops most translation.
- Replies that switch writing system (Devanagari to Latin, or the reverse) are discarded and the raw transcript is inserted.

For Indian languages, transcription accuracy depends mostly on the Whisper model: `small` struggles, `large-v3-turbo` is much better (~1.6 GB download, GPU only).

## Setup

Requirements: Windows 10/11, [uv](https://docs.astral.sh/uv/), and [Ollama](https://ollama.com).

```powershell
ollama pull qwen2.5:1.5b      # default cleanup model; any chat model works (Settings → Models)
uv sync                       # creates a Python 3.12 venv with all dependencies
uv sync --extra gpu           # optional: CUDA libraries so Whisper runs on an NVIDIA GPU
uv run python -m flow         # start, with logs in the console
```

To start it without a console window, double-click `run.pyw` (it must be opened with the venv's `pythonw.exe`),
or turn on **Settings → General → Start Flow when I sign in**.

The first launch downloads the Whisper model (`small` is about 500 MB) to `%APPDATA%\Flow\models`.

## Choosing models (4 GB GPU example)

| Whisper model | Quality | VRAM (int8_float16) |
| --- | --- | --- |
| `base` | ok | ~0.3 GB |
| `small` (default) | good | ~0.6 GB |
| `large-v3-turbo` | best | ~1.6 GB |

### Measured latency (RTX 3050, Whisper small, llama3.2 3B)

Time from releasing the shortcut to text appearing, median of 5 runs:

| Speech | v1 | after profiling | with streaming |
| --- | --- | --- | --- |
| 2.4 s | 3,304 ms | 688 ms | ~560 ms |
| 6.4 s | 4,723 ms | 1,324 ms | ~1,250 ms |
| 16.9 s | 7,975 ms | 2,210 ms | ~1,550 ms |
| 22.6 s (with pauses) | — | ~3,500 ms | ~2,400 ms |

The big early win was connecting to `127.0.0.1` instead of `localhost`: on Windows the latter tries
IPv6 first and Ollama only listens on IPv4, which cost 2.1 s per request. Streaming removes most of
what is left of speech recognition; the remainder is AI cleanup, which scales with how much you said.
Run `uv run python bench/benchmark.py --label mine` to measure your own machine.

`llama3.2` (3B) uses about 2.5 GB, so `small` plus `llama3.2` fits on a 4 GB card. If Whisper can't use CUDA,
it falls back to the CPU automatically; the tray menu shows which device is in use.

## Where things live

- `%APPDATA%\Flow\config.json`: settings
- `%APPDATA%\Flow\flow.db`: dictionary, snippets, history (SQLite)
- `%APPDATA%\Flow\flow.log`: logs

## Tips and limits

- When the `Ctrl + Win` shortcut is used, Flow sends a harmless "mask" key so the Start menu doesn't open.
- Windows doesn't let a normal app send keys into elevated (admin) windows. Run Flow as admin if you need to dictate into them.
- Command mode doesn't copy the selection in terminals, because Ctrl+C would interrupt the running program.
- If an app blocks pasting, switch **Insert text by** to *Type characters*.

## Development

```powershell
uv run pytest                                        # 58 tests
uv run python bench/benchmark.py --label mine        # latency benchmark
uv run python bench/benchmark.py --compare before mine
```

GitHub Actions runs the tests on every push (`.github/workflows/tests.yml`).

### Building a standalone Flow.exe

```powershell
uv sync --extra build
uv run pyinstaller packaging/flow.spec --noconfirm
```

The result is `dist/Flow/Flow.exe`, which runs without uv or Python (about 330 MB). Whisper models
are not bundled; they download to `%APPDATA%\Flow\models` on first use.

The packaged build runs Whisper on the **CPU** by default, because the CUDA runtime from the
`nvidia-*` wheels adds ~1.2 GB. To ship GPU support inside the exe:

```powershell
$env:FLOW_BUNDLE_CUDA = "1"; uv run pyinstaller packaging/flow.spec --noconfirm
```

Two things that bite when packaging on Windows, both handled in `packaging/flow.spec` and `run.pyw`:

- PyInstaller resolves dependent DLLs through `PATH`, so another OpenSSL on the machine gets
  bundled instead of the one Python was built against (Git for Windows ships 3.2, this Python
  needs 3.5) and `import ssl` then fails with "the specified procedure could not be found".
  The spec adds the right DLLs first, and `run.pyw` loads them by absolute path before anything
  imports `ssl`.
- The build needs ~2 GB of free disk space. Use `--distpath`/`--workpath` on a roomy drive.

A startup failure in a windowed build has no console, so `run.pyw` appends the traceback to
`%APPDATA%\Flow\crash.log`; set `FLOW_STARTUP_LOG=1` for DLL diagnostics in `startup.log`.

Code map: `flow/hotkeys.py` (shortcut state machine), `flow/winkeys.py` (low-level keyboard hook and SendInput),
`flow/audio.py`, `flow/stt.py`, `flow/llm.py`, `flow/inserter.py`, `flow/app.py` (wiring), `flow/ui/` (bubble, settings).

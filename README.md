# 🧠 Icarus Local AI Agent

![Screenshot](screenshot.png)

**Icarus** is a self-hosted local AI assistant powered by Ollama.  
It runs on your own machine, provides a responsive web chat UI, supports uploads, structured memory, vector memory, read-only file tools, and human-approved terminal commands.

> ⚠️ This project is experimental and intended for trusted local use only.

---

## ✨ Features

- 🏠 **Local-first AI assistant** using Ollama
- 💬 **Responsive web chat UI** built with Flask, HTML, CSS and vanilla JavaScript
- 🧠 **Structured profile memory** for stable user facts
- 🔎 **Vector memory** using FAISS + sentence-transformers
- 📎 **File uploads inside the chat UI**
- 📄 **PDF reading tool**
- 📝 **Word `.docx` reading tool**
- 🖼️ **Image metadata + optional OCR support**
- 📊 **CSV and JSON reading tools**
- 📁 **Read-only directory/file inspection**
- 🧑‍⚖️ **Human-in-the-loop terminal approval**
- ⏱️ **Response time display**
- 🔢 **Token usage display**
- ⚫⚪ **Minimal black-and-white responsive design**

---

## 🧩 What This Project Is

Icarus is a local AI agent that can:

1. talk to you through a browser-based chat interface,
2. use a local Ollama model,
3. remember stable information,
4. inspect uploaded files,
5. request read-only terminal commands,
6. wait for your approval before executing commands.

The core idea:

```text
The model may suggest actions.
The user approves actions.
The backend enforces boundaries.
```

---

## 🚨 Security Notice

This project can execute shell commands on your machine **after explicit user approval**.

Use it carefully.

### Do not:

- expose this server to the public internet,
- run it with `sudo`, root, or administrator privileges,
- store secrets in folders the agent can inspect,
- allow destructive commands,
- trust model-generated shell commands blindly.

### Recommended:

- run only on a trusted local network,
- keep access read-only by default,
- review every command before approving it,
- use a separate low-privilege user account if possible,
- keep uploads and memory files out of Git.

No local AI agent with shell access should be considered perfectly safe.

---

## 🏗️ Architecture

```text
Browser UI
   ↓
Flask Backend
   ↓
Ollama Local Model
   ↓
Tool Request / Command Request
   ↓
Python Tool Layer OR User Approval
   ↓
Result returned to model
   ↓
Final answer shown in chat
```

---

## 📂 Project Structure

```text
.
├── main.py
├── tools.py
├── requirements.txt
├── ALLOWED_COMMANDS.md
├── README.md
├── .gitignore
├── templates/
│   └── index.html
├── static/
│   └── style.css
├── memory/
│   └── .gitkeep
└── uploads/
    └── .gitkeep
```

---

## ⚙️ Requirements

- Python 3.10+
- Ollama installed and running
- At least one local Ollama model
- Linux/macOS recommended

Recommended models:

| Use case | Model |
|---|---|
| General local assistant | `qwen2.5:14b` |
| Coding-heavy tasks | `qwen2.5-coder:14b` |
| Stronger coding model | `qwen3-coder:30b` |
| Lightweight testing | `gemma3:4b` |

Example:

```bash
ollama pull qwen2.5-coder:14b
```

---

## 🚀 Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/icarus-local-ai-agent.git
cd icarus-local-ai-agent
```

Create a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start Ollama:

```bash
ollama serve
```

Start Icarus:

```bash
python main.py
```

Open in your browser:

```text
http://localhost:5000
```

For local network access:

```text
http://YOUR_LOCAL_IP:5000
```

---

## 📦 Example `requirements.txt`

```txt
flask
requests
faiss-cpu
sentence-transformers
pypdf
python-docx
pillow
pytesseract
```

OCR requires the system package `tesseract-ocr`.

On Debian/Ubuntu:

```bash
sudo apt install tesseract-ocr
```

---

## 🧠 Memory System

Icarus uses two memory layers.

### 1. Structured Profile Memory

Stored in:

```text
memory/profile_memory.json
```

Used for high-confidence facts such as:

- name,
- profession,
- preferences,
- hardware,
- skills,
- interests.

This is better for facts like:

```text
My name is Max.
I prefer short answers.
I use Linux.
```

### 2. Vector Memory

Stored in:

```text
memory/memory_texts.json
memory/memory_index.faiss
```

Used for softer long-term context and recurring topics.

Vector memory is useful, but it should not be trusted as the only source for identity facts like a user name.

---

## 📎 Uploads

Uploaded files are stored locally in:

```text
~/icarus_uploads
```

The chat UI sends uploaded file metadata to the model so it can request the correct tool.

Supported tools include:

- `read_pdf`
- `read_docx`
- `read_image`
- `read_csv`
- `read_json`
- `read_text_file`
- `list_directory`
- `file_info`
- `search_text`
- `hash_file`

---

## 🛠️ Tool System

For file inspection, Icarus should prefer dedicated Python tools over shell commands.

Example tool request:

```json
{
  "type": "tool_request",
  "tool": "read_pdf",
  "args": {
    "path": "/home/user/icarus_uploads/example.pdf"
  }
}
```

The backend runs the tool and sends the result back to the model.

This is safer and more reliable than asking the model to invent shell commands for every file type.

---

## 🖥️ Terminal Approval

For terminal access, the model must request a command.

Example:

```json
{
  "type": "command_request",
  "command": "ls -la ~/Projects",
  "reason": "I need to inspect the project directory."
}
```

The backend does not execute this automatically.

Flow:

```text
Model requests command
→ UI shows command and reason
→ User approves or denies
→ Backend validates command
→ Command runs only if allowed
→ Output goes back to the model
```

---

## ✅ Command Philosophy

Commands should be:

- read-only,
- inspectable,
- limited to the home folder,
- explicitly approved,
- blocked if risky.

Allowed examples:

```bash
ls
pwd
find
grep
cat
head
tail
stat
wc
du
df
file
uname
whoami
date
```

Blocked examples:

```bash
rm
rmdir
mv
cp
chmod
chown
sudo
curl
wget
ssh
scp
dd
mkfs
shutdown
reboot
```

---

## 📜 ALLOWED_COMMANDS.md

Use `ALLOWED_COMMANDS.md` to document the intended command policy.

Recommended structure:

```md
# Allowed Commands

These commands are intended for read-only inspection only.

## Directory inspection
- ls
- pwd
- find
- tree

## File inspection
- cat
- head
- tail
- file
- stat
- wc

## Search
- grep
- egrep
- fgrep

## System info
- date
- uname
- whoami
- id
- hostname
- df
- du
- free
- lscpu
```

The Markdown file is documentation. The backend must still enforce command validation in Python.

---

## 🧪 Development Notes

This project started as a rapid local AI experiment and is evolving toward a safer local-agent architecture.

The most important design correction:

```text
Do not use shell for everything.
Use dedicated tools for structured tasks.
```

Examples:

| Task | Better approach |
|---|---|
| Read PDF | `read_pdf` tool |
| Read Word doc | `read_docx` tool |
| Read image metadata | `read_image` tool |
| Inspect folders | `list_directory` tool or approved `ls` |
| Search text | `search_text` tool or approved `grep` |
| System info | safe read-only commands |

---

## 🧯 Troubleshooting

### Ollama is not reachable

Make sure Ollama is running:

```bash
ollama serve
```

### No models appear

Check installed models:

```bash
ollama list
```

Pull a model:

```bash
ollama pull qwen2.5-coder:14b
```

### PDF reading fails

Install:

```bash
pip install pypdf
```

### Word files fail

Install:

```bash
pip install python-docx
```

### Image reading fails

Install:

```bash
pip install pillow
```

### OCR fails

Install Python dependency:

```bash
pip install pytesseract
```

Install system dependency:

```bash
sudo apt install tesseract-ocr
```

---

## 🗺️ Roadmap

Potential improvements:

- 🔐 real sandboxing
- 👤 authentication for LAN access
- 🧰 stricter command parser
- 📁 per-folder permissions
- 🧠 memory editor UI
- 🧹 memory delete controls
- 🔄 streaming responses
- 📚 multi-file context selection
- 🧪 tests for command validation
- 📦 Docker setup
- 🧭 better tool-call protocol
- 🪪 user/session separation

---

## ❌ Not Production Ready

This project is not intended for production deployment.

It is best used as:

- a learning project,
- a local AI playground,
- a prototype for local tool-using agents,
- a personal workstation assistant.

---

## 📄 License

[MIT](LICENSE.md)

---

## 🙏 Credits

Built around the idea of a local-first AI assistant that keeps the user in control.

Human approval remains the safety boundary.

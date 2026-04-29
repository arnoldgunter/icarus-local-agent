from flask import Flask, request, jsonify, render_template
import requests
import os
import json
import re
import uuid
import subprocess
import platform
import base64
from datetime import datetime
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer

from tools import (
    list_available_tools,
    run_tool,
    ALLOWED_ROOTS,
    is_image_file,
    assert_safe_file,
)


# ==============================
# CONFIG
# ==============================

OLLAMA_URL = "http://localhost:11434"

BASE_DIR = Path(__file__).resolve().parent
MEMORY_DIR = BASE_DIR / "memory"
UPLOAD_DIR = Path.home() / "icarus_uploads"

MEMORY_DIR.mkdir(exist_ok=True)
UPLOAD_DIR.mkdir(exist_ok=True)

INDEX_FILE = str(MEMORY_DIR / "memory_index.faiss")
TEXT_FILE = str(MEMORY_DIR / "memory_texts.json")
PROFILE_FILE = str(MEMORY_DIR / "profile_memory.json")

DIM = 384
EMBED_MODEL = SentenceTransformer("all-MiniLM-L6-v2")

current_model = None
PENDING_COMMANDS = {}
CONVERSATIONS = {}
MAX_HISTORY_MESSAGES = 24

SYSTEM_PROMPT = f"""
You are Icarus, a locally running AI assistant.

You run on the user's workstation.
Use markdown fully.

Important conversation rule:
- You receive the recent chat history.
- Use it to answer follow-up questions like "why", "continue", "what do you mean", etc.
- Do not ask for context if the previous messages already contain it.

Important file rule:
- If uploaded images are provided in the message images field, inspect them directly.
- Do not guess image contents from filenames.
- For PDFs, Word files, CSV, JSON and text files, request tools.
- Prefer tools over shell.
- Never claim you read a file unless it was provided as image input, tool output, or approved command output.

Allowed read roots:
{json.dumps([str(p) for p in ALLOWED_ROOTS], indent=2)}

Available tools:
{json.dumps(list_available_tools(), indent=2)}

Tool request format:
{{
  "type": "tool_request",
  "tool": "read_pdf",
  "args": {{
    "path": "/absolute/path/to/file.pdf"
  }}
}}

Terminal command request format:
{{
  "type": "command_request",
  "command": "ls -la",
  "reason": "I need to inspect the current directory."
}}

Rules:
- Return ONLY JSON when requesting a tool or command.
- Request one tool or command at a time.
- Do not wrap JSON in markdown.
- Otherwise answer normally.
"""


# ==============================
# FLASK
# ==============================

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = str(UPLOAD_DIR)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024


# ==============================
# CHAT HISTORY
# ==============================

def get_chat_history(chat_id):
    if not chat_id:
        chat_id = "default"

    if chat_id not in CONVERSATIONS:
        CONVERSATIONS[chat_id] = []

    return CONVERSATIONS[chat_id]


def trim_history(history):
    if len(history) > MAX_HISTORY_MESSAGES:
        del history[:-MAX_HISTORY_MESSAGES]


def append_history(chat_id, role, content):
    if not content:
        return

    history = get_chat_history(chat_id)
    history.append({
        "role": role,
        "content": content
    })
    trim_history(history)


def clear_chat_history(chat_id):
    if not chat_id:
        chat_id = "default"
    CONVERSATIONS[chat_id] = []


# ==============================
# PROFILE MEMORY
# ==============================

def default_profile():
    return {
        "name": None,
        "profession": None,
        "preferences": [],
        "hardware": [],
        "skills": [],
        "interests": []
    }


def load_profile():
    if not os.path.exists(PROFILE_FILE):
        profile = default_profile()
        save_profile(profile)
        return profile

    try:
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            profile = json.load(f)
        if not isinstance(profile, dict):
            profile = default_profile()
    except Exception:
        profile = default_profile()

    base = default_profile()
    for key, value in base.items():
        if key not in profile:
            profile[key] = value

    return profile


def save_profile(profile):
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)


def add_unique_list_item(profile, key, value):
    value = value.strip()
    if not value:
        return

    if key not in profile or not isinstance(profile[key], list):
        profile[key] = []

    existing = [x.lower() for x in profile[key] if isinstance(x, str)]
    if value.lower() not in existing:
        profile[key].append(value)


def update_profile_from_user_text(user_text):
    profile = load_profile()
    text = user_text.strip()

    name_patterns = [
        r"\bich heiße\s+([A-ZÄÖÜ][a-zäöüßA-ZÄÖÜ\-]+)",
        r"\bmein name ist\s+([A-ZÄÖÜ][a-zäöüßA-ZÄÖÜ\-]+)",
        r"\bnenn mich\s+([A-ZÄÖÜ][a-zäöüßA-ZÄÖÜ\-]+)"
    ]

    for pattern in name_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            profile["name"] = match.group(1).strip()

    save_profile(profile)
    return profile


# ==============================
# VECTOR MEMORY
# ==============================

def load_vector_memory():
    if os.path.exists(INDEX_FILE):
        try:
            index = faiss.read_index(INDEX_FILE)
        except Exception:
            index = faiss.IndexFlatL2(DIM)
    else:
        index = faiss.IndexFlatL2(DIM)

    texts = []

    if os.path.exists(TEXT_FILE):
        try:
            with open(TEXT_FILE, "r", encoding="utf-8") as f:
                texts = json.load(f)
            if not isinstance(texts, list):
                texts = []
        except Exception:
            texts = []
    else:
        with open(TEXT_FILE, "w", encoding="utf-8") as f:
            json.dump(texts, f, ensure_ascii=False, indent=2)

    return index, texts


def save_vector_memory(index, texts):
    faiss.write_index(index, INDEX_FILE)
    with open(TEXT_FILE, "w", encoding="utf-8") as f:
        json.dump(texts, f, ensure_ascii=False, indent=2)


def add_memory(text):
    text = text.strip()
    if len(text) < 8:
        return

    index, texts = load_vector_memory()

    if text.lower() in [t.lower() for t in texts if isinstance(t, str)]:
        return

    emb = EMBED_MODEL.encode([text]).astype("float32")
    index.add(emb)
    texts.append(text)
    save_vector_memory(index, texts)


def search_memory(query, k=5):
    index, texts = load_vector_memory()

    if not texts:
        return []

    q = EMBED_MODEL.encode([query]).astype("float32")
    distances, ids = index.search(q, k)

    results = []
    for i in ids[0]:
        if 0 <= i < len(texts):
            results.append(texts[i])

    return results


def extract_memory(model, user_text):
    prompt = f"""
Extract ONLY stable long-term facts explicitly stated by the user.
Return ONLY valid JSON list of strings.
If no stable fact exists, return [].

User message:
{user_text}
"""

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }

    try:
        r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=60)
        r.raise_for_status()
        result = r.json()["message"]["content"].strip()

        match = re.search(r"\[.*\]", result, re.DOTALL)
        if match:
            result = match.group(0)

        facts = json.loads(result)
        if not isinstance(facts, list):
            return []

        return [
            f.strip()
            for f in facts
            if isinstance(f, str) and 8 <= len(f.strip()) <= 300
        ]

    except Exception:
        return []


# ==============================
# OLLAMA
# ==============================

def get_models():
    try:
        r = requests.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        r.raise_for_status()
        data = r.json()
        return [m["name"] for m in data.get("models", [])]
    except requests.RequestException:
        return []


def unload_model():
    global current_model

    if current_model is None:
        return

    try:
        requests.post(
            f"{OLLAMA_URL}/api/generate",
            json={"model": current_model, "keep_alive": 0},
            timeout=10
        )
    except requests.RequestException:
        pass

    current_model = None


def image_to_base64(path):
    resolved = assert_safe_file(path)
    with open(resolved, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def collect_uploaded_images(uploaded_files):
    images = []
    image_files = []
    other_files = []

    for file in uploaded_files or []:
        path = file.get("path")
        if not path:
            continue

        try:
            resolved = assert_safe_file(path)

            if is_image_file(str(resolved)):
                images.append(image_to_base64(str(resolved)))
                image_files.append(file)
            else:
                other_files.append(file)

        except Exception:
            other_files.append(file)

    return images, image_files, other_files


def chat_ollama(model, messages):
    global current_model

    if current_model and current_model != model:
        unload_model()

    current_model = model

    payload = {
        "model": model,
        "messages": messages,
        "stream": False
    }

    r = requests.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=300)
    r.raise_for_status()

    data = r.json()

    prompt_tokens = data.get("prompt_eval_count")
    completion_tokens = data.get("eval_count")
    total_tokens = None

    if prompt_tokens is not None and completion_tokens is not None:
        total_tokens = prompt_tokens + completion_tokens

    server_ms = None
    if data.get("total_duration") is not None:
        server_ms = round(data["total_duration"] / 1_000_000)

    return {
        "content": data["message"]["content"],
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "server_ms": server_ms
    }


# ==============================
# JSON PARSING
# ==============================

def try_parse_json_object(text):
    text = text.strip()

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        return None

    try:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return None

    return None


# ==============================
# COMMAND APPROVAL
# ==============================

BLOCKED_PATTERNS = [
    "rm ",
    "rm\t",
    "rm -",
    "rmdir",
    "mkfs",
    "dd if=",
    ":(){",
    "chmod",
    "chown",
    "sudo",
    "su ",
    "curl ",
    "wget ",
    "| bash",
    "| sh",
    "> /dev/",
    "shutdown",
    "reboot",
    "poweroff",
    "passwd",
    "userdel",
    "groupdel",
    "format ",
    "del /f",
    "rd /s",
    "reg delete",
    "python -c",
    "perl -e",
    "ruby -e",
    "node -e"
]

ALLOWED_COMMAND_PREFIXES = [
    "ls",
    "pwd",
    "whoami",
    "date",
    "uname",
    "df",
    "du",
    "free",
    "stat",
    "find",
    "grep",
    "egrep",
    "fgrep",
    "head",
    "tail",
    "wc",
    "file",
    "tree",
    "cat",
    "sort",
    "uniq",
    "cut",
    "awk",
    "sed",
    "ps",
    "top",
    "uptime",
    "lscpu",
    "lsblk",
    "mount",
    "id",
    "groups",
    "hostname"
]


def split_chained_command(command):
    parts = re.split(r"\s*(?:&&|\|\||;|\|)\s*", command)
    return [p.strip() for p in parts if p.strip()]


def command_prefix_allowed(command_part):
    parts = command_part.strip().split()
    if not parts:
        return False

    return parts[0] in ALLOWED_COMMAND_PREFIXES


def command_paths_are_safe(command):
    home = str(Path.home().resolve())
    upload = str(UPLOAD_DIR.resolve())

    absolute_paths = re.findall(r"(?<![\w.-])/(?:[^\s'\"`;&|<>]+)", command)

    for raw_path in absolute_paths:
        try:
            resolved = str(Path(raw_path).expanduser().resolve())
        except Exception:
            return False

        if not (
            resolved == home
            or resolved.startswith(home + os.sep)
            or resolved == upload
            or resolved.startswith(upload + os.sep)
        ):
            return False

    return True


def is_command_allowed(command):
    lowered = command.lower()

    for pattern in BLOCKED_PATTERNS:
        if pattern in lowered:
            return False, f"Command matched blocked pattern: {pattern}"

    if not command_paths_are_safe(command):
        return False, "Command references a path outside allowed read roots."

    parts = split_chained_command(command)
    if not parts:
        return False, "Empty command."

    for part in parts:
        if not command_prefix_allowed(part):
            first = part.split()[0] if part.split() else part
            return False, f"Command not whitelisted: {first}"

    return True, "Allowed."


def run_command(command):
    allowed, reason = is_command_allowed(command)

    if not allowed:
        return {
            "command": command,
            "blocked": True,
            "exit_code": None,
            "stdout": "",
            "stderr": reason
        }

    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(Path.home())
        )

        return {
            "command": command,
            "blocked": False,
            "exit_code": result.returncode,
            "stdout": result.stdout[-12000:],
            "stderr": result.stderr[-12000:]
        }

    except subprocess.TimeoutExpired:
        return {
            "command": command,
            "blocked": False,
            "exit_code": None,
            "stdout": "",
            "stderr": "Command timed out after 30 seconds."
        }


# ==============================
# MESSAGE BUILDING
# ==============================

def build_messages(user, uploaded_files=None, chat_id="default"):
    profile = update_profile_from_user_text(user)
    profile_block = json.dumps(profile, ensure_ascii=False, indent=2)

    relevant_memory = search_memory(user, k=5)
    memory_block = "\n".join(relevant_memory)

    uploaded_files = uploaded_files or []
    images, image_files, other_files = collect_uploaded_images(uploaded_files)
    history = get_chat_history(chat_id)

    context = {
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "home": str(Path.home()),
        "upload_dir": str(UPLOAD_DIR),
        "uploaded_files": uploaded_files,
        "image_files_sent_directly_to_model": image_files,
        "non_image_files_available_for_tools": other_files,
        "history_messages_available": len(history)
    }

    user_content = user

    if image_files:
        names = [f.get("filename") or f.get("original_name") or f.get("stored_name") for f in image_files]
        user_content += (
            "\n\nUploaded image files are attached directly in the images field. "
            "Analyze the actual image pixels, not filenames.\n"
            + json.dumps(names, ensure_ascii=False)
        )

    if other_files:
        user_content += (
            "\n\nUploaded non-image files are available via tools:\n"
            + json.dumps(other_files, ensure_ascii=False, indent=2)
        )

    user_message = {
        "role": "user",
        "content": user_content
    }

    if images:
        user_message["images"] = images

    messages = [
        {
            "role": "system",
            "content": (
                SYSTEM_PROMPT
                + "\n\nUser profile memory:\n"
                + profile_block
                + "\n\nRelevant vector memory:\n"
                + memory_block
                + "\n\nCurrent local server context:\n"
                + json.dumps(context, ensure_ascii=False, indent=2)
            )
        },
        *history,
        user_message
    ]

    return messages, profile_block, memory_block


def continue_after_tool(model, messages, tool_request, tool_result):
    messages.append({
        "role": "assistant",
        "content": json.dumps(tool_request, ensure_ascii=False)
    })

    messages.append({
        "role": "user",
        "content": (
            "Tool result:\n"
            + json.dumps(tool_result, ensure_ascii=False, indent=2)
            + "\n\nNow answer the original user request using this result."
        )
    })

    return chat_ollama(model, messages)


# ==============================
# ROUTES
# ==============================

@app.route("/")
def index():
    models = get_models()
    return render_template("index.html", models=models)


@app.route("/chat", methods=["POST"])
def chat():
    data = request.json or {}

    user = data.get("message", "").strip()
    model = data.get("model", "").strip()
    chat_id = data.get("chat_id") or "default"

    uploaded_files = data.get("uploaded_files")
    if uploaded_files is None:
        uploaded_files = data.get("files", [])

    if not user and not uploaded_files:
        return jsonify({"response": "Fehler: Leere Nachricht."}), 400

    if not model:
        return jsonify({"response": "Fehler: Kein Modell ausgewählt."}), 400

    if not user:
        user = "Bitte analysiere die hochgeladenen Dateien."

    messages, profile_block, memory_block = build_messages(user, uploaded_files, chat_id)

    try:
        response = chat_ollama(model, messages)
        request_obj = try_parse_json_object(response["content"])

        if request_obj and request_obj.get("type") == "tool_request":
            tool_name = request_obj.get("tool")
            args = request_obj.get("args", {})

            tool_result = run_tool(tool_name, args)
            
            print("TOOL CALL:", tool_name, args)
            print("TOOL RESULT:", tool_result)
            
            final_response = continue_after_tool(model, messages, request_obj, tool_result)

            append_history(chat_id, "user", user)
            append_history(chat_id, "assistant", final_response["content"])

            return jsonify({
                "response": final_response["content"],
                "prompt_tokens": final_response["prompt_tokens"],
                "completion_tokens": final_response["completion_tokens"],
                "total_tokens": final_response["total_tokens"],
                "server_ms": final_response["server_ms"]
            })

        if request_obj and request_obj.get("type") == "command_request":
            command = request_obj.get("command", "").strip()
            reason = request_obj.get("reason", "").strip()

            if not command:
                return jsonify({"response": "Fehler: Leerer Command."}), 400

            valid, validation_reason = is_command_allowed(command)
            command_id = str(uuid.uuid4())

            PENDING_COMMANDS[command_id] = {
                "command": command,
                "reason": reason,
                "original_user_message": user,
                "profile_block": profile_block,
                "memory_block": memory_block,
                "uploaded_files": uploaded_files,
                "chat_id": chat_id
            }

            return jsonify({
                "response": "COMMAND_APPROVAL_REQUIRED",
                "command_id": command_id,
                "command": command,
                "reason": reason,
                "valid": valid,
                "validation_reason": validation_reason,
                "prompt_tokens": response["prompt_tokens"],
                "completion_tokens": response["completion_tokens"],
                "total_tokens": response["total_tokens"],
                "server_ms": response["server_ms"]
            })

        new_facts = extract_memory(model, user)
        for fact in new_facts:
            add_memory(fact)

        append_history(chat_id, "user", user)
        append_history(chat_id, "assistant", response["content"])

        return jsonify({
            "response": response["content"],
            "prompt_tokens": response["prompt_tokens"],
            "completion_tokens": response["completion_tokens"],
            "total_tokens": response["total_tokens"],
            "server_ms": response["server_ms"]
        })

    except requests.RequestException as e:
        return jsonify({
            "response": f"Fehler: Ollama ist nicht erreichbar oder hat keine gültige Antwort geliefert.\n\n{str(e)}"
        }), 502

    except Exception as e:
        return jsonify({
            "response": f"Interner Fehler: {str(e)}"
        }), 500


@app.route("/approve-command", methods=["POST"])
def approve_command():
    data = request.json or {}

    command_id = data.get("command_id")
    approved = data.get("approved") is True
    model = data.get("model", "").strip()
    request_chat_id = data.get("chat_id") or "default"

    pending = PENDING_COMMANDS.pop(command_id, None)

    if not pending:
        return jsonify({"response": "Fehler: Command nicht gefunden oder bereits verarbeitet."}), 404

    if not model:
        return jsonify({"response": "Fehler: Kein Modell ausgewählt."}), 400

    command = pending["command"]
    chat_id = pending.get("chat_id") or request_chat_id

    if not approved:
        append_history(chat_id, "user", pending["original_user_message"])
        append_history(chat_id, "assistant", f"Ausführung abgelehnt.\n\n```bash\n{command}\n```")

        return jsonify({
            "response": f"Ausführung abgelehnt.\n\n```bash\n{command}\n```"
        })

    command_output = run_command(command)

    messages, _, _ = build_messages(
        pending["original_user_message"],
        pending.get("uploaded_files", []),
        chat_id
    )

    messages.append({
        "role": "assistant",
        "content": json.dumps({
            "type": "command_request",
            "command": command,
            "reason": pending["reason"]
        }, ensure_ascii=False)
    })

    messages.append({
        "role": "user",
        "content": (
            "The user approved the command. Here is the result:\n\n"
            + json.dumps(command_output, ensure_ascii=False, indent=2)
            + "\n\nNow answer the original user request using this command result."
        )
    })

    try:
        response = chat_ollama(model, messages)

        append_history(chat_id, "user", pending["original_user_message"])
        append_history(chat_id, "assistant", response["content"])

        return jsonify({
            "response": response["content"],
            "prompt_tokens": response["prompt_tokens"],
            "completion_tokens": response["completion_tokens"],
            "total_tokens": response["total_tokens"],
            "server_ms": response["server_ms"]
        })

    except Exception as e:
        return jsonify({"response": f"Fehler nach Command-Ausführung: {str(e)}"}), 500


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "Keine Datei im Request."}), 400

    file = request.files["file"]

    if file.filename == "":
        return jsonify({"error": "Leerer Dateiname."}), 400

    original_name = Path(file.filename).name
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", original_name)
    unique_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}_{safe_name}"

    target = UPLOAD_DIR / unique_name
    file.save(target)

    return jsonify({
        "filename": original_name,
        "original_name": original_name,
        "stored_name": unique_name,
        "path": str(target),
        "size_bytes": target.stat().st_size,
        "is_image": is_image_file(str(target))
    })


@app.route("/history", methods=["GET"])
def history_debug():
    chat_id = request.args.get("chat_id") or "default"
    return jsonify({
        "chat_id": chat_id,
        "history_count": len(get_chat_history(chat_id)),
        "history": get_chat_history(chat_id)
    })


@app.route("/history", methods=["DELETE"])
def history_clear():
    data = request.json or {}
    chat_id = data.get("chat_id") or request.args.get("chat_id") or "default"
    clear_chat_history(chat_id)
    return jsonify({
        "response": "Chat-Verlauf gelöscht.",
        "chat_id": chat_id
    })


@app.route("/memory", methods=["GET"])
def memory_debug():
    profile = load_profile()
    index, texts = load_vector_memory()

    return jsonify({
        "profile": profile,
        "vector_memory_count": len(texts),
        "vector_memory": texts
    })


@app.route("/memory", methods=["DELETE"])
def memory_clear():
    profile = default_profile()
    save_profile(profile)

    if os.path.exists(TEXT_FILE):
        os.remove(TEXT_FILE)

    if os.path.exists(INDEX_FILE):
        os.remove(INDEX_FILE)

    index = faiss.IndexFlatL2(DIM)
    texts = []
    save_vector_memory(index, texts)

    return jsonify({
        "response": "Memory gelöscht.",
        "profile": profile,
        "vector_memory": []
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

# !/usr/bin/python
# pareAI.py - AI assistance module for Paredicma (Ollama / OpenAI / Azure)

import re
import subprocess
from datetime import datetime

import requests
from pareConfig import *
from pareNodeList import *


# ─── Provider implementations ────────────────────────────────────────────────

def strip_thinking(text: str) -> str:
    """Keep only the answer when a model returns its reasoning inline, closed by </think>."""
    if "</think>" in text:
        return text.split("</think>")[-1].strip()
    if text.lstrip().startswith("<think>"):
        return "ERROR: Model is still reasoning and did not finish. Try again or disable thinking."
    return text


def ollama_chat(prompt: str, model: str = None, timeout: int = 120, thinking: bool = False, num_ctx: int = None) -> str:
    model = model or aiModel
    url = f"{ollamaUrl}/api/generate"
    # Thinking tokens count against num_predict, so the budget is larger when thinking is on
    options = {"temperature": 0.2, "num_predict": 4096 if thinking else 1024}
    if num_ctx:
        # Ollama defaults to a small context window; large merged prompts need it raised
        options["num_ctx"] = num_ctx
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": thinking,
        "options": options
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        if resp.status_code >= 400:
            # Show the body: Ollama and the gateway explain what was rejected there
            return f"ERROR: {resp.status_code} from {url}: {resp.text[:300]}"
        data = resp.json()
        text = data.get("response", "").strip()
        if thinking and data.get("done_reason") == "length" and "</think>" not in text:
            # The reply limit ran out while the model was still reasoning, so there is no answer yet
            return "ERROR: The model ran out of reply tokens while thinking, before giving an answer. Try again with a shorter log range, or turn thinking off."
        return strip_thinking(text)
    except requests.exceptions.ConnectionError:
        return "ERROR: Cannot reach Ollama at " + ollamaUrl + ". Is Ollama running?"
    except requests.exceptions.Timeout:
        return "ERROR: Ollama request timed out after " + str(timeout) + "s."
    except Exception as e:
        return f"ERROR: {str(e)}"


def openai_chat(prompt: str, timeout: int = 120) -> str:
    if not openaiApiKey:
        return "ERROR: openaiApiKey is not set in pareConfig.py."
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": "Bearer " + openaiApiKey,
        "Content-Type": "application/json"
    }
    payload = {
        "model": openaiModel,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 1024
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        return "ERROR: Cannot reach OpenAI API. Check your internet connection."
    except requests.exceptions.Timeout:
        return "ERROR: OpenAI request timed out after " + str(timeout) + "s."
    except Exception as e:
        return f"ERROR: {str(e)}"


def azure_chat(prompt: str, timeout: int = 120) -> str:
    if not azureApiKey:
        return "ERROR: azureApiKey is not set in pareConfig.py."
    if not azureEndpoint or not azureDeployment:
        return "ERROR: azureEndpoint and azureDeployment must be set in pareConfig.py."
    url = (
        azureEndpoint.rstrip("/")
        + "/openai/deployments/" + azureDeployment
        + "/chat/completions?api-version=" + azureApiVersion
    )
    headers = {
        "api-key": azureApiKey,
        "Content-Type": "application/json"
    }
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "max_tokens": 1024
    }
    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except requests.exceptions.ConnectionError:
        return "ERROR: Cannot reach Azure OpenAI endpoint: " + azureEndpoint
    except requests.exceptions.Timeout:
        return "ERROR: Azure OpenAI request timed out after " + str(timeout) + "s."
    except Exception as e:
        return f"ERROR: {str(e)}"


def ai_chat(prompt: str, timeout: int = 120, thinking: bool = False, num_ctx: int = None) -> str:
    """Unified AI call — routes to Ollama, OpenAI, or Azure based on aiProvider in pareConfig.
    thinking applies to Ollama only; OpenAI and Azure models do not take this option here."""
    provider = aiProvider.lower() if aiProvider else "ollama"
    if provider == "openai":
        return openai_chat(prompt, timeout)
    elif provider == "azure":
        return azure_chat(prompt, timeout)
    else:
        return ollama_chat(prompt, timeout=timeout, thinking=thinking, num_ctx=num_ctx)


def ai_timeout(thinking: bool) -> int:
    """
    Merged log prompts are about 25k tokens, and prompt processing alone can take minutes on a
    local model. Thinking adds generation time on top, so it gets a longer limit.
    """
    return 900 if thinking else 300


def ai_model_label(thinking: bool) -> str:
    label = aiProvider + ":" + (openaiModel if aiProvider == "openai" else azureDeployment if aiProvider == "azure" else aiModel)
    return label + (" (thinking)" if thinking and aiProvider.lower() not in ("openai", "azure") else "")


def _is_local(ip: str) -> bool:
    import socket
    if ip in ("127.0.0.1", "localhost", "::1", pareServerIp):
        return True
    try:
        local_ips = socket.gethostbyname_ex(socket.gethostname())[2]
        return ip in local_ips
    except Exception:
        return False

# ─── Feature 1: Cluster State Health Analysis ───────────────────────────────

def gather_cluster_topology() -> dict:
    contact_node = None
    for node in pareNodes:
        ip, port = node[0][0], node[1][0]
        if node[4]:
            try:
                result = subprocess.check_output(
                    [f"{redisBinaryDir}src/redis-cli", "-h", ip, "-p", port,
                     "-a", redisPwd, "--no-auth-warning", "PING"],
                    stderr=subprocess.DEVNULL, timeout=3
                ).decode().strip()
                if result == "PONG":
                    contact_node = (ip, port)
                    break
            except Exception:
                continue

    if not contact_node:
        return {"error": "No reachable Redis node found."}

    try:
        raw = subprocess.check_output(
            [f"{redisBinaryDir}src/redis-cli", "-h", contact_node[0],
             "-p", contact_node[1], "-a", redisPwd, "--no-auth-warning",
             "CLUSTER", "NODES"],
            stderr=subprocess.DEVNULL, timeout=5
        ).decode().strip()
    except Exception as e:
        return {"error": f"CLUSTER NODES failed: {e}"}

    masters = {}
    slaves = []
    down_nodes = []

    for line in raw.splitlines():
        parts = line.split()
        if len(parts) < 8:
            continue
        node_id = parts[0]
        address = parts[1].split("@")[0]
        flags = parts[2].split(",")
        master_ref = parts[3]
        connected = parts[7] if len(parts) > 7 else "unknown"
        try:
            srv_ip, srv_port = address.split(":")
        except ValueError:
            srv_ip, srv_port = address, "?"

        is_master = "master" in flags
        is_slave = "slave" in flags
        is_fail = "fail" in flags or "noaddr" in flags or connected == "disconnected"

        if is_fail:
            down_nodes.append({"id": node_id, "address": address,
                                "role": "slave" if is_slave else "master"})
            continue

        if is_master:
            slots = " ".join(p for p in parts[8:] if "-" in p or p.isdigit()) if len(parts) > 8 else ""
            masters[node_id] = {
                "address": address, "server_ip": srv_ip,
                "port": srv_port, "slots": slots, "replicas": []
            }
        elif is_slave:
            slaves.append({"id": node_id, "address": address,
                           "server_ip": srv_ip, "port": srv_port,
                           "master_id": master_ref})

    for slave in slaves:
        mid = slave["master_id"]
        if mid in masters:
            masters[mid]["replicas"].append(slave)

    return {
        "masters": masters,
        "down_nodes": down_nodes,
        "total_masters": len(masters),
        "total_slaves": len(slaves),
        "total_down": len(down_nodes)
    }

def build_cluster_health_prompt(topology: dict) -> str:
    if "error" in topology:
        return "Redis cluster topology error: " + topology["error"]

    masters = topology["masters"]
    down = topology["down_nodes"]

    lines = [
        "You are a Redis cluster operations expert.",
        "Analyze the following Redis cluster topology and report:",
        "1. Whether each master has at least one replica.",
        "2. Whether each replica is on a DIFFERENT server than its master.",
        "3. Masters with NO replicas (critical risk).",
        "4. Masters whose replica is on the SAME server (high risk, single point of failure).",
        "5. Any down nodes.",
        "6. Overall cluster health: OK / WARNING / CRITICAL.",
        "7. Specific actionable recommendations.",
        "",
        "Topology summary: "
        + str(topology["total_masters"]) + " masters, "
        + str(topology["total_slaves"]) + " replicas, "
        + str(topology["total_down"]) + " down nodes.",
        "",
        "Master nodes and their replicas:",
    ]

    for mid, m in masters.items():
        addr = m["address"]
        sip = m["server_ip"]
        slots = m["slots"] or "none"
        lines.append("")
        lines.append("  MASTER: " + addr + "  (server: " + sip + ", slots: " + slots + ")")
        if not m["replicas"]:
            lines.append("    ** NO REPLICAS - critical single point of failure! **")
        else:
            for r in m["replicas"]:
                same = r["server_ip"] == m["server_ip"]
                note = " [SAME SERVER - high risk!]" if same else " [different server - OK]"
                lines.append("    Replica: " + r["address"] + "  (server: " + r["server_ip"] + ")" + note)

    if down:
        lines.append("")
        lines.append("Down / Failed Nodes:")
        for d in down:
            lines.append("  FAIL: " + d["address"] + " (role: " + d["role"] + ")")

    lines.append("")
    lines.append("Provide a concise analysis with clear health status and actionable recommendations.")
    return "\n".join(lines)


def analyze_cluster_health(thinking: bool = False) -> dict:
    """Gather cluster topology and use AI to analyze it."""
    topology = gather_cluster_topology()
    if "error" in topology:
        return {"error": topology["error"], "analysis": None}
    prompt = build_cluster_health_prompt(topology)
    analysis = ai_chat(prompt, timeout=ai_timeout(thinking), thinking=thinking)
    return {"topology": topology, "analysis": analysis, "model": ai_model_label(thinking)}

# ─── Feature 2: Post-Failover Log Analysis ──────────────────────────────────

def get_raw_log_content(redisNode: str, line_count: int = 200) -> str:
    """Read raw Redis log content for a node (no HTML formatting)."""
    try:
        node_ip, port_number = redisNode.split(":")
    except ValueError:
        return f"ERROR: Invalid node format. Expected IP:port, got: {redisNode}"

    node_index = -1
    for i, node in enumerate(pareNodes):
        if node[0][0] == node_ip and node[1][0] == port_number and node[4]:
            node_index = i + 1
            break

    if node_index == -1:
        return f"ERROR: Node {redisNode} not found or inactive in configuration."

    log_path = f"{redisLogDir}redisN{node_index}_P{port_number}.log"

    try:
        if _is_local(node_ip):
            result = subprocess.check_output(
                ["tail", "-n", str(line_count), log_path],
                stderr=subprocess.STDOUT, timeout=10
            ).decode()
        else:
            cmd = f"ssh -q -o StrictHostKeyChecking=no {pareOSUser}@{node_ip} tail -n {line_count} {log_path}"
            result = subprocess.check_output(
                cmd, shell=True, stderr=subprocess.STDOUT, timeout=15
            ).decode()
        return result
    except subprocess.CalledProcessError as e:
        return f"ERROR: Could not read log file {log_path}: {e.output.decode()}"
    except Exception as e:
        return f"ERROR: {str(e)}"


# Log analysis limits: lines per node, 10 to 100. The prompt must fit COMBINED_NUM_CTX tokens together with the output.
MIN_LOG_LINES = 10
MAX_LOG_LINES = 100
COMBINED_NUM_CTX = 32768
PROMPT_OVERHEAD_TOKENS = 1000   # instructions and template text around the logs
REPLY_TOKENS = 1024             # num_predict without thinking
REPLY_TOKENS_THINKING = 4096    # num_predict with thinking (reasoning tokens count too)
# Measured on granite4.2:8b: Redis log text is about 2.25 characters per token. 2.0 keeps a margin.
CHARS_PER_TOKEN = 2.0

# Redis log line start: "<pid>:<role> DD Mon YYYY HH:MM:SS.mmm ..."
_LOG_TIMESTAMP = re.compile(r'^\d+:[A-Za-z] (\d{2} \w{3} \d{4} \d{2}:\d{2}:\d{2}\.\d{3})')


def log_char_budget(thinking: bool) -> int:
    """Characters available for log lines, derived from the context window and the reply size."""
    reply = REPLY_TOKENS_THINKING if thinking else REPLY_TOKENS
    tokens = COMBINED_NUM_CTX - reply - PROMPT_OVERHEAD_TOKENS
    return int(tokens * CHARS_PER_TOKEN)


def _fair_quotas(sizes: dict, budget: int) -> dict:
    """Splits budget across nodes. Nodes with little text keep all of it; the rest is shared equally."""
    quotas = {}
    remaining = budget
    ordered = sorted(sizes, key=lambda node: sizes[node])
    for index, node in enumerate(ordered):
        fair_share = remaining // (len(ordered) - index)
        quotas[node] = min(sizes[node], fair_share)
        remaining -= quotas[node]
    return quotas


def merge_node_logs(node_logs: dict, char_budget: int) -> tuple:
    """
    Merges the logs of several nodes into one timeline, sorted by timestamp, tagged with the node.
    Each node keeps its newest lines within a fair share of char_budget, so no node disappears
    because another node is chatty. Lines without a timestamp stay with the line before them.
    Returns (timeline_text, included_line_count, omitted_line_count).
    """
    per_node = {}  # node -> list of (timestamp, sequence, tagged_line)
    sequence = 0
    for node, text in node_logs.items():
        last_stamp = datetime.min
        entries = []
        for line in text.splitlines():
            if not line.strip():
                continue
            match = _LOG_TIMESTAMP.match(line)
            if match:
                last_stamp = datetime.strptime(match.group(1), '%d %b %Y %H:%M:%S.%f')
            entries.append((last_stamp, sequence, f"[{node}] {line}"))
            sequence += 1
        per_node[node] = entries

    sizes = {node: sum(len(tagged) + 1 for _, _, tagged in entries) for node, entries in per_node.items()}
    quotas = _fair_quotas(sizes, char_budget)

    kept = []
    total_lines = 0
    for node, entries in per_node.items():
        total_lines += len(entries)
        used = 0
        node_kept = []
        for entry in reversed(entries):  # newest first
            cost = len(entry[2]) + 1
            if used + cost > quotas[node]:
                break
            node_kept.append(entry)
            used += cost
        kept.extend(node_kept)

    kept.sort(key=lambda e: (e[0], e[1]))
    lines = [tagged for _, _, tagged in kept]
    omitted = total_lines - len(lines)
    return "\n".join(lines), len(lines), omitted


def build_combined_log_prompt(timeline: str, nodes: list, omitted: int) -> str:
    omitted_note = (
        f"Note: {omitted} earlier lines were omitted because of the size limit.\n"
        if omitted else ""
    )
    return (
        "You are a Redis operations expert analyzing logs from several nodes of the same cluster after a potential failover.\n"
        f"Nodes analyzed: {', '.join(nodes)}\n"
        "The lines below come from all these nodes, merged by timestamp. Each line starts with its node in brackets.\n"
        "The nodes' logs complete each other: a failover on one node is usually confirmed by lines on the others.\n\n"
        "Analyze the merged timeline and answer:\n"
        "1. Timeline: which failover or role change events happened, in order, and on which node.\n"
        "2. Was the failover successful? Confirm it from the other nodes' lines where possible.\n"
        "3. Current role of each node (master/replica), as far as the logs show.\n"
        "4. Replication and connection problems, cluster errors, or data integrity concerns, naming the node for each.\n"
        "5. Overall status: OK / WARNING / CRITICAL\n"
        "6. Recommended follow-up actions (if any).\n\n"
        "Be concise. Name the node for every finding.\n"
        f"{omitted_note}"
        f"--- Merged Redis logs ({len(timeline.splitlines())} lines) ---\n"
        + timeline +
        "\n--- End of Logs ---\n\n"
        "Analysis:"
    )


def _active_node_addresses() -> list:
    return [f"{node[0][0]}:{node[1][0]}" for node in pareNodes if node[4]]


def analyze_logs(nodes: list, line_count: int = 200, thinking: bool = False) -> dict:
    """
    Reads the logs of one or more nodes, merges them by time, and asks AI for one analysis.
    line_count is kept within MIN_LOG_LINES..MAX_LOG_LINES per node.
    """
    nodes = [node.strip() for node in nodes if node.strip()]
    if not nodes:
        return {"error": "ERROR: No nodes selected.", "analysis": None}

    requested_lines = line_count
    line_count = min(max(line_count, MIN_LOG_LINES), MAX_LOG_LINES)
    lines_clamped = line_count != requested_lines

    node_logs = {}
    node_errors = []
    for node in nodes:
        log_text = get_raw_log_content(node, line_count)
        if log_text.startswith("ERROR:"):
            node_errors.append(log_text)
        else:
            node_logs[node] = log_text

    if not node_logs:
        return {"error": " ".join(node_errors) or "ERROR: No logs could be read.", "analysis": None}

    timeline, included, omitted = merge_node_logs(node_logs, log_char_budget(thinking))
    prompt = build_combined_log_prompt(timeline, list(node_logs.keys()), omitted)
    analysis = ai_chat(prompt, timeout=ai_timeout(thinking), thinking=thinking, num_ctx=COMBINED_NUM_CTX)
    return {
        "nodes": list(node_logs.keys()),
        "analysis": analysis,
        "model": ai_model_label(thinking),
        "log_lines": included,
        "omitted_lines": omitted,
        "lines_per_node": line_count,
        "lines_clamped": lines_clamped,
        "node_errors": node_errors,
    }

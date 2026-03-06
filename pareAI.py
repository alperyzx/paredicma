# !/usr/bin/python
# pareAI.py - AI assistance module for Paredicma (Ollama / OpenAI / Azure)

import subprocess
import requests
from pareConfig import *
from pareNodeList import *


# ─── Provider implementations ────────────────────────────────────────────────

def ollama_chat(prompt: str, model: str = None, timeout: int = 120) -> str:
    model = model or aiModel
    url = f"{ollamaUrl}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 1024}
    }
    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()
        return resp.json().get("response", "").strip()
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


def ai_chat(prompt: str, timeout: int = 120) -> str:
    """Unified AI call — routes to Ollama, OpenAI, or Azure based on aiProvider in pareConfig."""
    provider = aiProvider.lower() if aiProvider else "ollama"
    if provider == "openai":
        return openai_chat(prompt, timeout)
    elif provider == "azure":
        return azure_chat(prompt, timeout)
    else:
        return ollama_chat(prompt, timeout=timeout)


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


def analyze_cluster_health() -> dict:
    """Gather cluster topology and use AI to analyze it."""
    topology = gather_cluster_topology()
    if "error" in topology:
        return {"error": topology["error"], "analysis": None}
    prompt = build_cluster_health_prompt(topology)
    analysis = ai_chat(prompt)
    provider_label = aiProvider + ":" + (openaiModel if aiProvider == "openai" else azureDeployment if aiProvider == "azure" else aiModel)
    return {"topology": topology, "analysis": analysis, "model": provider_label}

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


def build_log_analysis_prompt(log_text: str, redisNode: str) -> str:
    line_count = log_text.count("\n") + 1
    return (
        "You are a Redis operations expert analyzing logs after a potential failover.\n"
        f"Node being analyzed: {redisNode}\n\n"
        "Please analyze the following Redis log excerpt and answer:\n"
        "1. Did a failover or role change occur? Describe what happened and when.\n"
        "2. Was the failover successful? Any errors or warnings?\n"
        "3. What is the current role of this node (master/replica)?\n"
        "4. Are there connection failures, cluster errors, or data integrity concerns?\n"
        "5. Overall status: OK / WARNING / CRITICAL\n"
        "6. Recommended follow-up actions (if any).\n\n"
        "Be concise and focus on operations-relevant findings.\n\n"
        f"--- Redis Log ({line_count} lines from tail) ---\n"
        + log_text[:6000] +
        "\n--- End of Log ---\n\n"
        "Analysis:"
    )


def analyze_logs(redisNode: str, line_count: int = 200) -> dict:
    """Read a node log file and use AI to analyze it for post-failover health."""
    log_text = get_raw_log_content(redisNode, line_count)
    if log_text.startswith("ERROR:"):
        return {"error": log_text, "analysis": None}
    prompt = build_log_analysis_prompt(log_text, redisNode)
    analysis = ai_chat(prompt)
    provider_label = aiProvider + ":" + (openaiModel if aiProvider == "openai" else azureDeployment if aiProvider == "azure" else aiModel)
    return {
        "node": redisNode,
        "analysis": analysis,
        "model": provider_label,
        "log_lines": line_count
    }

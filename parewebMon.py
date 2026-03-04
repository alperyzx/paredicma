# !/usr/bin/python
#paredicma webview v1.0
#date: 27.02.2024
#author: alperyz


import os
import sys  # Ensure sys is imported for module reloading

from pareConfig import *
from pareNodeList import *
from pareFunc import *
from pareFuncWeb import *

from fastapi import *
from fastapi.responses import HTMLResponse  # Import HTMLResponse
from subprocess import getstatusoutput
from time import sleep  # Import sleep

# Create an instance of FastAPI
app = FastAPI()
router = APIRouter()

@app.middleware("http")
async def reload_nodes_middleware(request, call_next):
    """
    Middleware that reloads the pareNodes configuration before processing certain paths.
    This ensures the UI always shows the latest node configuration.
    """
    # List of paths that should trigger a configuration reload
    reload_paths = [
        "/monitor",  # Added main monitor page
        "/monitor/list-nodes/",
        "/monitor/ping-nodes/",
        "/monitor/node-info/",  # Added node-info endpoint
        "/monitor/slot-info/",
        "/monitor/cluster-state-info",
        "/monitor/memory-usage",
        "/maintain",
        "/manager"
    ]

    # Check if the current path should trigger a reload
    if any(request.url.path.startswith(path) for path in reload_paths):
        try:
            # Reload the pareNodeList module
            import importlib
            importlib.reload(sys.modules['pareNodeList'])
            from pareNodeList import pareNodes as fresh_pareNodes

            # Update the global pareNodes with the freshly loaded version
            global pareNodes
            pareNodes = fresh_pareNodes
        except Exception as e:
            print(f"Error reloading node configuration: {str(e)}")

    # Continue processing the request
    response = await call_next(request)
    return response

# Add an endpoint to manually refresh the node configuration
@app.get("/refresh-config", response_class=HTMLResponse)
async def refresh_config():
    """
    Endpoint to manually refresh the node configuration.
    """
    try:
        # Reload the pareNodeList module
        import importlib
        importlib.reload(sys.modules['pareNodeList'])
        from pareNodeList import pareNodes as fresh_pareNodes

        # Update the global pareNodes
        global pareNodes
        pareNodes = fresh_pareNodes

        # Generate the response message
        response_message = f"""
        {css_style}
        <html>
        <head><title>Configuration Refreshed</title></head>
        <body>
            <h2>Node Configuration Refreshed</h2>
            <p>The node configuration has been successfully reloaded.</p>
            <p>Current active nodes: {sum(1 for node in pareNodes if node[4])}</p>
        </body>
        </html>
        """
        return HTMLResponse(content=response_message)
    except Exception as e:
        response_message = f"""
        {css_style}
        <html>
        <head><title>Configuration Refresh Failed</title></head>
        <body>
            <h2>Node Configuration Refresh Failed</h2>
            <p style='color: red;'>Error: {str(e)}</p>
        </body>
        </html>
        """
        return HTMLResponse(content=response_message)

# Define the ping-nodes endpoint
@app.get("/monitor/ping-nodes/")
def ping_nodes():
    pong_number = 0
    non_pong_number = 0
    ping_results = []

    for pareNode in pareNodes:
        node_ip = pareNode[0][0]
        port_number = pareNode[1][0]

        if pareNode[4]:
            isPing = pingredisNode(node_ip, port_number)
            if isPing:
                ping_result = [node_ip, port_number, "OK"]
                pong_number += 1
            else:
                ping_result = [node_ip, port_number, "NOT OK"]
                non_pong_number += 1
            ping_results.append(ping_result)

    # Prepare the table content with inline CSS styles
    table_content = "<table><tr><th>Server IP</th><th>Port</th><th>Status</th></tr>"
    for result in ping_results:
        if result[2] == "OK":
            status_style = "color: green;"
        else:
            status_style = "color: red;"
        table_content += f"<tr><td>{result[0]}</td><td>{result[1]}</td><td style='{status_style}'>{result[2]}</td></tr>"
    table_content += "</table>"

    # Prepare the response message
    response_message = f"{css_style}<html><title>Pinging Nodes</title><body><h2>Pinging Nodes...</h2>{table_content}<p>OK Nodes = {pong_number}<br>Not OK Nodes = {non_pong_number}</p></body></html>"

    # Return the response with content type set to text/html
    return Response(content=response_message, media_type="text/html")


# Define the list-nodes endpoint
@app.get("/monitor/list-nodes/")
def list_nodes():
    # Find an active node to query
    contact_node = None
    for pare_node in pareNodes:
        node_ip = pare_node[0][0]
        port_number = pare_node[1][0]
        if pare_node[4] and pingredisNode(node_ip, port_number):
            contact_node = (node_ip, port_number)
            break

    if not contact_node:
        return Response(
            content=f"{css_style}<html><title>Node List</title><body><h2>Error</h2><p>No active node found to query cluster status.</p></body></html>",
            media_type="text/html"
        )

    # Query cluster nodes from the active node
    cluster_cmd = f"{redisConnectCmd(contact_node[0], contact_node[1], 'CLUSTER NODES')}"
    status, output = subprocess.getstatusoutput(cluster_cmd)

    if status != 0:
        return Response(
            content=f"{css_style}<html><title>Node List</title><body><h2>Error</h2><p>Failed to get cluster nodes information.</p></body></html>",
            media_type="text/html"
        )

    # Prepare data structures - now organize by master with their replicas
    masters = {}  # master_id -> {address, node_id, slots, replicas: []}
    down_nodes = []
    unknown_nodes = []

    # First pass: identify all masters
    for line in output.strip().split('\n'):
        parts = line.split()
        if len(parts) < 8:
            continue

        node_id = parts[0]
        address = parts[1].split('@')[0]
        role_status = parts[2]
        
        is_master = "master" in role_status
        is_fail = "fail" in role_status or ("disconnected" in parts[7] if len(parts) > 7 else False)

        if is_master and not is_fail:
            # Extract slot range if available
            slots = ' '.join([p for p in parts[8:] if '-' in p or p.isdigit()]) if len(parts) > 8 else ''
            masters[node_id] = {
                'address': address,
                'node_id': node_id,
                'slots': slots,
                'replicas': []
            }

    # Second pass: assign slaves to their masters and identify down/unknown nodes
    for line in output.strip().split('\n'):
        parts = line.split()
        if len(parts) < 8:
            continue

        node_id = parts[0]
        address = parts[1].split('@')[0]
        role_status = parts[2]
        
        is_master = "master" in role_status
        is_slave = "slave" in role_status
        is_fail = "fail" in role_status or ("disconnected" in parts[7] if len(parts) > 7 else False)

        if is_fail:
            master_id = parts[3] if len(parts) > 3 and is_slave else None
            role = "slave" if is_slave else "master" if is_master else "unknown"
            down_nodes.append({
                'address': address,
                'node_id': node_id,
                'master_id': master_id if master_id and master_id != '-' else None,
                'role': role
            })
        elif is_slave:
            master_id = parts[3] if len(parts) > 3 else None
            if master_id and master_id in masters:
                masters[master_id]['replicas'].append({
                    'address': address,
                    'node_id': node_id
                })
        elif not is_master:
            unknown_nodes.append({
                'address': address,
                'node_id': node_id
            })

    # Generate HTML with side-by-side master/replica layout
    html = f"""
    {css_style}
    <style>
        .node-card {{
            border: 1px solid #ddd;
            border-radius: 8px;
            margin-bottom: 15px;
            overflow: hidden;
            background: #fff;
        }}
        .master-header {{
            background: linear-gradient(135deg, #2196F3 0%, #1976D2 100%);
            color: white;
            padding: 12px 15px;
            font-weight: bold;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .master-address {{
            font-size: 1.1em;
        }}
        .master-id {{
            font-size: 0.85em;
            opacity: 0.9;
            font-family: monospace;
        }}
        .slot-info {{
            font-size: 0.85em;
            background: rgba(255,255,255,0.2);
            padding: 3px 8px;
            border-radius: 4px;
        }}
        .replicas-container {{
            padding: 10px 15px;
            background: #f9f9f9;
        }}
        .replica-row {{
            display: flex;
            align-items: center;
            padding: 8px 10px;
            margin: 5px 0;
            background: #fff;
            border: 1px solid #e0e0e0;
            border-left: 4px solid #4CAF50;
            border-radius: 4px;
        }}
        .replica-icon {{
            color: #4CAF50;
            margin-right: 10px;
            font-size: 1.2em;
        }}
        .replica-address {{
            flex-grow: 1;
            font-weight: 500;
        }}
        .replica-id {{
            font-size: 0.85em;
            color: #666;
            font-family: monospace;
        }}
        .no-replicas {{
            color: #999;
            font-style: italic;
            padding: 10px;
        }}
        .down-section, .unknown-section {{
            margin-top: 20px;
            padding: 15px;
            border-radius: 8px;
        }}
        .down-section {{
            background: #ffebee;
            border: 1px solid #ffcdd2;
        }}
        .unknown-section {{
            background: #f5f5f5;
            border: 1px solid #e0e0e0;
        }}
        .section-title {{
            font-weight: bold;
            margin-bottom: 10px;
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .down-section .section-title {{
            color: #c62828;
        }}
        .unknown-section .section-title {{
            color: #757575;
        }}
        .down-node, .unknown-node {{
            padding: 8px 12px;
            margin: 5px 0;
            border-radius: 4px;
            font-size: 0.95em;
        }}
        .down-node {{
            background: #fff;
            border-left: 4px solid #f44336;
        }}
        .unknown-node {{
            background: #fff;
            border-left: 4px solid #9e9e9e;
        }}
        .summary-bar {{
            display: flex;
            gap: 20px;
            padding: 15px;
            background: #e3f2fd;
            border-radius: 8px;
            margin-bottom: 20px;
            flex-wrap: wrap;
        }}
        .summary-item {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .summary-count {{
            font-size: 1.5em;
            font-weight: bold;
        }}
        .summary-label {{
            color: #666;
        }}
        @media (prefers-color-scheme: dark) {{
            .node-card {{
                background: #1e1e1e;
                border-color: #444;
            }}
            .master-header {{
                background: linear-gradient(135deg, #1565C0 0%, #0D47A1 100%);
            }}
            .replicas-container {{
                background: #252525;
            }}
            .replica-row {{
                background: #1e1e1e;
                border-color: #444;
            }}
            .replica-id {{
                color: #aaa;
            }}
            .no-replicas {{
                color: #777;
            }}
            .down-section {{
                background: #2d1a1a;
                border-color: #5c2828;
            }}
            .unknown-section {{
                background: #252525;
                border-color: #444;
            }}
            .down-node, .unknown-node {{
                background: #1e1e1e;
            }}
            .summary-bar {{
                background: #1a3a5c;
            }}
            .summary-label {{
                color: #aaa;
            }}
        }}
    </style>
    <html>
    <title>Node List</title>
    <body>
        <h2>Cluster Node Status</h2>
        
        <div class="summary-bar">
            <div class="summary-item">
                <span class="summary-count" style="color: #2196F3;">{len(masters)}</span>
                <span class="summary-label">Masters</span>
            </div>
            <div class="summary-item">
                <span class="summary-count" style="color: #4CAF50;">{sum(len(m['replicas']) for m in masters.values())}</span>
                <span class="summary-label">Replicas</span>
            </div>
            <div class="summary-item">
                <span class="summary-count" style="color: #f44336;">{len(down_nodes)}</span>
                <span class="summary-label">Down</span>
            </div>
        </div>
    """

    # Generate cards for each master with its replicas
    for master_id, master in masters.items():
        replicas_html = ""
        if master['replicas']:
            for replica in master['replicas']:
                replicas_html += f"""
                <div class="replica-row">
                    <span class="replica-icon">↳</span>
                    <span class="replica-address">{replica['address']}</span>
                    <span class="replica-id">{replica['node_id']}</span>
                </div>
                """
        else:
            replicas_html = '<div class="no-replicas">No replicas</div>'

        html += f"""
        <div class="node-card">
            <div class="master-header">
                <div>
                    <div class="master-address">🔷 {master['address']}</div>
                    <div class="master-id">{master['node_id']}</div>
                </div>
                <div class="slot-info">{master['slots'] if master['slots'] else 'No slots'}</div>
            </div>
            <div class="replicas-container">
                {replicas_html}
            </div>
        </div>
        """

    # Add down nodes section if any
    if down_nodes:
        html += """
        <div class="down-section">
            <div class="section-title">❌ Down Nodes</div>
        """
        for node in down_nodes:
            role_info = ""
            if node['role'] == 'slave' and node['master_id']:
                role_info = f" (Was replica of {node['master_id']})"
            elif node['role'] == 'master':
                role_info = " (Was master)"
            html += f"""
            <div class="down-node">
                {node['address']} <span style="color: #999;">({node['node_id']}){role_info}</span>
            </div>
            """
        html += "</div>"

    # Add unknown nodes section if any
    if unknown_nodes:
        html += """
        <div class="unknown-section">
            <div class="section-title">❓ Unknown Status</div>
        """
        for node in unknown_nodes:
            html += f"""
            <div class="unknown-node">
                {node['address']} <span style="color: #999;">({node['node_id']})</span>
            </div>
            """
        html += "</div>"

    html += """
    </body>
    </html>
    """

    return Response(content=html, media_type="text/html")


# Define the node-info endpoint
@app.get("/monitor/node-info/")
def get_node_info(redisNode, command):
    # Ensure we have the latest node list before processing the request
    try:
        import importlib
        importlib.reload(sys.modules['pareNodeList'])
        from pareNodeList import pareNodes as fresh_pareNodes
        global pareNodes
        pareNodes = fresh_pareNodes

        # Also refresh the nodeList
        nodeList = getNodeList()

        # Provide a message if the requested node isn't in the list
        if redisNode not in nodeList:
            return Response(
                content=f"{css_style}<html><body><h2>Node Not Found</h2>" +
                f"<p style='color: red;'>The node {redisNode} was not found in the current node list.</p>" +
                f"<p>This could happen if you're trying to access a newly added node. Please try refreshing the page or use the Refresh Configuration button.</p>" +
                "</body></html>",
                media_type="text/html"
            )
    except Exception as e:
        print(f"Error refreshing node list in node-info endpoint: {str(e)}")

    # Call the nodeInfo function to retrieve information about the node
    node_info_val = nodeInfo_wv(redisNode, command)

    # Construct the response message in HTML format
    response_message = f"{css_style}<html><body><h2>Node Info</h2><p>RedisNode: {redisNode}<br>Command: {command}<br>{node_info_val}</p></body></html>"

    return Response(content=response_message, media_type="text/html")



@app.get("/monitor/server-info/")
async def get_server_info(server_ip: str):
        # Call the serverInfo function to retrieve server information
        server_info = serverInfo_wv(server_ip)

        # Construct the HTML response
        html_content = f"""
        {css_style}
        <!DOCTYPE html>
        <html>
        <title>Server Info</title>
        <head>
        </head>
        <body>
            <p>{server_info}</p>
        </body>
        </html>
        """
        return Response(content=html_content, media_type="text/html")


# Modify the monitor_slot_info endpoint to return HTML-formatted cluster information
@app.get("/monitor/slot-info/", response_class=Response)
async def monitor_slot_info():
    html_content = f"{css_style}<html><title>Cluster Slot Info</title><body>"
    for pareNode in pareNodes:
        nodeIP = pareNode[0][0]
        portNumber = pareNode[1][0]
        if pareNode[4] and validIP(nodeIP):
            isPing = pingredisNode(nodeIP, portNumber)
            if isPing:
                try:
                    # Use the full detailed version for the monitor page
                    cluster_info = slotInfo_wv(nodeIP, portNumber)
                    if cluster_info:
                        # Format the cluster information in HTML
                        html_content += f"<pre>{cluster_info}</pre>"
                        break  # Stop processing after getting information from one node
                except Exception as e:
                    print(f"Error retrieving cluster information for Node IP: {nodeIP}, Port: {portNumber}")
                    print(f"Error message: {str(e)}")
                    continue  # Continue to the next node

    html_content += "</body></html>"
    return Response(content=html_content, media_type="text/html")


# Define the endpoint to retrieve cluster state information
@app.get("/monitor/cluster-state-info", response_class=HTMLResponse)
async def monitor_cluster_state_info():
    all_cluster_state_info = ""  # Initialize variable to hold information for all nodes
    for pareNode in pareNodes:
        nodeIP = pareNode[0][0]
        portNumber = pareNode[1][0]
        if pareNode[4]:
          isPing = pingredisNode(nodeIP, portNumber)
          try:
            if isPing:
                # Retrieve cluster state information for the node
                cluster_state_info = clusterStateInfo_wv(nodeIP, portNumber)
                # Determine the color based on the cluster state
                color = "green" if "ok" in cluster_state_info.lower() else "red"
                # Append the cluster state information to the overall information
                all_cluster_state_info += f"{css_style}<p style='color: {color};'>RedisNode: {nodeIP}:{portNumber} :: <b>{cluster_state_info}</b> </p>"
            else:
                # Node is unreachable, add it to the response with a label
                all_cluster_state_info += f"{css_style}<p style='color: gray;'>RedisNode: {nodeIP}:{portNumber} :: Unreachable</p>"
          except Exception as e:
            print(f"Error retrieving cluster information for RedisNode: {nodeIP}:{portNumber}")
            print(f"Error message: {str(e)}")
            continue  # Continue to the next node

    return all_cluster_state_info


@app.get("/monitor/memory-usage", response_class=HTMLResponse)
async def show_memory_usage():
    memory_usage_html = f"""
    {css_style}
    <html>
    <head>
        <title>Memory Usage</title>
        <style>
            .memory-table {{
                width: 100%;
                border-collapse: collapse;
                margin: 20px 0;
                font-family: Arial, sans-serif;
                box-shadow: 0 0 20px rgba(0, 0, 0, 0.15);
            }}
            .memory-table th {{
                padding: 12px 15px;
                text-align: left;
            }}
            .memory-table td {{
                padding: 10px 15px;
                border-bottom: 1px solid #ddd;
            }}
            .memory-table tr:hover {{
                background-color: rgba(200, 200, 200, 0.1);
            }}
            /* Different background colors for master and slave nodes */
            .master-node {{
                background-color: rgba(33, 150, 243, 0.1);
                border-left: 4px solid #2196F3;
            }}
            .slave-node {{
                background-color: rgba(76, 175, 80, 0.1);
                border-left: 4px solid #4CAF50;
            }}
            /* Memory usage indicators */
            .memory-usage-low {{ color: #4CAF50; }}
            .memory-usage-medium {{ color: #FFC107; }}
            .memory-usage-high {{ color: #F44336; }}
            .node-down {{ 
                color: #999; 
                background-color: rgba(150, 150, 150, 0.1);
                border-left: 4px solid #9E9E9E;
            }}
            .summary-box {{
                margin-top: 20px;
                padding: 15px;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.1);
                background-color: rgba(33, 150, 243, 0.05);
                border: 1px solid rgba(33, 150, 243, 0.2);
            }}
            .meter {{
                height: 10px;
                width: 100%;
                background: rgba(200, 200, 200, 0.2);
                border-radius: 5px;
                margin-top: 5px;
            }}
            .meter-fill {{
                height: 100%;
                border-radius: 5px;
                background-color: var(--meter-color, #4CAF50);
                transition: width 0.3s ease, background-color 0.3s ease;
            }}
            .section-header {{
                padding: 10px 15px;
                margin-top: 15px;
                border-radius: 3px;
                font-weight: bold;
            }}
            .master-header {{
                color: #2196F3;
            }}
            .slave-header {{
                color: #4CAF50;
            }}
            .down-header {{
                color: #9E9E9E;
            }}
        </style>
    </head>
    <body>
        <h2>Redis Cluster Memory Usage</h2>
        
        <div class="section-header master-header">Master Nodes</div>
        <table class="memory-table">
            <tr>
                <th>Node Address</th>
                <th>Used Memory</th>
                <th>Max Memory</th>
                <th>Usage</th>
            </tr>
    """

    total_used_mem_byte = 0
    total_max_mem_byte = 0
    master_nodes_info = ""
    slave_nodes_info = ""
    down_nodes_info = ""

    for pare_node in pareNodes:
        if pare_node[4]:  # Check if the node is marked as active
            node_ip = pare_node[0][0]
            port_number = pare_node[1][0]
            node_address = f"{node_ip}:{port_number}"

            # Check SSH availability first
            if is_ssh_available(node_ip):
                isPing = pingredisNode(node_ip, port_number)
                if isPing:
                    mem_status, mem_response = subprocess.getstatusoutput(
                        redisConnectCmd(node_ip, port_number, 'info memory | grep -e "used_memory:" -e "maxmemory:"')
                    )
                    if mem_status == 0:
                        used_mem_byte = float(mem_response[12:mem_response.find('maxmemory:') - 1])
                        max_mem_byte = float(mem_response[mem_response.find('maxmemory:') + 10:])
                        used_mem_gb = round(used_mem_byte / (1024 * 1024 * 1024), 3)
                        max_mem_gb = round(max_mem_byte / (1024 * 1024 * 1024), 3)
                        usage_per_mem = round((used_mem_gb / max_mem_gb) * 100, 2)

                        is_master = isNodeMaster(node_ip, None, port_number)
                        node_class = "master-node" if is_master else "slave-node"

                        # Determine usage level
                        usage_class = "memory-usage-low" if usage_per_mem < 70 else \
                                      "memory-usage-medium" if 70 <= usage_per_mem < 85 else \
                                      "memory-usage-high"

                        # Create a visual meter for memory usage
                        usage_meter = f"""
                        <div class="meter">
                            <div class="meter-fill" style="width: {usage_per_mem}%;"></div>
                        </div>
                        """

                        node_info = f"""
                        <tr class="{node_class}">
                            <td>{node_address}</td>
                            <td>{used_mem_gb} GB</td>
                            <td>{max_mem_gb} GB</td>
                            <td class="{usage_class}">{usage_per_mem}% {usage_meter}</td>
                        </tr>
                        """

                        if is_master:
                            master_nodes_info += node_info
                            total_used_mem_byte += used_mem_byte
                            total_max_mem_byte += max_mem_byte
                        else:
                            slave_nodes_info += node_info
                    else:
                        print(f"Error retrieving memory information for Node IP: {node_ip}, Port: {port_number}")
                else:
                    down_nodes_info += f"""
                    <tr class="node-down">
                        <td>{node_address}</td>
                        <td colspan="3">Node not responding</td>
                    </tr>
                    """
            else:
                down_nodes_info += f"""
                <tr class="node-down">
                    <td>{node_address}</td>
                    <td colspan="3">SSH unavailable</td>
                </tr>
                """

    memory_usage_html += master_nodes_info
    memory_usage_html += """</table>"""

    memory_usage_html += """
        <div class="section-header slave-header">Slave Nodes</div>
        <table class="memory-table">
            <tr>
                <th>Node Address</th>
                <th>Used Memory</th>
                <th>Max Memory</th>
                <th>Usage</th>
            </tr>
    """

    memory_usage_html += slave_nodes_info
    memory_usage_html += """</table>"""

    if down_nodes_info:
        memory_usage_html += """
            <div class="section-header down-header">Down Nodes</div>
            <table class="memory-table">
                <tr>
                    <th>Node Address</th>
                    <th colspan="3">Status</th>
                </tr>
        """
        memory_usage_html += down_nodes_info
        memory_usage_html += """</table>"""

    # Calculate summary information
    total_used_mem = round((total_used_mem_byte / (1024 * 1024 * 1024)), 3)
    total_max_mem = round((total_max_mem_byte / (1024 * 1024 * 1024)), 3)
    total_mem_per = round(((total_used_mem / total_max_mem) * 100), 2) if total_max_mem > 0 else 0

    # Create a visual meter for total memory usage
    total_meter = f"""
    <div class="meter">
        <div class="meter-fill" style="width: {total_mem_per}%;"></div>
    </div>
    """

    # Add summary box
    memory_usage_html += f"""
    <div class="summary-box">
        <h3>Cluster Summary (Master Nodes)</h3>
        <p><b>Total Memory Usage:</b> {total_used_mem} GB / {total_max_mem} GB ({total_mem_per}%)</p>
        {total_meter}
    </div>
    </body>
    </html>
    """

    return HTMLResponse(content=memory_usage_html)

# Define the CSS styles for different button types
css_style = """
    <style>
        /* Light mode styles (default) */
        body {
            font-family: Arial, sans-serif;
            background-color: #f0f0f0;
            color: #333333; /* Default text color */
            margin: 20px auto; /* Center horizontally with auto */
            max-width: 800px; /* Set maximum width */
            padding: 0 20px; /* Add some padding on the sides */
        }
        h1 {
            color: #ffffff;
            padding: 10px;
            border-radius: 5px;
            text-align: center;
        }
        .monitor-title {
            background-color: #4f4f4f; /* Dark gray */
        }
        .manager-title {
            background-color: #001f3f; /* Navy blue */
        }
        .maintenance-title {
            background-color: #800000; /* Claret */
        }
        th {
            text-align: left;
            padding: 8px;
            border-bottom: 1px solid #ddd;
        }
        td {
            padding: 8px;
            border-bottom: 1px solid #eee;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            margin-top: 10px;
        }
        ul {
            list-style-type: none;
            padding: 0;
        }
        li {
            margin-bottom: 10px;
        }
        label {
            display: inline-block;
            width: 150px;
            margin-right: 10px;
        }
        input[type="text"], input[type="number"], select {
            width: 200px;
            padding: 8px; /* Increased padding */
            border: 1px solid #cccccc;
            border-radius: 5px;
            box-sizing: border-box; /* Include padding in width */
            background-color: #ffffff; /* Explicit white background */
            color: #333333; /* Default text color */
        }
        input[type="checkbox"] {
            margin-left: 5px;
        }
        /* Common button styles */
        .monitor-button, .manager-button, .maintenance-button,
        .monitor-nav, .manager-nav, .maintenance-nav,
        .card-button, .confirm-btn, .cancel-btn, .btn-disabled {
            padding: 10px 15px;
            color: #ffffff;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            text-align: center;
            display: inline-block;
            vertical-align: middle;
            text-decoration: none;
            font-size: 14px; /* Consistent font size */
            margin: 5px 0; /* Add some margin */
        }
        /* Monitor specific colors */
        .monitor-button, .monitor-nav { background-color: #4f4f4f; }
        .monitor-button:hover, .monitor-nav:hover { background-color: #3f3f3f; }
        /* Manager specific colors */
        .manager-button, .manager-nav { background-color: #001f3f; }
        .manager-button:hover, .manager-nav:hover { background-color: #001a35; }
        /* Maintenance specific colors */
        .maintenance-button, .maintenance-nav { background-color: #800000; }
        .maintenance-button:hover, .maintenance-nav:hover { background-color: #660000; }
        /* Welcome page card button */
        .card-button { background-color: #555; }
        .card-button:hover { background-color: #444; }
        /* Confirmation/Deletion buttons */
        .confirm-btn { background-color: #d9534f; } /* Red for delete */
        .confirm-btn:hover { background-color: #c9302c; }
        .cancel-btn { background-color: #5bc0de; } /* Info blue */
        .cancel-btn:hover { background-color: #31b0d5; }
        /* Disabled button style */
        .btn-disabled { background-color: #aaa; cursor: not-allowed; }

        .collapsible {
            background-color: #e7e7e7; /* Lighter gray */
            color: #444;
            cursor: pointer;
            padding: 12px; /* Slightly more padding */
            width: 100%;
            border: none;
            text-align: left;
            outline: none;
            font-size: 16px;
            margin-bottom: 5px;
            border-radius: 3px; /* Subtle rounding */
        }
        .active, .collapsible:hover {
            background-color: #ddd;
        }
        .content {
            padding: 15px;
            display: none;
            overflow: hidden;
            background-color: #f9f9f9;
            border: 1px solid #ddd;
            margin-bottom: 10px;
            border-radius: 3px; /* Subtle rounding */
        }
        .content > * {
            margin-bottom: 10px;
        }
        .form-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 10px;
        }
        .form-group {
            display: flex;
            flex-direction: column;
        }
        .form-group.full-width {
            grid-column: span 2;
        }
        .button-container {
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap; /* Allow wrapping on smaller screens */
        }
        .button-container > * {
            margin: 0;
        }
        .nav-buttons {
            margin-bottom: 15px;
            display: flex;
            gap: 10px;
        }
        hr {
            border: 0;
            height: 1px;
            background: #ccc;
            margin: 20px 0;
        }
        pre {
            background-color: #eee;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
            white-space: pre-wrap; /* Allow wrapping */
            word-wrap: break-word; /* Break long words */
            color: #333; /* Text color for pre */
        }
        /* Welcome Page Specific Styles */
        .welcome-container { max-width: 1000px; margin: auto; padding: 20px; }
        .welcome-header { text-align: center; margin-bottom: 40px; }
        .welcome-header h1 { background: none; color: #333; font-size: 36px; margin-bottom: 10px; }
        .welcome-description { font-size: 18px; color: #666; }
        .section-cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; }
        .section-card { border: 1px solid #ddd; border-radius: 8px; overflow: hidden; background-color: #fff; display: flex; flex-direction: column; }
        .card-header { padding: 15px; font-size: 20px; text-align: center; color: #fff; }
        .monitor-card .card-header { background-color: #4f4f4f; }
        .manager-card .card-header { background-color: #001f3f; }
        .maintain-card .card-header { background-color: #800000; }
        .maker-card .card-header { background-color: #4f4f4f; }
        .card-content { padding: 15px; flex-grow: 1; color: #555; font-size: 14px; }
        .card-footer { padding: 15px; text-align: center; border-top: 1px solid #eee; }
        .card-button { display: inline-block; width: auto; } /* Adjust width */
        /* Maintenance Confirmation/Error Styles */
        .confirmation-needed, .delete-result, .error-message {
            padding: 15px;
            margin-top: 10px;
            border-radius: 5px;
            border: 1px solid transparent;
        }
        .confirmation-needed { border-color: #f0ad4e; background-color: #fcf8e3; color: #8a6d3b; }
        .delete-result { border-color: #5cb85c; background-color: #dff0d8; color: #3c763d; }
        .error-message { border-color: #d9534f; background-color: #f2dede; color: #a94442; }
        .error-message pre { background-color: #f8f8f8; color: #333; } /* Ensure pre inside error is styled */
        .response-container {
            margin-top: 10px;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
            background-color: #f9f9f9;
            color: #333333; /* Default text color for the container */
        }
        .response-container h3 { /* Style for potential headings in responses */
             margin-top: 0;
             font-size: 16px;
             color: #333;
        }
        .response-container p,
        .response-container div, /* Apply to divs inside */
        .response-container span, /* Apply to spans inside */
        .response-container b,   /* Apply to bold tags inside */
        .response-container i    /* Apply to italic tags inside */
        {
            color: inherit; /* Explicitly inherit color from parent */
            margin-bottom: 5px;
        }
        .response-container pre { /* Ensure preformatted text is styled */
            background-color: #eee;
            padding: 10px;
            border-radius: 5px;
            overflow-x: auto;
            white-space: pre-wrap;
            word-wrap: break-word;
            color: #333;
        }
        .response-container code { /* Style for inline code */
             background-color: #eee;
             padding: 2px 4px;
             border-radius: 3px;
             color: #c7254e; /* Example color for code */
        }
        
        /* Info box styles */
        .info-box {
            margin-top: 15px;
            padding: 10px;
            background-color: #e7f3ff;
            border-left: 4px solid #2196F3;
            font-size: 0.9em;
        }
        .info-box ul {
            margin: 5px 0 0 0;
            padding-left: 20px;
        }
        .info-box .note {
            margin: 10px 0 0 0;
            color: #666;
        }
        
        /* Error box styles */
        .error-box {
            margin-top: 10px;
            padding: 10px;
            background-color: #f8d7da;
            border-left: 4px solid red;
        }
        
        /* Warning box styles */
        .warning-box {
            margin-top: 10px;
            padding: 10px;
            background-color: #fff3cd;
            border-left: 4px solid orange;
        }
        
        /* Note box styles (amber/warning color for notes) */
        .note-box {
            margin-top: 15px;
            padding: 10px;
            background-color: #fff3cd;
            border-left: 4px solid #ffc107;
        }
        
        /* Table header row */
        .table-header {
            background-color: #f5f5f5;
        }
        .table-header th {
            padding: 8px;
            border: 1px solid #ddd;
            text-align: left;
        }
        
        /* Success box styles */
        .success-box {
            margin-top: 15px;
            padding: 15px;
            background-color: #d4edda;
            border-left: 4px solid #28a745;
        }
        
        /* Log messages pre block */
        .log-pre {
            max-height: 300px;
            overflow-y: auto;
            padding: 10px;
            background-color: #f8f9fa;
        }

        /* Dark mode styles */
        @media (prefers-color-scheme: dark) {
            body {
                background-color: #121212;
                color: #e0e0e0; /* Lighter text for dark background */
                margin: 20px auto; /* Center horizontally with auto */
                max-width: 800px; /* Set maximum width */
                padding: 0 20px; /* Add some padding on the sides */
            }
            h1 {
                color: #bce1f2; /* White text for better visibility on colored backgrounds */
            }
            /* Keep title backgrounds, they provide context */
            .monitor-title { background-color: #5a5a5a; } /* Slightly lighter dark gray */
            .manager-title { background-color: #002b55; } /* Slightly lighter navy */
            .maintenance-title { background-color: #990000; } /* Slightly lighter claret */

            table {
                border-collapse: collapse; /* Ensure borders collapse */
            }
            th {
                border-bottom: 1px solid #444; /* Darker border */
                color: #f1f1f1; /* Lighter header text */
            }
            td {
                border-bottom: 1px solid #333; /* Darker border */
            }
            /* Adjust memory usage table row colors */
            tr[style*="background-color:#d3ffce"] { background-color: #2a4d2a !important; } /* Dark green */
            tr[style*="background-color:yellow"] { background-color: #666600 !important; } /* Dark yellow */
            tr[style*="background-color:red"] { background-color: #660000 !important; } /* Dark red */

            input[type="text"], input[type="number"], select {
                background-color: #333333;
                color: #e0e0e0;
                border: 1px solid #555555;
            }
            /* Button adjustments for dark mode */
            .monitor-button, .monitor-nav { background-color: #5a5a5a; }
            .monitor-button:hover, .monitor-nav:hover { background-color: #6a6a6a; }
            .manager-button, .manager-nav { background-color: #002b55; }
            .manager-button:hover, .manager-nav:hover { background-color: #003f7c; }
            .maintenance-button, .maintenance-nav { background-color: #990000; }
            .maintenance-button:hover, .maintenance-nav:hover { background-color: #b30000; }
            .card-button { background-color: #666; }
            .card-button:hover { background-color: #777; }
            .confirm-btn { background-color: #b33c38; } /* Darker red */
            .confirm-btn:hover { background-color: #c7433e; }
            .cancel-btn { background-color: #4694b0; } /* Darker blue */
            .cancel-btn:hover { background-color: #5aa6c2; }
            .btn-disabled { background-color: #555; }

            .collapsible {
                background-color: #2a2a2a;
                color: #ccc;
            }
            .active, .collapsible:hover {
                background-color: #383838;
            }
            .content {
                background-color: #1e1e1e;
                border: 1px solid #444;
            }
            hr {
                background: #444;
            }
            pre {
                background-color: #2a2a2a;
                color: #ccc;
                border: 1px solid #444;
            }
            /* Welcome Page Dark Mode */
            .welcome-header h1 { color: #e0e0e0; }
            .welcome-description { color: #aaa; }
            .section-card { background-color: #1e1e1e; border-color: #444; }
            .card-header { /* Keep background colors, adjust text if needed */ }
            .card-content { color: #bbb; }
            .card-footer { border-top-color: #444; }
            .welcome-footer { color: #888; }
            /* Maintenance Confirmation/Error Dark Mode */
            .confirmation-needed { border-color: #b38600; background-color: #332a1a; color: #ffdead; }
            .delete-result { border-color: #3c763d; background-color: #1e351e; color: #90ee90; }
            .error-message { border-color: #d9534f; background-color: #351e1e; color: #f08080; }
            .error-message pre { background-color: #2a2a2a; color: #ccc; } /* Ensure pre inside error is styled */
            .response-container {
                background-color: #1e1e1e;
                border-color: #444;
                color: #e0e0e0; /* Ensure text color is inherited */
            }
            .response-container h3 {
                color: #f1f1f1; /* Lighter heading color */
            }
            .response-container p,
            .response-container div,
            .response-container span,
            .response-container b,
            .response-container i
            {
                 color: inherit; /* Explicitly inherit from .response-container */
            }
            .response-container pre { /* Style preformatted text in dark mode */
                background-color: #2a2a2a;
                color: #ccc;
                border: 1px solid #444;
            }
            .response-container code { /* Style for inline code in dark mode */
                 background-color: #333;
                 color: #ff8080; /* Example light red for code */
            }
            
            /* Make slave nodes more readable in dark mode */
            [style*="color: #001f3f"] {
                color: #4a9cf7 !important; /* Lighter blue color for better contrast in dark mode */
            }
            
            /* Info box dark mode */
            .info-box {
                background-color: #1a3a5c;
                border-left-color: #4dabf7;
                color: #e0e0e0;
            }
            .info-box .note {
                color: #aaa;
            }
            
            /* Error box dark mode */
            .error-box {
                background-color: #4a1a1a;
                border-left-color: #ff6b6b;
                color: #f0a0a0;
            }
            
            /* Warning box dark mode */
            .warning-box {
                background-color: #4a3a1a;
                border-left-color: #ffa500;
                color: #ffe0a0;
            }
            
            /* Note box dark mode */
            .note-box {
                background-color: #4a3a1a;
                border-left-color: #ffc107;
                color: #ffe0a0;
            }
            
            /* Table header dark mode */
            .table-header {
                background-color: #2a2a2a;
            }
            .table-header th {
                border-color: #444;
                color: #e0e0e0;
            }
            
            /* Success box dark mode */
            .success-box {
                background-color: #1a4a2a;
                border-left-color: #28a745;
                color: #a0f0a0;
            }
            
            /* Log messages pre block dark mode */
            .log-pre {
                background-color: #2a2a2a;
                color: #ccc;
            }
        }
        
        /* Added styles for slot information display */
        .cluster-info-table {
            width: auto;
            max-width: 100%;
            border-collapse: collapse;
            margin-bottom: 8px;
            font-size: 14px;
        }
        .cluster-info-table th, .cluster-info-table td {
            padding: 5px 8px;
            text-align: left;
            border: 1px solid #ddd;
            white-space: nowrap;
        }
        .cluster-info-table th {
            background-color: #f2f2f2;
            font-weight: bold;
        }
        .node-id {
            font-family: monospace;
            background-color: #f8f8f8;
            padding: 2px 4px;
            border-radius: 3px;
            font-size: 0.9em;
        }
        .master-node {
            color: #2c7be5;
            font-weight: bold;
        }
        .slave-node {
            color: #95aac9;
        }
        .cluster-check {
            background-color: #f9f9f9;
            padding: 8px;
            border: 1px solid #e9ecef;
            border-radius: 4px;
            margin: 5px 0;
            font-family: monospace;
            white-space: pre-wrap;
        }
        .status-ok {
            color: #2dce89;
            font-weight: bold;
        }
        .section-title {
            margin-top: 15px;
            margin-bottom: 5px;
            border-bottom: 1px solid #e9ecef;
            padding-bottom: 3px;
        }
        .log-section {
            margin-top: 15px;
            margin-bottom: 15px;
        }
        .help-info {
            margin-top: 20px;
            padding: 10px;
            background-color: #f8f9fa;
            border-left: 4px solid #6c757d;
        }
        
        /* Dark mode for slot information display */
        @media (prefers-color-scheme: dark) {
            .cluster-info-table th {
                background-color: #333;
            }
            .cluster-info-table tr:nth-child(even) {
                background-color: #222;
            }
            .cluster-info-table tr:hover {
                background-color: #444;
            }
            .cluster-info-table th, .cluster-info-table td {
                border: 1px solid #444;
            }
            .node-id {
                background-color: #333;
                border: 1px solid #555;
            }
            .master-node {
                color: #4a9cf7;
            }
            .slave-node {
                color: #b3c9e6;
            }
            .cluster-check {
                background-color: #222;
                border: 1px solid #444;
            }
            .help-info {
                background-color: #222;
                border-left: 4px solid #555;
            }
            .section-title {
                border-bottom: 1px solid #444;
            }
        }

        /* Progress bar styles */
        .progress-bar-container {
            width: 100%;
            background-color: #e0e0e0;
            height: 20px;
            border-radius: 10px;
            overflow: hidden;
        }
        .progress-bar {
            height: 100%;
            width: 0;
            background-color: #800000;
            transition: width 0.5s;
            border-radius: 10px;
        }
        
        /* Dark mode adjustments for progress bar */
        @media (prefers-color-scheme: dark) {
            .progress-bar-container {
                background-color: #444;
            }
            .progress-bar {
                background-color: #990000;
            }
        }
        
        /* Version control table row styles for master/replica */
        .version-master-row {
            background-color: rgba(33, 150, 243, 0.15);
            font-weight: 500;
        }
        .version-master-row td {
            color: #1565c0;
        }
        .version-replica-row {
            background-color: rgba(76, 175, 80, 0.1);
        }
        .version-replica-row td {
            color: #2e7d32;
        }
        
        /* Dark mode for version control rows */
        @media (prefers-color-scheme: dark) {
            .version-master-row {
                background-color: rgba(33, 150, 243, 0.25);
            }
            .version-master-row td {
                color: #64b5f6;
            }
            .version-replica-row {
                background-color: rgba(76, 175, 80, 0.15);
            }
            .version-replica-row td {
                color: #81c784;
            }
        }
        
        /* Version control warning icon with hover tooltip */
        .warning-icon-container {
            position: relative;
            display: inline-block;
            cursor: pointer;
        }
        .warning-icon {
            font-size: 1.2em;
        }
        .restart-tooltip {
            visibility: hidden;
            opacity: 0;
            position: absolute;
            bottom: 125%;
            left: 50%;
            transform: translateX(-50%);
            background-color: #333;
            color: #fff;
            text-align: center;
            padding: 10px 15px;
            border-radius: 6px;
            z-index: 1000;
            min-width: 200px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
            transition: opacity 0.3s, visibility 0.3s;
        }
        .restart-tooltip::after {
            content: "";
            position: absolute;
            top: 100%;
            left: 50%;
            margin-left: -5px;
            border-width: 5px;
            border-style: solid;
            border-color: #333 transparent transparent transparent;
        }
        .restart-tooltip p {
            margin: 0 0 10px 0;
            font-size: 0.9em;
        }
        .restart-btn {
            background-color: #800000;
            color: white;
            border: none;
            padding: 8px 15px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.9em;
            transition: background-color 0.2s;
        }
        .restart-btn:hover {
            background-color: #a00000;
        }
        .warning-icon-container:hover .restart-tooltip {
            visibility: visible;
            opacity: 1;
        }
        
        /* Dark mode for warning icon tooltip */
        @media (prefers-color-scheme: dark) {
            .restart-tooltip {
                background-color: #1e1e1e;
                border: 1px solid #444;
            }
            .restart-tooltip::after {
                border-color: #1e1e1e transparent transparent transparent;
            }
            .restart-btn {
                background-color: #990000;
            }
            .restart-btn:hover {
                background-color: #b30000;
            }
        }
        
        /* Custom Modal Dialog Styles */
        .modal-overlay {
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0, 0, 0, 0.5);
            display: flex;
            justify-content: center;
            align-items: center;
            z-index: 10000;
            opacity: 0;
            visibility: hidden;
            transition: opacity 0.3s, visibility 0.3s;
        }
        .modal-overlay.active {
            opacity: 1;
            visibility: visible;
        }
        .modal-dialog {
            background-color: #fff;
            border-radius: 10px;
            box-shadow: 0 10px 40px rgba(0, 0, 0, 0.3);
            max-width: 450px;
            width: 90%;
            transform: scale(0.9);
            transition: transform 0.3s;
            overflow: hidden;
        }
        .modal-overlay.active .modal-dialog {
            transform: scale(1);
        }
        .modal-header {
            padding: 20px;
            border-bottom: 1px solid #eee;
            display: flex;
            align-items: center;
            gap: 12px;
        }
        .modal-header.warning {
            background-color: #fff3cd;
            border-bottom-color: #ffc107;
        }
        .modal-header.danger {
            background-color: #f8d7da;
            border-bottom-color: #dc3545;
        }
        .modal-header .modal-icon {
            font-size: 28px;
        }
        .modal-header h3 {
            margin: 0;
            font-size: 18px;
            color: #333;
        }
        .modal-header.warning h3 {
            color: #856404;
        }
        .modal-header.danger h3 {
            color: #721c24;
        }
        .modal-body {
            padding: 20px;
            color: #555;
            line-height: 1.6;
        }
        .modal-body p {
            margin: 0 0 12px 0;
        }
        .modal-body ul {
            margin: 10px 0;
            padding-left: 20px;
        }
        .modal-body li {
            margin-bottom: 6px;
        }
        .modal-body .node-address {
            font-family: monospace;
            background-color: #f5f5f5;
            padding: 2px 8px;
            border-radius: 4px;
            font-weight: bold;
        }
        .modal-footer {
            padding: 15px 20px;
            border-top: 1px solid #eee;
            display: flex;
            justify-content: flex-end;
            gap: 10px;
            background-color: #f9f9f9;
        }
        .modal-btn {
            padding: 10px 20px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 500;
            transition: all 0.2s;
        }
        .modal-btn-cancel {
            background-color: #e0e0e0;
            color: #333;
        }
        .modal-btn-cancel:hover {
            background-color: #d0d0d0;
        }
        .modal-btn-confirm {
            background-color: #800000;
            color: white;
        }
        .modal-btn-confirm:hover {
            background-color: #a00000;
        }
        .modal-btn-confirm.danger {
            background-color: #dc3545;
        }
        .modal-btn-confirm.danger:hover {
            background-color: #c82333;
        }
        
        /* Dark mode for modal */
        @media (prefers-color-scheme: dark) {
            .modal-dialog {
                background-color: #1e1e1e;
                box-shadow: 0 10px 40px rgba(0, 0, 0, 0.6);
            }
            .modal-header {
                border-bottom-color: #444;
            }
            .modal-header.warning {
                background-color: #332a1a;
                border-bottom-color: #b38600;
            }
            .modal-header.danger {
                background-color: #351e1e;
                border-bottom-color: #dc3545;
            }
            .modal-header h3 {
                color: #e0e0e0;
            }
            .modal-header.warning h3 {
                color: #ffd700;
            }
            .modal-header.danger h3 {
                color: #ff6b6b;
            }
            .modal-body {
                color: #bbb;
            }
            .modal-body .node-address {
                background-color: #333;
                color: #4fc3f7;
            }
            .modal-footer {
                background-color: #252525;
                border-top-color: #444;
            }
            .modal-btn-cancel {
                background-color: #444;
                color: #e0e0e0;
            }
            .modal-btn-cancel:hover {
                background-color: #555;
            }
        }
    </style>
"""

# Add a root route handler for the welcome page
@app.get("/", response_class=HTMLResponse)
async def welcome_page():
    """
    Welcome page that serves as a landing page with links to the three main sections:
    Monitor, Manager, and Maintenance.
    """
    html_content = f"""
    {css_style}
    <!DOCTYPE html>
    <html>
    <head>
        <title>Paredicma - {projectName} - Redis Cluster Management</title>
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body>
        <div class="welcome-container">
            <div class="welcome-header">
                <h1>Paredicma - {projectName}</h1>
                <div class="welcome-description">
                    Redis Cluster Management Tool
                </div>
            </div>
            
            <div class="section-cards">
                <div class="section-card monitor-card">
                    <h2 class="card-header">Monitor</h2>
                    <div class="card-content">
                        <p>View real-time status of your Redis cluster. Monitor node health, memory usage, and cluster state.</p>
                        <p>Key features include ping nodes, list nodes, check cluster slots, view memory usage and more.</p>
                    </div>
                    <div class="card-footer">
                        <a href="/monitor" class="card-button">Go to Monitor</a>
                    </div>
                </div>
                
                <div class="section-card manager-card">
                    <h2 class="card-header">Manager</h2>
                    <div class="card-content">
                        <p>Manage your Redis cluster operations such as start/stop/restart nodes, switch master/slave roles, and change configurations.</p>
                        <p>Execute commands across all nodes, perform rolling restarts, and view Redis logs.</p>
                    </div>
                    <div class="card-footer">
                        <a href="/manager" class="card-button">Go to Manager</a>
                    </div>
                </div>
                
                <div class="section-card maintain-card">
                    <h2 class="card-header">Maintenance</h2>
                    <div class="card-content">
                        <p>Perform maintenance tasks such as adding new nodes, deleting nodes, moving slots, and upgrading Redis versions.</p>
                        <p>Manage cluster topology, migrate data, and balance slot distribution.</p>
                    </div>
                    <div class="card-footer">
                        <a href="/maintain" class="card-button">Go to Maintenance</a>
                    </div>
                </div>
                
                <div class="section-card maker-card">
                    <h2 class="card-header">Maker</h2>
                    <div class="card-content">
                        <p>Create a new Redis cluster from scratch. Configure nodes, set replication, and initialize the cluster.</p>
                        <p>Validate nodes, preview configuration, and monitor cluster creation progress.</p>
                    </div>
                    <div class="card-footer">
                        <a href="/maker" class="card-button">Go to Maker</a>
                    </div>
                </div>
            
            </div>
            
            <div class="welcome-footer" style="margin-top: 40px; text-align: center; color: #777;">
                <p>Select a section above to start working with your Redis cluster</p>
                <p style="font-size: 12px;">Paredicma v3.0 - Redis Cluster Management Tool</p>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

# Define the endpoint for the monitoring page
@app.get("/monitor", response_class=HTMLResponse)
async def monitor():
    """
    Displays the Redis Cluster Monitoring UI with collapsible sections.
    """
    # Reload the pareNodes configuration to ensure the latest node list
    import importlib
    importlib.reload(sys.modules['pareNodeList'])
    from pareNodeList import pareNodes as fresh_pareNodes

    # Update the global pareNodes
    global pareNodes
    pareNodes = fresh_pareNodes

    uniqueservers = getuniqueServers(pareNodes)
    commandsAvailable = ['server', 'clients', 'memory', 'persistence', 'stats', 'replication', 'cpu', 'cluster']
    nodeList = getNodeList()

    # Generate the HTML content for the monitoring page
    html_content = f"""
    {css_style}
    <html>
    <head>
        <title>Redis Cluster Monitor - {projectName}</title>
    </head>
    <body>
    <h1 class="monitor-title">Redis Cluster Monitor - {projectName}</h1>
    <div class="nav-buttons">
        <a href="/manager" class="manager-nav">Go to Manager</a>
        <a href="/maintain" class="maintenance-nav">Go to Maintenance</a>
    </div>
    <hr>

    <button class="collapsible">1 - Ping Nodes</button>
    <div class="content">
        <div class="button-container">
            <button class="monitor-button" onclick="fetchPingNodes()">Ping Nodes</button>
        </div>
        <div id="ping-nodes-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">2 - List Nodes</button>
    <div class="content">
        <div class="button-container">
            <button class="monitor-button" onclick="fetchListNodes()">List Nodes</button>
        </div>
        <div id="list-nodes-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">3 - Node Info</button>
    <div class="content">
        <form id="node-info-form" onsubmit="fetchNodeInfo(event)">
            <div class="button-container">
                <label for="redisNode">Redis Node:</label>
                <select id="redisNode" name="redisNode" onchange="fetchNodeInfo(new Event('submit', {{cancelable: true}}))">
                    {''.join([f"<option value='{node}'>{node}</option>" for node in nodeList])}
                </select>
            </div>
            <div class="button-container" style="margin-top: 10px;">
                <label for="command">Command:</label>
                <select id="command" name="command" onchange="fetchNodeInfo(new Event('submit', {{cancelable: true}}))">
                    {''.join([f"<option value='{command}'>{command}</option>" for command in commandsAvailable])}
                </select>
            </div>
        </form>
        <div id="node-info-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">4 - Server Info</button>
    <div class="content">
        <form id="server-info-form" onsubmit="fetchServerInfo(event)">
            <div class="button-container">
                <label for="server_ip"><input class="monitor-button" type="submit" value="Get Server Info"></label>
                <select id="server_ip" name="server_ip">
                    {''.join([f"<option value='{server}'>{server}</option>" for server in uniqueservers])}
                </select>
            </div>
        </form>
        <div id="server-info-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">5 - Slot Info</button>
    <div class="content">
        <div class="button-container">
            <button class="monitor-button" onclick="fetchSlotInfo()">Get Slot Info</button>
        </div>
        <div id="slot-info-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">6 - Cluster State Info</button>
    <div class="content">
        <div class="button-container">
            <button class="monitor-button" onclick="fetchClusterStateInfo()">Get Cluster State Info</button>
        </div>
        <div id="cluster-state-info-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">7 - Memory Usage</button>
    <div class="content">
        <div class="button-container">
            <button class="monitor-button" onclick="fetchMemoryUsage()">Get Memory Usage</button>
        </div>
        <div id="memory-usage-result" style="margin-top: 10px;"></div>
    </div>

    <script>
        const collapsibles = document.querySelectorAll(".collapsible");
        collapsibles.forEach(button => {{
            button.addEventListener("click", function() {{
                this.classList.toggle("active");
                const content = this.nextElementSibling;
                if (content.style.display === "block") {{
                    content.style.display = "none";
                }} else {{
                    content.style.display = "block";
                }}
            }});
        }});

        function fetchPingNodes() {{
            fetch('/monitor/ping-nodes/')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('ping-nodes-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('ping-nodes-result').innerHTML = "<p style='color: red;'>Error fetching ping nodes: " + error + "</p>";
                }});
        }}

        function fetchListNodes() {{
            fetch('/monitor/list-nodes/')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('list-nodes-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('list-nodes-result').innerHTML = "<p style='color: red;'>Error fetching list nodes: " + error + "</p>";
                }});
        }}

        function fetchNodeInfo(event) {{
            event.preventDefault();
            const formData = new FormData(document.getElementById('node-info-form'));
            const params = new URLSearchParams(formData).toString();
            
            document.getElementById('node-info-result').innerHTML = "<p>Loading...</p>";
            
            fetch('/monitor/node-info/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('node-info-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('node-info-result').innerHTML = "<p style='color: red;'>Error fetching node info: " + error + "</p>";
                }});
        }}

        function fetchServerInfo(event) {{
            event.preventDefault();
            const formData = new FormData(document.getElementById('server-info-form'));
            const params = new URLSearchParams(formData).toString();
            fetch('/monitor/server-info/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('server-info-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('server-info-result').innerHTML = "<p style='color: red;'>Error fetching server info: " + error + "</p>";
                }});
        }}

        function fetchSlotInfo() {{
            fetch('/monitor/slot-info/')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('slot-info-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('slot-info-result').innerHTML = "<p style='color: red;'>Error fetching slot info: " + error + "</p>";
                }});
        }}

        function fetchClusterStateInfo() {{
            fetch('/monitor/cluster-state-info/')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('cluster-state-info-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('cluster-state-info-result').innerHTML = "<p style='color: red;'>Error fetching cluster state info: " + error + "</p>";
                }});
        }}

        function fetchMemoryUsage() {{
            fetch('/monitor/memory-usage/')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('memory-usage-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('memory-usage-result').innerHTML = "<p style='color: red;'>Error fetching memory usage: " + error + "</p>";
                }});
        }}
        
        function updateMeter(element, percentage) {{
            element.style.width = percentage + '%';
            
            // Set color based on percentage thresholds
            if (percentage < 40) {{
                element.style.backgroundColor = '#4CAF50'; // Green for low usage
            }} else if (percentage < 70) {{
                element.style.backgroundColor = '#FFC107'; // Yellow for medium usage
            }} else {{
                element.style.backgroundColor = '#F44336'; // Red for high usage
            }}
        }}
        
        function initializeMeters() {{
            const meters = document.querySelectorAll('.meter-fill');
            meters.forEach(meter => {{
                const width = meter.style.width;
                const percentage = parseFloat(width);
                updateMeter(meter, percentage);
            }});
        }}
        
        document.addEventListener('DOMContentLoaded', function() {{
            initializeMeters();
        }});
        
        function fetchMemoryUsage() {{
            fetch('/monitor/memory-usage/')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('memory-usage-result').innerHTML = data;
                    setTimeout(initializeMeters, 100);
                }})
                .catch(error => {{
                    document.getElementById('memory-usage-result').innerHTML =
                        "<p style='color: red;'>Error fetching memory usage: " + error + "</p>";
                }});
        }}
        
        
    </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


# #############################################
# Manager Section
# #############################################

@app.get("/manager", response_class=HTMLResponse)
async def manager():
    """
    Displays the Redis Cluster Manager UI with collapsible sections.
    """
    # Reload the pareNodes configuration to ensure the latest node list
    import importlib
    importlib.reload(sys.modules['pareNodeList'])
    from pareNodeList import pareNodes as fresh_pareNodes

    # Update the global pareNodes
    global pareNodes
    pareNodes = fresh_pareNodes

    nodeList = getNodeList()

    # Get only master nodes for the switch master/slave feature
    masterNodes = []
    for pareNode in pareNodes:
        nodeIP = pareNode[0][0]
        portNumber = pareNode[1][0]
        if pareNode[4]:  # If node is active
            if slaveORMasterNode(nodeIP, portNumber) == 'M':  # If node is a master
                masterNodes.append(f"{nodeIP}:{portNumber}")

    actionsAvailable = ['Start', 'Stop', 'Restart']

    # Common Redis configuration parameters for quick selection
    common_configs = [
        "maxmemory",
        "maxmemory-policy",
        "timeout",
        "maxclients",
        "requirepass",
        "appendonly",
        "appendfsync",
        "cluster-node-timeout",
        "slowlog-log-slower-than",
        "slowlog-max-len"
    ]

    # Generate the HTML content for the manager page
    html_content = f"""
    {css_style}
    <html>
    <head>
        <title>Redis Cluster Manager - {projectName}</title>
    </head>
    <body>
    <h1 class="manager-title">Redis Cluster Manager - {projectName}</h1>
    <div class="nav-buttons">
        <a href="/monitor" class="monitor-nav">Go to Monitor</a>
        <a href="/maintain" class="maintenance-nav">Go to Maintenance</a>
    </div>
    <hr>

    <button class="collapsible">1 - Start/Stop/Restart Redis Node</button>
    <div class="content">
        <form id="node-action-form" onsubmit="performNodeAction(event)">
            <label for="action">Select Action:</label>
            <select id="action" name="action" onchange="updateNodeListByAction()">
                {''.join([f"<option value='{action.lower()}'>{action}</option>" for action in actionsAvailable])}
            </select>
            <br><br>
            <label for="redisNodeAction">Select Node:</label>
            <select id="redisNodeAction" name="redisNode">
                <option value="">Loading nodes...</option>
            </select>
            <span id="nodeLoadingSpinner" style="display: none; margin-left: 10px;">⏳</span>
            <br><br>
            <input class="manager-button" type="submit" value="Perform Action">
        </form>
        <div id="node-action-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">2 - Switch Master/Slave Nodes</button>
    <div class="content">
        <form id="switch-master-slave-form" onsubmit="switchMasterSlave(event)">
            <label for="masterNode"><input class="manager-button" type="submit" value="Switch Master/Slave">
</label>
            <select id="masterNode" name="redisNode">
                {''.join([f"<option value='{node}'>{node}</option>" for node in masterNodes])}
            </select>
            <br><br>
        </form>
        <div id="switch-master-slave-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">3 - Change Redis Configuration Parameter</button>
    <div class="content">
        <form id="change-config-form" onsubmit="changeConfig(event)">
            <label for="configNode">Select Node:</label>
            <select id="configNode" name="redisNode">
                {''.join([f"<option value='{node}'>{node}</option>" for node in nodeList])}
            </select>
            <br><br>
            <label for="parameter">Parameter:</label>
            <select id="parameter" name="parameter">
                <option value="">--- Select below ---</option>
                {''.join([f"<option value='{param}'>{param}</option>" for param in common_configs])}
            </select>
            <br><br>
            <label for="value">New Value:</label>
            <input type="text" id="value" name="value" placeholder="e.g., 2gb">
            <br><br>
           <div><input class="manager-button" type="submit" value="Apply Change">
           <label for="persist" style="margin-left: 45px; width: auto">Persist to config:</label>
            <input type="checkbox" id="persist" name="persist" value="true">
            </div>
        </form>
        <div id="change-config-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">4 - Save Redis Configuration to redis.conf</button>
    <div class="content">
        <form id="save-config-form" onsubmit="saveConfig(event)">
            <label for="saveConfigNode">            <input class="manager-button" type="submit" value="Save Configuration">
</label>
            <select id="saveConfigNode" name="redisNode">
                <option value="all">All Nodes</option>
                {''.join([f"<option value='{node}'>{node}</option>" for node in nodeList])}
            </select>
            <br><br>
        </form>
        <div id="save-config-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">5 - Rolling Restart</button>
    <div class="content">
        <form id="rolling-restart-form" onsubmit="rollingRestart(event)">
            <label for="wait_minutes" style="width: auto;">Wait between restarts:</label>
            <input type="number" id="wait_minutes" name="wait_minutes" min="0" max="10" placeholder="minutes" required>
            <br><br>
            <label for="restart_masters">Include masters:</label>
            <input type="checkbox" id="restart_masters" name="restart_masters" value="true">
            <br><br>
            <input class="manager-button" type="submit" value="Start Rolling Restart">
        </form>
        <div id="rolling-restart-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">6 - Command for all nodes</button>
    <div class="content">
        <form id="execute-command-form" onsubmit="executeCommand(event)">
            <label for="command">Redis Command:</label>
            <input type="text" id="command" name="command" placeholder="e.g., INFO MEMORY" required style="width: 300px;">
            <br><br>
            <label for="only_masters">Execute only on master nodes:</label>
            <input type="checkbox" id="only_masters" name="only_masters" value="true">
            <br><br>
            <label for="wait_seconds">Wait time between nodes (seconds):</label>
            <input type="number" id="wait_seconds" name="wait_seconds" min="0" value="0">
            <br><br>
            <input class="manager-button" type="submit" value="Execute Command">
        </form>
        <div id="execute-command-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">7 - Show Redis Log File</button>
    <div class="content">
        <form id="show-log-form" onsubmit="showLog(event)">
            <label for="logNode">Select Node:</label>
            <select id="logNode" name="redisNode">
                {''.join([f"<option value='{node}'>{node}</option>" for node in nodeList])}
            </select>
            <br><br>
            <label for="line_count"> <input class="manager-button" type="submit" value="View Log File">
            </label>
            <input type="number" id="line_count" name="line_count" min="10" max="500" value="50">
            <br><br>
        </form>
        <div id="show-log-result" style="margin-top: 10px;"></div>
    </div>

    <script>
        const collapsibles = document.querySelectorAll(".collapsible");
        collapsibles.forEach(button => {{
            button.addEventListener("click", function() {{
                this.classList.toggle("active");
                const content = this.nextElementSibling;
                if (content.style.display === "block") {{
                    content.style.display = "none";
                }} else {{
                    content.style.display = "block";
                }}
            }});
        }});

        // Function to update node list based on selected action
        function updateNodeListByAction() {{
            const action = document.getElementById('action').value;
            const nodeSelect = document.getElementById('redisNodeAction');
            const spinner = document.getElementById('nodeLoadingSpinner');
            
            // Show loading state
            nodeSelect.innerHTML = '<option value="">Loading nodes...</option>';
            nodeSelect.disabled = true;
            spinner.style.display = 'inline';
            
            fetch('/manager/get-nodes-by-action/?action=' + encodeURIComponent(action))
                .then(response => response.json())
                .then(data => {{
                    nodeSelect.innerHTML = '';
                    if (data.nodes && data.nodes.length > 0) {{
                        data.nodes.forEach(node => {{
                            const option = document.createElement('option');
                            option.value = node.address;
                            option.textContent = node.address + (node.role ? ' (' + node.role + ')' : '');
                            nodeSelect.appendChild(option);
                        }});
                    }} else {{
                        const option = document.createElement('option');
                        option.value = '';
                        option.textContent = data.message || 'No nodes available for this action';
                        nodeSelect.appendChild(option);
                    }}
                    nodeSelect.disabled = false;
                    spinner.style.display = 'none';
                }})
                .catch(error => {{
                    nodeSelect.innerHTML = '<option value="">Error loading nodes</option>';
                    nodeSelect.disabled = false;
                    spinner.style.display = 'none';
                    console.error('Error fetching nodes:', error);
                }});
        }}
        
        // Initialize node list on page load
        document.addEventListener('DOMContentLoaded', function() {{
            updateNodeListByAction();
        }});

        // Add event delegation for confirmation buttons
        document.addEventListener('click', function(e) {{
            // Handle confirmation buttons
            if (e.target && e.target.classList.contains('confirm-btn')) {{
                const node = e.target.getAttribute('data-node');
                const action = e.target.getAttribute('data-action');
                if (node && action) {{
                    confirmNodeAction(node, action);
                }}
            }}
            
            // Handle cancel buttons
            if (e.target && e.target.classList.contains('cancel-btn')) {{
                cancelNodeAction();
            }}
        }});

        function confirmNodeAction(redisNode, action) {{
            const submitBtn = document.querySelector('#node-action-form input[type="submit"]');
            submitBtn.disabled = true;
            submitBtn.value = 'Processing...';
            submitBtn.classList.add('btn-disabled');
            document.getElementById('node-action-result').innerHTML = '';
            
            // Log the values to help debug
            console.log("Confirming action for node:", redisNode, "action:", action);
            
            fetch('/manager/node-action/?redisNode=' + encodeURIComponent(redisNode) + '&action=' + encodeURIComponent(action) + '&confirmed=true')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('node-action-result').innerHTML = data;
                    // Refresh the node list after action completes
                    setTimeout(updateNodeListByAction, 1000);
                }})
                .catch(error => {{
                    document.getElementById('node-action-result').innerHTML = "<p style='color: red;'>Error: " + error + "</p>";
                }})
                .finally(() => {{
                    submitBtn.disabled = false;
                    submitBtn.value = 'Perform Action';
                    submitBtn.classList.remove('btn-disabled');
                }});
        }}
        
        function cancelNodeAction() {{
            document.getElementById('node-action-result').innerHTML = "<p>Operation cancelled.</p>";
        }}

        function performNodeAction(event) {{
            event.preventDefault();
            const submitBtn = document.querySelector('#node-action-form input[type="submit"]');
            submitBtn.disabled = true;
            submitBtn.value = 'Processing...';
            submitBtn.classList.add('btn-disabled');
            document.getElementById('node-action-result').innerHTML = '';
            
            const formData = new FormData(document.getElementById('node-action-form'));
            const params = new URLSearchParams(formData).toString();
            
            fetch('/manager/node-action/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('node-action-result').innerHTML = data;
                    // Refresh the node list after action completes
                    setTimeout(updateNodeListByAction, 1000);
                }})
                .catch(error => {{
                    document.getElementById('node-action-result').innerHTML = "<p style='color: red;'>Error performing action: " + error + "</p>";
                }})
                .finally(() => {{
                    submitBtn.disabled = false;
                    submitBtn.value = 'Perform Action';
                    submitBtn.classList.remove('btn-disabled');
                }});
        }}

        function switchMasterSlave(event) {{
            event.preventDefault();
            const formData = new FormData(document.getElementById('switch-master-slave-form'));
            const params = new URLSearchParams(formData).toString();
            
            // Add processing message
            document.getElementById('switch-master-slave-result').innerHTML = "<p>Processing request...</p>";
            
            fetch('/manager/switch-master-slave/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('switch-master-slave-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('switch-master-slave-result').innerHTML = "<p style='color: red;'>Error switching master/slave: " + error + "</p>";
                }});
        }}

        function changeConfig(event) {{
            event.preventDefault();
            const formData = new FormData(document.getElementById('change-config-form'));
            const params = new URLSearchParams(formData).toString();
            fetch('/manager/change-config/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('change-config-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('change-config-result').innerHTML = "<p style='color: red;'>Error changing config: " + error + "</p>";
                }});
        }}

        function saveConfig(event) {{
            event.preventDefault();
            const formData = new FormData(document.getElementById('save-config-form'));
            const params = new URLSearchParams(formData).toString();
            fetch('/manager/save-config/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('save-config-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('save-config-result').innerHTML = "<p style='color: red;'>Error saving config: " + error + "</p>";
                }});
        }}

        function rollingRestart(event) {{
                event.preventDefault();
                const form = document.getElementById('rolling-restart-form');
                const formData = new FormData(form);
            
                // Explicitly check the checkbox state
                const restartMastersChecked = form.querySelector('#restart_masters').checked;
            
                // Always include the parameter with true/false
                formData.set('restart_masters', restartMastersChecked ? 'true' : 'false');
            
                // Add confirmation dialog if master nodes will be restarted
                if (restartMastersChecked) {{
                    showConfirmModal(
                        '⚠️ Restart Master Nodes?',
                        '🔄',
                        `<p style="color: #dc3545; font-weight: 600;">WARNING: You are about to restart master nodes!</p>
                        <p style="margin-top: 10px;">This will trigger <strong>failover</strong> on each master node.</p>
                        <p style="margin-top: 15px;"><strong>Impact:</strong></p>
                        <ul style="margin-top: 5px;">
                            <li>Temporary service interruption</li>
                            <li>Cluster topology will change</li>
                            <li>Connected clients will be disconnected</li>
                        </ul>`,
                        'Continue Restart',
                        function() {{ executeRollingRestart(formData); }},
                        true
                    );
                    return;
                }}
            
                executeRollingRestart(formData);
            }}
            
        function executeRollingRestart(formData) {{
                const params = new URLSearchParams(formData);
            
                // Show initial status message
                document.getElementById('rolling-restart-result').innerHTML =
                    "<p>Starting rolling restart. This may take several minutes...</p>" ;
            
                // Make the request to the correct endpoint
                fetch('/manager/rolling-restart/?' + params)
                    .then(response => response.text())
                    .then(data => {{
                        document.getElementById('rolling-restart-result').innerHTML = data;
                    }})
                    .catch(error => {{
                        document.getElementById('rolling-restart-result').innerHTML =
                            "<p style='color: red;'>Error during rolling restart: " + error + "</p>";
                    }});
            }}

        function executeCommand(event) {{
            event.preventDefault();
            const formData = new FormData(document.getElementById('execute-command-form'));
            const params = new URLSearchParams(formData).toString();
            fetch('/manager/execute-command/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('execute-command-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('execute-command-result').innerHTML = "<p style='color: red;'>Error executing command: " + error + "</p>";
                }});
         }}

        function showLog(event) {{
            event.preventDefault();
            const formData = new FormData(document.getElementById('show-log-form'));
            const params = new URLSearchParams(formData).toString();
            fetch('/manager/show-log/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('show-log-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('show-log-result').innerHTML = "<p style='color: red;'>Error fetching log: " + error + "</p>";
                }});
        }}
    </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/manager/get-nodes-by-action/")
async def get_nodes_by_action(action: str):
    """
    Returns a list of nodes filtered by the action type:
    - start: returns only DOWN nodes (not responding to ping)
    - stop/restart: returns only RUNNING nodes (responding to ping)
    """
    from fastapi.responses import JSONResponse
    
    running_nodes = []
    down_nodes = []
    
    for pareNode in pareNodes:
        node_ip = pareNode[0][0]
        port_number = pareNode[1][0]
        address = f"{node_ip}:{port_number}"
        
        if pareNode[4]:  # If node is configured as active
            is_running = pingredisNode(node_ip, port_number)
            
            if is_running:
                # Get role (master/slave)
                role = slaveORMasterNode(node_ip, port_number)
                role_text = "master" if role == 'M' else "replica" if role == 'S' else ""
                running_nodes.append({"address": address, "role": role_text})
            else:
                down_nodes.append({"address": address, "role": "down"})
    
    action_lower = action.lower()
    
    if action_lower == "start":
        # For start action, show only down nodes
        if down_nodes:
            return JSONResponse(content={"nodes": down_nodes, "message": None})
        else:
            return JSONResponse(content={"nodes": [], "message": "All nodes are running"})
    
    elif action_lower in ["stop", "restart"]:
        # For stop/restart actions, show only running nodes
        if running_nodes:
            return JSONResponse(content={"nodes": running_nodes, "message": None})
        else:
            return JSONResponse(content={"nodes": [], "message": "No running nodes found"})
    
    else:
        # Unknown action, return all nodes
        all_nodes = running_nodes + down_nodes
        return JSONResponse(content={"nodes": all_nodes, "message": None})


@app.get("/manager/node-action/", response_class=HTMLResponse)
async def manager_node_action(redisNode: str, action: str, confirmed: bool = False):
    """
    Endpoint to perform start, stop, or restart actions on a Redis node.
    Returns styled HTML.
    """
    try:
        result = node_action_wv(redisNode, action, confirmed)
        # Wrap the result in a styled container
        return HTMLResponse(content=f'<div class="response-container">{result}</div>')
    except Exception as e:
        return HTMLResponse(content=f'<div class="response-container error-message"><p>Error: {str(e)}</p></div>')

@app.get("/manager/switch-master-slave/", response_class=HTMLResponse)
async def manager_switch_master_slave(redisNode: str):
    """
    Endpoint to switch roles between a master node and one of its slaves.
    Returns styled HTML.
    """
    try:
        result = switch_master_slave_wv(redisNode)
        # Wrap the result in a styled container
        return HTMLResponse(content=f'<div class="response-container">{result}</div>')
    except Exception as e:
        return HTMLResponse(content=f'<div class="response-container error-message"><p>Error: {str(e)}</p></div>')

@app.get("/manager/change-config/", response_class=HTMLResponse)
async def manager_change_config(redisNode: str, parameter: str, value: str, persist: bool = False):
    """
    Endpoint to change a Redis configuration parameter for a specific node.
    Returns styled HTML.
    """
    try:
        result = change_config_wv(redisNode, parameter, value, persist)
        # Wrap the result in a styled container
        return HTMLResponse(content=f'<div class="response-container">{result}</div>')
    except Exception as e:
        return HTMLResponse(content=f'<div class="response-container error-message"><p>Error: {str(e)}</p></div>')

@app.get("/manager/save-config/", response_class=HTMLResponse)
async def manager_save_config(redisNode: str):
    """
    Endpoint to save the Redis configuration to redis.conf for a specific node or all nodes.
    Returns styled HTML.
    """
    try:
        result = save_config_wv(redisNode)
        # Wrap the result in a styled container
        return HTMLResponse(content=f'<div class="response-container">{result}</div>')
    except Exception as e:
        return HTMLResponse(content=f'<div class="response-container error-message"><p>Error: {str(e)}</p></div>')

@app.get("/manager/rolling-restart/", response_class=HTMLResponse)
async def manager_rolling_restart(wait_minutes: int = 0, restart_masters: bool = False):
    """
    Endpoint to perform a rolling restart of Redis nodes.
    Returns styled HTML.
    """
    try:
        result = rolling_restart_wv(wait_minutes, restart_masters)
        # Wrap the result in a styled container
        return HTMLResponse(content=f'<div class="response-container">{result}</div>')
    except Exception as e:
        return HTMLResponse(content=f'<div class="response-container error-message"><p>Error: {str(e)}</p></div>')

@app.get("/manager/show-log/", response_class=HTMLResponse)
async def manager_show_log(redisNode: str, line_count: int = 50):
    """
    Endpoint to display the Redis log file for a specific node.
    Returns styled HTML.
    """
    try:
        # Assuming show_redis_log_wv returns plain text or HTML
        log_content = show_redis_log_wv(redisNode, line_count)
        # Modern, readable style for log output
        result_html = f"""
        <div class="response-container">
            <h3>Redis Log File</h3>
            <p>Node: {redisNode}</p>
            <p>Lines: {line_count}</p>
            <pre style="background: #222; color: #e0e0e0; font-family: 'Fira Mono', 'Consolas', 'Menlo', monospace; font-size: 11px; line-height: 1.5; padding: 16px; border-radius: 6px; overflow-x: auto; max-height: 500px; box-shadow: 0 2px 8px rgba(0,0,0,0.08);">{log_content}</pre>
        </div>
        """
        return HTMLResponse(content=result_html)
    except Exception as e:
        return HTMLResponse(content=f'<div class="response-container error-message"><h3>Error</h3><p>Error fetching log: {str(e)}</p></div>')

@app.get("/manager/execute-command/", response_class=HTMLResponse)
async def manager_execute_command(command: str, only_masters: bool = False, wait_seconds: int = 0):
    """
    Endpoint to execute a Redis command on all nodes or only master nodes.
    Returns styled HTML.
    """
    try:
        # Assuming execute_command_wv returns HTML, likely containing <pre>
        command_results = execute_command_wv(command, only_masters, wait_seconds)
        # Wrap the result in a styled container with heading
        result_html = f"""
        <div class="response-container">
            <h3>Command Execution Results</h3>
            <p>Command: <code>{command}</code></p>
            <p>Only Masters: {"Yes" if only_masters else "No"}</p>
            <p>Wait Seconds: {wait_seconds}</p>
            {command_results}
        </div>
        """
        return HTMLResponse(content=result_html)
    except Exception as e:
        return HTMLResponse(content=f'<div class="response-container error-message"><h3>Error</h3><p>Error executing command: {str(e)}</p></div>')

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """
    Handle requests for the favicon.ico file to avoid 404 errors.
    """
    return Response(content="", media_type="image/x-icon")


# #############################################
# Maintenance Section
# #############################################

@app.get("/maintain", response_class=HTMLResponse)
async def maintain():
    """
    Displays the Redis Cluster Maintenance UI with collapsible sections.
    """
    # Ensure we have the latest node list
    import importlib
    importlib.reload(sys.modules['pareNodeList'])
    from pareNodeList import pareNodes as fresh_pareNodes

    # Update the global pareNodes
    global pareNodes
    pareNodes = fresh_pareNodes

    nodeList = getNodeList()
    # Get active nodes for deletion dropdown
    active_nodes_with_id = []
    for i, pareNode in enumerate(pareNodes, start=1):
        if pareNode[4]:  # If active
            nodeIP = pareNode[0][0]
            portNumber = pareNode[1][0]
            active_nodes_with_id.append((i, f"{nodeIP}:{portNumber}"))

    # Generate the HTML content for the maintenance page
    html_content = f"""
    {css_style}
    <html>
    <head>
        <title>Redis Cluster Maintenance - {projectName}</title>
    </head>
    <body>
    <h1 class="maintenance-title">Redis Cluster Maintenance - {projectName}</h1>
    <div class="nav-buttons">
        <a href="/monitor" class="monitor-nav">Go to Monitor</a>
        <a href="/manager" class="manager-nav">Go to Manager</a>
    </div>
    <hr>

    <button class="collapsible">1 - Add/Delete Redis Node</button>
    <div class="content">
        <h3>Add a New Redis Node</h3>
        <form id="add-node-form" onsubmit="addNode(event)">
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 5px;">
                <label for="serverIP" style="width: 150px;">Server IP:</label>
                <input type="text" id="serverIP" name="serverIP" required placeholder="e.g., 192.168.1.10">
            </div>
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 5px;">
                <label for="serverPORT" style="width: 150px;">Port Number:</label>
                <input type="number" id="serverPORT" name="serverPORT" required placeholder="e.g., 6379">
            </div>
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 5px;">
                <label for="maxMemSize" style="width: 150px;">Maximum Memory:</label>
                <input type="text" id="maxMemSize" name="maxMemSize" required placeholder="e.g., 2gb or 500mb">
            </div>
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 5px;">
                <label for="cpuCoreIDs" style="width: 150px;">CPU Core IDs:</label>
                <input type="text" id="cpuCoreIDs" name="cpuCoreIDs" required placeholder="e.g., 1 or 1,2,3">
            </div>
           <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 5px;">
                <label for="nodeType" style="width: 150px;">Node Type:</label>
                <select id="nodeType" name="nodeType" onchange="toggleMasterDropdown()">
                    <option value="master">Master Node</option>
                    <option value="slave-specific">Slave Node</option>
                </select>
            </div>
            <div id="masterNodeWarning" style="color: #856404; padding: 10px; border-radius: 4px; margin: 10px 0; display: none;">
                <strong>Warning:</strong> Adding a master node will require slot migration afterward. <br>Make sure you have planned for slot allocation.
            </div>
            <div id="masterDropdownField" style="display: none; align-items: center; gap: 10px; margin-bottom: 10px;">
                <label for="masterID" style="width: 150px;">Master Node:</label>
                <select id="masterID" name="masterID">
                    <option value="">Loading...</option>
                </select>
            </div>
            <div style="display: flex; justify-content: flex-start; margin-top: 15px;">
                <input class="maintenance-button" type="submit" value="Add Node" style="width: auto;">
            </div>
        </form>
        <div id="add-node-result" style="margin-top: 10px;"></div>

        <h3>Delete a Redis Node</h3>
        <form id="delete-node-form" onsubmit="deleteNode(event)">
            <div style="display: flex; align-items: center; gap: 10px;">
                <select id="nodeId" name="nodeId" required>
                    {''.join([f"<option value='{id}'>{id} - {node}</option>" for id, node in active_nodes_with_id])}
                </select>
                <input class="maintenance-button" type="submit" value="Delete Node" style="width: auto; background-color: #d9534f; color: white;">
            </div>
        </form>
        <div id="delete-node-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">2 - Move Slot(s)</button>
    <div class="content">
        <h3>Move Redis Cluster Slots</h3>
        <p>Move slots between master nodes to rebalance your cluster.</p>
        
        <div id="slot-info-container" style="margin-bottom: 20px;">
            <button class="maintenance-button" onclick="fetchCurrentSlotInfo()">View Current Slots Distribution</button>
            <div id="current-slot-info" style="margin-top: 10px; max-height: 300px; overflow: auto;"></div>
        </div>
        
        <form id="move-slots-form" onsubmit="moveSlots(event)">
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                <label for="fromNodeID" style="width: 150px;">FROM Node ID:</label>
                <select id="fromNodeID" name="fromNodeID" required style="width: 300px;">
                    <option value="">-- Click "View Current Slots Distribution" first --</option>
                </select>
            </div>
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                <label for="toNodeID" style="width: 150px;">TO Node ID:</label>
                <select id="toNodeID" name="toNodeID" required style="width: 300px;">
                    <option value="">-- Click "View Current Slots Distribution" first --</option>
                </select>
            </div>
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                <label for="numberOfSlots" style="width: 150px;"><input class="maintenance-button" type="submit" value="Move Slots" style="width: auto;"></label>
                <input type="number" id="numberOfSlots" name="numberOfSlots" required placeholder="Number of slots to move" min="1" max="16384">
            </div>
        </form>
        <div id="move-slots-result" style="margin-top: 10px;"></div>
    </div>

<!-- Updated Section 3 -->
<button class="collapsible">3 - Redis Cluster Nodes Version Upgrade</button>
<div class="content">
    <h3>Choose a redis tarball from local machine or direct from redis.io</h3>
    <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 15px;">
        <form id="upload-redis-form" enctype="multipart/form-data" style="margin: 0; display: inline-block;">
            <button class="maintenance-button" type="button" onclick="document.getElementById('redis_file').click()">Upload local file</button>
            <input type="file" id="redis_file" name="upload_file" accept=".tar.gz" required style="display: none;" onchange="uploadRedisPackage()">
        </form>
        <span>OR</span>
        <form id="download-redis-form" onsubmit="downloadRedisVersion(event)" style="margin: 0; display: inline-flex; align-items: center; gap: 10px;">
            <button id="download-redis-button" class="maintenance-button" type="submit">Download from redis.io</button>
            <input type="text" id="redis_filename" name="redis_filename" required placeholder="e.g., redis-7.2.4.tar.gz" style="width:150px;">
        </form>
    </div>
    <span id="filename-validation-msg" style="color: red; font-size: 0.9em; display: block; margin-bottom: 10px;"></span>
    
    <!-- Extract and compile section (hidden by default) -->
    <div id="extract-compile-container" style="display: none; margin-top: 15px;">
        <button id="extract-compile-button" class="maintenance-button" onclick="extractCompileRedis()">Extract & Compile Package</button>
        <span id="selected-tarfile-display" style="margin-left: 10px; font-style: italic;"></span>
    </div>
    
    <!-- Progress bar container -->
    <div id="progress-container" style="display: none; margin-top: 15px;">
        <div style="margin-bottom: 5px;">Extracting and compiling Redis package... (2mins)</div>
        <div class="progress-bar-container">
            <div id="progress-bar" class="progress-bar"></div>
        </div>
        <div id="progress-status" style="margin-top: 5px; font-size: 0.9em;">Starting extraction...</div>
    </div>
    
    <!-- Results will appear here -->
    <div id="version-upgrade-result" style="margin-top: 15px;"></div>

    <!-- Add the new section for copying binaries -->
    <div id="copy-binaries-container" style="margin-top: 20px; padding-top: 15px; border-top: 1px solid #ddd;">
        <h3>Deploy Redis Binary to Cluster Nodes</h3>
        <p>After successful compilation, copy the Redis binary to all nodes in your cluster:</p>
        <div style="display: flex; align-items: center; gap: 15px;">
            <button id="copy-binaries-button" class="maintenance-button" onclick="copyRedisBinaries()">Copy Binary to All Nodes</button>
                        <input type="text" id="redis_copy_version" placeholder="e.g., 7.2.4" style="width: 100px;">
        </div>
        <div id="copy-binaries-result" style="margin-top: 15px;"></div>
    </div>
    
    <!-- New section for restarting slave nodes -->
    <div id="restart-slaves-container" style="margin-top: 20px; padding-top: 15px; border-top: 1px solid #ddd;">
        <h3>Restart Slave Nodes with New Version</h3>
        <p>After copying binary, restart all slave nodes with the new Redis version:</p>
            
        <div style="display: flex; flex-wrap: wrap; align-items: center; gap: 15px;"> 
        <button id="restart-slaves-button" class="maintenance-button" onclick="validateAndRestartSlaves()">Restart All Slave Nodes</button>
            <div style="display: flex; align-items: center; gap: 15px;">
    <div style="display: flex; align-items: center;">
        <input type="text" id="redis_restart_version" placeholder="e.g., 7.2.4" style="width: 100px;">
    </div>
    <div style="display: flex; align-items: center;">
        <label for="restart_wait_seconds">Wait between restarts (seconds):</label>
        <input type="number" id="restart_wait_seconds" min="0" value="30" style="width: 80px; margin-left: 5px;">
    </div>
</div>
        </div>
        <div id="restart-slaves-result" style="margin-top: 15px;"></div>
    </div>
    
    <!-- Update Redis Version in Configuration section -->
<div id="update-config-container" style="margin-top: 20px; padding-top: 15px; border-top: 1px solid #ddd;">
    <h3>Update Redis Version in Configuration</h3>
    <p>After copying binaries, update the Redis version in configuration files:</p>
    
    <div>
      <p>Update Redis Version in Configuration</p>
      <p>After copying binaries, update the Redis version in configuration files:</p>
      <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
        <button id="update-config-button" class="maintenance-button" onclick="updateRedisConfig()">Update Configuration</button>
        <span>Current Version: <strong id="current-redis-version">Loading...</strong></span>
        <label for="new_redis_version" style="width: 20px;">To:</label>
        <input type="text" id="new_redis_version" placeholder="e.g., 7.2.4" style="width: 80px;">
      </div>
      <div id="update-config-result" style="margin-top: 15px;"></div>
    </div>
  </div>    
</div>

    <button class="collapsible">4 - Redis Cluster Nodes Version Control</button>
    <div class="content">
        <div id="redis-version-control-container"></div>
    </div>

    <button class="collapsible">5 - Maintain Server</button>
    <div class="content">
        <h3>Reassign Slave to Another Master</h3>
        <p>Change a slave node's master assignment. This is useful when rebalancing replicas across masters.</p>
        
        <div style="margin-bottom: 15px;">
            <button class="maintenance-button" onclick="loadSlavesAndMasters()">Load Slaves & Masters</button>
            <span id="reassign-loading" style="display: none; margin-left: 10px;">⏳ Loading...</span>
        </div>
        
        <form id="reassign-slave-form" onsubmit="reassignSlave(event)">
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                <label for="slaveNodeSelect" style="width: 150px;">Select Slave:</label>
                <select id="slaveNodeSelect" name="slaveNode" required style="width: 350px;">
                    <option value="">-- Click "Load Slaves & Masters" first --</option>
                </select>
            </div>
            <div style="display: flex; align-items: center; gap: 10px; margin-bottom: 10px;">
                <label for="newMasterSelect" style="width: 150px;">New Master:</label>
                <select id="newMasterSelect" name="newMaster" required style="width: 350px;">
                    <option value="">-- Click "Load Slaves & Masters" first --</option>
                </select>
            </div>
            <div style="display: flex; justify-content: flex-start; margin-top: 15px;">
                <input id="reassign-submit-btn" class="maintenance-button" type="submit" value="Reassign Slave" style="width: auto;">
            </div>
        </form>
        <div id="reassign-slave-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">6 - Migrate Data From Remote Redis</button>
    <div class="content">
        <div style="text-align: center; padding: 20px; color: #888;">
            <p><i class="fas fa-tools"></i> This feature is not implemented yet.</p>
            <p>Migrate data from a remote Redis instance to this cluster.</p>
            <button onclick="fetchNotImplemented('migrate-data')" class="btn-disabled">Migrate Data</button>
        </div>
        <div id="migrate-data-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">7 - Cluster Slot(load) Balancer</button>
    <div class="content">
        <div style="text-align: center; padding: 20px; color: #888;">
            <p><i class="fas fa-tools"></i> This feature is not implemented yet.</p>
            <p>Balance slot distribution across your Redis cluster.</p>
            <button onclick="fetchNotImplemented('slot-balancer')" class="btn-disabled">Balance Slots</button>
        </div>
        <div id="slot-balancer-result" style="margin-top: 10px;"></div>
    </div>

    <!-- Custom Modal Dialog for Restart Confirmation -->
    <div id="restart-modal" class="modal-overlay">
        <div class="modal-dialog">
            <div id="modal-header" class="modal-header warning">
                <span class="modal-icon">⚠️</span>
                <h3 id="modal-title">Confirm Restart</h3>
            </div>
            <div class="modal-body">
                <div id="modal-body-content"></div>
            </div>
            <div class="modal-footer">
                <button class="modal-btn modal-btn-cancel" onclick="closeRestartModal()">Cancel</button>
                <button id="modal-confirm-btn" class="modal-btn modal-btn-confirm">🔄 Restart Node</button>
            </div>
        </div>
    </div>

    <!-- Generic Confirmation Modal -->
    <div id="confirm-modal" class="modal-overlay">
        <div class="modal-dialog">
            <div id="confirm-modal-header" class="modal-header">
                <span id="confirm-modal-icon" class="modal-icon">ℹ️</span>
                <h3 id="confirm-modal-title">Confirm Action</h3>
            </div>
            <div class="modal-body">
                <div id="confirm-modal-body"></div>
            </div>
            <div class="modal-footer">
                <button class="modal-btn modal-btn-cancel" onclick="closeConfirmModal()">Cancel</button>
                <button id="confirm-modal-btn" class="modal-btn modal-btn-confirm">Confirm</button>
            </div>
        </div>
    </div>

    <script>
        const collapsibles = document.querySelectorAll(".collapsible");
        collapsibles.forEach(button => {{
            button.addEventListener("click", function() {{
                this.classList.toggle("active");
                const content = this.nextElementSibling;
                if (content.style.display === "block") {{
                    content.style.display = "none";
                }} else {{
                    content.style.display = "block";
                }}
            }});
        }});
        
        const redisFilenameInput = document.getElementById('redis_filename');
        const downloadButton = document.getElementById('download-redis-button');
        const validationMsg = document.getElementById('filename-validation-msg');
        const downloadResultDiv = document.getElementById('version-upgrade-result'); // Renamed for clarity


   function validateRedisFilename() {{
       const filename = redisFilenameInput.value.trim();
       const isValid = filename.startsWith('redis-') && filename.endsWith('.tar.gz');
   
       if (isValid) {{
           downloadButton.disabled = false;
           downloadButton.classList.remove('btn-disabled'); // Use existing CSS class
           validationMsg.textContent = ''; // Clear validation message
       }} else {{
           downloadButton.disabled = true;
           downloadButton.classList.add('btn-disabled');
           if (filename === '') {{
               validationMsg.textContent = ''; // Don't show error if empty yet
           }} else {{
               validationMsg.textContent = 'Must start with "redis-" and end with ".tar.gz"';
           }}
       }}
       return isValid; // Return validation status
   }}
   
   // Add event listener to the input field
   if (redisFilenameInput) {{
       redisFilenameInput.addEventListener('input', validateRedisFilename);
       // Initial validation check in case the field is pre-filled
       validateRedisFilename();
   }}
   
   function downloadRedisVersion(event) {{
       event.preventDefault(); // Prevent default form submission
   
       // Re-validate before submitting
       if (!validateRedisFilename()) {{
           downloadResultDiv.innerHTML = '<div class="error-message"><p>Invalid filename format. Please ensure it starts with "redis-" and ends with ".tar.gz".</p></div>';
           return; // Stop if validation fails
       }}
   
       const form = document.getElementById('download-redis-form');
       const formData = new FormData(form);
       // Trim the filename when retrieving it
       const redisFilename = formData.get('redis_filename').trim();
   
       // Clear previous results and show loading message
       downloadResultDiv.innerHTML = '<p>Attempting to download...</p>';
   
       // Construct the URL with the query parameter
       const url = `/maintain/download-redis/?redis_filename=${{encodeURIComponent(redisFilename)}}`;
   
       fetch(url)
           .then(response => {{
               if (!response.ok) {{
                   // Try to read the response body for error details
                   return response.text().then(text => {{
                       // Attempt to parse as HTML to extract user-friendly message if possible
                       try {{
                           const parser = new DOMParser();
                           const doc = parser.parseFromString(text, "text/html");
                           const errorElement = doc.querySelector('.error-message p'); // Look for <p> inside .error-message
                           if (errorElement) {{
                               throw new Error(`Server error: ${{errorElement.textContent}} (Status: ${{response.status}})`);
                           }}
                       }} catch (parseError) {{
                           // Fallback if parsing fails or structure is unexpected
                           console.error("Could not parse error response:", parseError);
                       }}
                       // Fallback to raw text or generic message
                       throw new Error(`Download failed: ${{response.statusText}} (Status: ${{response.status}}). ${{text ? 'Details: ' + text.substring(0, 200) : ''}}`);
                   }});
               }}
               return response.text(); // If OK, read the response body as text (HTML)
           }})
           .then(html => {{
               // Display the HTML response from the server
               downloadResultDiv.innerHTML = html;
               
               // Check if download was successful
               if (html.includes('Successfully downloaded') || html.includes('already exists')) {{
                   // Ask the user if they want to extract and compile
                   showConfirmModal(
                       'Extract and Compile?',
                       '📦',
                       `<p>Download successful!</p><p style="margin-top: 10px;">Do you want to extract and compile this Redis package?</p><p style="margin-top: 15px; color: #666; font-size: 0.9em;"><strong>Note:</strong> This process may take a few minutes.</p>`,
                       'Extract & Compile',
                       function() {{ extractCompileRedisWithProgress(redisFilename); }},
                       false
                   );
               }}
           }})
           .catch(error => {{
               console.error('Error downloading Redis version:', error);
               // Display a user-friendly error message
               downloadResultDiv.innerHTML = `<div class="error-message"><p>Error during download:</p><pre>${{error.message}}</pre></div>`;
           }});
   }}

         function toggleMasterDropdown() {{
            const nodeType = document.getElementById('nodeType').value;
            const masterDropdownField = document.getElementById('masterDropdownField');
            const masterNodeWarning = document.getElementById('masterNodeWarning');
            
            if (nodeType === 'slave-specific') {{
                masterDropdownField.style.display = 'flex';
                masterNodeWarning.style.display = 'none';
                // Fetch master nodes for dropdown
                fetch('/maintain/view-master-nodes-dropdown')
                    .then(response => response.text())
                    .then(data => {{
                        document.getElementById('masterID').innerHTML = data;
                    }});
            }} else {{
                masterDropdownField.style.display = 'none';
                masterNodeWarning.style.display = 'block';
            }}
        }}

        // Call the function once on page load to set initial state
        document.addEventListener('DOMContentLoaded', toggleMasterDropdown);

        function addNode(event) {{
            event.preventDefault();
            const formData = new FormData(document.getElementById('add-node-form'));
            const params = new URLSearchParams(formData).toString();
            fetch('/maintain/add-node/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('add-node-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('add-node-result').innerHTML = "<p style='color: red;'>Error adding node: " + error + "</p>";
                }});
        }}

        function deleteNode(event) {{
            event.preventDefault();
            const formData = new FormData(document.getElementById('delete-node-form'));
            const params = new URLSearchParams(formData).toString();
            
            // Show loading indicator
            document.getElementById('delete-node-result').innerHTML = "<p>Loading...</p>";
            
            fetch('/maintain/delete-node/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('delete-node-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('delete-node-result').innerHTML = "<p style='color: red;'>Error deleting node: " + error + "</p>";
                }});
        }}
        
        function confirmDeleteNode(nodeId) {{
            // Show loading indicator
            document.getElementById('delete-node-result').innerHTML = "<p>Deleting node...</p>";
            
            fetch('/maintain/delete-node/?nodeId=' + nodeId + '&confirmed=true')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('delete-node-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('delete-node-result').innerHTML = "<p style='color: red;'>Error during node deletion: " + error + "</p>";
                }});
        }}
        
        function cancelDeleteNode() {{
            document.getElementById('delete-node-result').innerHTML = "<p>Node deletion cancelled.</p>";
        }}
        
        // Reassign Slave Functions
        function loadSlavesAndMasters() {{
            const loadingSpan = document.getElementById('reassign-loading');
            loadingSpan.style.display = 'inline';
            
            fetch('/maintain/get-slaves-and-masters/')
                .then(response => response.json())
                .then(data => {{
                    loadingSpan.style.display = 'none';
                    
                    if (data.error) {{
                        document.getElementById('reassign-slave-result').innerHTML = 
                            `<div class="error-box"><p>${{data.error}}</p></div>`;
                        return;
                    }}
                    
                    // Populate slave dropdown
                    const slaveSelect = document.getElementById('slaveNodeSelect');
                    slaveSelect.innerHTML = '<option value="">-- Select a slave node --</option>';
                    data.slaves.forEach(slave => {{
                        const option = document.createElement('option');
                        option.value = slave.node_id;
                        option.textContent = `${{slave.address}} → Master: ${{slave.current_master_address}}`;
                        option.dataset.address = slave.address;
                        option.dataset.currentMasterId = slave.current_master_id;
                        slaveSelect.appendChild(option);
                    }});
                    
                    // Populate master dropdown
                    const masterSelect = document.getElementById('newMasterSelect');
                    masterSelect.innerHTML = '<option value="">-- Select a new master --</option>';
                    data.masters.forEach(master => {{
                        const option = document.createElement('option');
                        option.value = master.node_id;
                        option.textContent = `${{master.address}} (Slots: ${{master.slots || 'N/A'}})`;
                        option.dataset.address = master.address;
                        masterSelect.appendChild(option);
                    }});
                    
                    if (data.slaves.length === 0) {{
                        document.getElementById('reassign-slave-result').innerHTML = 
                            `<div class="warning-box"><p>No slave nodes found in the cluster.</p></div>`;
                    }}
                }})
                .catch(error => {{
                    loadingSpan.style.display = 'none';
                    document.getElementById('reassign-slave-result').innerHTML = 
                        `<div class="error-box"><p>Error loading nodes: ${{error}}</p></div>`;
                }});
        }}
        
        function reassignSlave(event) {{
            event.preventDefault();
            
            const slaveSelect = document.getElementById('slaveNodeSelect');
            const masterSelect = document.getElementById('newMasterSelect');
            
            const slaveNodeId = slaveSelect.value;
            const newMasterId = masterSelect.value;
            
            if (!slaveNodeId || !newMasterId) {{
                document.getElementById('reassign-slave-result').innerHTML = 
                    `<div class="warning-box"><p>Please select both a slave node and a new master.</p></div>`;
                return;
            }}
            
            // Get additional info for display
            const slaveOption = slaveSelect.options[slaveSelect.selectedIndex];
            const masterOption = masterSelect.options[masterSelect.selectedIndex];
            const slaveAddress = slaveOption.dataset.address;
            const currentMasterId = slaveOption.dataset.currentMasterId;
            const newMasterAddress = masterOption.dataset.address;
            
            // Check if trying to reassign to the same master
            if (currentMasterId === newMasterId) {{
                document.getElementById('reassign-slave-result').innerHTML = 
                    `<div class="warning-box"><p>The slave is already assigned to this master. Please select a different master.</p></div>`;
                return;
            }}
            
            // Show confirmation modal
            showConfirmModal(
                'Reassign Slave Node',
                '🔄',
                `<p>Are you sure you want to reassign this slave node?</p>
                 <ul>
                    <li><strong>Slave:</strong> <span class="node-address">${{slaveAddress}}</span></li>
                    <li><strong>New Master:</strong> <span class="node-address">${{newMasterAddress}}</span></li>
                 </ul>
                 <p>The slave will replicate data from the new master.</p>`,
                'Reassign',
                function() {{
                    executeReassignSlave(slaveNodeId, newMasterId, slaveAddress, newMasterAddress);
                }},
                false
            );
        }}
        
        function executeReassignSlave(slaveNodeId, newMasterId, slaveAddress, newMasterAddress) {{
            const submitBtn = document.getElementById('reassign-submit-btn');
            submitBtn.disabled = true;
            submitBtn.value = 'Processing...';
            submitBtn.classList.add('btn-disabled');
            
            document.getElementById('reassign-slave-result').innerHTML = '';
            
            fetch(`/maintain/reassign-slave/?slaveNodeId=${{encodeURIComponent(slaveNodeId)}}&newMasterId=${{encodeURIComponent(newMasterId)}}`)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('reassign-slave-result').innerHTML = data;
                    // Reload the slaves and masters list after successful operation
                    setTimeout(loadSlavesAndMasters, 1000);
                }})
                .catch(error => {{
                    document.getElementById('reassign-slave-result').innerHTML = 
                        `<div class="error-box"><p>Error reassigning slave: ${{error}}</p></div>`;
                }})
                .finally(() => {{
                    submitBtn.disabled = false;
                    submitBtn.value = 'Reassign Slave';
                    submitBtn.classList.remove('btn-disabled');
                }});
        }}
        
        function fetchNotImplemented(feature) {{
            fetch('/maintain/' + feature + '/')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById(feature + '-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById(feature + '-result').innerHTML = "<p style='color: red;'>Error: " + error + "</p>";
                }});
        }}
        
        function fetchCurrentSlotInfo() {{
            document.getElementById('current-slot-info').innerHTML = "<p>Loading slot information...</p>";
            fetch('/maintain/slot-info/')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('current-slot-info').innerHTML = data;
                    
                    // Extract node IDs from the response to populate the dropdowns
                    extractAndPopulateNodeIDs(data);
                }})
                .catch(error => {{
                    document.getElementById('current-slot-info').innerHTML = "<p style='color: red;'>Error fetching slot information: " + error + "</p>";
                }});
        }}
        
        function extractAndPopulateNodeIDs(htmlContent) {{
            try {{
                // Create a temporary DOM element to parse the HTML
                const tempDiv = document.createElement('div');
                tempDiv.innerHTML = htmlContent;
                
                // Find all master node IDs in the HTML (look for elements with class node-id and master-node)
                const nodeElements = tempDiv.querySelectorAll('.node-id.master-node');
                
                // If we couldn't find node IDs with the class approach, try regex as fallback
                if (nodeElements.length === 0) {{
                    // Use regex to extract node IDs from table rows
                    const nodeIdRegex = new RegExp(String.raw`<td><span class="node-id.*?">(.*?)<\\/span><\\/td>`, 'g');
                    const matches = [...htmlContent.matchAll(nodeIdRegex)];
                    
                    if (matches.length > 0) {{
                        const nodeIds = matches.map(match => match[1]);
                        populateDropdowns(nodeIds);
                    }} else {{
                        console.error('No node IDs found in HTML content');
                        showNodeIDError();
                    }}
                }} else {{
                    // Extract text content from the node elements
                    const nodeIds = Array.from(nodeElements).map(el => el.textContent.trim());
                    populateDropdowns(nodeIds);
                }}
            }} catch (error) {{
                console.error('Error extracting node IDs:', error);
                showNodeIDError();
            }}
        }}
        
        function populateDropdowns(nodeIds) {{
            const fromDropdown = document.getElementById('fromNodeID');
            const toDropdown = document.getElementById('toNodeID');
            
            // Clear existing options
            fromDropdown.innerHTML = '';
            toDropdown.innerHTML = '';
            
            if (nodeIds && nodeIds.length > 0) {{
                // Add a default option
                fromDropdown.appendChild(new Option('-- Select Source Node ID --', ''));
                toDropdown.appendChild(new Option('-- Select Destination Node ID --', ''));
                
                // Add node IDs as options
                nodeIds.forEach(nodeId => {{
                    fromDropdown.appendChild(new Option(nodeId, nodeId));
                    toDropdown.appendChild(new Option(nodeId, nodeId));
                }});
                
                // Show success message
                const infoElement = document.createElement('div');
                infoElement.innerHTML = `<div class="info-box" style="margin-top: 10px;">
                    Node IDs have been loaded into the dropdowns. Select source and destination nodes to move slots.
                </div>`;
                
                // Insert after the current-slot-info div
                const slotInfoContainer = document.getElementById('slot-info-container');
                const moveForm = document.getElementById('move-slots-form');
                slotInfoContainer.parentNode.insertBefore(infoElement, moveForm);
                
                // Remove the message after 5 seconds
                setTimeout(() => {{
                    if (infoElement.parentNode) {{
                        infoElement.parentNode.removeChild(infoElement);
                    }}
                }}, 5000);
            }} else {{
                showNodeIDError();
            }}
        }}
        
        function showNodeIDError() {{
            const fromDropdown = document.getElementById('fromNodeID');
            const toDropdown = document.getElementById('toNodeID');
            
            // Add error option
            fromDropdown.innerHTML = '<option value="">No node IDs found. Try refreshing.</option>';
            toDropdown.innerHTML = '<option value="">No node IDs found. Try refreshing.</option>';
            
            // Show error message
            const errorElement = document.createElement('div');
            errorElement.innerHTML = `<div class="error-box" style="margin-top: 10px;">
                Could not extract node IDs from the response. Please refresh and try again.
            </div>`;
            
            // Insert after the current-slot-info div
            const slotInfoContainer = document.getElementById('slot-info-container');
            const moveForm = document.getElementById('move-slots-form');
            slotInfoContainer.parentNode.insertBefore(errorElement, moveForm);
            
            // Remove the message after 5 seconds
            setTimeout(() => {{
                if (errorElement.parentNode) {{
                    errorElement.parentNode.removeChild(errorElement);
                }}
            }}, 5000);
        }}
        
        function moveSlots(event) {{
            event.preventDefault();
            const formData = new FormData(document.getElementById('move-slots-form'));
            const params = new URLSearchParams(formData).toString();
            
            // Validate that node IDs are selected
            const fromNodeID = formData.get('fromNodeID');
            const toNodeID = formData.get('toNodeID');
            
            if (!fromNodeID || !toNodeID) {{
                document.getElementById('move-slots-result').innerHTML = "<div class='error-message'><p>Please select both FROM and TO node IDs.</p></div>";
                return;
            }}
            
            // Warn if moving slots to the same node
            if (fromNodeID === toNodeID) {{
                document.getElementById('move-slots-result').innerHTML = "<div class='error-message'><p>Source and destination nodes cannot be the same.</p></div>";
                return;
            }}
            
            // Show loading indicator
            document.getElementById('move-slots-result').innerHTML = "<p>Processing slot migration. This may take some time...</p>";
            
            fetch('/maintain/move-slots/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('move-slots-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('move-slots-result').innerHTML = "<p style='color: red;'>Error: " + error + "</p>";
                }});
        }}
        
        function uploadRedisPackage() {{
            const fileInput = document.getElementById('redis_file');
            const file = fileInput.files[0];
            
            if (!file) {{
                return;
            }}
            
            // Validate file name format
            const filenamePattern = /^redis-\\d+\\.\\d+\\.\\d+\\.tar\\.gz$/;
            if (!filenamePattern.test(file.name)) {{
                document.getElementById('version-upgrade-result').innerHTML = '<div class="error-message"><p>Invalid format. Use: redis-x.y.z.tar.gz</p></div>';
                return;
            }}
            
            // Clear previous results and show loading message
            const resultDiv = document.getElementById('version-upgrade-result');
            resultDiv.innerHTML = '<p>Uploading Redis package...</p>';
            
            // Create FormData object
            const formData = new FormData();
            formData.append('upload_file', file);
            
            // Send the file to the server
            fetch('/maintain/upload-redis/', {{
                method: 'POST',
                body: formData
            }})
            .then(response => response.text())
            .then(html => {{
                // Update the result area
                resultDiv.innerHTML = html;
                
                // If upload was successful, ask user if they want to extract and compile
                if (html.includes('Successfully uploaded') || html.includes('file-exists-message')) {{
                    // Ask the user if they want to extract and compile
                    showConfirmModal(
                        'Extract and Compile?',
                        '📦',
                        `<p>File uploaded successfully!</p><p style="margin-top: 10px;">Do you want to extract and compile this Redis package?</p><p style="margin-top: 15px; color: #666; font-size: 0.9em;"><strong>Note:</strong> This process may take a few minutes.</p>`,
                        'Extract & Compile',
                        function() {{ extractCompileRedisWithProgress(file.name); }},
                        false
                    );
                }}
            }})
            .catch(error => {{
                resultDiv.innerHTML = `<div class="error-message"><p>Error: ${{error.message}}</p></div>`;
            }});
        }}
        
        // Function to show progress bar and start updates
        function showProgressBar() {{
            // Hide the result div and show progress container
            document.getElementById('version-upgrade-result').innerHTML = '';
            document.getElementById('progress-container').style.display = 'block';
            
            // Reset progress bar
            const progressBar = document.getElementById('progress-bar');
            progressBar.style.width = '0%';
            
            // Set initial status message
            document.getElementById('progress-status').textContent = 'Starting extraction...';
        }}
        
        // Function to update progress bar
        function updateProgressBar(progressPercentage, statusMessage) {{
            const progressBar = document.getElementById('progress-bar');
            progressBar.style.width = progressPercentage + '%';
            
            if (statusMessage) {{
                document.getElementById('progress-status').textContent = statusMessage;
            }}
        }}
        
        // Function to hide progress bar
        function hideProgressBar() {{
            document.getElementById('progress-container').style.display = 'none';
        }}
        
        // Function to extract and compile Redis with progress bar
        function extractCompileRedisWithProgress(redisFilename) {{
            // Show progress bar
            showProgressBar();
            
            // Start time for progress calculation
            const startTime = Date.now();
            const expectedDurationMs = 120000; // 2 minutes
            
            // Simulated progress steps and messages
            const progressSteps = [
                {{ percentage: 5, message: 'Starting extraction...', timeOffset: 0 }},
                {{ percentage: 10, message: 'Extracting Redis package...', timeOffset: 2000 }},
                {{ percentage: 20, message: 'Extraction complete, starting compilation...', timeOffset: 10000 }},
                {{ percentage: 30, message: 'Compiling Redis core components...', timeOffset: 20000 }},
                {{ percentage: 50, message: 'Building Redis server...', timeOffset: 40000 }},
                {{ percentage: 70, message: 'Building Redis CLI tools...', timeOffset: 60000 }},
                {{ percentage: 85, message: 'Finalizing compilation...', timeOffset: 80000 }},
                {{ percentage: 95, message: 'Waiting for process to complete...', timeOffset: 100000 }}
            ];
            
            // Set up progress updates
            const progressIntervals = [];
            
            // Schedule the progress steps
            progressSteps.forEach(step => {{
                const interval = setTimeout(() => {{
                    updateProgressBar(step.percentage, step.message);
                }}, step.timeOffset);
                progressIntervals.push(interval);
            }});
            
            // Continuous small progress updates between major steps
            let lastPercentage = 0;
            const continuousUpdateInterval = setInterval(() => {{
                const currentTime = Date.now();
                const elapsedMs = currentTime - startTime;
                let calculatedPercentage = Math.min(Math.floor((elapsedMs / expectedDurationMs) * 100), 95);
                
                // Find the last scheduled step we passed
                for (let i = progressSteps.length - 1; i >= 0; i--) {{
                    if (elapsedMs >= progressSteps[i].timeOffset) {{
                        lastPercentage = progressSteps[i].percentage;
                        break;
                    }}
                }}
                
                // Don't go backwards or jump too far ahead
                calculatedPercentage = Math.max(calculatedPercentage, lastPercentage);
                
                // Update the progress bar
                updateProgressBar(calculatedPercentage);
            }}, 1000);
            progressIntervals.push(continuousUpdateInterval);
            
            // Begin the actual extraction and compilation
            fetch('/maintain/extract-compile-redis/?redis_tarfile=' + encodeURIComponent(redisFilename))
                .then(response => response.text())
                .then(html => {{
                    // Clean up all progress intervals
                    progressIntervals.forEach(interval => clearTimeout(interval));
                    clearInterval(continuousUpdateInterval);
                    
                    // Complete the progress bar
                    updateProgressBar(100, 'Process complete!');
                    
                    // After a brief delay, hide progress bar and show result
                    setTimeout(() => {{
                        hideProgressBar();
                        document.getElementById('version-upgrade-result').innerHTML = html;
                    }}, 1000);
                }})
                .catch(error => {{
                    // Clean up intervals
                    progressIntervals.forEach(interval => clearTimeout(interval));
                    clearInterval(continuousUpdateInterval);
                    
                    // Hide progress and show error
                    hideProgressBar();
                    document.getElementById('version-upgrade-result').innerHTML = 
                        `<div class="error-message"><p>Error during extraction/compilation:</p><pre>${{error.message}}</pre></div>`;
                }});
        }}
        
        // Function to extract and compile Redis (for direct button click)
        function extractCompileRedis() {{
            const redisFilename = document.getElementById('selected-tarfile-display').textContent.trim();
            if (redisFilename) {{
                extractCompileRedisWithProgress(redisFilename);
            }} else {{
                document.getElementById('version-upgrade-result').innerHTML = 
                    '<div class="error-message"><p>No Redis package selected. Please upload or download a package first.</p></div>';
            }}
        }}

        function copyRedisBinaries() {{
            const versionInput = document.getElementById('redis_copy_version');
            const version = versionInput.value.trim();
            
            // Basic validation
            if (!version) {{
                document.getElementById('copy-binaries-result').innerHTML = '<div class="error-message">Please enter a Redis version</div>';
                return;
            }}
            
            // Format validation (should be like 7.2.4)
            const versionPattern = /^\\d+\\.\\d+\\.\\d+$/;
            if (!versionPattern.test(version)) {{
                document.getElementById('copy-binaries-result').innerHTML = '<div class="error-message"><p>Invalid version format. Use format like: 7.2.4</p></div>';
                return;
            }}
            
            // Show loading message
            document.getElementById('copy-binaries-result').innerHTML = '<p>Copying Redis binary to all nodes in the cluster. Please wait...</p>';
            
            // Call the API endpoint
            fetch(`/maintain/copy-redis-binaries/?redis_version=${{encodeURIComponent(version)}}`)
                .then(response => response.text())
                .then(html => {{
                    document.getElementById('copy-binaries-result').innerHTML = html;
                }})
                .catch(error => {{
                    document.getElementById('copy-binaries-result').innerHTML = 
                        `<div class="error-message"><p>Error copying Redis binary:</p><pre>${{error.message}}</pre></div>`;
                }});
        }}

        function restartSlaveNodes() {{
            const versionInput = document.getElementById('redis_restart_version');
            const waitInput = document.getElementById('restart_wait_seconds');
            const version = versionInput.value.trim();
            const waitSeconds = parseInt(waitInput.value) || 0;
            
            // Validate wait seconds
            if (waitSeconds < 0) {{
                document.getElementById('restart-slaves-result').innerHTML = '<div class="error-message"><p>Wait time cannot be negative</p></div>';
                return;
            }}
            
            // Validate version format if specified
            if (version && !/^\\d+\\.\\d+\\.\\d+$/.test(version)) {{
                document.getElementById('restart-slaves-result').innerHTML = '<div class="error-message"><p>Invalid version format. Use format like: 7.2.4</p></div>';
                return;
            }}
            
            // Show loading message
            document.getElementById('restart-slaves-result').innerHTML = '<p>Processing request...</p>';
            
            // Call API with confirmation=false first to get the confirmation dialog
            const versionParam = version ? `&redis_version=${{encodeURIComponent(version)}}` : '';
            fetch(`/maintain/restart-slaves/?wait_seconds=${{waitSeconds}}${{versionParam}}`)
                .then(response => response.text())
                .then(html => {{
                    document.getElementById('restart-slaves-result').innerHTML = html;
                }})
                .catch(error => {{
                    document.getElementById('restart-slaves-result').innerHTML = 
                        `<div class="error-message"><p>Error processing request:</p><pre>${{error.message}}</pre></div>`;
                }});
        }}

        function confirmRestartSlaves(waitSeconds, redisVersion) {{
            document.getElementById('restart-slaves-result').innerHTML = '<p>Restarting slave nodes. This may take several minutes...</p>';
            
            const versionParam = redisVersion ? `&redis_version=${{encodeURIComponent(redisVersion)}}` : '';
            fetch(`/maintain/restart-slaves/?wait_seconds=${{waitSeconds}}${{versionParam}}&confirmed=true`)
                .then(response => response.text())
                .then(html => {{
                    document.getElementById('restart-slaves-result').innerHTML = html;
                }})
                .catch(error => {{
                    document.getElementById('restart-slaves-result').innerHTML = 
                        `<div class="error-message"><p>Error restarting slave nodes:</p><pre>${{error.message}}</pre></div>`;
                }});
        }}

        function cancelRestartSlaves() {{
            document.getElementById('restart-slaves-result').innerHTML = '<p>Operation cancelled.</p>';
        }}
        
    function validateAndRestartSlaves() {{
    const versionField = document.getElementById('redis_restart_version');
    const resultElement = document.getElementById('restart-slaves-result');
    
    // Check if version field is filled
    if (!versionField.value.trim()) {{
        resultElement.innerHTML = '<div class="error-message">Redis version is required. Please enter a version number.</div>';
        versionField.focus();
        return;
    }}
    
    // Check if binary exists before proceeding
    const version = versionField.value.trim();
    fetch(`/maintain/verify-redis-binary/?redis_version=${{encodeURIComponent(version)}}`)
        .then(response => response.json())
        .then(data => {{
            if (data.exists) {{
                // Binary exists, proceed with restart
                restartSlaveNodes();
            }} else {{
                // Binary doesn't exist, show error
                resultElement.innerHTML = `<div class="error-message">Redis ${{version}} binary not found at ${{data.path}}
                <br>Please make sure to upload and compile the binary first!</div>`;
            }}
        }})
        .catch(error => {{
            resultElement.innerHTML = `<div class="error-message">Error verifying Redis binary: ${{error.message}}</div>`;
        }});
   }}

// Modal functions for restart confirmation
let pendingRestartNode = null;
let pendingRestartIsMaster = false;

function showRestartModal(nodeAddress, isMaster) {{
    pendingRestartNode = nodeAddress;
    pendingRestartIsMaster = isMaster;
    
    const modal = document.getElementById('restart-modal');
    const header = document.getElementById('modal-header');
    const title = document.getElementById('modal-title');
    const bodyContent = document.getElementById('modal-body-content');
    const confirmBtn = document.getElementById('modal-confirm-btn');
    
    if (isMaster) {{
        header.className = 'modal-header danger';
        title.textContent = '⚠️ Restart Master Node?';
        confirmBtn.className = 'modal-btn modal-btn-confirm danger';
        bodyContent.innerHTML = `
            <p><strong>You are about to restart a MASTER node:</strong></p>
            <p><span class="node-address">${{nodeAddress}}</span></p>
            <p style="color: #dc3545; font-weight: 500;">This will trigger a FAILOVER!</p>
            <p>One of its replicas will be promoted to master.</p>
            <p style="margin-top: 15px;"><strong>Impact:</strong></p>
            <ul>
                <li>Brief service interruption for keys on this shard</li>
                <li>Cluster topology will change</li>
                <li>Connected clients will be disconnected</li>
            </ul>
        `;
    }} else {{
        header.className = 'modal-header warning';
        title.textContent = 'Restart Replica Node?';
        confirmBtn.className = 'modal-btn modal-btn-confirm';
        bodyContent.innerHTML = `
            <p>You are about to restart replica node:</p>
            <p><span class="node-address">${{nodeAddress}}</span></p>
            <p style="margin-top: 15px;">This will temporarily disconnect clients connected to this node.</p>
            <p>The cluster will continue to function normally.</p>
        `;
    }}
    
    modal.classList.add('active');
    document.body.style.overflow = 'hidden'; // Prevent background scrolling
}}

function closeRestartModal() {{
    const modal = document.getElementById('restart-modal');
    modal.classList.remove('active');
    document.body.style.overflow = ''; // Restore scrolling
    pendingRestartNode = null;
    pendingRestartIsMaster = false;
}}

// Generic confirmation modal
let pendingConfirmCallback = null;

function showConfirmModal(title, icon, content, confirmBtnText, confirmCallback, isDanger = false) {{
    pendingConfirmCallback = confirmCallback;
    
    const modal = document.getElementById('confirm-modal');
    const header = document.getElementById('confirm-modal-header');
    const modalIcon = document.getElementById('confirm-modal-icon');
    const modalTitle = document.getElementById('confirm-modal-title');
    const bodyContent = document.getElementById('confirm-modal-body');
    const confirmBtn = document.getElementById('confirm-modal-btn');
    
    modalIcon.textContent = icon;
    modalTitle.textContent = title;
    bodyContent.innerHTML = content;
    confirmBtn.textContent = confirmBtnText;
    
    if (isDanger) {{
        header.className = 'modal-header danger';
        confirmBtn.className = 'modal-btn modal-btn-confirm danger';
    }} else {{
        header.className = 'modal-header warning';
        confirmBtn.className = 'modal-btn modal-btn-confirm';
    }}
    
    modal.classList.add('active');
    document.body.style.overflow = 'hidden';
}}

function closeConfirmModal() {{
    const modal = document.getElementById('confirm-modal');
    modal.classList.remove('active');
    document.body.style.overflow = '';
    pendingConfirmCallback = null;
}}

function executeConfirmAction() {{
    if (pendingConfirmCallback) {{
        const callback = pendingConfirmCallback;
        closeConfirmModal();
        callback();
    }}
}}

function confirmRestart() {{
    if (!pendingRestartNode) return;
    
    const nodeAddress = pendingRestartNode;
    const isMaster = pendingRestartIsMaster;
    
    closeRestartModal();
    executeNodeRestart(nodeAddress, isMaster);
}}

// Initialize modal event handlers when DOM is ready
function initModalHandlers() {{
    // Attach confirm handler to restart modal button
    const confirmBtn = document.getElementById('modal-confirm-btn');
    if (confirmBtn) {{
        confirmBtn.addEventListener('click', confirmRestart);
    }}

    // Close restart modal when clicking outside
    const modal = document.getElementById('restart-modal');
    if (modal) {{
        modal.addEventListener('click', function(e) {{
            if (e.target === this) {{
                closeRestartModal();
            }}
        }});
    }}
    
    // Attach confirm handler to generic confirm modal button
    const confirmModalBtn = document.getElementById('confirm-modal-btn');
    if (confirmModalBtn) {{
        confirmModalBtn.addEventListener('click', executeConfirmAction);
    }}
    
    // Close confirm modal when clicking outside
    const confirmModal = document.getElementById('confirm-modal');
    if (confirmModal) {{
        confirmModal.addEventListener('click', function(e) {{
            if (e.target === this) {{
                closeConfirmModal();
            }}
        }});
    }}
}}

// Close modals with Escape key
document.addEventListener('keydown', function(e) {{
    if (e.key === 'Escape') {{
        const restartModal = document.getElementById('restart-modal');
        if (restartModal && restartModal.classList.contains('active')) {{
            closeRestartModal();
            return;
        }}
        const confirmModal = document.getElementById('confirm-modal');
        if (confirmModal && confirmModal.classList.contains('active')) {{
            closeConfirmModal();
        }}
    }}
}});

// Initialize handlers when DOM is ready
if (document.readyState === 'loading') {{
    document.addEventListener('DOMContentLoaded', initModalHandlers);
}} else {{
    initModalHandlers();
}}

// Show modal from Version Control section
function restartNodeFromVersion(nodeAddress, isMaster) {{
    showRestartModal(nodeAddress, isMaster);
}}

// Execute the actual restart (called after modal confirmation)
function executeNodeRestart(nodeAddress, isMaster) {{
    // Find the warning icon container for this node and show loading state
    const container = document.getElementById('redis-version-control-container');
    const warningContainers = container.querySelectorAll('.warning-icon-container');
    let targetContainer = null;
    
    // Find the container that has a button with this node address
    warningContainers.forEach(wc => {{
        const btn = wc.querySelector('.restart-btn');
        if (btn && btn.onclick.toString().includes(nodeAddress)) {{
            targetContainer = wc;
        }}
    }});
    
    // Update the specific warning icon to show loading
    if (targetContainer) {{
        targetContainer.innerHTML = `<span style="color: #856404;">⏳</span>`;
    }}
    
    // Add a status message above the table
    const statusDiv = document.createElement('div');
    statusDiv.id = 'restart-status-msg';
    const statusColor = isMaster ? 'background-color: #f8d7da; border: 1px solid #f5c6cb; color: #721c24;' : 'background-color: #fff3cd; border: 1px solid #ffc107; color: #856404;';
    statusDiv.style.cssText = `padding: 10px; margin-bottom: 10px; border-radius: 5px; ${{statusColor}}`;
    statusDiv.innerHTML = isMaster 
        ? `<strong>⏳ Restarting MASTER node ${{nodeAddress}}... (failover in progress)</strong>`
        : `<strong>⏳ Restarting node ${{nodeAddress}}...</strong>`;
    
    // Insert status at the top of the container
    const existingStatus = document.getElementById('restart-status-msg');
    if (existingStatus) {{
        existingStatus.remove();
    }}
    container.insertBefore(statusDiv, container.firstChild);
    
    // Call the restart endpoint
    fetch(`/manager/node-action/?redisNode=${{encodeURIComponent(nodeAddress)}}&action=restart&confirmed=true`)
        .then(response => response.text())
        .then(html => {{
            // Update status message to show success
            const statusMsg = document.getElementById('restart-status-msg');
            if (statusMsg) {{
                statusMsg.style.cssText = 'padding: 10px; margin-bottom: 10px; border-radius: 5px; background-color: #dff0d8; border: 1px solid #5cb85c; color: #3c763d;';
                statusMsg.innerHTML = isMaster
                    ? `<strong>✓ Master node ${{nodeAddress}} restarted successfully!</strong> Failover completed. Refreshing version data...`
                    : `<strong>✓ Node ${{nodeAddress}} restarted successfully!</strong> Refreshing version data...`;
            }}
            // Reload version control data after a short delay
            setTimeout(() => {{
                loadRedisVersionControl(true);
            }}, 2000);
        }})
        .catch(error => {{
            // Update status message to show error
            const statusMsg = document.getElementById('restart-status-msg');
            if (statusMsg) {{
                statusMsg.style.cssText = 'padding: 10px; margin-bottom: 10px; border-radius: 5px; background-color: #f2dede; border: 1px solid #d9534f; color: #a94442;';
                statusMsg.innerHTML = `<strong>❌ Error restarting node:</strong> ${{error.message}}`;
            }}
            // Reload to restore the warning icon
            setTimeout(() => {{
                loadRedisVersionControl(true);
            }}, 3000);
        }});
}}
    
    // Fetch current Redis version when page loads
document.addEventListener('DOMContentLoaded', function() {{
    fetch('/maintain/get-redis-version/')
        .then(response => response.text())
        .then(data => {{
            document.getElementById('current-redis-version').textContent = data;
        }})
        .catch(error => {{
            console.error('Error fetching Redis version:', error);
            document.getElementById('current-redis-version').textContent = 'Unknown';
        }});
}});

function updateRedisConfig() {{
    const newVersionField = document.getElementById('new_redis_version');
    const resultElement = document.getElementById('update-config-result');
    
    // Validate version input
    if (!newVersionField.value.trim()) {{
        resultElement.innerHTML = `
            <div class="warning-box">
                Please enter a valid Redis version.
            </div>
        `;
        return;
    }}
    
    const redisVersion = newVersionField.value.trim();
    resultElement.innerHTML = '<p>Updating configuration...</p>';
    
    fetch(`/maintain/update-redis-config/?redis_version=${{encodeURIComponent(redisVersion)}}`)
        .then(response => response.text())
        .then(data => {{
            resultElement.innerHTML = data;
            // Refresh displayed current version
            document.getElementById('current-redis-version').textContent = redisVersion;
        }})
        .catch(error => {{
            resultElement.innerHTML = `
                <div class="error-box">
                    Error updating configuration: ${{error.message}}
                </div>
            `;
        }});
}}

function loadRedisVersionControl(preserveScroll = false) {{
    const versionControlContainer = document.getElementById('redis-version-control-container');
    if (!versionControlContainer) return;

    // Save scroll position if preserveScroll is true
    const scrollTop = preserveScroll ? window.scrollY || document.documentElement.scrollTop : 0;

    versionControlContainer.innerHTML = '<div class=\"loading\">Loading version data...</div>';

    fetch('/maintain/redis-version-control/')
        .then(response => response.text())
        .then(html => {{
            versionControlContainer.innerHTML = html;
            // Restore scroll position if we were preserving it
            if (preserveScroll) {{
                window.scrollTo(0, scrollTop);
            }}
        }})
        .catch(error => {{
            versionControlContainer.innerHTML = `
                <div class=\"error-message\">
                    <p>Failed to load Redis version information: ${{error}}</p>
                </div>
            `;
            // Restore scroll position even on error
            if (preserveScroll) {{
                window.scrollTo(0, scrollTop);
            }}
        }});
}}

// Add event listener for Redis Version Control section
document.addEventListener('DOMContentLoaded', function() {{
    const collapsibles = document.querySelectorAll('.collapsible');
    collapsibles.forEach((button, index) => {{
        if (index === 3) {{ // Index 3 is the 4th collapsible (0-based index)
            button.addEventListener("click", function() {{
                // Check if content is being expanded (not collapsed)
                const content = this.nextElementSibling;
                if (getComputedStyle(content).maxHeight === "0px" || !content.style.maxHeight) {{
                    // Content is being expanded, load the version control data
                    loadRedisVersionControl();
                }}
            }});
        }}
    }});
}});
        
    </script>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content)

@app.get("/maintain/add-node/", response_class=HTMLResponse)
async def add_node(
    serverIP: str,
    serverPORT: str,
    maxMemSize: str,
    cpuCoreIDs: str,
    nodeType: str = "master",
    masterID: str = "",
    confirmed: bool = False
):
    """
    Endpoint to add a new Redis node to the cluster.
    """
    if not validIP(serverIP):
        return HTMLResponse(content=f"""
        {css_style}
        <html><head><title>Error</title></head>
        <body>
            <h2>Invalid IP Address</h2>
            <p style='color: red;'>The IP address {serverIP} is not valid.</p>
        </body></html>
        """)

    # Ensure a master ID is provided for slave nodes
    if nodeType == 'slave-specific' and (not masterID or masterID.strip() == ""):
        return HTMLResponse(content=f"""
        {css_style}
        <html><head><title>Error</title></head>
        <body>
            <h2>Missing Master ID</h2>
            <p style='color: red;'>When adding a slave node, a master node ID must be provided.</p>
            <p>Please select a valid master node from the dropdown menu.</p>
        </body></html>
        """)

    # Call add_delete_node_wv with proper parameters
    node_info = {
        'serverIP': serverIP,
        'serverPORT': serverPORT,
        'maxMemSize': maxMemSize,
        'cpuCoreIDs': cpuCoreIDs,
        'nodeType': nodeType,
        'masterID': masterID
    }

    result_html = add_delete_node_wv('add', node_info)

    # Construct the response message
    response_message = f"""
    {css_style}
    <html>
    <head><title>Add Redis Node</title></head>
    <body>
        <h2>Add Redis Node Result</h2>
        <div>{result_html}</div>
    </body>
    </html>
    """
    return HTMLResponse(content=response_message)

@app.get("/maintain/view-master-nodes-dropdown", response_class=HTMLResponse)
async def view_master_nodes_dropdown():
    """
    Returns a list of master nodes as a dropdown menu for the "Add Node" form.
    """
    master_nodes = []

    try:
        # Find a contact node to query cluster info
        contact_node = None
        for pareNode in pareNodes:
            if pareNode[4]:  # If active
                nodeIP = pareNode[0][0]
                portNumber = pareNode[1][0]
                if pingredisNode(nodeIP, portNumber):
                    contact_node = (nodeIP, portNumber)
                    break

        if not contact_node:
            return "<option value=''>No active master nodes found</option>"

        # Query the cluster for master nodes
        cmd_status, cmd_output = subprocess.getstatusoutput(
            redisConnectCmd(contact_node[0], contact_node[1], ' CLUSTER NODES | grep master'))

        if cmd_status != 0:
            return "<option value=''>Error retrieving master nodes</option>"

        lines = cmd_output.strip().split('\n')
        for line in lines:
            parts = line.split()
            if len(parts) >= 9 and "master" in line and "fail" not in line:
                node_id = parts[0]
                ip_port = parts[1]
                master_nodes.append((node_id, ip_port))

        # Generate HTML options for the dropdown
        options = "".join([f"<option value='{node[0]}'>{node[1]}</option>" for node in master_nodes])
        return options
    except Exception as e:
        return f"<option value=''>Error: {str(e)}</option>"

@app.get("/maintain/delete-node/", response_class=HTMLResponse)
async def delete_node(nodeId: str, confirmed: bool = False):
    """
    Endpoint to delete a Redis node from the cluster.
    """
    try:
        if not confirmed:
            # First verify the node exists and is active before showing confirmation
            try:
                node_id_int = int(nodeId)
                if node_id_int < 1 or node_id_int > len(pareNodes):
                    return HTMLResponse(content=f"""
                    <div class="error-message">
                        <p style='color: red;'>Node ID {nodeId} doesn't exist. Valid range is 1-{len(pareNodes)}</p>
                    </div>
                    """)

                if not pareNodes[node_id_int - 1][4]:
                    return HTMLResponse(content=f"""
                    <div class="error-message">
                        <p style='color: red;'>Node {nodeId} is already marked as inactive</p>
                    </div>
                    """)

                # Get node details for display
                serverIP = pareNodes[node_id_int - 1][0][0]
                serverPORT = pareNodes[node_id_int - 1][1][0]

                # Show confirmation dialog with node details
                return HTMLResponse(content=f"""
                <div class="confirmation-needed">
                    <p>Are you sure you want to delete this node from the cluster?</p>
                    <p><strong>Node:</strong> {nodeId} - {serverIP}:{serverPORT}</p>
                    <p style='color: red;'>This operation cannot be undone!</p>
                    <div class="confirmation-buttons">
                        <button onclick="confirmDeleteNode('{nodeId}')" class="confirm-btn">Yes, Delete Node</button>
                        <button onclick="cancelDeleteNode()" class="cancel-btn">Cancel</button>
                    </div>
                </div>
                """)
            except Exception as e:
                return HTMLResponse(content=f"""
                <div class="error-message">
                    <p style='color: red;'>An error occurred while processing node {nodeId}: {str(e)}</p>
                </div>
                """)

        # If confirmed, delegate to the add_delete_node_wv function
        result_html = add_delete_node_wv('del', nodeId)

        # Return just the result HTML, not a full page
        return HTMLResponse(content=f"""
        <div class="delete-result">
            <h3>Delete Node Result</h3>
            <div>{result_html}</div>
        </div>
        """)
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        return HTMLResponse(content=f"""
        <div class="error-message">
            <h3>Unexpected Error</h3>
            <p style='color: red;'>An unexpected error occurred: {str(e)}</p>
            <pre style='background-color: #f8f8f8; padding: 10px; overflow-x: auto; font-size: 12px;'>{trace}</pre>
        </div>
        """)

@app.get("/maintain/slot-info/", response_class=HTMLResponse)
async def maintain_slot_info():
    """
    Endpoint to display simplified slot information for moving slots in the maintenance page.
    """
    try:
        # Find a working node to get slot information
        for pareNode in pareNodes:
            nodeIP = pareNode[0][0]
            portNumber = pareNode[1][0]
            if pareNode[4]:  # Check if active
                isPing = pingredisNode(nodeIP, portNumber)
                if isPing:
                    try:
                        # Use the simplified function for maintenance page
                        slot_info = slotInfoSimplified_wv(nodeIP, portNumber)
                        
                        # Return the results in a more readable format
                        return HTMLResponse(content=f"""
                        <div class="response-container">
                            <div style="max-height: 400px; overflow-y: auto; margin-top: 10px; padding: 10px; border: 1px solid #ddd; border-radius: 5px;">
                                {slot_info}
                            </div>
                        </div>
                        """)
                    except Exception as e:
                        import traceback
                        return HTMLResponse(content=f"""
                        <div class="error-message">
                            <h4>Error Getting Slot Information</h4>
                            <p>Error retrieving slot information from node {nodeIP}:{portNumber}</p>
                            <p>Error details: {str(e)}</p>
                            <pre style="font-size: 12px;">{traceback.format_exc()}</pre>
                        </div>
                        """)

        # If no active node was found
        return HTMLResponse(content="""
        <div class="error-message">
            <h4>No Active Nodes</h4>
            <p>No active Redis nodes were found to retrieve slot information.</p>
            <p>Please ensure at least one node in your cluster is accessible.</p>
        </div>
        """)
    except Exception as e:
        import traceback
        return HTMLResponse(content=f"""
        <div class="error-message">
            <h4>Unexpected Error</h4>
            <p>An error occurred while trying to retrieve slot information: {str(e)}</p>
            <pre style="font-size: 12px;">{traceback.format_exc()}</pre>
        </div>
        """)

@app.get("/maintain/move-slots/", response_class=HTMLResponse)
async def move_slots(fromNodeID: str, toNodeID: str, numberOfSlots: str):
    """
    Endpoint to move slots between Redis nodes.
    """
    try:
        # Basic input validation
        if not fromNodeID or not toNodeID or not numberOfSlots:
            return HTMLResponse(content="<p style='color: red;'>All fields are required.</p>")

        if not numberOfSlots.isdigit():
            return HTMLResponse(content="<p style='color: red;'>Number of slots must be a positive integer.</p>")

        slots = int(numberOfSlots)
        if slots <= 0 or slots >= 16385:
            return HTMLResponse(content="<p style='color: red;'>Number of slots must be between 1 and 16384.</p>")

        # Find a contact node for the operation
        contact_node_number = 0
        for index, pareNode in enumerate(pareNodes):
            if pareNode[4]:  # If node is active
                nodeIP = pareNode[0][0]
                portNumber = pareNode[1][0]
                if pingredisNode(nodeIP, portNumber):
                    contact_node_number = index + 1
                    break

        if contact_node_number == 0:
            return HTMLResponse(content="<p style='color: red;'>No active Redis node found to perform the operation.</p>")

        # Call the function to move slots
        result = move_slots_wv(contact_node_number, fromNodeID, toNodeID, numberOfSlots)
        return HTMLResponse(content=result)

    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        return HTMLResponse(content=f"""
        <div class="error-message">
            <h3>Error Moving Slots</h3>
            <p>An unexpected error occurred: {str(e)}</p>
            <pre style="font-size: 12px;">{trace}</pre>
        </div>
        """)


@app.get("/maintain/get-slaves-and-masters/")
async def get_slaves_and_masters():
    """
    Returns a JSON list of all slave nodes and master nodes in the cluster.
    Used for the reassign slave feature.
    """
    from fastapi.responses import JSONResponse
    
    try:
        # Find a working node to query cluster info
        contact_node = None
        for pareNode in pareNodes:
            nodeIP = pareNode[0][0]
            portNumber = pareNode[1][0]
            if pareNode[4] and pingredisNode(nodeIP, portNumber):
                contact_node = (nodeIP, portNumber)
                break
        
        if not contact_node:
            return JSONResponse(content={"error": "No active Redis node found to query cluster information."})
        
        # Query cluster nodes
        cluster_cmd = f"{redisConnectCmd(contact_node[0], contact_node[1], 'CLUSTER NODES')}"
        status, output = subprocess.getstatusoutput(cluster_cmd)
        
        if status != 0:
            return JSONResponse(content={"error": f"Failed to get cluster nodes: {output}"})
        
        masters = []
        slaves = []
        master_addresses = {}  # node_id -> address mapping for masters
        
        # First pass: collect all masters
        for line in output.strip().split('\n'):
            parts = line.split()
            if len(parts) < 8:
                continue
            
            node_id = parts[0]
            address = parts[1].split('@')[0]
            role_status = parts[2]
            
            is_master = "master" in role_status
            is_fail = "fail" in role_status
            
            if is_master and not is_fail:
                slots = ' '.join([p for p in parts[8:] if '-' in p or p.isdigit()]) if len(parts) > 8 else ''
                masters.append({
                    "node_id": node_id,
                    "address": address,
                    "slots": slots
                })
                master_addresses[node_id] = address
        
        # Second pass: collect all slaves
        for line in output.strip().split('\n'):
            parts = line.split()
            if len(parts) < 8:
                continue
            
            node_id = parts[0]
            address = parts[1].split('@')[0]
            role_status = parts[2]
            master_id = parts[3] if len(parts) > 3 else None
            
            is_slave = "slave" in role_status
            is_fail = "fail" in role_status
            
            if is_slave and not is_fail:
                current_master_address = master_addresses.get(master_id, "Unknown")
                slaves.append({
                    "node_id": node_id,
                    "address": address,
                    "current_master_id": master_id,
                    "current_master_address": current_master_address
                })
        
        return JSONResponse(content={
            "masters": masters,
            "slaves": slaves
        })
        
    except Exception as e:
        import traceback
        return JSONResponse(content={"error": f"Error: {str(e)}"})


@app.get("/maintain/reassign-slave/", response_class=HTMLResponse)
async def reassign_slave(slaveNodeId: str, newMasterId: str):
    """
    Reassigns a slave node to a new master using CLUSTER REPLICATE command.
    """
    try:
        # Find the slave node's address
        slave_address = None
        for pareNode in pareNodes:
            nodeIP = pareNode[0][0]
            portNumber = pareNode[1][0]
            if pareNode[4] and pingredisNode(nodeIP, portNumber):
                # Query cluster nodes to find the slave's address
                cluster_cmd = f"{redisConnectCmd(nodeIP, portNumber, 'CLUSTER NODES')}"
                status, output = subprocess.getstatusoutput(cluster_cmd)
                
                if status == 0:
                    for line in output.strip().split('\n'):
                        parts = line.split()
                        if len(parts) >= 2 and parts[0] == slaveNodeId:
                            slave_address = parts[1].split('@')[0]
                            break
                break
        
        if not slave_address:
            return HTMLResponse(content="""
            <div class="error-box">
                <p>Could not find the slave node in the cluster.</p>
            </div>
            """)
        
        # Parse slave address
        slave_ip, slave_port = slave_address.split(':')
        
        # Check if the slave node is running
        if not pingredisNode(slave_ip, slave_port):
            return HTMLResponse(content=f"""
            <div class="error-box">
                <p>The slave node {slave_address} is not responding. Please ensure it's running.</p>
            </div>
            """)
        
        # Execute CLUSTER REPLICATE command on the slave node
        replicate_cmd = f"{redisConnectCmd(slave_ip, slave_port, f'CLUSTER REPLICATE {newMasterId}')}"
        status, output = subprocess.getstatusoutput(replicate_cmd)
        
        if status != 0 or "OK" not in output.upper():
            return HTMLResponse(content=f"""
            <div class="error-box">
                <h4>Failed to Reassign Slave</h4>
                <p>The CLUSTER REPLICATE command failed.</p>
                <pre>{output}</pre>
            </div>
            """)
        
        # Verify the reassignment by checking the new master
        # Wait a moment for the change to propagate
        import time
        time.sleep(0.5)
        
        # Get the new master's address for display
        new_master_address = "Unknown"
        for pareNode in pareNodes:
            nodeIP = pareNode[0][0]
            portNumber = pareNode[1][0]
            if pareNode[4] and pingredisNode(nodeIP, portNumber):
                cluster_cmd = f"{redisConnectCmd(nodeIP, portNumber, 'CLUSTER NODES')}"
                status, output = subprocess.getstatusoutput(cluster_cmd)
                if status == 0:
                    for line in output.strip().split('\n'):
                        parts = line.split()
                        if len(parts) >= 2 and parts[0] == newMasterId:
                            new_master_address = parts[1].split('@')[0]
                            break
                break
        
        return HTMLResponse(content=f"""
        <div class="success-box">
            <h4>✓ Slave Reassigned Successfully</h4>
            <p>Slave node <strong>{slave_address}</strong> is now replicating from master <strong>{new_master_address}</strong>.</p>
            <p style="font-size: 0.9em; color: #666; margin-top: 10px;">
                Note: It may take a few moments for the replication to synchronize fully.
            </p>
        </div>
        """)
        
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        return HTMLResponse(content=f"""
        <div class="error-box">
            <h4>Error Reassigning Slave</h4>
            <p>An unexpected error occurred: {str(e)}</p>
            <pre style="font-size: 12px;">{trace}</pre>
        </div>
        """)


### upgrade progress
## first step, download redis release package
@app.get("/maintain/download-redis/", response_class=HTMLResponse)
async def maintain_download_redis(redis_filename: str = Query(..., title="Redis Filename", description="The exact filename of the Redis release to download (e.g., redis-7.2.4.tar.gz)")):
    """
    Endpoint to download a specific Redis version package.
    Calls the download_redis_version_wv function.
    """
    try:
        # Call the function from pareFuncWeb.py
        result_html = download_redis_version_wv(redis_filename)
        # The function already returns HTML, so wrap it in HTMLResponse
        return HTMLResponse(content=result_html)
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        # Return an error message in the standard HTML format
        error_html = f"""
        <div class="error-message">
            <p>An unexpected error occurred while trying to initiate the download:</p>
            <pre>{str(e)}\n{trace}</pre>
        </div>
        """
        return HTMLResponse(content=error_html, status_code=500)


from fastapi import File, UploadFile

@app.post("/maintain/upload-redis/", response_class=HTMLResponse)
async def maintain_upload_redis(upload_file: UploadFile = File(...)):
    """
    Endpoint to upload a Redis release tarball.
    """
    try:
        # Read file content
        file_content = await upload_file.read()

        # Get filename
        filename = upload_file.filename

        # Use the upload function from pareFuncWeb.py
        result_html = upload_redis_version_wv(file_content, filename)

        return HTMLResponse(content=result_html)
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        error_html = f"""
        <div class="error-message">
            <h4>Upload Error</h4>
            <p>An error occurred while processing your upload:</p>
            <p>{str(e)}</p>
            <pre style="font-size: 12px;">{trace}</pre>
        </div>
        """
        return HTMLResponse(content=error_html, status_code=500)


@app.get("/maintain/extract-compile-redis/", response_class=HTMLResponse)
async def maintain_extract_compile_redis(redis_tarfile: str = Query(..., title="Redis Tarfile", description="The filename of the Redis tarball to extract and compile (e.g., redis-7.2.4.tar.gz)")):
    """
    Endpoint to extract and compile a Redis release package.
    Calls the extract_compile_redis_wv function.
    """
    try:
        # Call the function from pareFuncWeb.py
        result_html = extract_compile_redis_wv(redis_tarfile)
        # Return the HTML response
        return HTMLResponse(content=result_html)
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        # Return an error message in the standard HTML format
        error_html = f"""
        <div class="error-message">
            <h4>Processing Error</h4>
            <p>An unexpected error occurred while trying to extract and compile Redis:</p>
            <pre style="font-size: 12px;">{str(e)}\n{trace}</pre>
        </div>
        """
        return HTMLResponse(content=error_html, status_code=500)

@app.get("/maintain/copy-redis-binaries/", response_class=HTMLResponse)
async def maintain_copy_redis_binaries(redis_version: str = Query(..., title="Redis Version", description="The version of Redis to copy (e.g., 7.2.4)")):
    """
    Endpoint to copy newly compiled Redis binaries to all nodes in the cluster.
    Calls the redisNewBinaryCopier_wv function.
    """
    try:
        # Call the function from pareFuncWeb.py
        result_html = redisNewBinaryCopier_wv(redis_version)
        # Return the HTML response
        return HTMLResponse(content=result_html)
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        # Return an error message in the standard HTML format
        error_html = f"""
        <div class="error-message">
            <h4>Processing Error</h4>
            <p>An unexpected error occurred while trying to copy Redis binary:</p>
            <pre style="font-size: 12px;">{str(e)}\n{trace}</pre>
        </div>
        """
        return HTMLResponse(content=error_html, status_code=500)

@app.get("/maintain/restart-slaves/", response_class=HTMLResponse)
async def maintain_restart_slaves(wait_seconds: int = 30, redis_version: str = None, confirmed: bool = False):
    """
    Endpoint to restart all slave nodes with a specified delay between restarts.
    If redis_version is provided, updates the nodes to use that version.
    """
    try:
        if not confirmed:
            # Return confirmation dialog
            return HTMLResponse(content=f"""
            <div class="confirmation-needed">
                <h4>Confirm Restart of All Slave Nodes</h4>
                <p>You are about to restart <strong>all slave nodes</strong> in your Redis cluster.</p>
                <p>Wait time between restarts: <strong>{wait_seconds} seconds</strong></p>
                {f"<p>Update to Redis version: <strong>{redis_version}</strong></p>" if redis_version else ""}
                <p>This operation may cause temporary unavailability for replicated data.</p>
                <div class="button-container">
                    <button class="confirm-btn" onclick="confirmRestartSlaves({wait_seconds}, '{redis_version or ''}')">Confirm Restart</button>
                    <button class="cancel-btn" onclick="cancelRestartSlaves()">Cancel</button>
                </div>
            </div>
            """)

        # If confirmed, call the function to restart slave nodes
        result = restartAllSlaves_wv(wait_seconds, redis_version)
        return HTMLResponse(content=result)

    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        error_html = f"""
        <div class="error-message">
            <h4>Error Restarting Slave Nodes</h4>
            <p>An unexpected error occurred:</p>
            <pre style="font-size: 12px;">{str(e)}\n{trace}</pre>
        </div>
        """
        return HTMLResponse(content=error_html)


@app.get("/maintain/verify-redis-binary/")
async def verify_redis_binary(redis_version: str):
    """Check if the Redis binary exists for the specified version."""
    binary_path = f"{redisBinaryBase}redis-{redis_version}/src/redis-server"
    exists = os.path.isfile(binary_path)
    return {"exists": exists, "path": binary_path}


@app.get("/maintain/update-redis-config/", response_class=HTMLResponse)
async def update_redis_config(redis_version: str):
    """
    Endpoint to update Redis version in configuration files.
    """
    try:
        result = update_redis_config_wv(redis_version)
        return HTMLResponse(content=result)
    except Exception as e:
        return HTMLResponse(content=f'<div class="error-message"><h4>Error</h4><p>{str(e)}</p></div>')


@app.get("/maintain/get-redis-version/", response_class=HTMLResponse)
async def get_redis_version():
    """
    Get current Redis version from configuration.
    """
    try:
        from pareConfig import redisVersion
        return HTMLResponse(content=redisVersion)
    except Exception as e:
        return HTMLResponse(content=f"Error: {str(e)}")


@app.get("/maintain/redis-version-control/", response_class=HTMLResponse)
async def redis_version_control():
    """
    Endpoint for Redis version control functionality.
    Shows current Redis versions across all nodes and provides controls.
    """
    try:
        from pareFuncWeb import redisNodesVersionControl_wv
        version_html = redisNodesVersionControl_wv()
        return HTMLResponse(content=version_html)
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        return HTMLResponse(
            content=f"""
            <div class="error-message">
                <h4>Error</h4>
                <p>Failed to retrieve Redis version information: {str(e)}</p>
                <pre>{trace}</pre>
            </div>
            """
        )


# #############################################
# Maker Section - Create Redis Cluster
# #############################################

@app.get("/maker", response_class=HTMLResponse)
async def maker():
    """
    Displays the Redis Cluster Maker UI for creating a new cluster.
    """
    # Ensure we have the latest node list
    import importlib
    importlib.reload(sys.modules['pareNodeList'])
    from pareNodeList import pareNodes as fresh_pareNodes

    # Update the global pareNodes
    global pareNodes
    pareNodes = fresh_pareNodes

    # Count active nodes
    active_nodes = [node for node in pareNodes if node[4]]
    total_nodes = len(active_nodes)
    
    # Calculate max replicas possible
    max_replicas = (total_nodes // 3) - 1 if total_nodes >= 3 else 0
    
    # Build replication options
    replication_options = ""
    for i in range(max(0, max_replicas + 1)):
        required = 3 * (1 + i)
        disabled = "disabled" if total_nodes < required else ""
        if i == 0:
            label = f"0 replicas (no redundancy) - requires 3 nodes"
        elif i == 1:
            label = f"1 replica (recommended) - requires 6 nodes"
        else:
            label = f"{i} replicas - requires {required} nodes"
        selected = "selected" if i == 1 and total_nodes >= 6 else ""
        replication_options += f'<option value="{i}" {disabled} {selected}>{label}</option>'
    
    # If no valid options, add a placeholder
    if not replication_options:
        replication_options = '<option value="" disabled selected>Not enough nodes (minimum 3 required)</option>'

    # Check if cluster already exists
    cluster_exists = os.path.isfile('paredicma.done')
    cluster_status_class = "warning" if cluster_exists else "info"
    cluster_status_icon = "⚠️" if cluster_exists else "ℹ️"
    cluster_status_msg = "A cluster already exists. Remove 'paredicma.done' to recreate." if cluster_exists else "No cluster exists. Ready to create a new cluster."
    create_btn_disabled = "disabled" if cluster_exists else ""

    # Get available Redis versions
    from pareFuncWeb import get_available_redis_versions_wv
    versions_info = get_available_redis_versions_wv()
    compiled_versions = versions_info.get('compiled', [])
    tarball_versions = versions_info.get('tarballs', [])
    current_version = versions_info.get('current', redisVersion)
    
    # Build version options for the dropdown
    version_options = f'<option value="{current_version}" selected>{current_version} (configured)</option>'
    
    # Add compiled versions (excluding current)
    for v in compiled_versions:
        if v != current_version:
            version_options += f'<option value="{v}">{v} (compiled)</option>'
    
    # Add tarball versions that aren't compiled yet
    for v in tarball_versions:
        if v not in compiled_versions and v != current_version:
            version_options += f'<option value="{v}">{v} (needs compilation)</option>'

    # Generate the HTML content for the maker page
    html_content = f"""
    {css_style}
    <html>
    <head>
        <title>Redis Cluster Maker - {projectName}</title>
        <style>
            .status-box {{
                padding: 15px;
                margin: 15px 0;
                border-radius: 5px;
                border-left: 4px solid;
            }}
            .status-box.info {{
                background-color: rgba(23, 162, 184, 0.1);
                border-color: #17a2b8;
            }}
            .status-box.warning {{
                background-color: rgba(255, 193, 7, 0.1);
                border-color: #ffc107;
            }}
            .status-box.success {{
                background-color: rgba(40, 167, 69, 0.1);
                border-color: #28a745;
            }}
            .status-box.error {{
                background-color: rgba(220, 53, 69, 0.1);
                border-color: #dc3545;
            }}
            .config-table {{
                width: 100%;
                margin: 10px 0;
            }}
            .config-table td {{
                padding: 8px;
                border-bottom: 1px solid #eee;
            }}
            .config-table td:first-child {{
                font-weight: bold;
                width: 200px;
            }}
            .step-indicator {{
                padding: 10px 15px;
                margin: 5px 0;
                border-left: 4px solid #6c757d;
                background-color: rgba(108, 117, 125, 0.05);
            }}
            .step-indicator.success {{
                border-color: #28a745;
                background-color: rgba(40, 167, 69, 0.1);
            }}
            .step-indicator.error {{
                border-color: #dc3545;
                background-color: rgba(220, 53, 69, 0.1);
            }}
            .step-indicator.active {{
                border-color: #17a2b8;
                background-color: rgba(23, 162, 184, 0.1);
            }}
            .maker-button {{
                padding: 10px 20px;
                color: #ffffff;
                border: none;
                border-radius: 5px;
                cursor: pointer;
                margin: 5px;
                background-color: #28a745;
            }}
            .maker-button:hover {{
                background-color: #218838;
            }}
            .maker-button:disabled {{
                background-color: #6c757d;
                cursor: not-allowed;
            }}
            .maker-button.secondary {{
                background-color: #6c757d;
            }}
            .maker-button.secondary:hover {{
                background-color: #5a6268;
            }}
            .preview-table {{
                width: 100%;
                border-collapse: collapse;
                margin: 10px 0;
            }}
            .preview-table th, .preview-table td {{
                padding: 8px;
                border: 1px solid #ddd;
                text-align: left;
            }}
            .preview-table th {{
                background-color: #f8f9fa;
            }}
            @media (prefers-color-scheme: dark) {{
                .status-box.info {{
                    background-color: rgba(23, 162, 184, 0.2);
                }}
                .status-box.warning {{
                    background-color: rgba(255, 193, 7, 0.2);
                }}
                .status-box.success {{
                    background-color: rgba(40, 167, 69, 0.2);
                }}
                .status-box.error {{
                    background-color: rgba(220, 53, 69, 0.2);
                }}
                .preview-table th {{
                    background-color: #333;
                }}
                .preview-table th, .preview-table td {{
                    border-color: #444;
                }}
            }}
        </style>
    </head>
    <body>
    <h1 class="maintenance-title">Redis Cluster Maker - {projectName}</h1>
    <div class="nav-buttons">
        <a href="/monitor" class="monitor-nav">Go to Monitor</a>
        <a href="/manager" class="manager-nav">Go to Manager</a>
        <a href="/maintain" class="maintenance-nav">Go to Maintenance</a>
    </div>
    <hr>

    <!-- Cluster Status -->
    <div class="status-box {cluster_status_class}">
        <strong>{cluster_status_icon} Cluster Status:</strong> {cluster_status_msg}
    </div>

    <button class="collapsible">0 - Download/Upload Redis Package</button>
    <div class="content">
        <h3>Choose a Redis tarball from local machine or download from redis.io</h3>
        <div style="display: flex; align-items: center; gap: 15px; margin-bottom: 15px;">
            <form id="maker-upload-redis-form" enctype="multipart/form-data" style="margin: 0; display: inline-block;">
                <button class="maker-button secondary" type="button" onclick="document.getElementById('maker_redis_file').click()">Upload local file</button>
                <input type="file" id="maker_redis_file" name="upload_file" accept=".tar.gz" required style="display: none;" onchange="makerUploadRedisPackage()">
            </form>
            <span>OR</span>
            <form id="maker-download-redis-form" onsubmit="makerDownloadRedisVersion(event)" style="margin: 0; display: inline-flex; align-items: center; gap: 10px;">
                <button id="maker-download-redis-button" class="maker-button secondary" type="submit">Download from redis.io</button>
                <input type="text" id="maker_redis_filename" name="redis_filename" required placeholder="e.g., redis-7.2.4.tar.gz" style="width:180px; padding: 8px;">
            </form>
        </div>
        <span id="maker-filename-validation-msg" style="color: red; font-size: 0.9em; display: block; margin-bottom: 10px;"></span>
        
        <!-- Extract and compile section (hidden by default) -->
        <div id="maker-extract-compile-container" style="display: none; margin-top: 15px;">
            <button id="maker-extract-compile-button" class="maker-button" onclick="makerExtractCompileRedis()">Extract & Compile Package</button>
            <span id="maker-selected-tarfile-display" style="margin-left: 10px; font-style: italic;"></span>
        </div>
        
        <!-- Progress bar container -->
        <div id="maker-progress-container" style="display: none; margin-top: 15px;">
            <div style="margin-bottom: 5px;">Extracting and compiling Redis package... (this may take a few minutes)</div>
            <div class="progress-bar-container" style="width: 100%; background-color: #e0e0e0; border-radius: 5px; height: 20px;">
                <div id="maker-progress-bar" class="progress-bar" style="width: 0%; height: 100%; background-color: #28a745; border-radius: 5px; transition: width 0.5s;"></div>
            </div>
            <div id="maker-progress-status" style="margin-top: 5px; font-size: 0.9em;">Starting extraction...</div>
        </div>
        
        <!-- Results will appear here -->
        <div id="maker-download-result" style="margin-top: 15px;"></div>
        
        <!-- Deploy to remote servers section -->
        <div id="maker-deploy-container" style="display: none; margin-top: 20px; padding-top: 15px; border-top: 1px solid #ddd;">
            <h3>Deploy Redis Binary to Remote Servers</h3>
            <p>Compile Redis on remote servers with different CPU architectures:</p>
            <div style="display: flex; align-items: center; gap: 15px;">
                <button id="maker-deploy-button" class="maker-button" onclick="makerDeployToRemote()">Deploy to Remote Servers</button>
                <input type="text" id="maker_deploy_version" placeholder="e.g., 7.2.4" style="width: 100px; padding: 8px;">
            </div>
            <div id="maker-deploy-result" style="margin-top: 15px;"></div>
        </div>
    </div>

    <button class="collapsible">1 - Check Cluster Status</button>
    <div class="content">
        <p>Check if a Redis cluster already exists and view current status.</p>
        <div class="button-container">
            <button class="maker-button secondary" onclick="checkClusterStatus()">Check Status</button>
        </div>
        <div id="cluster-status-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">2 - Validate Nodes</button>
    <div class="content">
        <p>Validate all configured nodes before cluster creation. Checks server reachability and configuration.</p>
        <div class="button-container">
            <button class="maker-button secondary" onclick="validateNodes()">Validate All Nodes</button>
        </div>
        <div id="validate-nodes-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">3 - Preview Cluster Configuration</button>
    <div class="content">
        <p>Preview how the cluster will be configured with your current settings.</p>
        <div style="margin-bottom: 15px;">
            <label for="preview_replication">Replication Factor:</label>
            <select id="preview_replication" name="preview_replication" style="padding: 8px; margin-left: 10px;">
                {replication_options}
            </select>
        </div>
        <div class="button-container">
            <button class="maker-button secondary" onclick="previewCluster()">Preview Configuration</button>
        </div>
        <div id="preview-cluster-result" style="margin-top: 10px;"></div>
    </div>

    <button class="collapsible">4 - Create Redis Cluster</button>
    <div class="content">
        <h3>Create New Redis Cluster</h3>
        
        <div class="status-box info">
            <strong>Current Configuration:</strong>
            <table class="config-table">
                <tr><td>Configured Redis Version:</td><td>{redisVersion}</td></tr>
                <tr><td>Cluster Mode:</td><td>{redisCluster}</td></tr>
                <tr><td>Authentication:</td><td>{'Enabled' if redisPwdAuthentication == 'on' else 'Disabled'}</td></tr>
                <tr><td>Auto Compile:</td><td>{'Yes' if doCompile else 'No'}</td></tr>
                <tr><td>Auto Start Nodes:</td><td>{'Yes' if doStartNodes else 'No'}</td></tr>
                <tr><td>Active Nodes:</td><td>{total_nodes}</td></tr>
            </table>
        </div>

        <form id="create-cluster-form" onsubmit="createCluster(event)">
            <div style="margin-bottom: 15px;">
                <label for="redis_version_select" style="display: block; margin-bottom: 5px;"><strong>Redis Version:</strong></label>
                <select id="redis_version_select" name="redis_version" style="padding: 8px; width: 300px;">
                    {version_options}
                </select>
                <p style="font-size: 0.9em; color: #6c757d; margin-top: 5px;">
                    Select the Redis version to use. Use section "0 - Download/Upload Redis Package" to add more versions.
                </p>
            </div>
            
            <div style="margin-bottom: 15px;">
                <label for="replication_number" style="display: block; margin-bottom: 5px;"><strong>Replication Factor:</strong></label>
                <select id="replication_number" name="replication_number" style="padding: 8px; width: 300px;">
                    {replication_options}
                </select>
                <p style="font-size: 0.9em; color: #6c757d; margin-top: 5px;">
                    Active nodes available: {total_nodes}
                </p>
            </div>
            
            <div style="margin-bottom: 15px;">
                <label>
                    <input type="checkbox" id="skip_compile" name="skip_compile" {'checked' if not doCompile else ''}>
                    Skip compilation (use existing binaries)
                </label>
            </div>
            
            <div style="margin-bottom: 15px;">
                <label>
                    <input type="checkbox" id="skip_start" name="skip_start">
                    Skip starting nodes (assume already running)
                </label>
            </div>

            <div class="button-container" style="margin-top: 20px;">
                <button type="submit" class="maker-button" {create_btn_disabled}>
                    🚀 Create Cluster
                </button>
            </div>
        </form>
        
        <div id="create-cluster-result" style="margin-top: 15px;"></div>
    </div>

    <script>
        const collapsibles = document.querySelectorAll(".collapsible");
        collapsibles.forEach(button => {{
            button.addEventListener("click", function() {{
                this.classList.toggle("active");
                const content = this.nextElementSibling;
                if (content.style.display === "block") {{
                    content.style.display = "none";
                }} else {{
                    content.style.display = "block";
                }}
            }});
        }});

        function checkClusterStatus() {{
            document.getElementById('cluster-status-result').innerHTML = "<p>Checking cluster status...</p>";
            fetch('/maker/check-status/')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('cluster-status-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('cluster-status-result').innerHTML = 
                        "<p style='color: red;'>Error checking status: " + error + "</p>";
                }});
        }}

        function validateNodes() {{
            document.getElementById('validate-nodes-result').innerHTML = "<p>Validating nodes...</p>";
            fetch('/maker/validate-nodes/')
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('validate-nodes-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('validate-nodes-result').innerHTML = 
                        "<p style='color: red;'>Error validating nodes: " + error + "</p>";
                }});
        }}

        function previewCluster() {{
            const replication = document.getElementById('preview_replication').value;
            document.getElementById('preview-cluster-result').innerHTML = "<p>Generating preview...</p>";
            fetch('/maker/preview/?replication_number=' + replication)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('preview-cluster-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('preview-cluster-result').innerHTML = 
                        "<p style='color: red;'>Error generating preview: " + error + "</p>";
                }});
        }}

        function createCluster(event) {{
            event.preventDefault();
            
            const form = document.getElementById('create-cluster-form');
            const redisVersion = document.getElementById('redis_version_select').value;
            const replication = document.getElementById('replication_number').value;
            const skipCompile = document.getElementById('skip_compile').checked;
            const skipStart = document.getElementById('skip_start').checked;
            
            // Confirm before creating
            showConfirmModal(
                'Create Redis Cluster?',
                '🚀',
                `<p>You are about to create a Redis cluster with:</p>
                <ul style="margin-top: 10px;">
                    <li><strong>Redis Version:</strong> ${{redisVersion}}</li>
                    <li><strong>Replication Factor:</strong> ${{replication}}</li>
                </ul>
                <p style="margin-top: 15px; color: #666; font-size: 0.9em;"><strong>Note:</strong> This process may take several minutes.</p>`,
                'Create Cluster',
                function() {{ executeCreateCluster(redisVersion, replication, skipCompile, skipStart); }},
                false
            );
        }}
        
        function executeCreateCluster(redisVersion, replication, skipCompile, skipStart) {{
            document.getElementById('create-cluster-result').innerHTML = `
                <div class="status-box info">
                    <h4>🔄 Creating Cluster with Redis ${{redisVersion}}...</h4>
                    <p>This process may take several minutes. Please wait...</p>
                    <div class="progress-bar-container" style="margin-top: 10px;">
                        <div class="progress-bar" style="width: 0%; animation: progress 120s linear forwards;"></div>
                    </div>
                </div>
                <style>
                    @keyframes progress {{
                        from {{ width: 0%; }}
                        to {{ width: 95%; }}
                    }}
                </style>
            `;
            
            const params = new URLSearchParams({{
                redis_version: redisVersion,
                replication_number: replication,
                skip_compile: skipCompile,
                skip_start: skipStart
            }});
            
            fetch('/maker/create-cluster/?' + params)
                .then(response => response.text())
                .then(data => {{
                    document.getElementById('create-cluster-result').innerHTML = data;
                }})
                .catch(error => {{
                    document.getElementById('create-cluster-result').innerHTML = 
                        "<div class='status-box error'><p>Error creating cluster: " + error + "</p></div>";
                }});
        }}

        // ===== Download/Upload Redis Package Functions =====
        
        let makerSelectedTarfile = '';
        
        function makerValidateRedisFilename() {{
            const input = document.getElementById('maker_redis_filename');
            const filename = input.value.trim();
            const isValid = filename.startsWith('redis-') && filename.endsWith('.tar.gz');
            const validationMsg = document.getElementById('maker-filename-validation-msg');
            
            if (isValid) {{
                validationMsg.textContent = '';
            }} else if (filename !== '') {{
                validationMsg.textContent = 'Must start with "redis-" and end with ".tar.gz"';
            }} else {{
                validationMsg.textContent = '';
            }}
            return isValid;
        }}
        
        document.getElementById('maker_redis_filename').addEventListener('input', makerValidateRedisFilename);
        
        function makerDownloadRedisVersion(event) {{
            event.preventDefault();
            
            if (!makerValidateRedisFilename()) {{
                document.getElementById('maker-download-result').innerHTML = 
                    '<div class="status-box error"><p>Invalid filename format. Must start with "redis-" and end with ".tar.gz"</p></div>';
                return;
            }}
            
            const filename = document.getElementById('maker_redis_filename').value.trim();
            document.getElementById('maker-download-result').innerHTML = '<p>Downloading ' + filename + '...</p>';
            
            fetch('/maintain/download-redis/?redis_filename=' + encodeURIComponent(filename))
                .then(response => response.text())
                .then(html => {{
                    document.getElementById('maker-download-result').innerHTML = html;
                    
                    if (html.includes('Successfully downloaded') || html.includes('already exists')) {{
                        makerSelectedTarfile = filename;
                        document.getElementById('maker-extract-compile-container').style.display = 'block';
                        document.getElementById('maker-selected-tarfile-display').textContent = filename;
                        
                        // Extract version and set deploy field
                        const version = filename.replace('redis-', '').replace('.tar.gz', '');
                        document.getElementById('maker_deploy_version').value = version;
                    }}
                }})
                .catch(error => {{
                    document.getElementById('maker-download-result').innerHTML = 
                        '<div class="status-box error"><p>Error: ' + error.message + '</p></div>';
                }});
        }}
        
        function makerUploadRedisPackage() {{
            const fileInput = document.getElementById('maker_redis_file');
            const file = fileInput.files[0];
            
            if (!file) return;
            
            if (!file.name.startsWith('redis-') || !file.name.endsWith('.tar.gz')) {{
                document.getElementById('maker-download-result').innerHTML = 
                    '<div class="status-box error"><p>Invalid filename. Must start with "redis-" and end with ".tar.gz"</p></div>';
                return;
            }}
            
            document.getElementById('maker-download-result').innerHTML = '<p>Uploading ' + file.name + '...</p>';
            
            const formData = new FormData();
            formData.append('upload_file', file);
            
            fetch('/maintain/upload-redis/', {{
                method: 'POST',
                body: formData
            }})
            .then(response => response.text())
            .then(html => {{
                document.getElementById('maker-download-result').innerHTML = html;
                
                if (html.includes('successfully') || html.includes('Success')) {{
                    makerSelectedTarfile = file.name;
                    document.getElementById('maker-extract-compile-container').style.display = 'block';
                    document.getElementById('maker-selected-tarfile-display').textContent = file.name;
                    
                    // Extract version and set deploy field
                    const version = file.name.replace('redis-', '').replace('.tar.gz', '');
                    document.getElementById('maker_deploy_version').value = version;
                }}
            }})
            .catch(error => {{
                document.getElementById('maker-download-result').innerHTML = 
                    '<div class="status-box error"><p>Upload error: ' + error.message + '</p></div>';
            }});
        }}
        
        function makerExtractCompileRedis() {{
            if (!makerSelectedTarfile) {{
                document.getElementById('maker-download-result').innerHTML = 
                    '<div class="status-box error"><p>No Redis package selected.</p></div>';
                return;
            }}
            
            // Show progress bar
            document.getElementById('maker-progress-container').style.display = 'block';
            document.getElementById('maker-progress-bar').style.width = '0%';
            document.getElementById('maker-progress-status').textContent = 'Extracting...';
            
            // Simulate progress
            let progress = 0;
            const progressInterval = setInterval(() => {{
                if (progress < 90) {{
                    progress += Math.random() * 10;
                    document.getElementById('maker-progress-bar').style.width = progress + '%';
                    if (progress < 30) {{
                        document.getElementById('maker-progress-status').textContent = 'Extracting...';
                    }} else if (progress < 80) {{
                        document.getElementById('maker-progress-status').textContent = 'Compiling Redis... (this takes a while)';
                    }} else {{
                        document.getElementById('maker-progress-status').textContent = 'Finalizing...';
                    }}
                }}
            }}, 2000);
            
            fetch('/maintain/extract-compile-redis/?redis_tarfile=' + encodeURIComponent(makerSelectedTarfile))
                .then(response => response.text())
                .then(html => {{
                    clearInterval(progressInterval);
                    document.getElementById('maker-progress-bar').style.width = '100%';
                    document.getElementById('maker-progress-status').textContent = 'Complete!';
                    
                    setTimeout(() => {{
                        document.getElementById('maker-progress-container').style.display = 'none';
                        document.getElementById('maker-download-result').innerHTML = html;
                        
                        if (html.includes('successfully') || html.includes('Success') || html.includes('compiled')) {{
                            document.getElementById('maker-deploy-container').style.display = 'block';
                        }}
                    }}, 500);
                }})
                .catch(error => {{
                    clearInterval(progressInterval);
                    document.getElementById('maker-progress-container').style.display = 'none';
                    document.getElementById('maker-download-result').innerHTML = 
                        '<div class="status-box error"><p>Compilation error: ' + error.message + '</p></div>';
                }});
        }}
        
        function makerDeployToRemote() {{
            const version = document.getElementById('maker_deploy_version').value.trim();
            
            if (!version || !/^\\d+\\.\\d+\\.\\d+$/.test(version)) {{
                document.getElementById('maker-deploy-result').innerHTML = 
                    '<div class="status-box error"><p>Please enter a valid version (e.g., 7.2.4)</p></div>';
                return;
            }}
            
            document.getElementById('maker-deploy-result').innerHTML = 
                '<p>Deploying Redis ' + version + ' to remote servers (compiling on each server)...</p>';
            
            fetch('/maintain/copy-redis-binaries/?redis_version=' + encodeURIComponent(version))
                .then(response => response.text())
                .then(html => {{
                    document.getElementById('maker-deploy-result').innerHTML = html;
                }})
                .catch(error => {{
                    document.getElementById('maker-deploy-result').innerHTML = 
                        '<div class="status-box error"><p>Deploy error: ' + error.message + '</p></div>';
                }});
        }}

        // Generic confirmation modal
        let pendingConfirmCallback = null;

        function showConfirmModal(title, icon, content, confirmBtnText, confirmCallback, isDanger = false) {{
            pendingConfirmCallback = confirmCallback;

            const modal = document.getElementById('confirm-modal');
            const header = document.getElementById('confirm-modal-header');
            const modalIcon = document.getElementById('confirm-modal-icon');
            const modalTitle = document.getElementById('confirm-modal-title');
            const bodyContent = document.getElementById('confirm-modal-body');
            const confirmBtn = document.getElementById('confirm-modal-btn');

            modalIcon.textContent = icon;
            modalTitle.textContent = title;
            bodyContent.innerHTML = content;
            confirmBtn.textContent = confirmBtnText;

            if (isDanger) {{
                header.className = 'modal-header danger';
                confirmBtn.className = 'modal-btn modal-btn-confirm danger';
            }} else {{
                header.className = 'modal-header warning';
                confirmBtn.className = 'modal-btn modal-btn-confirm';
            }}

            modal.classList.add('active');
            document.body.style.overflow = 'hidden';
        }}

        function closeConfirmModal() {{
            const modal = document.getElementById('confirm-modal');
            modal.classList.remove('active');
            document.body.style.overflow = '';
            pendingConfirmCallback = null;
        }}

        function executeConfirmAction() {{
            if (pendingConfirmCallback) {{
                const callback = pendingConfirmCallback;
                closeConfirmModal();
                callback();
            }}
        }}

        // Attach confirm modal event handlers
        (function initConfirmModal() {{
            const confirmModalBtn = document.getElementById('confirm-modal-btn');
            if (confirmModalBtn) {{
                confirmModalBtn.addEventListener('click', executeConfirmAction);
            }}

            const confirmModal = document.getElementById('confirm-modal');
            if (confirmModal) {{
                confirmModal.addEventListener('click', function(e) {{
                    if (e.target === this) {{
                        closeConfirmModal();
                    }}
                }});
            }}
        }})();

        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape') {{
                const confirmModal = document.getElementById('confirm-modal');
                if (confirmModal && confirmModal.classList.contains('active')) {{
                    closeConfirmModal();
                }}
            }}
        }});
    </script>

    <!-- Generic Confirmation Modal -->
    <div id="confirm-modal" class="modal-overlay">
        <div class="modal-dialog">
            <div id="confirm-modal-header" class="modal-header">
                <span id="confirm-modal-icon" class="modal-icon">ℹ️</span>
                <h3 id="confirm-modal-title">Confirm Action</h3>
            </div>
            <div class="modal-body">
                <div id="confirm-modal-body"></div>
            </div>
            <div class="modal-footer">
                <button class="modal-btn modal-btn-cancel" onclick="closeConfirmModal()">Cancel</button>
                <button id="confirm-modal-btn" class="modal-btn modal-btn-confirm">Confirm</button>
            </div>
        </div>
    </div>

    </body>
    </html>
    """
    return HTMLResponse(content=html_content)


@app.get("/maker/check-status/", response_class=HTMLResponse)
async def maker_check_status():
    """
    Check if a Redis cluster already exists.
    """
    try:
        from pareFuncWeb import check_cluster_exists_wv
        result = check_cluster_exists_wv()
        return HTMLResponse(content=result['html'])
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        return HTMLResponse(
            content=f"""
            <div class="error-message">
                <h4>Error</h4>
                <p>Failed to check cluster status: {str(e)}</p>
                <pre>{trace}</pre>
            </div>
            """
        )


@app.get("/maker/validate-nodes/", response_class=HTMLResponse)
async def maker_validate_nodes():
    """
    Validate all nodes before cluster creation.
    """
    try:
        from pareFuncWeb import validate_cluster_nodes_wv
        result = validate_cluster_nodes_wv()
        return HTMLResponse(content=result['html'])
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        return HTMLResponse(
            content=f"""
            <div class="error-message">
                <h4>Error</h4>
                <p>Failed to validate nodes: {str(e)}</p>
                <pre>{trace}</pre>
            </div>
            """
        )


@app.get("/maker/preview/", response_class=HTMLResponse)
async def maker_preview(replication_number: int = 1):
    """
    Preview cluster configuration before creation.
    """
    try:
        from pareFuncWeb import get_cluster_preview_wv
        result = get_cluster_preview_wv(replication_number)
        return HTMLResponse(content=result)
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        return HTMLResponse(
            content=f"""
            <div class="error-message">
                <h4>Error</h4>
                <p>Failed to generate preview: {str(e)}</p>
                <pre>{trace}</pre>
            </div>
            """
        )


@app.get("/maker/create-cluster/", response_class=HTMLResponse)
async def maker_create_cluster(
    redis_version: str = None,
    replication_number: int = 1,
    skip_compile: bool = False,
    skip_start: bool = False
):
    """
    Create the Redis cluster with specified Redis version.
    """
    try:
        from pareFuncWeb import create_cluster_wv
        result = create_cluster_wv(replication_number, skip_compile, skip_start, redis_version)
        return HTMLResponse(content=result)
    except Exception as e:
        import traceback
        trace = traceback.format_exc()
        return HTMLResponse(
            content=f"""
            <div class="error-message">
                <h4>Error</h4>
                <p>Failed to create cluster: {str(e)}</p>
                <pre>{trace}</pre>
            </div>
            """
        )


if __name__ == "__main__":
    import uvicorn
    import os
    port = int(os.environ.get('PARE_WEB_PORT', 8000))
    host = os.environ.get('PARE_SERVER_IP', '0.0.0.0')
    uvicorn.run(app, host=host, port=port)

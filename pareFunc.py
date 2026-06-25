# !/usr/bin/python

import os
import sys
import subprocess
from time import *
from pareConfig import *
from pareNodeList import *
import socket
from string import *
from screenMenu import *
import importlib


def is_local_server(serverIP):
    """
    Comprehensive check if a server IP refers to the local machine.
    
    This function checks multiple conditions to determine if an IP address
    refers to the local server where the application is running:
    1. Direct match with configured pareServerIp
    2. Localhost addresses (127.0.0.1, localhost)
    3. Match with any local network interface IP addresses
    
    Args:
        serverIP: The IP address or hostname to check
        
    Returns:
        True if the IP refers to the local server, False otherwise
    """
    # Check if it matches the configured server IP
    if serverIP == pareServerIp:
        return True
    
    # Check for localhost addresses
    if serverIP in ['127.0.0.1', 'localhost', '::1']:
        return True
    
    # Get all local IP addresses from network interfaces
    try:
        # Get the hostname
        hostname = socket.gethostname()
        
        # Get all IP addresses associated with the hostname
        local_ips = socket.gethostbyname_ex(hostname)[2]
        
        # Also add the result of gethostbyname for the hostname
        local_ips.append(socket.gethostbyname(hostname))
        
        # Check if serverIP matches any local IP
        if serverIP in local_ips:
            return True
            
        # Additional check: try to resolve the serverIP and compare
        try:
            # If serverIP is a hostname, resolve it
            resolved_ip = socket.gethostbyname(serverIP)
            if resolved_ip in local_ips or resolved_ip == pareServerIp:
                return True
        except socket.gaierror:
            # If we can't resolve, continue with other checks
            pass
            
    except Exception as e:
        # If we can't determine local IPs, fall back to pareServerIp check only
        print(f"Warning: Could not determine local IPs: {e}")
        pass
    
    return False


def validIP(IPaddr):
    try:
        socket.inet_aton(IPaddr)
        return True
    except socket.error:
        return False


def is_ssh_available(serverIP):
    if serverIP == pareServerIp:
        return True  # No need for SSH control
    try:
        subprocess.run(
            f"ssh -o PasswordAuthentication=no -o ConnectTimeout=2 {pareOSUser}@{serverIP} exit",
            shell=True,
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return True  # SSH connection succeeded
    except subprocess.CalledProcessError:
        return False  # SSH connection failed


def pingServer (nodeIP):
    try:
        # Use subprocess to execute the ping command
        # -c 1 sets the count of ping packets to 1
        # -W 1 sets the timeout to 1 second
        # The command returns 0 if the server is reachable, else a non-zero value
        subprocess.run(["ping", "-c", "1", "-W", "1", nodeIP], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True  # Server is reachable
    except subprocess.CalledProcessError:
        return False  # Server is not reachable or ping command failed


def pingredisNode(nodeIP, portNumber):
    pingStatus, pingResponse = subprocess.getstatusoutput(redisConnectCmdwithTimeout(nodeIP, portNumber, ' ping '))
    if pingStatus == 0 & pingResponse.find('PONG') > -1:
        return True
    else:
        return False


def getnodeNumbers(serverIP):
    nodenumbers = []
    for index, pareNode in enumerate(pareNodes, start=1):
        if pareNode[0][0] == serverIP:
            nodenumbers.append(index)
    return nodenumbers


def getNodeList():
    """
    Returns a list of active Redis nodes in 'ip:port' format.
    Forces a reload of the pareNodes configuration before returning the list.
    """
    # Force reload the pareNodeList module to get fresh data
    try:
        import importlib
        importlib.reload(sys.modules['pareNodeList'])
        from pareNodeList import pareNodes as fresh_pareNodes

        # Build nodeList from the freshly loaded configuration
        nodeList = []
        for pareNode in fresh_pareNodes:
            if pareNode[4]:  # Check if the node is active
                nodeIP = pareNode[0][0]
                port = pareNode[1][0]
                nodeList.append(f"{nodeIP}:{port}")

        return nodeList
    except Exception as e:
        # If reload fails, fall back to using current pareNodes (better than nothing)
        print(f"Warning: Failed to reload pareNodeList module: {str(e)}")
        nodeList = []
        for pareNode in pareNodes:
            if pareNode[4]:  # Check if the node is active
                nodeIP = pareNode[0][0]
                port = pareNode[1][0]
                nodeList.append(f"{nodeIP}:{port}")
        return nodeList


def getuniqueServers(pareNodes):
    servers = set()
    for pareNode in pareNodes:
        nodeIp = pareNode[0][0]
        if pareNode[4]:  # Check if the node is active
            servers.add(nodeIp)
    uniqueservers = list(servers)
    return uniqueservers


def redisConnectCmd(nodeIP, portNumber, redisCmd, cluster_mode=False):
    redisCliCmd = ''
    cluster_flag = ' -c' if cluster_mode else ''
    if redisPwdAuthentication:
        redisCliCmd = redisBinaryDir + 'src/redis-cli -h ' + nodeIP + ' -p ' + portNumber + cluster_flag + ' --no-auth-warning -a ' + redisPwd + ' ' + redisCmd
    else:
        redisCliCmd = redisBinaryDir + '/src/redis-cli -h ' + nodeIP + ' -p ' + portNumber + cluster_flag + ' ' + redisCmd
    return redisCliCmd


def redisConnectCmdwithTimeout(nodeIP, portNumber, redisCmd):
    redisCliCmd = ''
    if redisPwdAuthentication:
        redisCliCmd = 'timeout 3  ' + redisBinaryDir + 'src/redis-cli -h ' + nodeIP + ' -p ' + portNumber + ' --no-auth-warning -a ' + redisPwd + ' ' + redisCmd
    else:
        redisCliCmd = 'timeout 3  ' + redisBinaryDir + '/src/redis-cli -h ' + nodeIP + ' -p ' + portNumber + ' ' + redisCmd
    return redisCliCmd


def isNodeMaster(nodeIP, nodeNumber, portNumber):
    queryRespond = '  master'
    pingStatus, queryRespond = subprocess.getstatusoutput(
        redisConnectCmd(nodeIP, portNumber, 'info replication | grep role '))
    if queryRespond.find('master') > 0:
        return True
    else:
        return False



def isNodeHasSlave(nodeIP, nodeNumber, portNumber):
    pingStatus, pingResponse = subprocess.getstatusoutput(
        redisConnectCmd(nodeIP, portNumber, ' info replication | grep connected_slaves '))
    if pingStatus == 0 & pingResponse.find(':0') > 0:
        return False
    else:
        return True


def clusterCheck(contactNode):
    myNodeIP = pareNodes[contactNode - 1][0][0]
    myNodePORT = pareNodes[contactNode - 1][1][0]
    clusterString = redisBinaryDir + 'src/redis-cli --cluster check ' + myNodeIP + ':' + myNodePORT + ''
    if redisPwdAuthentication == 'on':
        clusterString += ' -a ' + redisPwd + ' '
    retVal = 'Unknown'
    checkStatus, checkResponse = subprocess.getstatusoutput(clusterString)
    if checkResponse.find('[ERR]') != -1:
        return False
    else:
        return True


def clusterFix(contactNode):
    myNodeIP = pareNodes[contactNode - 1][0][0]
    myNodePORT = pareNodes[contactNode - 1][1][0]
    clusterString = redisBinaryDir + 'src/redis-cli --cluster fix ' + myNodeIP + ':' + myNodePORT
    if redisPwdAuthentication == 'on':
        clusterString += ' -a ' + redisPwd + ' '
    retVal = 'Unknown'
    fixStatus, fixResponse = subprocess.getstatusoutput(clusterString)
    if fixResponse.find('[OK]') != -1:
        return True
    else:
        return False


def showRedisLogFile(nodeIP, nodeNum, portNumber, myLineNum):
    if is_local_server(nodeIP):
        returnCmd, cmdResponse = subprocess.getstatusoutput(
            'tail -' + myLineNum + ' ' + redisLogDir + 'redisN' + nodeNum + '_P' + portNumber + '.log')
        print(bcolors.OKGREEN + cmdResponse + bcolors.ENDC)
        input(bcolors.BOLD + '\n----------------------\nPress Enter to Return Paredicman Menu' + bcolors.ENDC)
    else:
        returnCmd, cmdResponse = subprocess.getstatusoutput(
            'ssh -q -o "StrictHostKeyChecking no"  ' + pareOSUser + '@' + nodeIP + ' -C  "tail -' + myLineNum + ' ' + redisLogDir + 'redisN' + nodeNum + '_P' + portNumber + '.log"')
        print(bcolors.OKGREEN + cmdResponse + bcolors.ENDC)
        input(bcolors.BOLD + '\n----------------------\nPress Enter to Return Paredicman Menu' + bcolors.ENDC)


def clusterSlotBalanceMapper(balanceStrategy, maxSlotBarier):
    nodeNumber = 0
    contactNode = -1
    spResponse = ''
    myNodeInfoList = []
    allSlotNumber = 16386
    if maxSlotBarier == 0:
        maxSlotBarier = 4000
    maxSlotBarier += 1
    for pareNode in pareNodes:
        nodeIP = pareNode[0][0]
        portNumber = pareNode[1][0]
        nodeNumber = nodeNumber + 1
        if pareNode[4]:
            isPing = pingredisNode(nodeIP, portNumber)
            if isPing:
                if contactNode == -1:
                    contactNode = nodeNumber
                # spStatus,spResponse = subprocess.getstatusoutput(redisConnectCmd(nodeIP,portNumber,' CLUSTER NODES |  grep master |  grep myself | grep -v fail'))
                spStatus, spRes = subprocess.getstatusoutput(
                    redisConnectCmd(nodeIP, portNumber, ' CLUSTER NODES |  grep master |  grep myself | grep -v fail'))
                if len(spRes) > 20:
                    spResponse += spRes + '\n'
    # break
    spResponseRaw = spResponse.split('\n')
    # print spResponseRaw
    for spResponseLine in spResponseRaw:
        spResponseArray = spResponseLine.split(' ')
        nodeSlotNumber = 0
        if len(spResponseArray) >= 8 and spResponseArray[7] == 'connected':

            if len(spResponseArray) == 8:
                myNodeInfoList.append([spResponseArray[0], 0])
            # print 'step 1')
            else:
                myIndex = 8
                maxIndexNumber = len(spResponseArray)
                while myIndex <= maxIndexNumber:
                    slotNumber = spResponseArray[myIndex - 1]
                    if slotNumber.find('-') == -1:
                        nodeSlotNumber += 1
                    else:
                        slotRange = slotNumber.split('-')
                        # print ('step 4')
                        nodeSlotNumber = nodeSlotNumber + (int(slotRange[1]) - int(slotRange[0])) + 1
                    myIndex += 1
                myNodeInfoList.append([spResponseArray[0], nodeSlotNumber - 1])

    if balanceStrategy == 'nodeBase':
        movedSlotsNumber = 0
        balanceSlotNumber = 0
        totalNodes = len(myNodeInfoList)
        FloatBalanceSlotNumber = float(allSlotNumber / totalNodes)
        FloatBalanceSlotNumberInt = int(allSlotNumber / totalNodes)
        # print (str(FloatBalanceSlotNumber))
        # print (str(float(FloatBalanceSlotNumberInt)))
        # sleep(3)
        if maxSlotBarier == 4001:
            clusterString = redisBinaryDir + 'src/redis-cli --cluster rebalance ' + pareNodes[contactNode - 1][0][
                0] + ':' + pareNodes[contactNode - 1][1][0]
            if redisPwdAuthentication == 'on':
                clusterString += ' -a ' + redisPwd + ' '
            os.system(clusterString)
        else:

            if FloatBalanceSlotNumber == float(FloatBalanceSlotNumberInt):
                balanceSlotNumber = int(FloatBalanceSlotNumber)
            else:
                balanceSlotNumber = int(FloatBalanceSlotNumber) - 1
            myNodeInfoListIndexer = 0
            processHealth = True
            for myNodeInfo in myNodeInfoList:
                if processHealth:
                    if movedSlotsNumber <= maxSlotBarier:
                        # print ('Step 1:Slot Barier :'+str(maxSlotBarier))
                        # print ('Step 1:balanceSlotNumber :'+str(balanceSlotNumber))
                        if myNodeInfo[1] < balanceSlotNumber:
                            slotDiff = balanceSlotNumber - myNodeInfo[1]
                            stepSize = 1
                            while slotDiff > 0 and movedSlotsNumber <= maxSlotBarier:
                                # print ('Step 3:balanceSlotNumber :'+str(balanceSlotNumber))
                                # if(slotDiff>10 and slotDiff<=100):
                                # stepSize=10
                                if (myNodeInfoList[myNodeInfoListIndexer][1] > balanceSlotNumber and
                                        myNodeInfoList[myNodeInfoListIndexer][0] != myNodeInfo[0]):
                                    if myNodeInfoList[myNodeInfoListIndexer][1] > balanceSlotNumber + 30 and slotDiff > 30:
                                        stepSize = 30
                                    elif (myNodeInfoList[myNodeInfoListIndexer][
                                              1] > balanceSlotNumber + 10 and slotDiff > 10):
                                        stepSize = 10
                                    elif (myNodeInfoList[myNodeInfoListIndexer][
                                              1] > balanceSlotNumber + 5 and slotDiff > 5):
                                        stepSize = 5
                                    else:
                                        stepSize = 1
                                    reshardClusterSilent(contactNode, myNodeInfoList[myNodeInfoListIndexer][0],
                                                         myNodeInfo[0], str(stepSize))
                                    print('FROM Node ID' + myNodeInfoList[myNodeInfoListIndexer][
                                        0] + '\n-> TO Node ID :' + myNodeInfo[0] + '\nMoved Slots :' + str(
                                        stepSize) + bcolors.OKGREEN + ' OK :)' + bcolors.ENDC)
                                    print('TO Node ID :' + str(
                                        myNodeInfo[0]) + '              Slot Diff :' + bcolors.OKBLUE + str(
                                        slotDiff) + bcolors.ENDC)
                                    sleep(3)
                                    if not clusterCheck(contactNode):
                                        print(
                                            bcolors.FAIL + '!!! Warning !!! Cluster Check Fail. I will try to fix It' + bcolors.ENDC)
                                        sleep(10)
                                        if clusterFix(contactNode):
                                            print(bcolors.OKGREEN + ' OK :) I fixed it ;)' + bcolors.ENDC)
                                            sleep(5)
                                        else:
                                            processHealth = False
                                    myNodeInfoList[myNodeInfoListIndexer][1] -= stepSize
                                    myNodeInfo[1] += stepSize
                                    slotDiff -= stepSize
                                    movedSlotsNumber += stepSize
                                if slotDiff <= 10:
                                    stepSize = 1
                                if myNodeInfoListIndexer < len(myNodeInfoList) - 1:
                                    myNodeInfoListIndexer += 1
                                else:
                                    myNodeInfoListIndexer = 0
                        else:
                            print(
                                bcolors.WARNING + 'This node has more (or equal ) slots than  balance slot level :) ' +
                                myNodeInfo[0] + bcolors.ENDC)
                    else:
                        print(
                            bcolors.WARNING + 'You reached "max  move slots" per node barier. If you want to move '
                                              'further, run balancer again. Total Moved Slot Number:  '
                            + str(movedSlotsNumber) + bcolors.ENDC)
                else:
                    print(
                        bcolors.FAIL + '!!! ERROR !!! I tried to fix Slots, however it does NOT work. The process '
                                       'was terminated !!! ' + bcolors.ENDC)

        clusterInfo(pareNodes[contactNode - 1][0][0], pareNodes[contactNode - 1][1][0])
        showMemoryUsage()
    elif balanceStrategy == 'memBase':
        movedSlotsNumber = 0
        stepSize = 1
        loopControl = 0
        myIndexArray1 = 0
        myIndexArray2 = 0
        myNodeSlotList = getMemoryBaseBalanceSlotNumbers()
        myIndexMax = len(myNodeSlotList)
        # print myNodeSlotList
        # print '----------***************************------------'
        # print myNodeInfoList
        sleep(1)
        # myNodeInfoList[nodeId][SlotNumber]
        # myNodeSlotList [nodeNumber][balancedSlotsNumber]
        processHealth = True
        stepSize = 1
        if myIndexMax == len(myNodeInfoList):
            if movedSlotsNumber < maxSlotBarier:
                while myIndexArray1 < myIndexMax and movedSlotsNumber < maxSlotBarier:
                    #                                   print 'step 1 myIndexArray1 :'+str(myIndexArray1 )+' <  myIndexMax:'+str(myIndexMax)
                    #                                   print 'step 1 movedSlotsNumber :'+str(movedSlotsNumber )+' <  maxSlotBarier:'+str(maxSlotBarier)
                    stepSize = 1
                    #                                   sleep(1)
                    while myNodeInfoList[myIndexArray1][1] < myNodeSlotList[myIndexArray1][1]:
                        print('Node Slot Number :' + str(
                            myNodeInfoList[myIndexArray1][1]) + '               Slot Diff :' + bcolors.OKBLUE + str(
                            myNodeSlotList[myIndexArray1][1] - myNodeInfoList[myIndexArray1][1]) + bcolors.ENDC)
                        # print 'step 2 myNodeInfoList[myIndexArray1][1]:'+str(myNodeInfoList[myIndexArray1][1])+' <
                        # yNodeSlotList[myIndexArray1][1]-1:'+str(myNodeSlotList[myIndexArray1][1]-1)
                        myIndexArray2 = 0
                        loopControl += 1
                        while myIndexArray2 < myIndexMax and movedSlotsNumber < maxSlotBarier:
                            # print 'step 3 myIndexArray2:'+str(myIndexArray2)+'  myIndexMax'+str(myIndexMax) print
                            # 'step 3 movedSlotsNumber:'+str(movedSlotsNumber)+'  maxSlotBarier'+str(maxSlotBarier)
                            loopControl += 1
                            if myIndexArray1 == myIndexArray2 and myIndexArray2 < myIndexMax - 1:
                                myIndexArray2 += 1
                            elif myIndexArray1 == myIndexArray2 and myIndexArray2 >= myIndexMax - 1:
                                myIndexArray2 = 0
                            else:
                                if (myNodeInfoList[myIndexArray2][1] > myNodeSlotList[myIndexArray2][1] and
                                        myNodeInfoList[myIndexArray1][1] < myNodeSlotList[myIndexArray1][1]):
                                    # print 'step 4 myNodeInfoList[myIndexArray2][1]:'+str(myNodeInfoList[myIndexArray2][1])+'  myNodeSlotList[myIndexArray2][1]+1:'+str(myNodeSlotList[myIndexArray2][1]+1)
                                    # print 'step 4 myNodeInfoList[myIndexArray1][1]:'+str(myNodeInfoList[myIndexArray1][1])+'  myNodeSlotList[myIndexArray1][1]-1'+str(myNodeSlotList[myIndexArray1][1]-1)
                                    if (myNodeInfoList[myIndexArray2][1] > myNodeSlotList[myIndexArray2][1] + 30 and
                                            myNodeInfoList[myIndexArray1][1] < myNodeSlotList[myIndexArray1][1] - 30):
                                        stepSize = 30
                                    elif (myNodeInfoList[myIndexArray2][1] > myNodeSlotList[myIndexArray2][1] + 10 and
                                          myNodeInfoList[myIndexArray1][1] < myNodeSlotList[myIndexArray1][1] - 10):
                                        stepSize = 10
                                    elif (myNodeInfoList[myIndexArray2][1] > myNodeSlotList[myIndexArray2][1] + 5 and
                                          myNodeInfoList[myIndexArray1][1] < myNodeSlotList[myIndexArray1][1] - 5):
                                        stepSize = 5
                                    else:
                                        stepSize = 1
                                    if (reshardClusterSilent(contactNode, myNodeInfoList[myIndexArray2][0],
                                                             myNodeInfoList[myIndexArray1][0], str(stepSize))):
                                        print('FROM Node ID' + myNodeInfoList[myIndexArray2][0] + '\n-> TO Node ID :' +
                                              myNodeInfoList[myIndexArray1][0] + '\nMoved Slots :' + str(
                                            stepSize) + bcolors.OKGREEN + ' OK :)' + bcolors.ENDC)
                                        myNodeInfoList[myIndexArray1][1] += stepSize
                                        myNodeInfoList[myIndexArray2][1] -= stepSize
                                        movedSlotsNumber += stepSize
                                        myIndexArray2 += 1
                                    stepSize = 1
                                else:
                                    myIndexArray2 += 1
                            stepSize = 1
                            if movedSlotsNumber >= maxSlotBarier or loopControl == 100000:
                                break
                        if movedSlotsNumber >= maxSlotBarier or loopControl == 100000:
                            break

                    sleep(2)
                    if not clusterCheck(contactNode):
                        print(bcolors.FAIL + '!!! Warning !!! Cluster Check Fail. I will try to fix It' + bcolors.ENDC)
                        sleep(2)
                        if clusterFix(contactNode):
                            print(bcolors.OKGREEN + ' OK :) I fixed it ;)' + bcolors.ENDC)
                            sleep(2)
                    myIndexArray1 += 1
                    if movedSlotsNumber >= maxSlotBarier or loopControl == 100000:
                        break
            clusterInfo(pareNodes[contactNode - 1][0][0], pareNodes[contactNode - 1][1][0])
            showMemoryUsage()

        else:
            (bcolors.WARNING + '!!! ERROR Different Array Size !!!' + bcolors.ENDC)
    else:
        return False


# def reshardClusterSilentUbuntu(contactNode,fromNodeID,toNodeID,slotNumber): myNodeIP=pareNodes[contactNode-1][0][0]
# myNodePORT=pareNodes[contactNode-1][1][0] clusterString=redisBinaryDir+'src/redis-cli --cluster reshard
# '+myNodeIP+':'+myNodePORT+' --cluster-from '+fromNodeID+' --cluster-to '+toNodeID+' --cluster-slots '+slotNumber+'
# --cluster-yes' returnCmd=os.system(clusterString) if(returnCmd==0): return True else: return False
def reshardClusterSilent(contactNode, fromNodeID, toNodeID, slotNumber):
    myNodeIP = pareNodes[contactNode - 1][0][0]
    myNodePORT = pareNodes[contactNode - 1][1][0]
    clusterString = (redisBinaryDir + 'src/redis-cli --cluster reshard ' + myNodeIP + ':'
                     + myNodePORT + ' --cluster-from ' + fromNodeID + ' --cluster-to ' + toNodeID
                     + ' --cluster-slots ' + slotNumber + ' --cluster-yes')
    # returnCmd=os.system(clusterString)
    if redisPwdAuthentication == 'on':
        clusterString += ' -a ' + redisPwd + ' '
    returnCmd, cmdResponse = subprocess.getstatusoutput(clusterString)
    if returnCmd == 0:
        return True
    else:
        return False


def reshardCluster(contactNode, fromNodeID, toNodeID, slotNumber):
    myNodeIP = pareNodes[contactNode - 1][0][0]
    myNodePORT = pareNodes[contactNode - 1][1][0]
    clusterString = redisBinaryDir + 'src/redis-cli --cluster reshard ' + myNodeIP + ':' + myNodePORT + ' --cluster-from ' + fromNodeID + ' --cluster-to ' + toNodeID + ' --cluster-slots ' + slotNumber + ' --cluster-yes'
    if redisPwdAuthentication == 'on':
        clusterString += ' -a ' + redisPwd + ' '
    returnCmd = os.system(clusterString)
    if returnCmd == 0:
        return True
    else:
        return False
    slotInfo(myNodeIP, myNodePORT)


def changePareNodeListFile(oldValue, newValue):
    """
    Updates the pareNodeList.py file by replacing oldValue with newValue.
    Now handles variations in spacing within array notation.
    Returns True if file was updated successfully, False otherwise.
    """
    try:
        fileContent = fileReadFull("pareNodeList.py")
        match_found = False
        updated_content = False
        newFileContent = fileContent

        # Save the original oldValue for logging purposes
        original_oldValue = oldValue

        # First try exact match
        if oldValue in fileContent:
            newFileContent = fileContent.replace(oldValue, newValue)
            match_found = True
            logWrite(pareLogFile, f"Found exact match for: {oldValue}")

            # Immediately write the file with changes - properly handle file operations
            try:
                with open("pareNodeList.py", 'w') as f:
                    f.write(newFileContent + '\n#### Node list File was Changed by paredicma at ' + get_datetime() +
                            '\n#### old value:' + original_oldValue + '\n#### new value:' + newValue)
                    # Perform flush inside the with block before file is closed
                    f.flush()
                    os.fsync(f.fileno())  # Ensure write is committed to disk

                updated_content = True
                logWrite(pareLogFile, f"File updated successfully with new content")
                return True  # Return immediately after successful write
            except Exception as e:
                logWrite(pareLogFile, f"Error writing to file after exact match: {str(e)}")
                return False
        else:
            # Try using regex patterns for matching
            try:
                import re

                # Extract the IP, port, cores, memsize from oldValue
                pattern = r"pareNodes\.append\(\[\['([^']+)'\],\['([^']+)'\],\['([^']+)'\],\['([^']+)'\],([Tt]rue)\]\)"
                match = re.search(pattern, oldValue)

                if match:
                    serverIP = match.group(1)
                    serverPORT = match.group(2)
                    cpuCoreIDs = match.group(3)
                    maxMemSize = match.group(4)

                    # Create pattern to search for this node with any formatting
                    node_pattern = fr"pareNodes\.append\(\[\['{re.escape(serverIP)}'\],\s*\['{re.escape(serverPORT)}'\],\s*\['{re.escape(cpuCoreIDs)}'\],\s*\['{re.escape(maxMemSize)}'\],\s*([Tt]rue)\]\)"

                    # Find the node in the file content
                    existing = re.search(node_pattern, fileContent)
                    if existing:
                        # Get the exact text that matched for replacement
                        exact_match = existing.group(0)
                        match_found = True
                        logWrite(pareLogFile, f"Found match using regex: {exact_match}")

                        # Replace only this exact match
                        newFileContent = fileContent.replace(exact_match, newValue)

                        # Write the file with the proper old value
                        with open("pareNodeList.py", 'w') as f:
                            f.write(newFileContent + '\n#### Node list File was Changed by paredicma at ' + get_datetime() +
                                    '\n#### old value:' + exact_match + '\n#### new value:' + newValue)
                            # Perform flush inside the with block
                            f.flush()
                            os.fsync(f.fileno())  # Ensure write is committed to disk

                        updated_content = True
                        logWrite(pareLogFile, f"File updated successfully with new content")
                        return True
            except Exception as regex_error:
                logWrite(pareLogFile, f"Error in regex replacement: {str(regex_error)}")

            # If all else fails, try direct string replacement one more time
            if not match_found:
                logWrite(pareLogFile, f"No match found, attempting direct file edit")

                # Try direct node identification using IP and port
                try:
                    import re
                    # Extract IP and PORT from the oldValue
                    ip_port_match = re.search(r"\[\['([^']+)'\],\['([^']+)'\]", oldValue)
                    if ip_port_match:
                        ip = ip_port_match.group(1)
                        port = ip_port_match.group(2)

                        # Search for lines containing this IP and port with True
                        lines = fileContent.split('\n')
                        for i, line in enumerate(lines):
                            if f"[['{ip}'" in line and f"['{port}'" in line and "True]" in line:
                                # Found the line - replace it and preserve it as the old value
                                exact_line = lines[i]
                                lines[i] = newValue
                                newFileContent = '\n'.join(lines)
                                match_found = True

                                # Write the updated content
                                with open("pareNodeList.py", 'w') as f:
                                    f.write(newFileContent + '\n#### Node list File was Changed by paredicma at ' + get_datetime() +
                                            '\n#### old value:' + exact_line + '\n#### new value:' + newValue)
                                    f.flush()
                                    os.fsync(f.f.fileno())

                                logWrite(pareLogFile, f"Found and replaced line by IP:PORT search: {ip}:{port}")
                                updated_content = True
                                return True
                except Exception as line_error:
                    logWrite(pareLogFile, f"Error in line-by-line replacement: {str(line_error)}")

            # If we still haven't found a match, just try a basic replace as last resort
            if not match_found:
                logWrite(pareLogFile, f"No match found using any method, trying simple replace")
                newFileContent = fileContent.replace(oldValue, newValue)

                with open("pareNodeList.py", 'w') as f:
                    f.write(newFileContent + '\n#### Node list File was Changed by paredicma at ' + get_datetime() +
                            '\n#### old value:' + original_oldValue + '\n#### new value:' + newValue)
                    f.flush()
                    os.fsync(f.fileno())

                updated_content = True
                logWrite(pareLogFile, f"Attempted simple file replace")
                return updated_content

        # We should never get here, but just in case
        return updated_content

    except Exception as e:
        logWrite(pareLogFile, f"Error in changePareNodeListFile: {str(e)}")
        return False


def changePareConfigFile(oldValue, newValue):
    retVal = False
    fileContent = fileReadFull("pareConfig.py")
    newFileContent = fileContent.replace(oldValue, newValue)
    fileClearWrite("pareConfig.py",
                   newFileContent + '\n#### Config File was Changed by paredicma at ' + get_datetime() + '\n#### old value:' + oldValue + '\n#### new value:' + newValue)
    retVal = True
    return retVal


def redisNodesVersionControl():
    nodeNumber = 0
    for pareNode in pareNodes:
        nodeIP = pareNode[0][0]
        portNumber = pareNode[1][0]
        nodeNumber = nodeNumber + 1
        if pareNode[4]:
            print(bcolors.BOLD + 'Node Number :' + str(
                nodeNumber) + '  Node IP :' + nodeIP + '  Node Port :' + portNumber + bcolors.ENDC)
            os.system(redisConnectCmd(nodeIP, portNumber, ' info server | grep  redis_version'))


def checkReplicationStatus():
    retCRS = True
    for pareNode in pareNodes:
        pareConfig.redisBinaryDir = redisBinaryDir.replace('redis-' + redisVersion, 'redis-' + newRedisVersion)
        nodeIP = pareNode[0][0]
        portNumber = pareNode[1][0]
        nodeNumber = nodeNumber + 1
        if pareNode[4]:
            print(bcolors.BOLD + 'Node Number :' + str(
                nodeNumber) + '  Node IP :' + nodeIP + '  Node Port :' + portNumber + bcolors.ENDC)
            if isNodeMaster(nodeIP, nodeNumber, portNumber):
                pmdStatus, cmdResponse = subprocess.getstatusoutput(
                    redisConnectCmd(nodeIP, portNumber, ' info replication'))
                if cmdResponse.find('state=online') == -1:
                    retCRS = False
                    print(bcolors.WARNING + '!!! Master Node :' + str(
                        nodeNumber) + ' IP: ' + nodeIP + ' PORT:' + portNumber + ' has no ONLINE REPLICA SLAVE !!!\n Operation canceled.  ' + bcolors.ENDC)
                searchKeyOffset = 'offset='
                searchMasterKeyOffset = 'master_repl_offset:'
                colNumOffset = cmdResponse.find('offset=')
                cmdResponse = cmdResponse[colNumOffset + len(searchKeyOffset):]
                colNumOffset = cmdResponse.find(',')
                slaveOffset = int(cmdResponse[:colNumOffset])
                colNumOffset = cmdResponse.find(searchMasterKeyOffset)
                cmdResponse = cmdResponse[colNumOffset + len(searchMasterKeyOffset):]
                colNumOffset = cmdResponse.find('\n')
                masterOffset = int(cmdResponse[:colNumOffset])
                print('Master offset:' + str(masterOffset) + ' : slave offset:' + str(slaveOffset))
                if masterOffset - slaveOffset > 3:
                    retCRS = False
                    print(bcolors.WARNING + '!!! Master Node :' + str(
                        nodeNumber) + ' IP: ' + nodeIP + ' PORT:' + portNumber + 'has no SYNC REPLICA SLAVE !!!\n '
                                                                                 'Operation canceled. ' + bcolors.ENDC)
    return retCRS


def restartAllMasters(newRedisVersion):
    global redisBinaryDir
    global redisVersion
    stateResult = True
    nodeNumber = 0
    if checkReplicationStatus:
        for pareNode in pareNodes:
            redisBinaryDir = redisBinaryDir.replace('redis-' + redisVersion, 'redis-' + newRedisVersion)
            nodeIP = pareNode[0][0]
            portNumber = pareNode[1][0]
            dedicateCpuCores = pareNode[2][0]
            nodeNumber = nodeNumber + 1
            if pareNode[4]:
                print(bcolors.BOLD + 'Node Number :' + str(
                    nodeNumber) + '  Node IP :' + nodeIP + '  Node Port :' + portNumber + bcolors.ENDC)
                if isNodeMaster(nodeIP, nodeNumber, portNumber):
                    pmdStatus, cmdResponse = subprocess.getstatusoutput(
                        redisConnectCmd(nodeIP, portNumber, ' info server | grep  redis_version'))
                    if cmdResponse.find(newRedisVersion) == -1:
                        stopNode(nodeIP, str(nodeNumber), portNumber)
                        startNode(nodeIP, str(nodeNumber), portNumber, dedicateCpuCores)
                        # sleep(2)
                        pmdStatus, cmdResponse = subprocess.getstatusoutput(
                            redisConnectCmd(nodeIP, portNumber, ' info server | grep  redis_version'))
                        if cmdResponse.find(newRedisVersion) >= 0:
                            logWrite(pareLogFile,
                                     bcolors.OKGREEN + 'Master redis node started  with new version :' + newRedisVersion + bcolors.ENDC)
                            print(cmdResponse)
                            logWrite(pareLogFile, bcolors.BOLD + 'node Id :' + str(
                                nodeNumber) + ' nodeIP: ' + nodeIP + ' nodePort:' + portNumber + bcolors.ENDC)
                        else:
                            stateResult = False
                            logWrite(pareLogFile,
                                     bcolors.FAIL + '!!! There might be a problem with master restart !!! Manuel '
                                                    'check is recommended !!!' + bcolors.ENDC)
                    else:
                        logWrite(pareLogFile, bcolors.WARNING + 'This node has already upgraded..' + bcolors.ENDC)
    # restartNode(nodeIP,str(nodeNumber),portNumber,dedicateCpuCores)
    else:
        logWrite(pareLogFile, '!!! Master nodes upgrade was canceled !!! Not Sync !!!')
        stateResult = False
    return stateResult


def restartAllSlaves(newRedisVersion):
    global redisBinaryDir
    global redisVersion
    stateResult = True
    nodeNumber = 0
    for pareNode in pareNodes:
        redisBinaryDir = redisBinaryDir.replace('redis-' + redisVersion, 'redis-' + newRedisVersion)
        nodeIP = pareNode[0][0]
        portNumber = pareNode[1][0]
        dedicateCpuCores = pareNode[2][0]
        nodeNumber = nodeNumber + 1
        if pareNode[4]:
            print(bcolors.BOLD + 'Node Number :' + str(
                nodeNumber) + '  Node IP :' + nodeIP + '  Node Port :' + portNumber + bcolors.ENDC)
            if not isNodeMaster(nodeIP, nodeNumber, portNumber):
                pmdStatus, cmdResponse = subprocess.getstatusoutput(
                    redisConnectCmd(nodeIP, portNumber, ' info server | grep  redis_version'))
                if cmdResponse.find(newRedisVersion) == -1:
                    stopNode(nodeIP, str(nodeNumber), portNumber)
                    startNode(nodeIP, str(nodeNumber), portNumber, dedicateCpuCores)
                    pmdStatus, cmdResponse = subprocess.getstatusoutput(
                        redisConnectCmd(nodeIP, portNumber, ' info server | grep  redis_version'))
                    if cmdResponse.find(newRedisVersion) >= 0:
                        logWrite(pareLogFile,
                                 bcolors.BOLD + 'Slave redis node started  with new version :' + newRedisVersion)
                        print(cmdResponse)
                        logWrite(pareLogFile, bcolors.BOLD + 'node Id :' + str(
                            nodeNumber) + ' nodeIP: ' + nodeIP + ' nodePort:' + portNumber + bcolors.ENDC)
                    else:
                        stateResult = False
                        logWrite(pareLogFile,
                                 bcolors.FAIL + '!!! There might be a problem with slave restart !!! Manuel check is '
                                                'recommended !!!' + bcolors.ENDC)
                else:
                    print(bcolors.WARNING + 'This node has already upgraded..' + bcolors.ENDC)
    # restartNode(nodeIP,str(nodeNumber),portNumber,dedicateCpuCores)
    return stateResult


def clusterStateInfo(nodeIP, nodeNumber, portNumber):
    print(bcolors.BOLD + '\nCluster State node ->' + str(
        nodeNumber) + ' node IP :' + nodeIP + ' node Port : ' + portNumber + '\n' + bcolors.ENDC)
    pmdStatus, cmdResponse = subprocess.getstatusoutput(
        redisConnectCmd(nodeIP, portNumber, ' cluster info | grep  cluster_state'))
    if cmdResponse.find('ok') >= 0:
        print(bcolors.OKGREEN + cmdResponse + bcolors.ENDC)
    else:
        print(bcolors.FAIL + cmdResponse + bcolors.ENDC)


def clusterInfo(nodeIP, portNumber):
    print('\n------- Cluster Nodes -------\n')
    os.system(redisConnectCmd(nodeIP, portNumber, ' CLUSTER NODES |  grep master'))
    print('\nCluster Slots Check\n------------------------------------------ ')
    clusterString = redisBinaryDir + 'src/redis-cli --cluster check ' + nodeIP + ':' + portNumber
    if redisPwdAuthentication == 'on':
        clusterString += ' -a ' + redisPwd + ' '
    clStatus, clResponse = subprocess.getstatusoutput(clusterString)
    print(bcolors.BOLD + clResponse[:clResponse.find('>>>')] + bcolors.ENDC)
    input(bcolors.BOLD + '\n----------------------\nPress Enter to Return Paredicmon Menu' + bcolors.ENDC)


def slotInfo(nodeIP, portNumber):
    print('\n------- Cluster Slots -------\n')
    os.system(redisConnectCmd(nodeIP, portNumber, ' CLUSTER SLOTS'))
    os.system(redisConnectCmd(nodeIP, portNumber, ' CLUSTER NODES |  grep master'))
    print('\nCluster Slots Check\n------------------------------------------ ')
    clusterString = redisBinaryDir + 'src/redis-cli --cluster check ' + nodeIP + ':' + portNumber
    if redisPwdAuthentication == 'on':
        clusterString += ' -a ' + redisPwd + ' '
    clStatus, clResponse = subprocess.getstatusoutput(clusterString)
    print(bcolors.BOLD + clResponse[:clResponse.find('>>>')] + bcolors.ENDC)
    input(bcolors.BOLD + '\n----------------------\nPress Enter to Return Paredicmon Menu' + bcolors.ENDC)


def funcNodesList():
    print(bcolors.BOLD + 'Listing Nodes' + bcolors.ENDC)
    masterNodeList = ''
    slaveNodeList = ''
    unknownNodeList = ''
    nodeNumber = 0
    for pareNode in pareNodes:
        nodeIP = pareNode[0][0]
        portNumber = pareNode[1][0]
        nodeNumber = nodeNumber + 1
        if pareNode[4]:
            returnVal = slaveORMasterNode(nodeIP, portNumber)
            if returnVal == 'M':
                masterNodeList += bcolors.OKGREEN + 'Node Number :' + str(
                    nodeNumber) + ' Server IP :' + nodeIP + ' Port:' + portNumber + ' UP\n' + bcolors.ENDC
            elif returnVal == 'S':
                myStatus, myResponse = subprocess.getstatusoutput(redisConnectCmd(nodeIP, portNumber,
                                                                                  ' info replication | grep  -e "master_host:" -e "master_port:" '))
                if myStatus == 0:
                    slaveNodeList += bcolors.OKBLUE + 'Node Number :' + str(
                        nodeNumber) + ' Server IP :' + nodeIP + ' Port:' + portNumber + ' UP   ' + bcolors.ENDC + bcolors.OKGREEN + ' -> ' + myResponse.replace(
                        "\nmaster_port", "") + '\n' + bcolors.ENDC
                else:
                    slaveNodeList += bcolors.OKBLUE + 'Node Number :' + str(
                        nodeNumber) + ' Server IP :' + nodeIP + ' Port:' + portNumber + ' UP\n' + bcolors.ENDC
            else:
                unknownNodeList += bcolors.FAIL + 'Node Number :' + str(
                    nodeNumber) + ' Server IP :' + nodeIP + ' Port:' + portNumber + ' DOWN\n' + bcolors.ENDC
    returnVAl = input(
        bcolors.BOLD + '\n------- Master Nodes -------\n' + bcolors.ENDC + masterNodeList + bcolors.BOLD + '\n------- Slave Nodes -------\n' + bcolors.ENDC + slaveNodeList + bcolors.BOLD + '\n------- Down Nodes -------\n' + bcolors.ENDC + unknownNodeList + bcolors.BOLD + '\n--------------\nPress enter to continue...' + bcolors.ENDC)


def serverInfo(serverIP):
    if is_local_server(serverIP):
        print('\n------- Server Informations (' + serverIP + ') ------\n')
        print('\n------- CPU Cores -------------------------------\n')
        os.system("numactl --hardware")
        print('\n------- Memory Usage-----------------------------\n')
        os.system("free -g")
        print('\n------- Disk Usage-------------------------------\n')
        os.system("df -h")
        print('\n------- Redis  Nodes ----------------------------\n')
    else:
        print('\n------- Server Informations (' + serverIP + ') ------\n')
        print('\n------- CPU Cores -------------------------------\n')
        os.system('ssh -q -o "StrictHostKeyChecking no"  ' + pareOSUser + '@' + serverIP + ' -C  "numactl --hardware"')
        print('\n------- Memory Usage-----------------------------\n')
        os.system('ssh -q -o "StrictHostKeyChecking no"  ' + pareOSUser + '@' + serverIP + ' -C  "free -g"')
        print('\n------- Disk Usage-------------------------------\n')
        os.system('ssh -q -o "StrictHostKeyChecking no"  ' + pareOSUser + '@' + serverIP + ' -C  "df -h"')
        print('\n------- Redis  Nodes ----------------------------\n')

    masterNodeList = ''
    slaveNodeList = ''
    unknownNodeList = ''
    nodenumbers = getnodeNumbers(serverIP)

    for pareNode in pareNodes:
        if pareNode[0][0] == serverIP:
						   
            portNumber = pareNode[1][0]
									   
            if pareNode[4]:
                returnVal = slaveORMasterNode(serverIP, portNumber)
                nodeNumber = nodenumbers.pop(0)
                if returnVal == 'M':
																			  
                    masterNodeList += bcolors.OKGREEN + f'Node Number: {nodeNumber} Server IP: {serverIP} Port: {portNumber} UP\n' + bcolors.ENDC
                elif returnVal == 'S':
																			
                    slaveNodeList += bcolors.OKBLUE + f'Node Number: {nodeNumber} Server IP: {serverIP} Port: {portNumber} UP\n' + bcolors.ENDC
                else:
                    unknownNodeList += bcolors.FAIL + f'Node Number: {nodeNumber} Server IP: {serverIP} Port: {portNumber} DOWN\n' + bcolors.ENDC

    input(
        bcolors.BOLD + '\n------- Master Nodes -------\n' + bcolors.ENDC + masterNodeList + bcolors.BOLD + '\n------- Slave Nodes -------\n' + bcolors.ENDC + slaveNodeList + bcolors.BOLD + '\n------- Unknown Nodes -------\n' + bcolors.ENDC + unknownNodeList + bcolors.BOLD + '\n--------------\nPress Enter to Return Paredicmon Menu' + bcolors.ENDC)



def validIP(IPaddr):
    try:
        socket.inet_aton(IPaddr)
        return True
    except socket.error:
        return False


def redisConnectCmd(nodeIP, portNumber, redisCmd, cluster_mode=False):
    redisCliCmd = ''
    cluster_flag = ' -c' if cluster_mode else ''
    if redisPwdAuthentication:
        redisCliCmd = redisBinaryDir + 'src/redis-cli -h ' + nodeIP + ' -p ' + portNumber + cluster_flag + ' --no-auth-warning -a ' + redisPwd + ' ' + redisCmd
    else:
        redisCliCmd = redisBinaryDir + '/src/redis-cli -h ' + nodeIP + ' -p ' + portNumber + cluster_flag + ' ' + redisCmd
    return redisCliCmd


def redisConnectCmdwithTimeout(nodeIP, portNumber, redisCmd):
    redisCliCmd = ''
    if redisPwdAuthentication:
        redisCliCmd = 'timeout 3  ' + redisBinaryDir + 'src/redis-cli -h ' + nodeIP + ' -p ' + portNumber + ' --no-auth-warning -a ' + redisPwd + ' ' + redisCmd
    else:
        redisCliCmd = 'timeout 3  ' + redisBinaryDir + '/src/redis-cli -h ' + nodeIP + ' -p ' + portNumber + ' ' + redisCmd
    return redisCliCmd


def nodeInfo(nodeIP, nodeNumber, portNumber, infoCmd):
    retVal = 'Unknown'
    listStatus, listResponse = subprocess.getstatusoutput(redisConnectCmd(nodeIP, portNumber, 'info ' + infoCmd))
    if listStatus == 0:
        retVal = listResponse
    else:
        retVal = bcolors.FAIL + ' !!! No Information or Connection Problem !!!' + bcolors.ENDC
    return retVal


def slaveORMasterNode(nodeIP, portNumber):
    retVal = 'U'
    listStatus, listResponse = subprocess.getstatusoutput(
        redisConnectCmdwithTimeout(nodeIP, portNumber, 'cluster nodes | grep myself'))
    if listStatus == 0:
        if 'master' in listResponse:
            retVal = 'M'
        elif 'slave' in listResponse:
            retVal = 'S'
    else:
        retVal = 'U'
    return retVal


def getMemoryBaseBalanceSlotNumbers():
    nodeNumber = 0
    totalMemPer = 0.0
    totalMaxMemByte = 0.0
    nodeListSlots = []
    nodeListMem = []
    for pareNode in pareNodes:
        nodeIP = pareNode[0][0]
        portNumber = pareNode[1][0]
        nodeNumber = nodeNumber + 1
        if pareNode[4]:
            memStatus, memResponse = subprocess.getstatusoutput(
                redisConnectCmd(nodeIP, portNumber, ' info memory | grep  -e "maxmemory:" '))
            if memStatus == 0 and isNodeMaster(nodeIP, nodeNumber, portNumber):
                maxMemByte = float(memResponse[memResponse.find('maxmemory:') + 10:])
                nodeListMem.append([nodeNumber, maxMemByte])
                totalMaxMemByte += maxMemByte
    if totalMaxMemByte == 0:
        print(bcolors.FAIL + '!!!Division by Zero ERROR !!!' + bcolors.ENDC)
    else:
        for nodeMem in nodeListMem:
            nodeListSlots.append([nodeMem[0], int((nodeMem[1] / totalMaxMemByte) * 16384)])
    return nodeListSlots


def showMemoryUsage():
    os.system("clear")
    # while(True):
    # sleep(1)
    print('Memory Usage\n-------------------------------')
    print(
        bcolors.HEADER + 'nodeID                NodeIP                           NodePort       Used Mem(GB)    Max Mem(GB)     Usage (%)' + bcolors.ENDC)
    nodeNumber = 0
    totalMemPer = 0.0
    totalUsedMemByte = 0
    totalMaxMemByte = 0
    printTextMaster = ''
    printTextSlave = ''
    isMaster = False
    for pareNode in pareNodes:
        nodeIP = pareNode[0][0]
        portNumber = pareNode[1][0]
        nodeNumber = nodeNumber + 1
        if pareNode[4]:
            memStatus, memResponse = subprocess.getstatusoutput(
                redisConnectCmd(nodeIP, portNumber, ' info memory | grep  -e "used_memory:" -e "maxmemory:" '))
            if memStatus == 0:
                usedMemByte = float(memResponse[12:memResponse.find('maxmemory:') - 1])
                maxMemByte = float(memResponse[memResponse.find('maxmemory:') + 10:])
                usedMem = round(usedMemByte / (1024 * 1024 * 1024), 3)
                maxMem = round(maxMemByte / (1024 * 1024 * 1024), 3)
                usagePerMem = round((usedMem / maxMem) * 100, 2)
                # totalUsedMemByte+=usedMemByte
                # totalMaxMemByte+=maxMemByte
                if isNodeMaster(nodeIP, nodeNumber, portNumber):
                    isMaster = True
                    totalUsedMemByte += usedMemByte
                    totalMaxMemByte += maxMemByte
                    str(nodeNumber) + ' ' + nodeIP + '-( M )                    ' + portNumber + '              ' + str(
                        usedMem) + '            ' + str(maxMem) + '             ' + str(usagePerMem) + '%' + bcolors.ENDC + '\n'
                else:
                    isMaster = False
                    str(nodeNumber) + ' ' + nodeIP + '-( S )                    ' + portNumber + '              ' + str(
                        usedMem) + '            ' + str(maxMem) + '             ' + str(usagePerMem) + '%' + bcolors.ENDC + '\n'
                if usagePerMem >= 90.0:
                    if isMaster:
                        printTextMaster += bcolors.FAIL + str(
                            nodeNumber) + '     ' + nodeIP + '-( M )                    ' + portNumber + '              ' + str(
                            usedMem) + '                ' + str(maxMem) + '             ' + str(
                            usagePerMem) + '%' + bcolors.ENDC + '\n'
                    else:
                        printTextSlave += bcolors.FAIL + str(
                            nodeNumber) + '     ' + nodeIP + '-( S )                    ' + portNumber + '              ' + str(
                            usedMem) + '                ' + str(maxMem) + '             ' + str(
                            usagePerMem) + '%' + bcolors.ENDC + '\n'
                elif 80.00 <= usagePerMem < 90.00:
                    if isMaster:
                        printTextMaster += bcolors.WARNING + str(
                            nodeNumber) + '     ' + nodeIP + '-( M )                    ' + portNumber + '              ' + str(
                            usedMem) + '                ' + str(maxMem) + '             ' + str(
                            usagePerMem) + '%' + bcolors.ENDC + '\n'
                    else:
                        printTextSlave += bcolors.WARNING + str(
                            nodeNumber) + '     ' + nodeIP + '-( S )                    ' + portNumber + '              ' + str(
                            usedMem) + '                ' + str(maxMem) + '             ' + str(
                            usagePerMem) + '%' + bcolors.ENDC + '\n'
                else:
                    if isMaster:
                        printTextMaster += bcolors.OKGREEN + str(
                            nodeNumber) + '     ' + nodeIP + '-( M )                    ' + portNumber + '              ' + str(
                            usedMem) + '                ' + str(maxMem) + '             ' + str(
                            usagePerMem) + '%' + bcolors.ENDC + '\n'
                    else:
                        printTextSlave += bcolors.OKGREEN + str(
                            nodeNumber) + '     ' + nodeIP + '-( S )                    ' + portNumber + '              ' + str(
                            usedMem) + '                ' + str(maxMem) + '             ' + str(
                            usagePerMem) + '%' + bcolors.ENDC + '\n'
            else:
                print(
                    bcolors.FAIL + '!!! Warning !!!! A problem occurred, while memory usage checking !!! nodeID :' + str(
                        nodeNumber) + ' NodeIP:' + nodeIP + ' NodePort:' + portNumber + '' + bcolors.ENDC)
    print(
        printTextMaster + bcolors.BOLD + '-------------------------------------------' + bcolors.ENDC)
    print(printTextSlave)
    totalUsedMem = round((totalUsedMemByte / (1024 * 1024 * 1024)), 3)
    totalMaxMem = round((totalMaxMemByte / (1024 * 1024 * 1024)), 3)
    if totalMaxMem == 0:
        totalMemPer = 0.0
    else:
        totalMemPer = round(((totalUsedMem / totalMaxMem) * 100), 2)
    print(
        bcolors.BOLD + '-----------------------------' + bcolors.ENDC)
    print(bcolors.BOLD + 'TOTAL ( Only Master )                                         :' + str(totalUsedMem) + 'GB    ' + str(
        totalMaxMem) + 'GB              ' + str(totalMemPer) + '% ' + bcolors.ENDC)
    input('\n-----------------------------------------\nPress Enter to Return Paredicmon Menu')


								 
																										
														
				   
		 
					


												 
							 
														  
																			 
									   
				   
		 
					


def migrateDataFrom(toIP, toPort, fromIP, fromPORT, fromPWD):
    if redisPwdAuthentication == 'on':
        nodeNumber = 0
        for pareNode in pareNodes:
            nodeIP = pareNode[0][0]
            portNumber = pareNode[1][0]
            nodeNumber = nodeNumber + 1
            if pareNode[4]:
                # print ('Redis configuration will change  will rewrite on Node Number :'+str(nodeNumber)+'  Node IP
                # :'+nodeIP+'  Node Port :'+portNumber )
                os.system(redisConnectCmd(nodeIP, portNumber, ' CONFIG SET requirepass "" '))
    if fromPWD == '':
        os.system('date')
        logWrite(pareLogFile, bcolors.BOLD + "\nData importing is starting... Please wait !!!" + bcolors.ENDC)
        os.system(
            './redis-' + redisVersion + '/src/redis-cli --cluster import ' + toIP + ':' + toPort + ' --cluster-from ' + fromIP + ':' + fromPORT + ' --cluster-copy > /dev/null')
        os.system('date')
        logWrite(pareLogFile, bcolors.BOLD + "\nData importing ended. " + bcolors.ENDC)
    else:
        os.system(
            './redis-' + redisVersion + '/src/redis-cli -h ' + fromIP + ' -p ' + fromPORT + ' --no-auth-warning -a ' + fromPWD + ' Config set requirepass ""')
        os.system('date')
        logWrite(pareLogFile, bcolors.BOLD + "\nData importing is starting... Please wait !!!" + bcolors.ENDC)
        os.system(
            './redis-' + redisVersion + '/src/redis-cli --cluster import ' + toIP + ':' + toPort + ' --cluster-from ' + fromIP + ':' + fromPORT + ' --cluster-copy > /dev/null')
        os.system('date')
        logWrite(pareLogFile, bcolors.BOLD + "\nData importing ended. " + bcolors.ENDC)
        os.system(
            './redis-' + redisVersion + '/src/redis-cli -h ' + fromIP + ' -p ' + fromPORT + ' Config set requirepass "' + fromPWD + '"')
    if redisPwdAuthentication == 'on':
        nodeNumber = 0
        for pareNode in pareNodes:
            nodeIP = pareNode[0][0]
            portNumber = pareNode[1][0]
            nodeNumber = nodeNumber + 1
            if pareNode[4]:
                # print ('Redis configuration will change  will rewrite on Node Number :'+str(nodeNumber)+'  Node IP
                # :'+nodeIP+'  Node Port :'+portNumber )
                os.system(redisConnectCmd(nodeIP, portNumber, ' CONFIG SET requirepass ' + redisPwd))


												   
														  
																						  
													 
					
		 
				   


def makeRedisCluster(nodesString, redisReplicationNumber):
    clusterString = ''
    if redisReplicationNumber == '0':
        clusterString = redisBinaryDir + 'src/redis-cli --cluster create ' + nodesString
    else:
        clusterString = redisBinaryDir + 'src/redis-cli --cluster create ' + nodesString + ' --cluster-replicas ' + redisReplicationNumber
    if redisPwdAuthentication == 'on':
        clusterString += ' -a ' + redisPwd + ' '
    logWrite(pareLogFile, bcolors.BOLD + ':: Cluster create string : ' + clusterString + bcolors.ENDC)
    os.system(clusterString)


def delPareNode(delNodeID):
    try:
        # Force reload pareNodeList to get the latest data
        try:
            import importlib
            importlib.reload(sys.modules['pareNodeList'])
            from pareNodeList import pareNodes as fresh_pareNodes

            # Use the fresh_pareNodes list for validation
            node_id_int = int(delNodeID)
            if node_id_int < 1 or node_id_int > len(fresh_pareNodes):
                logWrite(pareLogFile, f'Error: Invalid node ID {delNodeID}. Valid range is 1-{len(fresh_pareNodes)}')
                return False

            # Use the fresh node data
            pareNode = fresh_pareNodes[node_id_int - 1]
            serverIP = pareNode[0][0]
            serverPORT = pareNode[1][0]
        except Exception as e:
            # Fall back to current pareNodes if reload fails
            node_id_int = int(delNodeID)
            if node_id_int < 1 or node_id_int > len(pareNodes):
                logWrite(pareLogFile, f'Error: Invalid node ID {delNodeID}. Valid range is 1-{len(pareNodes)}')
                return False

            serverIP = pareNodes[node_id_int - 1][0][0]
            serverPORT = pareNodes[node_id_int - 1][1][0]

        nodeNumber = 0
        contactNodeIP = ""
        contactNodePort = ""

        # First, find a healthy node to serve as contact point for the cluster operation
        for pareNode in pareNodes:
            if pareNode[4]:
                if isNodeMaster(pareNode[0][0], str(nodeNumber + 1), pareNode[1][0]):
                    contactNodeIP = pareNode[0][0]
                    contactNodePort = pareNode[1][0]
                    break
            nodeNumber += 1

        # If we couldn't find a contact node, report error
        if not contactNodeIP or not contactNodePort:
            logWrite(pareLogFile, bcolors.FAIL + 'Error: Could not find an active master node to use as contact point' + bcolors.ENDC)
            return False

        # Check if the node to delete is reachable
        if not pingredisNode(serverIP, serverPORT):
            logWrite(pareLogFile, bcolors.WARNING + f'Warning: Node {delNodeID} ({serverIP}:{serverPORT}) is not responding. Will attempt to delete from cluster anyway.' + bcolors.ENDC)

        # Get the cluster node ID of the node we want to delete
        pingStatus, queryRespond = subprocess.getstatusoutput(
            redisConnectCmd(serverIP, serverPORT, ' cluster nodes | grep myself'))

        if pingStatus == 0:
            queryRespondList = queryRespond.split(' ')
            nodeId = queryRespondList[0]

            clusterString = redisBinaryDir + 'src/redis-cli --cluster del-node ' + contactNodeIP + ':' + contactNodePort + ' ' + nodeId + ' '
            if redisPwdAuthentication == 'on':
                clusterString += ' -a ' + redisPwd + ' '

            logWrite(pareLogFile,
                     bcolors.BOLD + 'Deleting node ' + serverIP + ':' + serverPORT + ' (ID: ' + nodeId + ') from cluster using contact node ' +
                     contactNodeIP + ':' + contactNodePort + bcolors.ENDC)
            logWrite(pareLogFile, bcolors.BOLD + 'Command: ' + clusterString + bcolors.ENDC)

            procStatus, procResult = subprocess.getstatusoutput(clusterString)
            if procResult.find('[ERR]') == -1:
                logWrite(pareLogFile, queryRespond)
                logWrite(pareLogFile,
                         bcolors.OKGREEN + 'Node ' + serverIP + ':' + serverPORT + ' was successfully deleted from the cluster' + bcolors.ENDC)
                return True
            else:
                logWrite(pareLogFile, queryRespond)
                logWrite(pareLogFile,
                         bcolors.FAIL + '!!! Failed to delete node ' + serverIP + ':' + serverPORT + ' !!!' + bcolors.ENDC)
                logWrite(pareLogFile, bcolors.FAIL + '!!! This node might be a NON-empty master node !!!' + bcolors.ENDC)
                logWrite(pareLogFile, bcolors.FAIL + 'Error: ' + procResult + bcolors.ENDC)
                return False
        else:
            logWrite(pareLogFile,
                     bcolors.FAIL + '!!! Failed to get node ID for ' + serverIP + ':' + serverPORT + ' !!!' + bcolors.ENDC)

            # Special case: Try to get the node ID from a contact node instead
            # This helps when the node is unreachable but still in the cluster config
            altLookupCmd = redisConnectCmd(contactNodeIP, contactNodePort, f' cluster nodes | grep "{serverIP}:{serverPORT}"')
            lookupStatus, lookupResult = subprocess.getstatusoutput(altLookupCmd)

            if lookupStatus == 0 and lookupResult.strip():
                # We found the node info - extract the ID
                try:
                    nodeId = lookupResult.strip().split(' ')[0]

                    logWrite(pareLogFile,
                         bcolors.WARNING + f'Node {serverIP}:{serverPORT} is unreachable but found in cluster config. Using node ID: {nodeId}' + bcolors.ENDC)

                    clusterString = redisBinaryDir + 'src/redis-cli --cluster del-node ' + contactNodeIP + ':' + contactNodePort + ' ' + nodeId + ' '
                    if redisPwdAuthentication == 'on':
                        clusterString += ' -a ' + redisPwd + ' '

                    logWrite(pareLogFile, bcolors.BOLD + 'Command: ' + clusterString + bcolors.ENDC)

                    procStatus, procResult = subprocess.getstatusoutput(clusterString)
                    if procResult.find('[ERR]') == -1:
                        logWrite(pareLogFile,
                                 bcolors.OKGREEN + 'Node ' + serverIP + ':' + serverPORT + ' was successfully deleted from the cluster' + bcolors.ENDC)
                        return True
                    else:
                        logWrite(pareLogFile,
                                 bcolors.FAIL + '!!! Failed to delete node ' + serverIP + ':' + serverPORT + ' !!!' + bcolors.ENDC)
                        logWrite(pareLogFile, bcolors.FAIL + 'Error: ' + procResult + bcolors.ENDC)
                except Exception as e:
                    logWrite(pareLogFile,
                             bcolors.FAIL + f'Error processing alternate node lookup: {str(e)}' + bcolors.ENDC)

            return False
    except Exception as e:
        import traceback
        logWrite(pareLogFile, bcolors.FAIL + f'Unexpected error in delPareNode: {str(e)}' + bcolors.ENDC)
        logWrite(pareLogFile, bcolors.FAIL + traceback.format_exc() + bcolors.ENDC)
        return False


def addMasterNode(serverIP, serverPORT):
    targetIP = ''
    targetPORT = ''
    nodeNumber = 0
    for pareNode in pareNodes:
        if pareNode[4]:
            if isNodeMaster(pareNode[0][0], str(nodeNumber + 1), pareNode[1][0]):
                targetIP = pareNode[0][0]
                targetPORT = pareNode[1][0]
                break
        nodeNumber += 1
    clusterString = redisBinaryDir + 'src/redis-cli --cluster add-node ' + serverIP + ':' + serverPORT + ' ' + targetIP + ':' + targetPORT
    if redisPwdAuthentication == 'on':
        clusterString += ' -a ' + redisPwd + ' '
    if pingredisNode(serverIP, serverPORT):
        logWrite(pareLogFile,
                 bcolors.BOLD + 'Adding new master node to redis cluster : ' + clusterString + bcolors.ENDC)
        if os.system(clusterString) == 0:
            return True
            logWrite(pareLogFile,
                     bcolors.OKGREEN + 'New Node was added. OK :)!!!: Node IP:' + serverIP + ' PORT:' + serverPORT + bcolors.ENDC)
        else:
            return False
    else:
        return False


def addSlaveNode(serverIP, serverPORT):
    """
    Note: This function is deprecated. Use addSpecificSlaveNode instead to assign
    slave nodes to specific masters.

    Legacy function that attempts to add a new slave node to the Redis cluster
    with automatic master assignment, but this approach is no longer recommended.
    """


def addSpecificSlaveNode(serverIP, serverPORT, cMasterID):
    targetIP = ''
    targetPORT = ''
    nodeNumber = 0

    # Validate master ID format (should be 40 character hex string)
    if not (len(cMasterID) == 40 and all(c in '0123456789abcdef' for c in cMasterID.lower())):
        logWrite(pareLogFile, bcolors.FAIL + 'Invalid master node ID format: ' + cMasterID + '. Expected 40 character hex string.' + bcolors.ENDC)
        return False

    # Find a contact node to use as entry point to the cluster
    for pareNode in pareNodes:
        if pareNode[4]:
            if isNodeMaster(pareNode[0][0], str(nodeNumber + 1), pareNode[1][0]):
                targetIP = pareNode[0][0]
                targetPORT = pareNode[1][0]
                break
        nodeNumber += 1

    # Verify the master ID exists in the cluster
    verifyCmd = redisConnectCmd(targetIP, targetPORT, ' CLUSTER NODES | grep ' + cMasterID)
    verifyStatus, verifyOutput = subprocess.getstatusoutput(verifyCmd)

    if verifyStatus != 0 or not verifyOutput or len(verifyOutput.strip()) == 0:
        logWrite(pareLogFile, bcolors.FAIL + 'Master node ID ' + cMasterID + ' not found in the cluster' + bcolors.ENDC)
        return False

    # Make sure the target is actually a master
    if 'master' not in verifyOutput:
        logWrite(pareLogFile, bcolors.FAIL + 'Node ID ' + cMasterID + ' is not a master node' + bcolors.ENDC)
        return False

    # Build the cluster command
    clusterString = redisBinaryDir + 'src/redis-cli --cluster add-node ' + serverIP + ':' + serverPORT + ' ' + targetIP + ':' + targetPORT + ' --cluster-slave --cluster-master-id ' + cMasterID
    if redisPwdAuthentication == 'on':
        clusterString += ' -a ' + redisPwd + ' '

    # Execute the command only if the node is pingable
    if pingredisNode(serverIP, serverPORT):
        logWrite(pareLogFile, bcolors.BOLD + 'Adding new slave node to redis cluster : ' + clusterString + bcolors.ENDC)
        cmdStatus, cmdOutput = subprocess.getstatusoutput(clusterString)

        if cmdStatus == 0:
            logWrite(pareLogFile, bcolors.OKGREEN + 'Successfully added slave node to master ' + cMasterID + bcolors.ENDC)
            return True
        else:
            logWrite(pareLogFile, bcolors.FAIL + 'Failed to add slave node: ' + cmdOutput + bcolors.ENDC)
            return False
    else:
        logWrite(pareLogFile, bcolors.FAIL + 'Cannot ping the new node at ' + serverIP + ':' + serverPORT + bcolors.ENDC)
        return False


def getMasterNodesID():
    print('Master Node IDs :')
    pongNumber = 0
    nonPongNumber = 0
    for pareNode in pareNodes:
        nodeIP = pareNode[0][0]
        portNumber = pareNode[1][0]
        if pareNode[4]:
            isPing = pingredisNode(nodeIP, portNumber)
            if isPing:
                os.system(redisConnectCmd(nodeIP, portNumber, ' cluster nodes | grep master'))
                break



def startNode(nodeIP, nodeNumber, portNumber, dedicateCpuCores,redis_version=None):
    startResult = 1
    # Get the latest redisVersion if not explicitly provided
    if redis_version is None:
        import importlib
        importlib.reload(sys.modules['pareConfig'])
        from pareConfig import redisVersion
        redis_version = redisVersion

    startResult = 1

    # Build the correct Redis binary path
    redis_binary_path = redisBinaryBase + 'redis-' + redis_version + '/src/redis-server'

    if pingredisNode(nodeIP, portNumber):
        logWrite(pareLogFile,
                 bcolors.WARNING + ':: ' + nodeIP + ' :: WARNING !!! redis node  ' + nodeNumber + ' has been  already started. The process was canceled.' + bcolors.ENDC)
    else:
        if is_local_server(nodeIP):
            if dedicateCore:
                start_cmd = 'cd ' + redisDataDir + ';numactl --physcpubind=' + dedicateCpuCores + ' --localalloc ' + redis_binary_path + ' ' + redisConfigDir + 'node' + nodeNumber + '/redisN' + nodeNumber + '_P' + portNumber + '.conf'
                print(start_cmd)  # Print the command for debugging
                startResult, startOutput = subprocess.getstatusoutput(start_cmd)

                # Log both success and error output
                if startResult != 0:
                    logWrite(pareLogFile,
                        bcolors.FAIL + ':: ' + nodeIP + ' :: ERROR starting redis node ' + nodeNumber + ': ' + startOutput + bcolors.ENDC)
                    print(bcolors.FAIL + 'Error output: ' + startOutput + bcolors.ENDC)
            else:
                start_cmd = 'cd ' + redisDataDir + ';' + redis_binary_path + ' ' + redisConfigDir + 'node' + nodeNumber + '/redisN' + nodeNumber + '_P' + portNumber + '.conf'
                print(start_cmd)  # Print the command for debugging
                startResult, startOutput = subprocess.getstatusoutput(start_cmd)

                # Log both success and error output
                if startResult != 0:
                    logWrite(pareLogFile,
                        bcolors.FAIL + ':: ' + nodeIP + ' :: ERROR starting redis node ' + nodeNumber + ': ' + startOutput + bcolors.ENDC)
                    print(bcolors.FAIL + 'Error output: ' + startOutput + bcolors.ENDC)
        else:
            if dedicateCore:
                start_cmd = 'ssh -q -o "StrictHostKeyChecking no"  ' + pareOSUser + '@' + nodeIP + ' -C  "cd ' + redisDataDir + ';numactl --physcpubind=' + dedicateCpuCores + ' --localalloc ' + redis_binary_path + ' ' + redisConfigDir + 'node' + nodeNumber + '/redisN' + nodeNumber + '_P' + portNumber + '.conf"'
                print(start_cmd)  # Print the command for debugging
                startResult, startOutput = subprocess.getstatusoutput(start_cmd)

                # Log both success and error output
                if startResult != 0:
                    logWrite(pareLogFile,
                        bcolors.FAIL + ':: ' + nodeIP + ' :: ERROR starting redis node ' + nodeNumber + ': ' + startOutput + bcolors.ENDC)
                    print(bcolors.FAIL + 'Error output: ' + startOutput + bcolors.ENDC)
            else:
                start_cmd = 'ssh -q -o "StrictHostKeyChecking no"  ' + pareOSUser + '@' + nodeIP + ' -C  "cd ' + redisDataDir + ';' + redis_binary_path + ' ' + redisConfigDir + 'node' + nodeNumber + '/redisN' + nodeNumber + '_P' + portNumber + '.conf"'
                print(start_cmd)  # Print the command for debugging
                startResult, startOutput = subprocess.getstatusoutput(start_cmd)

                # Log both success and error output
                if startResult != 0:
                    logWrite(pareLogFile,
                        bcolors.FAIL + ':: ' + nodeIP + ' :: ERROR starting redis node ' + nodeNumber + ': ' + startOutput + bcolors.ENDC)
                    print(bcolors.FAIL + 'Error output: ' + startOutput + bcolors.ENDC)

        if startResult == 0:
            logWrite(pareLogFile,
                     bcolors.OKGREEN + ':: ' + nodeIP + ' :: OK -> redis node  ' + nodeNumber + ' started.' + bcolors.ENDC)
            logWrite(pareLogFile,
                     bcolors.BOLD + ':: ' + nodeIP + ' :: checking... -> redis node : ' + nodeNumber + bcolors.ENDC)
            sleep(5)
            pingStatus, pingResponse = subprocess.getstatusoutput(redisConnectCmd(nodeIP, portNumber, ' ping '))
            if pingStatus == 0 & pingResponse.find('PONG') > -1:
                logWrite(pareLogFile,
                         bcolors.OKGREEN + ':: ' + nodeIP + ' :: OK  -> redis node : ' + nodeNumber + bcolors.ENDC)
            else:
                logWrite(pareLogFile,
                         bcolors.FAIL + ':: ' + nodeIP + ' :: WARNING !!! redis node  ' + nodeNumber + ' WAS NOT PING. CHECK IT.' + bcolors.ENDC)
        else:
            # Enhanced error reporting
            logWrite(pareLogFile,
                     bcolors.FAIL + ':: ' + nodeIP + ' :: WARNING !!! redis node  ' + nodeNumber + ' DID NOT start. CHECK IT.' + bcolors.ENDC)

            # Check for common error conditions
            try:
                # Verify directory and file permissions
                if is_local_server(nodeIP):
                    config_path = redisConfigDir + 'node' + nodeNumber + '/redisN' + nodeNumber + '_P' + portNumber + '.conf'
                    if not os.path.exists(config_path):
                        logWrite(pareLogFile,
                                bcolors.FAIL + 'ERROR: Config file does not exist: ' + config_path + bcolors.ENDC)

                    # Check if the binary exists
                    if not os.path.exists(redis_binary_path):
                        logWrite(pareLogFile,
                                bcolors.FAIL + 'ERROR: Redis server binary does not exist: ' + redis_binary_path + bcolors.ENDC)

                    # Try to get more info by running redis-server with the config directly
                    check_cmd = redis_binary_path + ' ' + config_path + ' --test-conf'
                    logWrite(pareLogFile,
                            bcolors.BOLD + 'Running config check: ' + check_cmd + bcolors.ENDC)
                    check_status, check_output = subprocess.getstatusoutput(check_cmd)
                    logWrite(pareLogFile,
                            bcolors.BOLD + 'Config check result: ' + check_output + bcolors.ENDC)
            except Exception as e:
                logWrite(pareLogFile,
                        bcolors.FAIL + 'Error during troubleshooting: ' + str(e) + bcolors.ENDC)


def switchMasterSlave(nodeIP, nodeNumber, portNumber):
    if isNodeMaster(nodeIP, nodeNumber, portNumber):
        processStatus, processResponse = subprocess.getstatusoutput(
            redisConnectCmd(nodeIP, portNumber, ' info replication | grep slave0'))
        spStatus = 1
        if processResponse.find('online') > 0:
            cutCursor1 = processResponse.find('ip=')
            processResponse = processResponse[cutCursor1 + 3:]
            cutCursor2 = processResponse.find(',')
            slaveIP = processResponse[:cutCursor2]
            processResponse = processResponse[cutCursor2:]
            cutCursor3 = processResponse.find('port=')
            processResponse = processResponse[cutCursor3 + 5:]
            cutCursor4 = processResponse.find(',')
            slavePort = processResponse[:cutCursor4]
            logWrite(pareLogFile,
                     bcolors.WARNING + 'Master/slave switch process is starting... This might take some times' + bcolors.ENDC)
            spStatus, spResponse = subprocess.getstatusoutput(redisConnectCmd(slaveIP, slavePort, ' CLUSTER FAILOVER '))
            # sleep(20)
            if spStatus == 0:
                turnWhile = True
                while turnWhile:
                    spStat, spResp = subprocess.getstatusoutput(
                        redisConnectCmdwithTimeout(slaveIP, slavePort, ' INFO replication '))
                    if spResp.find('role:master') > -1:
                        turnWhile = False
                        logWrite(pareLogFile, bcolors.OKGREEN + 'Switch master/slave command successed.' + bcolors.ENDC)
                        logWrite(pareLogFile,
                                 bcolors.OKBLUE + 'New Slave  IP:PORT ' + nodeIP + ':' + portNumber + bcolors.ENDC)
                        logWrite(pareLogFile,
                                 bcolors.OKBLUE + 'New Master IP:PORT ' + slaveIP + ':' + slavePort + bcolors.ENDC)
                        sleep(3)
                    else:
                        print(bcolors.WARNING + 'Switch master/slave continue... Please wait' + bcolors.ENDC)
                        sleep(5)

                return True
            else:
                logWrite(pareLogFile, bcolors.FAIL + '!!! Switch master/slave command failed. !!!' + bcolors.ENDC)
                return False

        else:
            logWrite(pareLogFile, bcolors.FAIL + '!!! There is no designated slave for node :' + str(
                nodeNumber) + ' . Operation was canceled !!!' + bcolors.ENDC)
            return False
    else:
        logWrite(pareLogFile, bcolors.FAIL + '!!!This node is not Master. The process canceled!!!' + bcolors.ENDC)
        return False


def killNode(nodeIP, nodeNumber, portNumber):
    processResponse = ''
    processID = 'NULL'
    killNode = 'NO'
    hasSlave = False

    # Use slaveORMasterNode instead of isNodeMaster for more reliable role identification
    if slaveORMasterNode(nodeIP, portNumber) == 'M':
        myResponse = input(
            bcolors.FAIL + "\nThis node is Master node( nodeIP:" + nodeIP + " nodePort:" + portNumber + "), Do you want to stop this node (yes/no): " + bcolors.ENDC)
        myResponse = myResponse.lower()
        if myResponse == 'yes':
            if isNodeHasSlave(nodeIP, nodeNumber, portNumber):
                isSwitch = switchMasterSlave(nodeIP, nodeNumber, portNumber)
                if isSwitch:
                    killNode = 'YES'
                else:
                    myResponse = input(
                        bcolors.FAIL + "\n Switching Master to slave failed \n Do you want to continue (force kill) ? "
                                       "(yes/no): " + bcolors.ENDC)
                    if myResponse == 'yes':
                        killNode = 'YES'
                    elif myResponse == 'no':
                        print(bcolors.WARNING + ' You canceled stopping process.' + bcolors.ENDC)
                        sleep(2)
                    else:
                        print(bcolors.FAIL + 'You entered wrong value :' + myResponse + bcolors.ENDC)
            else:
                myResponse = input(
                    "\n!!!! This node is Master node, and has no slave !!!!!\n !!!! which means that redis cluster will be DOWN(FAIL) !!!!!\n Do you want to continue ? (yes/no): " + bcolors.ENDC)
                myResponse = myResponse.lower()
                if myResponse == 'yes':
                    killNode = 'YES'
                elif myResponse == 'no':
                    print(bcolors.WARNING + ' You canceled stopping process.' + bcolors.ENDC)
                    sleep(2)
                else:
                    print(bcolors.FAIL + 'You entered wrong value :' + myResponse + bcolors.ENDC)
                    sleep(2)
        elif myResponse == 'no':
            killNode = 'NO'
            print(bcolors.WARNING + ' You canceled stopping process.' + bcolors.ENDC)
            sleep(3)
        else:
            print(bcolors.FAIL + 'You entered wrong value :' + myResponse + bcolors.ENDC)
    else:
        # This is a slave node, no need to confirm
        killNode = 'YES'

    processStatus, processResponse = subprocess.getstatusoutput(
        redisConnectCmd(nodeIP, portNumber, ' info server | grep process_id:'))
    prCursor = processResponse.find('process_id:')
    processID = processResponse[prCursor + 11:].strip()  # Extract process ID
    if is_local_server(nodeIP) and processID != 'NULL' and killNode == 'YES':
        killResult = os.system('kill ' + processID + ' ')
        turnWhile = True
        while turnWhile:
            killResult, killOutput = subprocess.getstatusoutput(
                'ps -ef | grep redis-server | grep "' + processID + ' " | grep -v "grep"')
            if killOutput.find(processID) > -1:
                print(bcolors.WARNING + '!!! Redis Node Stopping process continue... !!! Please wait. ' + bcolors.ENDC)
                sleep(5)
            else:
                logWrite(pareLogFile, bcolors.BOLD + '!!! Redis Node Stopped !!! ' + bcolors.ENDC)
                turnWhile = False

        sleep(2)
    elif not is_local_server(nodeIP) and processID != 'NULL' and killNode == 'YES':
        killResult = os.system(
            'ssh -q -o "StrictHostKeyChecking no"  ' + pareOSUser + '@' + nodeIP + ' -C  "kill  ' + processID + '"')
        turnWhile = True
        while turnWhile:
            killResult, killOutput = subprocess.getstatusoutput(
                'ssh -q -o "StrictHostKeyChecking no"  ' + pareOSUser + '@' + nodeIP + ' -C  "ps -ef | grep redis-server"  | grep ' + processID + ' | grep -v "grep"')
            if killOutput.find(processID) > -1:
                print(bcolors.WARNING + '!!! Redis Node Stopping process continue... !!! Please wait. ' + bcolors.ENDC)
                sleep(5)
            else:
                logWrite(pareLogFile, bcolors.BOLD + '!!! Redis Node Stopped !!! ' + bcolors.ENDC)
                turnWhile = False
        sleep(2)
    else:
        print('!!!The process canceled!!!')


def stopNode(nodeIP, nodeNumber, portNumber, non_interactive=False):
    stopResult = 1
    if pingredisNode(nodeIP, portNumber):
        if non_interactive:
            # Non-interactive version for web interface
            kill_node_non_interactive(nodeIP, nodeNumber, portNumber)
        else:
            killNode(nodeIP, nodeNumber, portNumber)
    else:
        logWrite(pareLogFile,
                 bcolors.FAIL + ':: ' + nodeIP + ' :: WARNING !!! redis node  ' + nodeNumber + 'has been already '
                                                                                               'stopped. The process '
                                                                                               'was canceled.' +
                 bcolors.ENDC)


def kill_node_non_interactive(nodeIP, nodeNumber, portNumber):
    """Non-interactive version of killNode for web interface"""
    processID = 'NULL'

    # Get the process ID
    processStatus, processResponse = subprocess.getstatusoutput(
        redisConnectCmd(nodeIP, portNumber, ' info server | grep process_id:'))

    if processStatus == 0 and 'process_id:' in processResponse:
        prCursor = processResponse.find('process_id:')
        processID = processResponse[prCursor + 11:].strip()  # Extract process ID

        logWrite(pareLogFile, f'Stopping Redis node {nodeIP}:{portNumber} (process ID: {processID})')

        if is_local_server(nodeIP):
            # Local node
            killResult = os.system(f'kill {processID}')
            wait_for_process_end(processID)
        else:
            # Remote node
            killResult = os.system(
                f'ssh -q -o "StrictHostKeyChecking no" {pareOSUser}@{nodeIP} -C "kill {processID}"')
            wait_for_remote_process_end(nodeIP, processID)

        logWrite(pareLogFile, bcolors.BOLD + '!!! Redis Node Stopped !!! ' + bcolors.ENDC)


def wait_for_process_end(processID, max_attempts=12):
    """Wait for a process to end, checking every 5 seconds"""
    for i in range(max_attempts):
        killResult, killOutput = subprocess.getstatusoutput(
            f'ps -ef | grep redis-server | grep "{processID} " | grep -v "grep"')

        if killOutput.find(processID) == -1:
            return True  # Process has ended

        logWrite(pareLogFile, bcolors.WARNING + f'!!! Redis Node Stopping process continue... (attempt {i+1}/{max_attempts}) !!! Please wait.' + bcolors.ENDC)
        sleep(5)

    logWrite(pareLogFile, bcolors.FAIL + f'!!! Redis Node may still be running (PID: {processID}) after {max_attempts} attempts !!!' + bcolors.ENDC)
    return False


def wait_for_remote_process_end(nodeIP, processID, max_attempts=12):
    """Wait for a process to end on a remote server, checking every 5 seconds"""
    for i in range(max_attempts):
        killResult, killOutput = subprocess.getstatusoutput(
            f'ssh -q -o "StrictHostKeyChecking no" {pareOSUser}@{nodeIP} -C "ps -ef | grep redis-server | grep {processID} | grep -v grep"')

        if not killOutput.strip():
            return True  # Process has ended

        logWrite(pareLogFile, bcolors.WARNING + f'!!! Remote Redis Node Stopping process continue... (attempt {i+1}/{max_attempts}) !!! Please wait.' + bcolors.ENDC)
        sleep(5)

    logWrite(pareLogFile, bcolors.FAIL + f'!!! Remote Redis Node may still be running (PID: {processID}) after {max_attempts} attempts !!!' + bcolors.ENDC)
    return False


def restartNode(nodeIP, nodeNumber, portNumber, dedicateCpuCores, redis_version=None):
    stopNode(nodeIP, nodeNumber, portNumber)
    startNode(nodeIP, nodeNumber, portNumber, dedicateCpuCores, redis_version)


def logWrite(logfile, message):
    """
    Write a message to the specified log file and print to console.

    Args:
        logfile: The path to the log file
        message: The message to write to the log file
    """
    try:
        with open(logfile, 'a') as f:
            f.write(f"{message}\n")
        print(message)  # Also print to console
    except Exception as e:
        print(f"Error writing to log file: {e}")


# Make sure pareLogFile is defined
if 'pareLogFile' not in globals():
    pareLogFile = "/tmp/paredicma.log"

def redisBinaryCopier(myServerIP, myRedisVersion):
    if is_local_server(myServerIP):
        # Check if the directory exists locally
        if not makeDir(redisBinaryDir):
            return False

        cmdStatus, cmdResponse = subprocess.getstatusoutput(
            f'cp -pr redis-{myRedisVersion}/* {redisBinaryDir}'
        )
        if cmdStatus == 0:
            logWrite(pareLogFile,
                     bcolors.OKGREEN + f':: {myServerIP} :: OK -> redis binary was copied.' + bcolors.ENDC)
            return True
        else:
            logWrite(pareLogFile,
                     bcolors.FAIL + ' !!! A problem occurred while copying binary files locally !!!' + bcolors.ENDC)
            return False
    else:
        # Check if the directory exists remotely
        if not makeRemoteDir(redisBinaryDir, myServerIP):
            return False

        # Replace scp with rsync for remote copying
        cmdStatus, cmdResponse = subprocess.getstatusoutput(
            f'rsync -aqz redis-{myRedisVersion}/ {pareOSUser}@{myServerIP}:{redisBinaryDir}'
        )
        if cmdStatus == 0:
            logWrite(pareLogFile,
                     bcolors.OKGREEN + f':: {myServerIP} :: OK -> redis binary was copied via rsync.' + bcolors.ENDC)
            return True
        else:
            logWrite(pareLogFile,
                     bcolors.FAIL + ' !!! A problem occurred while copying binary files remotely using rsync !!!' + bcolors.ENDC)
            return False


def redisNewBinaryCopier(myServerIP, myRedisVersion):
    global redisBinaryDir
    global redisVersion
    redisBinaryDir = redisBinaryDir.replace('redis-' + redisVersion, 'redis-' + myRedisVersion)

    if is_local_server(myServerIP):
        # Check if the directory exists locally
        if not makeDir(redisBinaryDir):
            logWrite(pareLogFile,
                     bcolors.FAIL + ' !!! A problem occurred while creating local binary directory !!!' + bcolors.ENDC)
            return False

        # Replace cp with rsync for local copying to prevent failures with busy files
        cmdStatus = os.system('rsync -a redis-' + myRedisVersion + '/ ' + redisBinaryDir + ' > /dev/null')

        if cmdStatus == 0:
            logWrite(pareLogFile,
                     bcolors.OKGREEN + ':: ' + myServerIP + ' :: OK -> redis binary was copied.' + bcolors.ENDC)
            return True

        else:
            logWrite(pareLogFile,
                     bcolors.FAIL + ' !!! A problem occurred while copying binary files !!!' + bcolors.ENDC)
            return False
    else:
        # Check if the directory exists remotely
        if not makeRemoteDir(redisBinaryDir, myServerIP):
            logWrite(pareLogFile,
                     bcolors.FAIL + ' !!! A problem occurred while creating remote binary directory !!!' + bcolors.ENDC)
            return False

        # Replace scp with rsync
        cmdStatus = os.system(
            'rsync -aqz redis-' + myRedisVersion + '/ ' + pareOSUser + '@' + myServerIP + ':' + redisBinaryDir)
        if cmdStatus == 0:
            logWrite(pareLogFile,
                     bcolors.OKGREEN + ':: ' + myServerIP + ' :: OK -> redis binary was copied.' + bcolors.ENDC)

            return True
        else:
            logWrite(pareLogFile,
                     bcolors.FAIL + ' !!! A problem occurred while copying binary files using rsync !!!' + bcolors.ENDC)
            return False


def compileRedis(redisTarFileName, redisCurrentVersion):
    compileStatus = False
    isExtract, comResponse = subprocess.getstatusoutput('tar -xvf ' + redisTarFileName)
    if isExtract == 0:
        logWrite(pareLogFile,
                 bcolors.OKGREEN + ' ::' + redisTarFileName + ' was extracted.\nplease wait, the process (compile '
                                                              'Redis - make) continue...' + bcolors.ENDC)
        os.system('cd redis-' + redisCurrentVersion)
        compileResponse = subprocess.getoutput('cd redis-' + redisCurrentVersion + ';make')
        # os.system('pwd')
        if compileResponse.find('make test') != -1:
            logWrite(pareLogFile, bcolors.OKGREEN + ' :: OK ->  redis was compiled.' + bcolors.ENDC)
            doMakeTest = input(bcolors.BOLD + '\n Do you want to "make test" Press (yes/no): ' + bcolors.ENDC)
            doMakeTest = doMakeTest.lower()
            if doMakeTest == 'yes':
                logWrite(pareLogFile,
                         bcolors.WARNING + 'please wait, the process (compile test - make test ) continue...' + bcolors.ENDC)
                compileResponseTest = subprocess.getoutput('cd redis-' + redisCurrentVersion + ';make test')
                if compileResponseTest.find('All tests passed') != -1:
                    # print ("step 3")
                    logWrite(pareLogFile, bcolors.OKGREEN + ' :: OK -> redis make test is successfull.' + bcolors.ENDC)
                    compileStatus = True
                else:
                    doContinue = input(
                        bcolors.FAIL + '!!! A problem was occurred, during "make test". \n You should run command  '
                                       '"make test" manually on another screen then you should continue from here.  '
                                       '\n Do you want to continue? Press (yes/no): ' + bcolors.ENDC)
                    doContinue = doContinue.lower()
                    if doContinue == 'yes':
                        compileStatus = True
                    else:
                        compileStatus = False
            elif doMakeTest == 'no':
                compileStatus = True
                logWrite(pareLogFile, bcolors.WARNING + 'You entered "no" . "make test" canceled.' + bcolors.ENDC)
            else:
                compileStatus = True
                logWrite(pareLogFile,
                         bcolors.WARNING + ' !!! You entered wrong value. "make test" canceled !!!' + bcolors.ENDC)
    return compileStatus


def compileRedisRemote(serverIP, redisTarFileName, redisCurrentVersion):
    """
    Compiles Redis on a remote server.
    This is necessary when remote servers have different architectures (e.g., Linux vs macOS).
    The tar file is copied to the remote server and compiled there.
    
    Returns True if compilation was successful, False otherwise.
    """
    if is_local_server(serverIP):
        logWrite(pareLogFile,
                 bcolors.WARNING + f' ::{serverIP}:: Skipping remote compile - this is the local server.' + bcolors.ENDC)
        return True
    
    logWrite(pareLogFile,
             bcolors.BOLD + f' ::{serverIP}:: Starting remote Redis compilation...' + bcolors.ENDC)
    
    # Check if tar file exists locally
    if not os.path.exists(redisTarFileName):
        logWrite(pareLogFile,
                 bcolors.FAIL + f' :: ERROR: Redis tar file not found: {redisTarFileName}' + bcolors.ENDC)
        return False
    
    # Create binary base directory on remote server
    if not makeRemoteDir(redisBinaryBase, serverIP):
        logWrite(pareLogFile,
                 bcolors.FAIL + f' ::{serverIP}:: Failed to create binary base directory: {redisBinaryBase}' + bcolors.ENDC)
        return False
    
    # Copy tar file to remote server
    logWrite(pareLogFile,
             bcolors.BOLD + f' ::{serverIP}:: Copying Redis tar file to remote server...' + bcolors.ENDC)
    
    scpStatus, scpOutput = subprocess.getstatusoutput(
        f'scp {redisTarFileName} {pareOSUser}@{serverIP}:{redisBinaryBase}')
    
    if scpStatus != 0:
        logWrite(pareLogFile,
                 bcolors.FAIL + f' ::{serverIP}:: Failed to copy tar file: {scpOutput}' + bcolors.ENDC)
        return False
    
    logWrite(pareLogFile,
             bcolors.OKGREEN + f' ::{serverIP}:: Tar file copied successfully.' + bcolors.ENDC)
    
    # Extract and compile on remote server
    logWrite(pareLogFile,
             bcolors.BOLD + f' ::{serverIP}:: Extracting and compiling Redis (this may take a few minutes)...' + bcolors.ENDC)
    
    remote_compile_cmd = (
        f'ssh -q -o "StrictHostKeyChecking no" {pareOSUser}@{serverIP} -C "'
        f'cd {redisBinaryBase} && '
        f'tar -xvf {redisTarFileName} && '
        f'cd redis-{redisCurrentVersion} && '
        f'make"'
    )
    
    compileStatus, compileOutput = subprocess.getstatusoutput(remote_compile_cmd)
    
    # Check for successful compilation (look for "make test" in output which indicates success)
    if 'make test' in compileOutput or 'Hint: It' in compileOutput:
        logWrite(pareLogFile,
                 bcolors.OKGREEN + f' ::{serverIP}:: Redis compiled successfully on remote server.' + bcolors.ENDC)
        
        # Verify the binary exists
        verify_cmd = (
            f'ssh -q -o "StrictHostKeyChecking no" {pareOSUser}@{serverIP} -C "'
            f'test -x {redisBinaryBase}redis-{redisCurrentVersion}/src/redis-server && echo EXISTS"'
        )
        verifyStatus, verifyOutput = subprocess.getstatusoutput(verify_cmd)
        
        if 'EXISTS' in verifyOutput:
            logWrite(pareLogFile,
                     bcolors.OKGREEN + f' ::{serverIP}:: Redis binary verified at {redisBinaryBase}redis-{redisCurrentVersion}/src/redis-server' + bcolors.ENDC)
            return True
        else:
            logWrite(pareLogFile,
                     bcolors.FAIL + f' ::{serverIP}:: Compilation appeared successful but binary not found!' + bcolors.ENDC)
            return False
    else:
        logWrite(pareLogFile,
                 bcolors.FAIL + f' ::{serverIP}:: Remote compilation failed. Output: {compileOutput[-500:]}' + bcolors.ENDC)
        return False


def redisConfMaker(nodeIP, nodeNumber, portNumber, maxMemorySize):
    redisConfigText = '#######This config file was generated by paredicma#######\n'
    redisConfigText += 'bind ' + nodeIP + '\n'
    redisConfigText += 'port ' + portNumber + '\n'
    redisConfigText += 'unixsocket "' + unixSocketDir + 'redisN' + nodeNumber + '_P' + portNumber + '.sock"\n'
    redisConfigText += 'pidfile "' + pidFileDir + 'redisN' + nodeNumber + '_P' + portNumber + '.pid"\n'
    redisConfigText += 'logfile "' + redisLogDir + 'redisN' + nodeNumber + '_P' + portNumber + '.log"\n'
    if rdb == 'on':
        redisConfigText += 'dbfilename  "dumpN' + nodeNumber + '_P' + portNumber + '.rdb"\n'
        redisConfigText += rdbValue + '\n'
    if aof == 'on':
        redisConfigText += 'appendonly yes\n'
        redisConfigText += 'appendfilename  "appendonlyN' + nodeNumber + '_P' + portNumber + '.aof"\n'
        redisConfigText += aofValue + '\n'
    if redisCluster == 'on':
        redisConfigText += 'cluster-enabled yes\n'
        redisConfigText += 'cluster-config-file "' + redisConfigDir + 'node' + nodeNumber + '/' + 'node' + nodeNumber + '_P' + portNumber + '.conf"\n'
        redisConfigText += clusterNodeTimeout + '\n'
        redisConfigText += clusterParameters + '\n'
    if maxMemory == 'on':
        redisConfigText += 'maxmemory ' + maxMemorySize + '\n'
    if redisPwdAuthentication == 'on':
        redisConfigText += 'requirepass "' + redisPwd + '"\n'
        redisConfigText += 'masterauth "' + redisPwd + '"'
    redisConfigText += redisParameters
    fileClearWrite(pareTmpDir + 'redisN' + nodeNumber + '_P' + portNumber + '.conf', redisConfigText)
    logWrite(pareLogFile,
             bcolors.OKGREEN + ' ::' + nodeIP + '::' + pareTmpDir + 'redisN' + nodeNumber + '_P' + portNumber + '.conf file was created.' + bcolors.ENDC)

    targetDir = redisConfigDir + 'node' + nodeNumber + '/'

    if is_local_server(nodeIP):
        # First verify target directory exists
        if not os.path.exists(targetDir):
            try:
                os.makedirs(targetDir)
                logWrite(pareLogFile,
                         bcolors.OKGREEN + ' ::' + nodeIP + ':: Directory created: ' + targetDir + bcolors.ENDC)
            except Exception as e:
                logWrite(pareLogFile,
                         bcolors.FAIL + ' ::' + nodeIP + ':: ERROR creating directory: ' + targetDir + ' - ' + str(e) + bcolors.ENDC)
                return False

        # Now copy the file
        copyStatus, copyOutput = subprocess.getstatusoutput(
            'cp -f ' + pareTmpDir + 'redisN' + nodeNumber + '_P' + portNumber + '.conf ' + targetDir)

        if copyStatus == 0:
            # Verify file was actually copied
            if os.path.exists(targetDir + 'redisN' + nodeNumber + '_P' + portNumber + '.conf'):
                logWrite(pareLogFile,
                     bcolors.OKGREEN + ' ::' + nodeIP + ':: redisN' + nodeNumber + '_P' + portNumber + '.conf file was copied.' + bcolors.ENDC)
                return True
            else:
                logWrite(pareLogFile,
                     bcolors.FAIL + ' ::' + nodeIP + ':: File copy appeared to succeed but file not found in destination! Check permissions.' + bcolors.ENDC)
                return False
        else:
            logWrite(pareLogFile,
                     bcolors.FAIL + ' ::' + nodeIP + ':: ERROR copying file: ' + copyOutput + bcolors.ENDC)
            return False
    else:
        # For remote nodes, first make sure the directory exists
        mkdirStatus, mkdirOutput = subprocess.getstatusoutput(
            'ssh -q -o "StrictHostKeyChecking no" ' + pareOSUser + '@' + nodeIP + ' -C "mkdir -p ' + targetDir + '"')

        if mkdirStatus != 0:
            logWrite(pareLogFile,
                     bcolors.FAIL + ' ::' + nodeIP + ':: ERROR creating directory on remote server: ' + mkdirOutput + bcolors.ENDC)
            return False

        # Now copy the file
        copyStatus, copyOutput = subprocess.getstatusoutput(
            'scp ' + pareTmpDir + 'redisN' + nodeNumber + '_P' + portNumber + '.conf ' + pareOSUser + '@' + nodeIP + ':' + targetDir)

        if copyStatus == 0:
            # Verify file was copied
            verifyStatus, verifyOutput = subprocess.getstatusoutput(
                'ssh -q -o "StrictHostKeyChecking no" ' + pareOSUser + '@' + nodeIP + ' -C "ls ' + targetDir + 'redisN' + nodeNumber + '_P' + portNumber + '.conf"')

            if verifyStatus == 0:
                logWrite(pareLogFile,
                         bcolors.OKGREEN + ' ::' + nodeIP + ':: redisN' + nodeNumber + '_P' + portNumber + '.conf file was copied.' + bcolors.ENDC)
                return True
            else:
                logWrite(pareLogFile,
                         bcolors.FAIL + ' ::' + nodeIP + ':: File copy appeared to succeed but file not found in destination! Check permissions. ' + verifyOutput + bcolors.ENDC)
                return False
        else:
            logWrite(pareLogFile,
                     bcolors.FAIL + ' ::' + nodeIP + ':: redisN' + nodeNumber + '_P' + portNumber + '.conf ERROR when file copy: ' + copyOutput + bcolors.ENDC)
            return False


def redisDirMaker(nodeIP, nodeNumber):
    """
    Creates the necessary directories for Redis on local or remote server.
    Returns True if all directories were successfully created, False otherwise.
    """
    directoryDone = True

    if is_local_server(nodeIP):
        # Local server
        directories = [
            redisDataDir,
            redisConfigDir,
            redisLogDir,
            redisBinaryDir,
            unixSocketDir,
            pidFileDir,
            redisConfigDir + 'node' + nodeNumber
        ]

        for directory in directories:
            if not makeDir(directory):
                logWrite(pareLogFile,
                         bcolors.FAIL + ' ::' + nodeIP + ':: Failed to create directory: ' + directory + bcolors.ENDC)
                directoryDone = False
    else:
        # Remote server
        print(bcolors.WARNING + 'Working on remote server...' + bcolors.ENDC)
        directories = [
            redisDataDir,
            redisConfigDir,
            redisLogDir,
            redisBinaryDir,
            unixSocketDir,
            pidFileDir,
            redisConfigDir + 'node' + nodeNumber
        ]

        for directory in directories:
            if not makeRemoteDir(directory, nodeIP):
                logWrite(pareLogFile,
                         bcolors.FAIL + ' ::' + nodeIP + ':: Failed to create directory: ' + directory + bcolors.ENDC)
                directoryDone = False

    return directoryDone


def makeRemoteDir(dir_name, nodeIP):
    try:
        # Check if the directory exists remotely
        isOK, checkOutput = subprocess.getstatusoutput(
            'ssh -q -o "StrictHostKeyChecking no" ' + pareOSUser + '@' + nodeIP + ' -C "if [ -d \'' + dir_name + '\' ]; then echo yesThereIs; else echo noThereIsNot; fi"'
        )

        # Check for connection issues
        if isOK != 0:
            logWrite(pareLogFile,
                     bcolors.FAIL + ' ::' + nodeIP + ':: SSH connection failed when checking directory: ' + dir_name + ' - ' + checkOutput + bcolors.ENDC)
            return False

        if 'yesThereIs' in checkOutput:
            # Directory already exists remotely
            logWrite(pareLogFile,
                     bcolors.WARNING + ' ::' + nodeIP + ':: Directory already exists = ' + dir_name + bcolors.ENDC)
            return True
        else:
            # Directory doesn't exist, create it remotely
            mkdirStatus, mkdirOutput = subprocess.getstatusoutput(
                'ssh -q -o "StrictHostKeyChecking no" ' + pareOSUser + '@' + nodeIP + ' -C "mkdir -p \'' + dir_name + '\'"'
            )

            if mkdirStatus == 0:
                logWrite(pareLogFile,
                         bcolors.OKGREEN + ' ::' + nodeIP + ':: Directory was created = ' + dir_name + bcolors.ENDC)
                return True
            else:
                logWrite(pareLogFile,
                         bcolors.FAIL + ' ::' + nodeIP + ':: Failed to create directory: ' + dir_name + ' - ' + mkdirOutput + bcolors.ENDC)
                return False

    except Exception as e:
        logWrite(pareLogFile,
                 bcolors.FAIL + ' ::' + nodeIP + ':: Error occurred while creating directory: ' + dir_name + ' - ' + str(e) + bcolors.ENDC)
        return False


def makeDir(dir_name):
    try:
        if os.path.isdir(dir_name):
            logWrite(pareLogFile, bcolors.WARNING + 'Directory already exists = ' + dir_name + bcolors.ENDC)
            return True
        else:
            os.makedirs(dir_name, exist_ok=True)
            logWrite(pareLogFile, bcolors.OKGREEN + 'Directory was created = ' + dir_name + bcolors.ENDC)
            return True
    except Exception as e:
        logWrite(pareLogFile,
                 bcolors.FAIL + '!!! Error occurred while creating directory !!! = ' + dir_name + ' - ' + str(e) + bcolors.ENDC)
        return False


def get_datetime():
    my_year = str(localtime()[0])
    my_mounth = str(localtime()[1])
    my_day = str(localtime()[2])
    my_hour = str(localtime()[3])
    my_min = str(localtime()[4])
    my_sec = str(localtime()[5])
    if len(str(my_mounth)) == 1:
        my_mounth = "0" + my_mounth
    if len(my_day) == 1:
        my_day = "0" + my_day
    if len(my_hour) == 1:
        my_hour = "0" + my_hour
    if len(my_min) == 1:
        my_min = "0" + my_min
    if len(my_sec) == 1:
        my_sec = "0" + my_sec
    return my_year + "." + my_mounth + "." + my_day + " " + my_hour + ":" + my_min + ":" + my_sec


def fileAppendWrite(file, writeText):
    try:
        with open(file, 'a') as fp:  # Open file in append mode ('a' for text mode)
            fp.write(writeText + '\n')  # Writing text along with a newline character
    except Exception as e:
        print(f"An error occurred while writing to the file {file}: {e}")


def fileRead(file):
    returnTEXT = ""
    try:
        fp = open(file, 'r')
        returnTEXT = fp.readlines()
        fp.close()
        return returnTEXT
    except:
        print(bcolors.FAIL + '!!! An error is occurred while reading file !!!' + bcolors.ENDC)
        return ""


def fileReadFull(file):
    returnTEXT = ""
    try:
        fp = open(file, 'r')
        returnTEXT = fp.read()
        fp.close()
        return returnTEXT
    except:
        print(bcolors.FAIL + '!!! An error is occurred while reading file !!!' + bcolors.ENDC)
        return ""


def fileClearWrite(file, writeText):
    try:
        with open(file, 'w') as fp:  # Open file in write mode ('w' for text mode)
            fp.write(writeText + '\n')  # Writing text along with a newline character
    except Exception as e:
        print(f"An error occurred while writing to the file {file}: {e}")


def logWrite(logFile, logText):
    if writePareLogFile:
        print(logText)
        logText = '* (' + get_datetime() + ') ' + logText
        fileAppendWrite(logFile, logText)
    else:
        print(logText)










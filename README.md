## Python Automatic REDIs Cluster MAnager & MAker

#### Paredicma is a comprehensive web-based tool for monitoring, managing, and maintaining Redis clusters. It provides an intuitive interface to perform complex Redis cluster operations through a simple web UI.

<img width="2048" height="2048" alt="image" src="https://github.com/user-attachments/assets/8f7fcbfb-03a0-4942-afca-0229d37218bf" />


## Python Automatic REDIs Cluster MAnager&MAker
This program was developed to make Redis Cluster installation, managament, upgrade and maintanence easier, especially for non-Docker environments. 

## Prerequirements:
sshd ( with passwordless ssh-keygen auth. between servers ),
numactl( if you want to use dedicate cpu-core )

cli: python 3.1 <br>
webview: python 3.8, fastapi, uvicorn

## 1- Download and extract :
Download -> paredicmaV2-master.zip
extract -> unzip paredicmaV2-master.zip
cd paredicmaV2-master

## 2- Installation :
You do not need to install it, Just configure and run it.

## 3- Configuration :
Configure pareNodeList.py file, change ip, port, cpu core and max_memory per node, according to your cluster.
Configure pareConfig.py file, according to your cluster

## 4 - run program
cli: python3.x paredicma-cli.py <br>
webview: ./run.sh

<img width="799" height="927" alt="image" src="https://github.com/user-attachments/assets/48357446-2c37-4bf2-990a-ffb993447c3a" />


## Version: 3.1             :
### Update Date             : 11.03.2025
### UpdatedBy               : Alper Yıldız 
### Release Note            : AI features, Session Management

## Version: 3.0
#### UpdateDate				: 30.11.2025
#### UpdatedBy				: Alper Yıldız
#### Release Note			: Cluster Maker Feature was added to Web View.


## Version: 2.5
#### UpdateDate				: 05.05.2025
#### UpdatedBy				: Alper Yıldız
#### Release Note			: Enhanced Management and Maintenance features, including Redis Cluster Upgrade.


## Version: 2.1
#### UpdateDate				: 27.02.2024
#### UpdatedBy				: Alper Yıldız
#### Release Note			: Web View Support with FastAPI (Monitoring Section)

## Version: 2.0 
#### UpdateDate				: 07.12.2023
#### UpdatedBy				: Alper Yıldız
#### Release Note			: Python3 support
#### Software Requirement	: Python3.x or above, sshd( with passwordless ssh-keygen auth. between servers ), numactl 
#### OS System 				: Redhat/Centos 7+ ( possible Ubuntu, debian )

## Version: 1.0 
#### Author				: Mustafa YAVUZ
#### E-mail				: msyavuz@gmail.com


<br>

© 2026 GitHub, Inc.

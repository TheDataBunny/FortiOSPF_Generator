# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Fortinet OSPF configuration generator for network automation. The project creates optimized OSPF configurations for Fortigate firewalls with intelligent route summarization to reduce OSPF table size and improve network efficiency.

## Commands

### Running the Generator
```bash
# Basic usage with default output filename
python ospf_generator.py <input_file>

# Specify custom output filename  
python ospf_generator.py <input_file> <output_file>

# Examples
python ospf_generator.py ospf-networks.txt
python ospf_generator.py ospf-networks.txt custom-config.txt
```

## Architecture

Single-file Python application following a clear pipeline pattern: Parse → Optimize → Generate

### Core Components

1. **OSPFConfigParser**: Parses input files containing network definitions and interface settings
2. **NetworkSummarizer**: Advanced route summarization engine with dual-phase algorithm:
   - Phase 1: Major network block summarization (/8, /16, /24 boundaries)  
   - Phase 2: Contiguous network block detection using `ipaddress.collapse_addresses()`
   - Hierarchical processing prevents conflicting summaries
   - Efficiency validation ensures meaningful route reduction
3. **FortigateConfigGenerator**: Produces FortiOS CLI syntax with optimized configurations

### Data Models
- **OSPFInterface** (dataclass): Interface configuration with cost, authentication, passive mode
- **OSPFConfig** (dataclass): Container for router ID, areas, networks, and interfaces

### Input File Formats

**Standard Format** (`ospf-networks.txt`):
```
OSPF Router ID: x.x.x.x
Areas: x.x.x.x

Interfaces
Name: <interface_name>
Interface: <interface_id>  
Cost: <cost_value>
Authentication: <auth_type>
Passive: <enabled/disabled>

<network_ip>/<cidr>
<network_ip>/<cidr>
...
```

**Simple Format** (legacy):
```
OSPF Router ID: x.x.x.x
Areas: x.x.x.x
<network_ip>/<cidr>
...
```

### Output Structure

Generated configurations include:
- Router ID and OSPF area definitions
- Network statements using summarized prefixes
- OSPF interface configurations (cost, priority, authentication, passive mode)
- Summary address advertisements for LSA optimization
- Detailed summarization report showing efficiency gains

## Summarization Algorithm

The NetworkSummarizer implements a sophisticated dual-phase approach:

**Phase 1 - Major Network Summarization** (`_find_major_network_summaries`):
- Groups networks by first 2 octets for /16 boundaries (172.16.x.x → 172.16.0.0/16)
- Groups networks by first 3 octets for /24 boundaries  
- Uses hierarchical processing to prevent conflicting summaries
- Only creates summaries when multiple networks exist in the same block

**Phase 2 - Contiguous Block Detection** (`_find_contiguous_summaries`):
- Processes remaining unsummarized networks using `ipaddress.collapse_addresses()`
- Applies efficiency validation (prevents summaries larger than /28)
- Ensures meaningful route reduction before creating summaries

### Typical Results
- 62-75% route reduction efficiency on mixed network topologies  
- Automatic handling of point-to-point links (/30) and subnets (/28, /24)
- Preserves granular routes when summarization wouldn't provide benefit
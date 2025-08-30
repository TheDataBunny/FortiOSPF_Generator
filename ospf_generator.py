#!/usr/bin/env python3
"""
OSPF Configuration Generator for Fortigate
Generates optimized OSPF configurations with route summarization
"""

import ipaddress
import re
import sys
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass


@dataclass
class OSPFInterface:
    name: str
    interface: str
    cost: int
    authentication: str = "none"
    passive: bool = False
    priority: int = 1


@dataclass 
class OSPFConfig:
    router_id: str
    areas: List[str]
    networks: List[str]
    interfaces: List[OSPFInterface]


class NetworkSummarizer:
    """Handles network summarization logic"""
    
    @staticmethod
    def find_summary_routes(networks: List[str]) -> Dict[str, List[str]]:
        """Find networks that can be summarized together"""
        summaries = {}
        network_objects = []
        
        # Parse all networks
        for net in networks:
            try:
                network_objects.append(ipaddress.ip_network(net, strict=False))
            except ValueError:
                continue
        
        if not network_objects:
            return summaries
            
        # Sort networks for better processing
        network_objects.sort(key=lambda x: (x.network_address, x.prefixlen))
        
        # Try multiple summarization strategies
        summaries.update(NetworkSummarizer._find_major_network_summaries(network_objects))
        summaries.update(NetworkSummarizer._find_contiguous_summaries(network_objects, summaries))
        
        return summaries
    
    @staticmethod
    def _find_major_network_summaries(networks: List[ipaddress.IPv4Network]) -> Dict[str, List[str]]:
        """Find precise summaries using optimal prefix lengths instead of fixed boundaries"""
        summaries = {}
        
        # Use a more systematic approach to find optimal summaries
        # Group networks by major network classes first, then find optimal summaries within each group
        major_groups = NetworkSummarizer._group_by_major_network_class(networks)
        
        for group_networks in major_groups:
            if len(group_networks) < 2:
                continue
                
            # Find the optimal summary for this group using progressive refinement
            optimal_summary = NetworkSummarizer._find_tightest_summary(group_networks)
            if optimal_summary:
                summary_net, original_nets = optimal_summary
                summaries[summary_net] = original_nets
                        
        return summaries
    
    @staticmethod
    def _group_by_major_network_class(networks: List[ipaddress.IPv4Network]) -> List[List[ipaddress.IPv4Network]]:
        """Group networks by major network classes (10.x, 172.16.x, 192.168.x, etc.)"""
        groups = {}
        
        for net in networks:
            # Determine the major network class
            addr_bytes = net.network_address.packed
            
            if addr_bytes[0] == 10:
                # Class A private (10.0.0.0/8)
                key = "10"
            elif addr_bytes[0] == 172 and 16 <= addr_bytes[1] <= 31:
                # Class B private (172.16.0.0/12 - 172.31.0.0/12)
                key = f"172.{addr_bytes[1]}"
            elif addr_bytes[0] == 192 and addr_bytes[1] == 168:
                # Class C private (192.168.0.0/16)
                key = "192.168"
            else:
                # Other networks - group by first two octets
                key = f"{addr_bytes[0]}.{addr_bytes[1]}"
            
            if key not in groups:
                groups[key] = []
            groups[key].append(net)
        
        # Return only groups with multiple networks
        return [group for group in groups.values() if len(group) > 1]
    
    @staticmethod
    def _find_tightest_summary(group_networks: List[ipaddress.IPv4Network]) -> Optional[Tuple[str, List[str]]]:
        """Find the tightest possible summary for a group of networks"""
        if len(group_networks) < 2:
            return None
            
        try:
            # Sort networks by network address
            sorted_networks = sorted(group_networks, key=lambda x: x.network_address)
            
            # Try to find the optimal summary using Python's collapse_addresses first
            collapsed = list(ipaddress.collapse_addresses(sorted_networks))
            if len(collapsed) == 1:
                summary_net = collapsed[0]
                # Verify this actually provides summarization benefit
                if summary_net.prefixlen < min(net.prefixlen for net in sorted_networks):
                    original_nets = [str(net) for net in sorted_networks]
                    return str(summary_net), original_nets
            
            # If collapse_addresses doesn't work, manually find the tightest summary
            min_addr = min(net.network_address for net in sorted_networks)
            max_addr = max(net.broadcast_address for net in sorted_networks)
            
            # Find the shortest prefix length that contains the range from min to max
            best_summary = None
            best_efficiency = 0
            
            for prefix_len in range(8, 29):  # Test from /8 to /28
                try:
                    # Create a summary network with this prefix length
                    summary_candidate = ipaddress.ip_network(f"{min_addr}/{prefix_len}", strict=False)
                    
                    # Check if this summary contains all our networks
                    if all(net.subnet_of(summary_candidate) for net in sorted_networks):
                        # Calculate efficiency
                        used_addresses = sum(net.num_addresses for net in sorted_networks)
                        total_addresses = summary_candidate.num_addresses
                        efficiency = used_addresses / total_addresses
                        
                        # Check if this is actually a summarization (smaller prefix than originals)
                        if prefix_len < min(net.prefixlen for net in sorted_networks):
                            # Keep track of the most efficient valid summary
                            if efficiency > best_efficiency:
                                best_efficiency = efficiency
                                best_summary = (str(summary_candidate), [str(net) for net in sorted_networks])
                            
                            # If we find a very efficient summary (>5%), take it immediately
                            if efficiency >= 0.05:
                                return str(summary_candidate), [str(net) for net in sorted_networks]
                        
                except ValueError:
                    continue
            
            # Return the best summary we found, even if efficiency is low
            # OSPF route reduction is valuable even with low efficiency
            if best_summary and best_efficiency > 0:
                return best_summary
                    
        except Exception:
            pass
            
        return None
    
    @staticmethod
    def _find_contiguous_summaries(networks: List[ipaddress.IPv4Network], existing_summaries: Dict[str, List[str]]) -> Dict[str, List[str]]:
        """Find contiguous network blocks that can be summarized"""
        summaries = {}
        
        # Get networks not already summarized
        already_summarized = set()
        for original_nets in existing_summaries.values():
            already_summarized.update(original_nets)
        
        remaining_networks = [net for net in networks if str(net) not in already_summarized]
        
        if len(remaining_networks) < 2:
            return summaries
        
        # Try to find contiguous blocks
        for i in range(len(remaining_networks)):
            for j in range(i + 1, len(remaining_networks)):
                try:
                    # Use ipaddress collapse_addresses for optimal summarization
                    pair_summary = list(ipaddress.collapse_addresses([remaining_networks[i], remaining_networks[j]]))
                    if len(pair_summary) == 1 and pair_summary[0].prefixlen < max(remaining_networks[i].prefixlen, remaining_networks[j].prefixlen):
                        summary_net = str(pair_summary[0])
                        original_nets = [str(remaining_networks[i]), str(remaining_networks[j])]
                        # Only add if it's a meaningful summarization (saves at least 1 route)
                        if pair_summary[0].prefixlen <= 28:  # Don't create summaries larger than /28
                            summaries[summary_net] = original_nets
                except:
                    continue
        
        return summaries

    @staticmethod
    def get_optimized_networks(networks: List[str]) -> Tuple[List[str], Dict[str, List[str]]]:
        """Return optimized network list and summary mappings"""
        summaries = NetworkSummarizer.find_summary_routes(networks)
        optimized = []
        summarized_networks = set()
        
        # Add summary routes
        for summary, original in summaries.items():
            optimized.append(summary)
            summarized_networks.update(original)
        
        # Add non-summarized networks
        for net in networks:
            if net not in summarized_networks:
                optimized.append(net)
                
        return optimized, summaries


class OSPFConfigParser:
    """Parses OSPF configuration files"""
    
    @staticmethod
    def parse_file(filename: str) -> OSPFConfig:
        """Parse OSPF configuration from input file"""
        config = OSPFConfig("", [], [], [])
        
        try:
            with open(filename, 'r') as file:
                content = file.read()
                
            lines = content.strip().split('\n')
            current_interface = None
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                # Parse router ID
                if line.startswith('OSPF Router ID:'):
                    config.router_id = line.split(':', 1)[1].strip()
                
                # Parse areas
                elif line.startswith('Areas:'):
                    areas = line.split(':', 1)[1].strip()
                    config.areas = [area.strip() for area in areas.split(',')]
                
                # Parse interface sections
                elif line.startswith('Name:'):
                    if current_interface:
                        config.interfaces.append(current_interface)
                    current_interface = OSPFInterface("", "", 1)
                    current_interface.name = line.split(':', 1)[1].strip()
                
                elif line.startswith('Interface:') and current_interface:
                    current_interface.interface = line.split(':', 1)[1].strip()
                
                elif line.startswith('Cost:') and current_interface:
                    current_interface.cost = int(line.split(':', 1)[1].strip())
                
                elif line.startswith('Authentication:') and current_interface:
                    current_interface.authentication = line.split(':', 1)[1].strip().lower()
                
                elif line.startswith('Passive:') and current_interface:
                    passive_val = line.split(':', 1)[1].strip().lower()
                    current_interface.passive = passive_val == 'enabled'
                
                # Parse networks (CIDR format)
                elif '/' in line and '.' in line:
                    try:
                        ipaddress.ip_network(line, strict=False)
                        config.networks.append(line)
                    except ValueError:
                        continue
            
            # Add the last interface if exists
            if current_interface:
                config.interfaces.append(current_interface)
                
        except FileNotFoundError:
            print(f"Error: File {filename} not found")
            sys.exit(1)
        except Exception as e:
            print(f"Error parsing file: {e}")
            sys.exit(1)
            
        return config


class FortigateConfigGenerator:
    """Generates Fortigate OSPF configuration"""
    
    @staticmethod
    def ip_to_netmask(network: str) -> Tuple[str, str]:
        """Convert CIDR to IP and netmask format"""
        net = ipaddress.ip_network(network, strict=False)
        return str(net.network_address), str(net.netmask)
    
    @staticmethod
    def generate_config(config: OSPFConfig, output_file: str):
        """Generate complete Fortigate OSPF configuration"""
        
        # Get optimized networks with summarization
        optimized_networks, summaries = NetworkSummarizer.get_optimized_networks(config.networks)
        
        output_lines = []
        output_lines.append("config router ospf")
        output_lines.append(f"    set router-id {config.router_id}")
        
        # Configure areas
        output_lines.append("    config area")
        for area in config.areas:
            output_lines.append(f'        edit "{area}"')
            output_lines.append("            set type regular")
            output_lines.append("        next")
        output_lines.append("    end")
        
        # Configure networks
        output_lines.append("    config network")
        for i, network in enumerate(optimized_networks, 1):
            ip, mask = FortigateConfigGenerator.ip_to_netmask(network)
            output_lines.append(f"        edit {i}")
            output_lines.append(f"            set prefix {ip} {mask}")
            output_lines.append(f"            set area {config.areas[0] if config.areas else '0.0.0.0'}")
            output_lines.append("        next")
        output_lines.append("    end")
        
        # Configure OSPF interfaces
        if config.interfaces:
            output_lines.append("    config ospf-interface")
            for interface in config.interfaces:
                output_lines.append(f'        edit "{interface.interface}"')
                output_lines.append(f"            set interface \"{interface.interface}\"")
                output_lines.append(f"            set cost {interface.cost}")
                output_lines.append(f"            set priority {interface.priority}")
                if interface.authentication != "none":
                    output_lines.append(f"            set authentication {interface.authentication}")
                else:
                    output_lines.append("            set authentication none")
                passive_setting = "enable" if interface.passive else "disable"
                output_lines.append(f"            set passive-interface {passive_setting}")
                output_lines.append("        next")
            output_lines.append("    end")
        
        # Configure summary addresses
        if summaries:
            output_lines.append("    config summary-address")
            for i, summary in enumerate(summaries.keys(), 1):
                ip, mask = FortigateConfigGenerator.ip_to_netmask(summary)
                output_lines.append(f"        edit {i}")
                output_lines.append(f"            set prefix {ip} {mask}")
                output_lines.append("            set advertise enable")
                output_lines.append("        next")
            output_lines.append("    end")
        
        output_lines.append("end")
        
        # Write to file
        try:
            with open(output_file, 'w') as f:
                f.write('\n'.join(output_lines))
            print(f"Configuration written to {output_file}")
            
            # Print summarization report
            if summaries:
                print(f"\nRoute Summarization Report:")
                print(f"Original networks: {len(config.networks)}")
                print(f"Optimized networks: {len(optimized_networks)}")
                print(f"Reduction: {len(config.networks) - len(optimized_networks)} routes")
                print(f"Efficiency: {((len(config.networks) - len(optimized_networks)) / len(config.networks) * 100):.1f}%")
                
                for summary, original in summaries.items():
                    print(f"\nSummary {summary} includes:")
                    for net in original:
                        print(f"  - {net}")
            
        except Exception as e:
            print(f"Error writing configuration: {e}")
            sys.exit(1)


def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python ospf_generator.py <input_file> [output_file]")
        print("Examples:")
        print("  python ospf_generator.py PD-Networks.txt")
        print("  python ospf_generator.py ospf-networks.txt custom-config.txt")
        sys.exit(1)
    
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else f"fortigate-{input_file.replace('.txt', '')}-config.txt"
    
    # Parse input configuration
    config = OSPFConfigParser.parse_file(input_file)
    
    if not config.router_id:
        print("Error: No OSPF Router ID found in input file")
        sys.exit(1)
    
    if not config.networks:
        print("Error: No networks found in input file")
        sys.exit(1)
    
    # Generate Fortigate configuration
    FortigateConfigGenerator.generate_config(config, output_file)


if __name__ == "__main__":
    main()
import dpkt
import socket
from datetime import datetime
import operator
from helpers import Output
import random
import collections

#### HELPER FUNCTIONS FROM 
#### http://dpkt.readthedocs.io/en/latest/_modules/examples/print_packets.html#mac_addr
#### With modification
def mac_addr(address):
    """Convert a MAC address to a readable/printable string

       Args:
           address (str): a MAC address in hex form (e.g. '\x01\x02\x03\x04\x05\x06')
       Returns:
           str: Printable/readable MAC address
    """
    result = ""
    for b in address:
        result += ':' + '%02x' % dpkt.compat.compat_ord(b)
    return result[1:]



def inet_to_str(inet):
    """Convert inet object to a string

        Args:
            inet (inet struct): inet network address
        Returns:
            str: Printable/readable IP address
    """
    # First try ipv4 and then ipv6
    try:
        return socket.inet_ntop(socket.AF_INET, inet)
    except ValueError:
        return socket.inet_ntop(socket.AF_INET6, inet)

#### MORE HELPERS
class IP_PROTOCOL():
    ICMP = 1
    TCP = 6
    UDP = 17
    



# the class to simulate a switch
class Switch:
    def __init__(self, id, timeout, to_file, **kwargs):
        self.id = id
        
        self.current_time = 0
        # should be same as timeout if it's less than 100
        self.dump_interval = timeout if timeout < 100 else 100 
        # last time statistic dump time
        # also used for check for timeout
        self.last_dump_time = 0 
        self.total_packets = 0
        self.missed = 0 # # of packets that needs to create a new flow for it
        self.to_file = to_file
        if self.to_file:
            filename = "log_" + str(self.id)
            self.outfile = open(filename, "w+") # create or overwrite the file
                

        self.flow_table = BaseFlowTable(timeout) # default flow table
        self.rule = "simple_timeout"
        switch_info_str_extend = None
        if "rule" in kwargs.keys():
            rule = kwargs["rule"]
            if rule == "cache_no_timeout_random":
                if "cache_size" in kwargs.keys():
                    cache_size = kwargs["cache_size"]
                else:
                    cache_size = 10

                self.flow_table = RecycleBinFlowTable(timeout, 1, cache_size)

            elif rule == "cache_no_timeout_fifo":
                if "cache_size" in kwargs.keys():
                    cache_size = kwargs["cache_size"]
                else:
                    cache_size = 10

                self.flow_table = RecycleBinFlowTable(timeout, 2, cache_size)

            elif rule == "cache_fixed_timeout":
                ctm = 10
                threshold = 1
                if "cache_timeout_multiplier" in kwargs.keys():
                    ctm = kwargs["cache_timeout_multiplier"]

                if "cache_active_threshold" in kwargs.keys():
                    if int(kwargs["cache_active_threshold"]) >= 1:
                            threshold = int(kwargs["cache_active_threshold"])
                
                switch_info_str_extend = "Cache timeout multiplier: " + str(ctm)
                switch_info_str_extend += "\nCache active threshold: " + str(threshold)

                self.flow_table = ParallelSecondaryTable(timeout, 1, float(ctm), int(threshold))

            elif rule == "cache_dynamic_timeout_last_rules":     
                threshold = 2
                if "cache_active_threshold" in kwargs.keys():
                    if int(kwargs["cache_active_threshold"]) >= 2:
                        threshold = int(kwargs["cache_active_threshold"])
                
                switch_info_str_extend = "Cache active threshold: " + str(threshold)

                self.flow_table = ParallelSecondaryTable(timeout, 2, 0, threshold)

            elif rule == "smart_time":
                self.flow_table = SmartTimeTable(timeout)
                
            self.rule = rule

        switch_info_str = \
'''
Running Switch: {id} 
Default timeout: {to}
Rule: {rule}
'''.format(id=self.id, to=timeout, rule=self.rule)

        if switch_info_str_extend:
            switch_info_str += switch_info_str_extend

        print(switch_info_str)

    def process_packet(self, timestamp, raw_packet):
        '''
        Process an IP packet and output statstics
        '''
        Output.VERBOSE("---------Processing Packet At Time:----------")
        Output.VERBOSE(datetime.utcfromtimestamp(timestamp))
        self.current_time = timestamp
        self.total_packets += 1

        if (self.current_time - self.last_dump_time) * 1000 > self.dump_interval:
            self.flow_table.all_timeout(self.current_time)
            self.output_statistics(self.to_file)
            self.last_dump_time = self.current_time

        try:
            eth = dpkt.ethernet.Ethernet(raw_packet)
        except Exception:
            return
        
        ip = eth.data

        if not isinstance(ip, dpkt.ip.IP):
            Output.VERBOSE("Not an IP packet")
            return

        packet = Packet(timestamp)
        packet.size = len(raw_packet)

        packet.eth_src = eth.src
        packet.eth_dst = eth.dst
        packet.eth_type = eth.type

        packet.ip_src = ip.src
        packet.ip_dst = ip.dst
        packet.ip_protocol = ip.p

        tcp, udp = None, None

        if packet.ip_protocol == IP_PROTOCOL.TCP: # tcp
            tcp = ip.data
        elif packet.ip_protocol == IP_PROTOCOL.UDP: # udp
            udp =  ip.data
        else:
            Output.VERBOSE("Not TCP or UDP")
            return


        if tcp and type(tcp) == dpkt.tcp.TCP:
            packet.sport = tcp.sport
            packet.dport = tcp.dport
        elif udp and type(udp) == dpkt.udp.UDP:
            packet.sport = udp.sport
            packet.dport = udp.dport
        else:
            return
        

        id = packet.get_id()

        if self.flow_table.if_flow_exists(id):
            self.flow_table.existing_flow(packet)
        else:
            self.flow_table.non_existing_flow(packet)

    def output_statistics(self, to_file):

        hit_ratio = float((self.total_packets - self.flow_table.missed) / self.total_packets)

        output_str = '''
Current Time is: {time}
Total Number of Packets Processed: {total_packet}
Timeout Set to: {timeout}
Currently Active Flows: {active_flow}
Maximum Number of Packets In Active Flows: {max_packets}
Total Number of Rules Ever Installed: {total_rules}
Overall Hit Ratio: {hit_ratio}
Maximum Number of Installed Rules At a Time: {max_flow_count}
        '''.format(time=str(datetime.utcfromtimestamp(self.current_time)),\
        total_packet=str(self.total_packets),\
        timeout=str(self.flow_table.timeout),\
        active_flow=str(self.flow_table.current_active_flow),\
        total_rules=str(self.flow_table.total_rules),\
        max_flow_count=str(self.flow_table.max_flow_count),\
        max_packets=str("N/A"),\
        hit_ratio=hit_ratio)

        if self.rule in ["cache_fixed_timeout", 
                        "cache_dynamic_timeout_last_rules", 
                        "cache_no_timeout_random",
                        "cache_no_timeout_fifo"]:
            output_str += self.flow_table.out_secondary_stats()

        output_str += "*"
        
        if to_file:
            self.outfile.write(output_str)
        else:
            print(output_str)


    def output_all_flow(self, to_file=True):
        self.flow_table.output_all_flow(self.id, to_file)
        self.outfile.close()


class BaseFlowTable:
    '''
    Most basic flow table
    With 1 dictionary and fixed timeout
    '''
    def __init__(self, timeout):
        self.table = {}
        self.timeout = timeout
        # statistics figures
        self.timeout_flow_count = 0
        self.max_flow_count = 0
        self.current_active_flow = 0
        self.total_flows = 0
        self.total_rules = 0
        self.missed = 0

        # keep track of stack of flow rule ids should be update
        # so new and updated flows id and update time are pushed to the stack
        # when need to timeout, check the first(earliest) check if it is timed out
        # if yes, pop it and check the new first, if not, stop, because anything after will 
        # not be timed out out
        self.should_active = []

    def if_flow_exists(self, id):
        if id in self.table.keys():
            return True
        else:
            return False

    def existing_flow(self, packet):
        ''' 
        Handles cases where a flow already exists.
        If it's active, update the last rule in rule list.
        If it's not active, a new rule needs to be created.
        '''
        id = packet.get_id()
        if not self.if_flow_exists(id):
            raise Exception("Flow does not exist")

        flow = self.table[id]
        latest_rule = None

        if flow.active:
            latest_rule = flow.rules[-1]
        else:
            latest_rule = flow.create_rule(packet.timestamp)
            self.missed += 1
            self.total_rules += 1
            self.current_active_flow += 1
            flow.active = True
            Output.DEBUG("Added new rule")

        flow.last_update = packet.timestamp
        latest_rule.new_packet(packet)
        
        self.table[id] = flow

        if self.current_active_flow > self.max_flow_count:
            self.max_flow_count = self.current_active_flow

        self.should_active.append((flow.id, flow.last_update))


    def non_existing_flow(self, packet):
        '''
        Handles cases where a flow DNE.
        Create a new flow and added to flow table then
        call the existing flow handler
        '''

        id = packet.get_id()
        if self.if_flow_exists(id):
            raise Exception("Flow exists")

        self.table[id] = self.create_flow(packet)
        self.existing_flow(packet)
        self.total_flows += 1


    def deactivate_flow(self, id):
        '''
        Set a flow as deactivated, decrement the active flow counter
        
        '''
        if not self.if_flow_exists(id):
            raise Exception("Flow does not exist")
        
        self.table[id].deactivate_flow()
        self.current_active_flow -= 1

    def check_timeout(self, flow, current_time):
        # converts to ms
        delta = (current_time - flow.last_update) * 1000

        if self.check_delta(current_time, flow.last_update, self.timeout):
            Output.DEBUG("Timing out " + flow.id)
            return True
        else:
            return False


    def check_delta(self, current_time, last_update, timeout):
        delta = (current_time - last_update) * 1000

        if delta > timeout:
            return True
        else:
            return False
    
    def all_timeout(self, current_time):
        """
        Iterates through the flow table and checks for timeout.
        """
        should_expired = []
        while len(self.should_active) > 0:
            earliest = self.should_active[0]
            if self.check_delta(current_time, earliest[1], self.timeout):
                should_expired.append(self.should_active.pop(0)[0])
            else:
                break

       
        should_active_ids = [i[0] for i in self.should_active]


        for id in should_expired:
            flow = self.table[id]
            if not flow.active or id in should_active_ids:
                continue
            self.deactivate_flow(id)


    def get_max_packets_flow(self):
        if len(self.table.values()) > 0:
            max_flow = max(self.table.values(), key=lambda x : x.rules[-1].packets_count)
            return max_flow.rules[-1].packets_count
        else:
            return 0


    def create_flow(self, packet):
        id = packet.get_id()
        flow = Flow(id, packet.ip_src, packet.ip_dst, packet.ip_protocol,
                    packet.sport, packet.dport, packet.timestamp)

        flow.deactivate_flow()
        
        return flow

    def output_all_flow(self, switch_id, to_file):
        out_str = ""

        for id, flow in self.table.items():
            
            flow_stats = \
'''
Total number of Rules: {num_rules}
Total packets: {packets_count}
Total bytes: {byte_count}
Flow Hit Rate: {hit_rate}
*
            '''.format(num_rules=len(flow.rules),
            hit_rate=flow.get_hit_rate(),
            packets_count=flow.get_packet_count(),
            byte_count=flow.get_byte_count())

            out_str += (flow.output_info() + flow_stats)

        if to_file:
            filename = "log_flow_" + str(switch_id)            
            with open(filename, "w+")  as out_file:
                out_file.write(out_str)
                out_file.close()
        
        else:
            print(out_str)


class SmartTimeTable(BaseFlowTable):
    '''
    https://rishabhpoddar.com/publications/SmartTime.pdf 
    '''

    def __init__(self, min_timeout):
        super().__init__(min_timeout)
        self.timeout_table = {} # because the original table doesn't have timeout info and I don't want to change to much code
            
    

    def existing_flow(self, packet):
        pid = packet.get_id()
        flow = self.table[pid]
        MAX_TIMEOUT = self.timeout * 100 # if 100ms then 10s

        if flow.get_byte_count() == 0:
            # if a flow has never been observed before
            self.timeout_table[pid] = [self.timeout]

        else:
            timeout = self.timeout * (2 ** flow.num_rules())

            prev_timeout = self.timeout_table[pid][-1]
            if prev_timeout >= MAX_TIMEOUT and self.hold_factor(pid, packet.timestamp) > 3:
                timeout = self.timeout
            
            if prev_timeout >= MAX_TIMEOUT:
                timeout = MAX_TIMEOUT

            self.timeout_table[pid].append(timeout)

        super().existing_flow(packet)
        
        self.should_active = [] # reset this to 0 because it's not used for less memory

    def hold_factor(self, flow_id, cur_time):
        '''
        Calculate hold factor: http://citeseerx.ist.psu.edu/viewdoc/summary?doi=10.1.1.10.9508
        "Hold Factor is defined as the sum of active time and idle time, 
        divided by the active time: it is desirable to have the hold factor as close to 1 as possible"
        
        '''

        flow = self.table[flow_id]
        prev = None
        active_time = 0
        inactive_time = 0
        for r in flow.rules:
            if not r.last_update:
                continue

            active_time += r.last_update - r.first_seen
            
            if prev and prev.last_update:
                inactive_time += r.first_seen - prev.last_update

            prev = r

        inactive_time += cur_time - prev.last_update

        if inactive_time == 0 or active_time == 0:
            return 999
        else:
            return float((active_time + inactive_time) / active_time)
        

    def all_timeout(self, current_time):
        """
        Iterates through the flow table and checks for timeout.
        """
        expired = [k for k, v in self.table.items() if v.active and self.check_timeout(v, current_time)]
        for id in expired:	
            self.deactivate_flow(id)	


    def check_timeout(self, flow, current_time):
        # converts to ms
    
        timeout = self.timeout_table[flow.id][-1]

        if self.check_delta(current_time, flow.last_update, timeout):
            Output.DEBUG("Timing out " + flow.id)
            return True
        else:
            return False


class ParallelSecondaryTable(BaseFlowTable):
    '''
    Secondary table acts as parallel toward the first table.
    Selected rules will be put there and have a different timeout for each flow.
    The more time the flow missed, the longer the timeout is.

    After second time misses happens, the flow will be also pushed into secondary table
    with # of misses * 100ms timeout in secondary table

    TODO: make argument kwargs
    '''

    def __init__(self, timeout, timeout_policy, cache_multiplier=10, threshold=2):
        super().__init__(timeout)

        self.cache_multiplier = cache_multiplier # TODO: make it variable
        self.secondary_table = collections.OrderedDict() # {flow_id:time_should_expire}
        self.cache_misses = 1
        self.cache_hits = 1
        # timeout_policy == 1: default fixed timeout with multiplier
        # timeout_policy == 2: timeout based on differences between last two installed rules of this flow
        self.timeout_policy = timeout_policy 
        self.threshold = threshold



    def if_secondary_exists(self, id):
        if id in self.secondary_table.keys():
            self.cache_hits += 1
            return True
        else:
            self.cache_misses += 1
            return False

    def existing_flow(self, packet):
        id = packet.get_id()
        if not self.if_flow_exists(id):
            raise Exception("Flow does not exist")

        flow = self.table[id]
        latest_rule = None
        cur_time = packet.timestamp

        if flow.active:
            latest_rule = flow.rules[-1]
        elif self.if_secondary_exists(id) and not flow.active:
            # in secondary table
            self.table[id].active = True
            del self.secondary_table[id] # remove entry in cache
            self.current_active_flow += 1
            latest_rule = flow.rules[-1]

        else:
            latest_rule = flow.create_rule(cur_time)
            self.missed += 1
            self.total_rules += 1
            self.current_active_flow += 1
            flow.active = True
            Output.DEBUG("Added new rule")

        flow.last_update = cur_time
        latest_rule.new_packet(packet)
        
        self.table[id] = flow

        if self.current_active_flow > self.max_flow_count:
            self.max_flow_count = self.current_active_flow

        self.should_active.append((flow.id, flow.last_update))


    def all_timeout(self, current_time):
        """
        Also timeout flows in secondary table
        """
        # timeout primary table

        #expired = [k for k, v in self.table.items() if v.active and self.check_timeout(v, current_time)]

        should_expired = []
        while len(self.should_active) > 0:
            earliest = self.should_active[0]
            if self.check_delta(current_time, earliest[1], self.timeout):
                should_expired.append(self.should_active.pop(0)[0])
            else:
                break

       
        should_active_ids = [i[0] for i in self.should_active]


        for id in should_expired:
            flow = self.table[id]
            if not flow.active or id in should_active_ids:
                continue
            self.deactivate_flow(id)

            # Rule #1, fixed timeout
            if self.timeout_policy == 1:

                # a miss happens for a second time, insert into cache when timed out
                # in reality, controller will tell switch this information
                if self.table[id].num_rules() >= self.threshold:
                    Output.DEBUG("Adding to secondary")
                    self.secondary_table[id] = current_time + (self.timeout * self.cache_multiplier) / 1000 # in seconds
            # Rule #2, timeout based on last rules

            elif self.timeout_policy == 2:
                
                # the threshold must be greater than 2, because of course
                # TODO: make it variable
                flow = self.table[id]
                if flow.num_rules() >= self.threshold:
                    last_rule = flow.rules[-1]
                    second_last = flow.rules[-2]
                    cachetime = current_time + (last_rule.first_seen - second_last.last_update) * 1.1
                    if (last_rule.first_seen - second_last.last_update)  > 1: 
                        cachetime = current_time + 1  # greater than 1 second make it 1 second

                    self.secondary_table[id] = cachetime


        # timeout secondary table
        expired = [k for k, v in self.secondary_table.items() if current_time > v]

        for k in expired:
            Output.DEBUG("deleting " + k + " from secondary")
            del self.secondary_table[k]
                
    def out_secondary_stats(self):
        # TODO: add more stats
        out_str = \
'''
Current Cache Size: {snd_size}
Current Cache Hit Rate: {hit_rate}
'''.format(snd_size=len(self.secondary_table),
           hit_rate=(self.cache_hits/(self.cache_hits + self.cache_misses)))

        return out_str
    

class RecycleBinFlowTable(BaseFlowTable):
    '''
    Recycle bin style secondary cache, when rule expires push flow to a cache.
    Next time check the recycle bin first, if exists, restore from it, avoid a miss
    '''

    def __init__(self, timeout, eviction_policy, secondary_table_size=10):
        super().__init__(timeout)
        # secondary table is a list only keep track of id, 
        # because we already have everything in main table
        # we pretend we have rule info in secondary table
        self.secondary_table = [] 
        self.secondary_table_size = secondary_table_size
        self.cache_hits = 1
        self.cache_misses = 1
                        
        if eviction_policy == 1:
            self.eviction_policy = self.random_eviction
        if eviction_policy == 2:
            self.eviction_policy = self.FIFO
        else:
            self.eviction_policy = self.random_eviction

    def deactivate_flow(self, id):
        super().deactivate_flow(id)
        self.push_secondary(id) # push to secondary table
    
    def existing_flow(self, packet):
        id = packet.get_id()
        if not self.if_flow_exists(id):
            raise Exception("Flow does not exist")

        flow = self.table[id]
        latest_rule = None

        if flow.active:
            latest_rule = flow.rules[-1]
        elif self.if_secondary_exists(id) and not flow.active:
            self.table[id].active = True
            self.secondary_table.remove(id)
            self.current_active_flow += 1
            latest_rule = flow.rules[-1]
        else:
            latest_rule = flow.create_rule(packet.timestamp)
            self.missed += 1
            self.total_rules += 1
            self.current_active_flow += 1
            flow.active = True
            Output.DEBUG("Added new rule")

        flow.last_update = packet.timestamp
        latest_rule.new_packet(packet)
        
        self.table[id] = flow

        if self.current_active_flow > self.max_flow_count:
            self.max_flow_count = self.current_active_flow


    def if_secondary_exists(self, id):
        if id in self.secondary_table:
            self.cache_hits += 1
            return True
        else:
            self.cache_misses += 1
            return False


    def push_secondary(self, id):
        if len(self.secondary_table) > self.secondary_table_size:
            Output.DEBUG("Evicting: "+ id)
            self.eviction_policy()

        self.secondary_table.append(id)

        
    def random_eviction(self):
        evicted = random.choice(self.secondary_table)
        self.secondary_table.remove(evicted)


    def FIFO(self):
        self.secondary_table.pop(0)


    def out_secondary_stats(self):
        out_str = \
'''
Current Cache Size: {snd_size}
Current Cache Hit Rate: {hit_rate}
Current Cache Access: {access}
'''.format(snd_size=self.secondary_table_size,
           hit_rate=(self.cache_hits/(self.cache_hits + self.cache_misses)),
           access=self.cache_hits + self.cache_misses)

        return out_str

class Flow:
    def __init__(self, id, ip_src, ip_dst, ip_protocol, sport, dport, cur_time):
        self.id = id # Rule, souce_ip + ip_dst + portocol + sport + dport
        self.ip_src = ip_src
        self.ip_dst = ip_dst
        self.ip_protocol = ip_protocol
        self.sport = sport
        self.dport = dport
        self.last_update = cur_time
        self.active = True # if timeout, mark inactive
        self.rules = []

    def num_rules(self):
        return len(self.rules)

    def deactivate_flow(self):
        self.active = False

    def create_rule(self, create_time):
        rule = Rule(create_time)
        self.rules.append(rule)

        return rule

    def get_packet_count(self):
        total = 0
        for r in self.rules:
            total += r.packets_count

        return total

    def get_byte_count(self):
        total = 0

        for r in self.rules:
            total += r.byte_count

        return total

    def get_hit_rate(self):
        '''Get hit rate of individual flow'''

        # only when a packet missed, an rule will be added
        missed = self.num_rules()
        packets_count = self.get_packet_count()

        return float((packets_count - missed) / packets_count)

    def output_info(self):
        '''return a string of self's info'''
        if self.ip_protocol == IP_PROTOCOL.TCP:
            protocol = "TCP" 
        elif self.ip_protocol == IP_PROTOCOL.UDP:
            protocol = "UDP"
            
        out_str = '''
Flow id: {flow_id}
Source IP: {ip_src}
Dest IP: {dest_ip}
IP protocol: {protocol}
Src port: {sport}
Dest port: {dport}
            '''.format(flow_id=self.id,
            ip_src=inet_to_str(self.ip_src),
            dest_ip=inet_to_str(self.ip_dst),
            protocol=protocol,
            sport=self.sport,
            dport=self.dport)

        return out_str
        

class Rule:
    def __init__(self, first_seen):
        self.packets_count = 0
        self.byte_count = 0
        self.first_seen = first_seen  
        self.last_update = None

    def new_packet(self, packet):
        self.last_update = packet.timestamp
        self.packets_count += 1
        self.byte_count += packet.size


class Packet:
    def __init__(self, timestamp):
        self.timestamp = timestamp
        self.eth_src = None
        self.eth_dst = None
        self.eth_type = None
        self.ip_src = None
        self.ip_dst = None
        self.ip_protocol = None
        self.sport = None
        self.dport = None

        self.size = 0
        #Output.DEBUG(func=self.print_packet)
    
    def get_id(self):

        return "" + str(self.ip_src) + str(self.ip_dst) + \
                  str(self.ip_protocol) + str(self.sport) + str(self.dport)
    
    def print_packet(self):
        print("Packet with ID: " + self.get_id())
        print("Source MAC: " + mac_addr(self.eth_src))
        print("Dest Mac: " + mac_addr(self.eth_dst))
        print("Source IP: " + inet_to_str(self.ip_src))
        print("Dest IP: " + inet_to_str(self.ip_dst))
        print("Protocol: " + str(self.ip_protocol))
        print("Source port: " + str(self.sport))
        print("Dest port: " + str(self.dport))


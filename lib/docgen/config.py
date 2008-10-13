## $Id$

"""
Configuration of the Document Generator
"""
import re
import sys
import os
import socket
import struct
import csv
from warnings import warn
from ConfigParser import SafeConfigParser
from lxml import etree

#from xml.parsers.expat import ParserCreate
#from xml.dom.minidom import Document, Text

import logging
import debug

_configdir = '/usr/local/docgen/etc'

log = logging.getLogger('docgen')

xinclude_re = re.compile(r'.*<xi:include href=[\'\"](?P<uri>.*)[\'\"].*')

FILER_TYPES = [
    'primary',
    'secondary',
    'nearstore',
#    'dr_primary',
#    'dr_secondary',
#    'dr_nearstore',
    ]

def get_create_size(size):
    """
    Utility function
    Get the raw size in a format acceptable to the vol or lun create command,
    ie: integer amounts, and the appropriate scale (0.02g == 20m)
    """
    # Figure out if the raw volume size is fractional.
    # NetApps won't accept fractional numbers for the vol create command,
    # so we convert it from the default gigabytes to megabytes.
    if 0 < float(size) - int(size) < 1:
        log.debug("size %s is fractional gigabytes, using megabytes for create command", size)
        # Note: This uses 1000 megabytes per gigabytes, which is not true.
        # It should be base 2, not base 10, == 1024, but most humans prefer base 10.
        roundsize = round(size * 1000)
        if roundsize == 0:
            log.error("Size error: %s", size)
            raise ValueError("Attempting to create Volume/LUN of size 0!")
        return '%dm' % roundsize

    return '%dg' % round(size)
    
class Revision:
    """
    A Revision is a particular revision of a document. A single
    document may have many revisions.
    """
    def __init__(self, majornum=0, minornum=0, date='', authorinitials='', revremark='',
                 reviewer='', reviewdate=''):
        self.majornum = majornum
        self.minornum = minornum
        self.date = date
        self.authorinitials = authorinitials
        self.revremark = revremark
        self.reviewer = reviewer
        self.reviewdate = reviewdate
        pass
    pass

class Host:
    """
    A host definition
    """
    def __init__(self, name, platform, os, site, location, description='',
                 drhosts=[], interfaces=[], iscsi_initiator=None, is_virtual=False):

        self.name = name
        self.platform = platform
        self.os = os
        self.location = location
        self.description = description

        # drhosts is a reference to other hosts that will take on
        # this host's role in the event of a DR, and so they should
        # inherit the exports configuration for this host, but for the
        # DR targetvol of the snapmirrors for this host's volumes.
        self.drhosts = drhosts

        self.interfaces = interfaces
        #self.filesystems = filesystems

        self.iscsi_initiator = iscsi_initiator

        self.is_virtual = is_virtual
        
        log.debug("Created host: %s", self)

    def __str__(self):
        return "%s (%s, %s)" % (self.name, self.os, self.location)

    def get_storage_ips(self):
        """
        Find the IP address of the active storage interface(s).
        """
        #log.debug("Interfaces on %s: %s", self.name, self.interfaces)
        # Find the first 'storage' type interface that is 'active'
        ifacelist = [ x for x in self.interfaces if x.type == 'storage' and x.mode == 'active' ]

        iplist = [ int.ipaddress for int in ifacelist ]
        return iplist

##         try:
##             if ifacelist[0] is None:
##                 raise ValueError("Cannot find active Storage IP for host '%s'")
##             return ifacelist[0].ipaddress

##         except IndexError:
##             raise ValueError("Host '%s' has no storage IP addresses defined." % self.name)

class Filesystem:

    def __init__(self, type, name):

        self.type = type
        self.name = name

class Switch:

    def __init__(self, name, type, sitename, location, connected_switches=[]):

        self.name = name
        if type not in ['core', 'edge']:
            raise ValueError("Switch '%s' has unknown type '%s'" % (name, type))
        self.type = type
        self.site = None # site is 'primary' or 'secondary'
        self.sitename = sitename
        self.location = location

        self.connected_switches = connected_switches

class Interface:

    def __init__(self, type, mode, switchname=None, switchport=None, hostport=None, ipaddress=None, mtu=9000, vlans=[]):

        self.type = type
        self.mode = mode
        self.switchname = switchname
        self.switchport = switchport
        self.hostport = hostport
        self.ipaddress = ipaddress
        self.mtu = mtu
        self.vlans = vlans

    def __repr__(self):
        return '<Interface %s:%s %s:%s (%s)>' % (self.type, self.mode, self.switchname, self.switchport, self.ipaddress)

class Site:
    """
    A site contains Filers, VLANS, etc.
    """
    def __init__(self, name, type, location, nameservers, winsservers):
        """
        @param type: type is one of ('primary' | 'secondary') and is unique for a project.
        @param location: a descriptive string for the site
        """
        self.name = name
        self.type = type
        self.location = location

        self.nameservers = nameservers
        self.winsservers = winsservers

        # Hosts, keyed by hostname
        self.hosts = {}
        
        # Filers, keyed by unique name
        self.filers = {}

        # VLANs. This is a list, because the same VLAN number can be used
        # for different sites.
        self.vlans = []

        # Volumes, just a list
        self.volumes = []

        log.debug("Added Site: %s", self)

    def __repr__(self):
        """
        String representation of a Site object
        """
        return '<Site: %s, type: %s, location: %s>' % (self.name, self.type, self.location)


class NAS:

    def __init__(self, vlan, protocols=['NFS',]):

        self.vlan = vlan
        self.protocols = protocols
        self.filers = {}

class Filer:

    def __init__(self, name, type, site):
        self.name = name

        if type not in FILER_TYPES:
            raise ValueError("filer type '%s' not a known filer type", type)

        self.type = type
        self.site = site

        # Add me to the site's list of Filers
        site.filers[name] = self

        self.volumes = []
        self.vfilers = {}

        # If I am a secondary, who am I a secondary for?
        self.secondary_for = None

        # If I have a secondary, who is it?
        self.secondary_is = None

    def __str__(self):
        return '<Filer: %s (site:%s/type:%s)>' % (self.name, self.site, self.type)

    def as_string(self):
        """
        Dump out as a string.
        """
        retstr = '<Filer: %s (%s)' % ( self.name, self.type )

        if self.type == 'secondary':
            retstr += ' [secondary for %s]' % self.secondary_for
            pass

        retstr += '>\n'

        log.debug("vfilers: %s", self.vfilers)
        vfiler_strings = [ '  %s' % x.as_string() for x in self.vfilers.values() ]
        retstr += '\n'.join(vfiler_strings)
        return retstr

class VFiler:
    
    def __init__(self, filer, name, rootaggr, vlan, ipaddress, gateway, netmask='255.255.255.254',
                 alias_ips = [],
                 dns_domain_name = 'eigenmagic.com',
                 ad_account_location = 'OU=IPSAN,OU=eigenmagic,OU=com',
                 nameservers = [],
                 winsservers = [],
                 ):

        self.filer = filer
        self.name = name
        self.rootaggr = rootaggr
        self.vlan = vlan
        self.ipaddress = ipaddress
        self.netmask = netmask
        self.gateway = gateway
        self.alias_ips = alias_ips
        self.volumes = []

        # We will need at least one additional 'services' VLAN
        # This will have a separate interface, IP address and gateway route
        # The format of each entry in the list is a tuple:
        # (vlan, ipaddress)
        self.services_ips = []

        #
        # CIFS related configuration stuff
        #
        self.dns_domain_name = dns_domain_name
        self.ad_account_location = ad_account_location

        self.nameservers = nameservers
        self.winsservers = winsservers
        
##         if self.filer.name.startswith('exip'):
##             self.nameservers = [ '161.117.218.175',
##                                  '161.117.245.73',
##                                  ]
##             self.winsservers = [ '161.117.218.175',
##                                  '161.117.245.73',
##                                  ]

##         elif self.filer.name.startswith('clip'):
##             self.nameservers = [ '161.117.245.73',
##                                  '161.117.218.175',
##                                  ]

##             self.winsservers = [ '161.117.245.73',
##                                  '161.117.218.175',
##                                  ]
##             pass

        self.netbios_aliases = []

        vfiler_key = '%s:%s' % (filer.name, name)
        filer.vfilers[vfiler_key] = self

    def as_string(self):
        """
        Dump vFiler config as a string
        """
        retstr = '<vFiler: %s, %s %s>' % (self.name, self.ipaddress, self.netmask)
        volume_strings = [ '  %s' % x for x in self.volumes ]
        return retstr

    def netbios_name(self):
        """
        Return my NetBIOS name.
        This is limited to 15 characters, which is a pain, so we
        have to cobble together yet another naming convention.
        This once is: XYnn-<vfiler-name>
        Where:
          X is 'ex' if the filer is at exhibition st, or 'cl' for clayton.
          Y is 'a' for filer head a, and 'B' for filer head b
          nn is the number of the filer.
        So, a vfiler called 'blah' on exip-fashda-01 would have the following
        NetBIOS name: exa01-blah
        """
        # Due to the naming convention for NearStores, the 'head_prefix'
        # ends up as 't'. We swap it to 'n' so that it's more obviously a
        # NearStore.
        site_prefix = self.filer.name[:2]
        if self.filer.type in [ 'primary', 'secondary' ]:
            head_prefix = 'f'
        else:
            head_prefix = 'n'            

        head_num = self.filer.name[-2:]

        retstr = '%s%s%s-%s' % (site_prefix, head_prefix, head_num, self.name)
        if len(retstr) > 15:
            log.warn("NetBIOS name of '%s' is longer than 15 characters. Truncating it.", retstr)
            retstr = retstr[:15]
            log.info("NetBIOS name is now '%s'", retstr)            
            pass

        log.debug("NetBIOS name: %s", retstr)
        return retstr

    def fqdn(self):
        """
        Return my fully qualified domain name.
        """
        return '%s.%s' % ( self.netbios_name(), self.dns_domain_name )

    def add_service_ip(self, vlan, ipaddress):
        self.services_ips.append( (vlan, ipaddress) )
    pass

class Volume:

    def __init__(self, name, filer, aggr, usable, snapreserve=20, raw=None, type="fs", proto="nfs", voloptions=[], volnode=None, snapref=[], snapvaultref=[], snapmirrorref=[], snapvaultmirrorref=[], iscsi_snapspace=0):
        self.name = name
        self.filer = filer
        self.type = type
        self.proto = proto
        self.aggregate = aggr
        self.usable = float(usable)

        # A special kind of usable that is used for the actual iscsi LUN space
        # iSCSI really is a pain to allocate on WAFL
        self.iscsi_usable = self.usable
        self.iscsi_snapspace = iscsi_snapspace

        # Check that the filer doesn't already have a volume of this name on it
        if len([ vol for vol in self.filer.volumes if vol.name == self.name ]) > 0:
            raise ValueError("Filer '%s' already has a volume named '%s'" % (filer.name, self.name))

        # iSCSI LUN sizing is... interesting
        # Best practice is to have no snapreserve for volumes
        # used for iscsi, but we need to have some storage
        # available for snapshots. Because LUNs are just files full
        # of blocks, we have to allocate enough storage for all
        # of the blocks to change, so we need 2 * LUNsize GiB to
        # store the snapshots.
        # If you're not using snapshots, you will need a little extra
        # space in the volume so the LUN can fit within it. The LUN
        # can't take up 100% of the volume (i.e.: A LUN of 100GiB
        # will require a volume of 101GiB in size)

        if proto == 'iscsi':
            log.debug("volume proto is iscsi")
            # If snapshots are configured, double the usable storage to allow for 50% 'snapreserve'
##             log.debug("snapref: %s", snapref)
##             log.debug("snapvaultref: %s", snapvaultref)
##             log.debug("snapvaultmirrorref: %s", snapvaultmirrorref)
##             log.debug("snapmirrorref: %s", snapmirrorref)
            if len(snapref) > 0 or len(snapvaultref) > 0 or len(snapmirrorref) > 0 or len(snapvaultmirrorref) > 0:
                log.debug("snapshots present. doubling usable space of %s GiB for iscsi volume", self.usable)
                #snapdiv = (100 - float(iscsi_snapspace))/100
                snapspace = self.usable * ( float(iscsi_snapspace)/100 )
                log.debug("Adding iscsi_snapspace (%s%%) of %s GiB", iscsi_snapspace, snapspace)
                self.usable = (self.usable * 2.0) + snapspace
                log.debug("usable is now: %s GiB, iscsi_usable is: %s GiB", self.usable, self.iscsi_usable)
            else:
                # If no snapshots are configured, make the raw slightly more than usable
                log.debug("No snapshots, adding 1 GiB usable to volume size.")
                raw = self.usable + 1

        if raw is None:
            try:
                raw = self.usable / ( (100 - float(snapreserve) )/100 )
            except ZeroDivisionError, e:
                log.critical("snapreserve of 100% is not a valid value. You probably mean 50%.")
                raise ConfigInvalid(e)
            
        self.raw = raw

        self.snapreserve = int(round(snapreserve))

        self.snapref = snapref
        self.snapvaultref = snapvaultref
        self.snapmirrorref = snapmirrorref
        self.snapvaultmirrorref = snapvaultmirrorref

        # Lists of the actual snapX objects, added when they're created
        self.snaps = []
        self.snapvaults = []
        self.snapmirrors = []

        self.qtrees = {}

        # Set default volume options
        if len(voloptions) == 0:
            voloptions = [ 'nvfail=on',
                           'create_ucode=on',
                           'convert_ucode=on',
                           ]
        self.voloptions = voloptions
        self.volnode = volnode

        if self.name.endswith("root"):
            self.filer.volumes.insert(0, self)
        else:
            self.filer.volumes.append(self)
            pass

        self.filer.site.volumes.append(self)

        self.autosize = None
        self.autodelete = None

        # Default volume space guarantee setting is 'volume',
        # but for NearStores we want the space guarantee to be 'none',
        # unless overridden in the node definition
        if self.volnode is not None and self.volnode.attrib.has_key('space_guarantee'):
            log.debug("vol %s has space_guarantee set!", self)
            self.space_guarantee(self.volnode.attrib['space_guarantee'])
        else:
            log.debug("space_guarantee not set. Using default.")
            if self.filer.type == 'nearstore':
                # Default for NearStore volumes
                self.space_guarantee('none')
            else:
                # General default
                self.vol_space_guarantee = 'volume'
                pass
            pass
        
        log.debug("Created: %s", self)

    def __str__(self):
        return '<Volume: %s:/vol/%s, %s, aggr: %s, size: %sg usable (%sg raw)>' % (self.filer.name, self.name, self.type, self.aggregate, self.usable, self.raw)

    def get_create_size(self):
        """
        Get the raw size in a format acceptable to the vol create command,
        ie: integer amounts, and the appropriate scale (0.02g == 20m)
        """
        return get_create_size(self.raw)

    def shortpath(self):
        """
        The short path for the volume, eg: /vol/myproj_vol03
        """
        return '/vol/%s' % self.name
    
    def namepath(self):
        """
        The name path to the filer/volume, eg: exip-nas-02:/vol/myproj_vol03
        """
        return '%s:%s' % ( self.filer.name, self.shortpath() )
    
    def _ippath(self):
        """
        Similar to the name path, but using the storage IP of the filer as the target.
        """
        return '%s:%s' % ( self.filer.name, self.shortpath() )

    def has_snaps(self):
        """
        If the volume has snapshots of any kind (snapshot, SnapVaults, SnapMirrors), return True
        """
        if len(self.snaps) > 0 or len(self.snapvaults) > 0 or len(self.snapmirrors) > 0:
            return True

    def space_guarantee(self, value=None):
        """
        Set the volume space guarantee value, or fetch
        the current setting if no value is passed in
        """
        if value is not None:
            # check it's a valid value
            value = value.lower()
##             if value not in [ 'none', 'volume' ]:
##                 raise ValueError("Unsupported space guarantee value of '%s' for volume '%s'" % (value, self))
            self.vol_space_guarantee = value
            pass
        return self.vol_space_guarantee

class VolumeAutoSize:
    """
    VolumeAutoSize is a setting used for Volumes to define how
    they grow automatically.
    """
    def __init__(self, volume, max, increment):

        # My parent Volume object
        self.volume = volume

        # The maximum size to grow to
        self.max = max

        # How much to grow by whenever we increase
        self.increment = increment

    ## FIXME: These should be split off into a subclass. This would
    ## allow another set of 'zapi_add' style commands, or ModiPy
    ## changes or change templates, perhaps.
    def command_add(self):
        """
        The sequence of commands to use when provisioning for the first time
        """
        cmdset = []
        cmdset.append("vol autosize %s -m %s -i %s on" % (self.volume.name, self.max, self.increment) )
        return cmdset

    def command_change(self, previous):
        """
        The sequence of commands to use when changing my value when compared
        with the 'previous' setting.
        """
        cmdset = []
        cmdset.append("vol autosize %s -m %s -i %s on" % (self.volume.name, self.max, self.increment) )
        return cmdset

    def command_delete(self):
        """
        The sequence of commands to use when deleting me from the device configuration.
        """
        cmdset = []
        cmdset.append("vol autosize %s off" % (self.volume.name))
        return cmdset

class VolumeAutoDelete:
    """
    VolumeAutoDelete defines how a volume can be set up to have
    snapshots automatically deleted if it gets full.
    """
    
    def __init__(self, volume, commitment='try',
                 trigger='volume',
                 target_free_space=80,
                 delete_order='oldest_first',
                 defer_delete='none'):
        """
        Define the snapshot autodelete settings for a volume
        """
        self.volume = volume
        self.commitment = commitment
        self.trigger = trigger
        self.target_free_space = target_free_space
        self.delete_order = delete_order
        self.defer_delete = defer_delete
        self.prefix = None

    def __str__(self):
        """
        Stringified representation of VolumeAutoDelete
        """
        return "<AutoDelete: %s: %s %s %s %s" % ( self.volume.name, self.commitment,
                                                  self.trigger, self.target_free_space,
                                                  self.delete_order)

    def configure_from_node(self, node):
        """
        Re-configure myself from the settings defined in the XML node
        """
        for option in ['commitment',
                       'trigger',
                       'target_free_space',
                       'delete_order',
                       ]:
            try:
                setattr(self, option, node.attrib[option])
                #log.debug("set attribute '%s' to '%s'", option, getattr(self, option))
            except KeyError:
                #log.debug("attribute '%s' not defined in XML node." % option)
                pass

    def command_add(self):
        """
        Commandset to add this configuration to a device.
        """
        cmdset = []
        # set all the autodelete options
        for option in [ 'commitment',
                        'trigger',
                        'target_free_space',
                        'delete_order',
                        ]:
            cmdset.append("snap autodelete %s %s %s" % (self.volume.name, option, getattr(self, option)) )
            pass

        # then, actually turn on autodelete
        cmdset.append("snap autodelete %s on" % (self.volume.name))
        return cmdset

    def get_settings(self):
        """
        Return a dictionary of my settings.
        This is useful for building tables in the human readable output documents.
        """
        dict = {}
        for option in [ 'commitment',
                        'trigger',
                        'target_free_space',
                        'delete_order',
                        ]:
            dict[option] = getattr(self, option)
            pass
        return dict

class Qtree:
    def __init__(self, volume, qtree_name=None, security='unix', comment='', rwexports=[], roexports=[], qtreenode=None, oplocks=True):

        """
        A Qtree representation
        """
        self.volume = volume
        if qtree_name is None:
            qtree_name = 'data'
        
        self.name = qtree_name
        self.security = security
        self.comment = comment
        self.rwexports = rwexports
        self.roexports = roexports
        self.qtreenode = qtreenode

        self.oplocks = oplocks

        self.luns = []
        
        log.debug("Created qtree: %s", self)
        
        self.volume.qtrees[self.name] = self
        #self.volume.qtrees.append(self)

    def __str__(self):
        return '<Qtree: %s, %s, sec: %s, rw: %s, ro: %s>' % (self.full_path(), self.volume.proto, self.security, [ str(x) for x in self.rwexports ], [ str(x) for x in self.roexports])

    def full_path(self):
        """
        The full qtree path, including the volume prefix.
        """
        return '/vol/%s/%s' % (self.volume.name, self.name)

    def cifs_share_name(self, hidden=True):
        """
        Get the CIFS share name for the qtree.
        """
        retstr = '%s_%s' % (self.volume.name, self.name)
        if hidden:
            retstr += '$'
            pass
        return retstr

class LUN:
    """
    A LUN lives in a Qtree and is used for iSCSI, predominantly.
    """

    def __init__(self, name, qtree, lunid, size, ostype, exportlist, lunnode=None):

        self.name = name
        self.qtree = qtree
        self.size = size

        if ostype.lower().startswith('solaris'):
            ostype = 'solaris'

        elif ostype.lower().startswith('windows'):
            ostype = 'windows'

        elif ostype.lower().startswith('linux'):
            ostype = 'linux'

        else:
            raise ValueError("Operating system '%s' not support for iSCSI LUNs" % ostype)

        self.ostype = ostype
        self.lunid = lunid
        self.lunnode = lunnode
        self.exportlist = exportlist
        
        self.igroup = None

        log.debug("Created lun: %s", self.name)

        qtree.luns.append(self)

    def full_path(self):
        """
        Return the full path string for LUN creation
        """
        return '%s/%s' % (self.qtree.full_path(), self.name)
        #return self.name

    def get_create_size(self):
        return get_create_size(self.size)

    def __repr__(self):
        return '<LUN %d: %s, %sg, %s, %s>' % (self.lunid, self.full_path(), self.size, self.ostype, self.igroup)

class Vlan:
    """
    A vlan defines the layer 2 network a vfiler belongs to, or a services vlan.
    """

    def __init__(self, number, site='primary', type='project', networks=[], description='', mtu=9000, node=None):

        self.description = description
        self.site = site
        self.sitetype = site
        self.type = type
        self.number = number

        self.networks = networks
        
##         self.network = network
##         self.netmask = netmask
##         self.gateway = gateway
##         self.maskbits = maskbits

        self.mtu = mtu
        self.node = node

        log.debug("Created vlan: %s", self)

    def __repr__(self):
        return '<Vlan: %s, %s/%s: %s>' % (self.number, self.site, self.type, self.networks)

class Network:
    """
    A Network object encapsulates an IP network.
    """

    def __init__(self, number, netmask, maskbits, gateway):
        """
        Create a Network object
        """
        self.number = number
        self.netmask = netmask
        self.maskbits = maskbits
        self.gateway = gateway

    def __repr__(self):

        return "<Network: %s/%s (%s) -> %s>" % (self.number, self.maskbits, self.netmask, self.gateway)

class Export:
    """
    An encapsulation of a storage export to a specific host/IP
    """
    def __init__(self, tohost, fromip, type='rw', toip=None):
        """
        An export to a given host, from a particular address
        """
        self.type = type
        self.tohost = tohost
        self.fromip = fromip
        self.toip = toip

    def __eq__(self, export):
        if export.type == self.type and export.tohost == self.tohost and \
           export.fromip == self.fromip and export.toip == self.toip:
            return True
        
        return False

    def __ne__(self, export):
        if self == export:
            return False
        
        return True

class iGroup:
    """
    An iGroup is a LUN mask for NetApp filers. It maps particular LUNs
    to the hosts (iSCSI initiators) that can access the LUNs.
    """

    def __init__(self, name, filer, exportlist=[], lunlist=[], type='windows'):
        self.name = name
        self.filer = filer
        self.type = type
        self.exportlist = exportlist
        self.lunlist = lunlist
        log.debug("Created iGroup %s", self)

    def __repr__(self):
        return '<iGroup: %s, %s, %s, %s>' % (self.name, self.type, self.filer.name, self.exportlist)

class Snapshot:
    """
    A Snapshot is a local snapshot backup.
    SnapVaults and SnapMirrors are different objects, defined below.
    """
    def __init__(self, sourcevol, numweekly, numdaily, hourly_schedule):
        self.sourcevol = sourcevol
        self.numweekly = numweekly
        self.numdaily = numdaily
        self.hourly_schedule = hourly_schedule

        self.sourcevol.snaps.append(self)

    def __str__(self):
        return '<Snapshot: %s -> %s, %s, %s>' % (self.sourcevol.namepath(),
                                                  self.targetvol.namepath(),
                                                  self.basename,
                                                  self.schedule,
                                                  )

class SnapVault:
    """
    A SnapVault is a special kind of snapshot that requires a baseline
    to be taken on the source volume, which is then transferred to a
    SnapVault secondary device at some later time.

    A variant of the SnapVault is a destination only SnapVault snapshot,
    which assumes there is another SnapVault defined that will cause
    data to be transferred from a primary device. This destination only
    SnapVault is the mechanism recommended in the NetApp Best Practices Guide
    for doing weekly snapshots when you transfer data daily.
    """

    def __init__(self, sourcevol, targetvol, basename, src_schedule=None, dst_schedule=None):

        self.sourcevol = sourcevol
        self.targetvol = targetvol
        self.basename = basename
        self.src_schedule = src_schedule
        self.dst_schedule = dst_schedule

        self.sourcevol.snapvaults.append(self)
        self.targetvol.snapvaults.append(self)

    def __str__(self):
        return '<SnapVault: %s -> %s, %s, %s, %s>' % (self.sourcevol.namepath(),
                                                      self.targetvol.namepath(),
                                                      self.basename,
                                                      self.src_schedule,
                                                      self.dst_schedule,
                                                      )

class SnapMirror:

    def __init__(self, sourcevol, targetvol, minute='*', hour='*', dayofmonth='*', dayofweek='*', arguments='-'):

        self.sourcevol = sourcevol
        self.targetvol = targetvol
        self.minute = minute
        self.hour = hour
        self.dayofmonth = dayofmonth
        self.dayofweek = dayofweek

        self.arguments = arguments

        self.sourcevol.snapmirrors.append(self)
        self.targetvol.snapmirrors.append(self)

    def __str__(self):
        return '<SnapMirror: %s -> %s, %s>' % (self.sourcevol.namepath(),
                                                  self.targetvol.namepath(),
                                                  self.etc_snapmirror_conf_schedule(),
                                                  )
    def etc_snapmirror_conf_schedule(self):
        """
        Returns a string of the schedule part of the /etc/snapmirror.conf
        entry for this SnapMirror.
        """
        return '%s %s %s %s' % (self.minute, self.hour, self.dayofmonth, self.dayofweek)

    def etc_snapmirror_conf_arguments(self):
        """
        Returns the arguments for the snapmirror in the format expected for
        /etc/snapmirror.conf.
        Currently this only supports the default of '-'.
        """
        return self.arguments

class ConfigInvalid(Exception):
    """
    A ConfigInvalid Exception is raised if the configuration is invalid for some
    reason that has been captured and an error logged. This allows cleaner
    exiting when a known error is detected, as distinct from some other, unhandled
    error condition that may occur.
    This helps users see useful error messages that can help them fix the config
    issue, rather than receiving a Python traceback, which confuses them, and
    comes after the error message, so they can't see if when building a full set
    of project documentation.
    """
    pass
        
class ProjectConfig:

    def __init__(self, configfile, defaultsfile):
        """
        Create a ProjectConfig object based on a parsed configuration .xml definition file.

        This enables us to more easily represent the configuration as a set of objects,
        rather than an XML document.
        """
        self.defaults = SafeConfigParser()
        parsedfiles = self.defaults.read(defaultsfile)
        if len(parsedfiles) == 0:
            raise ValueError("Cannot load defaults file: %s" % defaultsfile)
        
        self.tree = etree.parse(configfile)

        self.filers = {}
        self.volumes = []

        self.snapshots = []
        self.snapvaults = []
        self.snapmirrors = []
        self.allowed_protocols = []

        self.has_dr = False

        self.load_project_details()

        # Define a series of attributes that a ProjectConfig can have.
        # These are all the things that are used by the documentation templates.

        self.primary_project_vlan = self.get_project_vlan('primary').number
        if self.has_dr:
            self.secondary_project_vlan = self.get_project_vlan('secondary').number

        self.verify_config()

    def load_project_details(self):

        self.prefix = self.tree.xpath('//project/prefix')[0].text
        self.code = self.tree.xpath('//project/code')[0].text
        self.shortname = self.tree.xpath('//project/shortname')[0].text
        self.longname = self.tree.xpath('//project/longname')[0].text

        self.known_switches = self.load_known_switches()

        # Project switches is populated when loading the hosts.
        self.project_switches = {}

        self.revlist = self.load_revisions()

        self.sites = self.load_sites()

        self.vlans = self.load_vlans()

        self.interfaces = []
        self.hosts = self.load_hosts()

        # Perform some sanity checking on the hosts
        self.sanity_check_hosts(self.hosts)

        self.drhosts = []
        for host in self.hosts.values():
            for drhostname in host.drhosts:
                self.drhosts.append(self.hosts[drhostname])
                
        self.filers = self.load_filers()
        self.vfilers = self.load_vfilers()

        self.sanity_check_vfilers(self.vfilers)
        
        self.volumes = self.load_volumes()

        for vol in self.volumes:
            if vol.proto not in self.allowed_protocols and vol.proto is not None:
                self.allowed_protocols.append(vol.proto)

        self.qtrees = self.load_qtrees('primary')
        self.qtrees.extend( self.load_qtrees('secondary') )

        self.luns = self.load_luns()
        self.igroups = self.load_igroups()

    def load_revisions(self):
        """
        Load all the document revisions into a list
        """
        revlist = []

        for element in self.tree.xpath('revhistory/revision'):
            majornumber = element.xpath('majornumber')[0].text
            minornumber = element.xpath('minornumber')[0].text
            date = element.xpath('date')[0].text
            authorinitials = element.xpath('authorinitials')[0].text
            remark = element.xpath('revremark')[0].text
            try:
                reviewer = element.xpath('reviewer')[0].text
            except IndexError:
                log.warn("Revision '%s.%s' has no reviewer." % (majornumber, minornumber) )
                reviewer = ''
                pass
            try:
                reviewdate = element.xpath('reviewdate')[0].text
            except IndexError:
                log.warn("Revision '%s.%s' has no reviewer." % (majornumber, minornumber) )
                reviewdate = ''
                
            rev = Revision(majornumber, minornumber, date, authorinitials, remark, reviewer, reviewdate)
            revlist.append(rev)

        return revlist

    def get_latest_revision(self):
        """
        Sort the revisions and return the latest one.
        Sorts based on the revision number
        """
        # Use the decorate, sort, undecorate idiom
        
        revlist = [ ('%s.%s' % (x.majornum, x.minornum), x) for x in self.revlist ]
        revlist.sort()
        #log.debug("Last revision is: %s", revlist[-1])
        return revlist[-1][1]

    def load_known_switches(self, config_file=None):
        """
        Load known switches from a configuration file.
        You can thus define site-wide switch configurations for known
        devices, containing their names, physical locations, connectivity information, etc.
        """
        known_switches = {}
        # FIXME: Add the ability to define a switches.conf in the defaults docgen.conf file
        config_file = os.path.join(_configdir, 'switches.conf')
        reader = csv.reader( open(config_file, 'rb'))
        for row in reader:
            if len(row) < 1:
                continue
            
            if row[0].startswith('#'):
                continue
            (switchname, type, sitename, location, core01, core02) = row
            switch = Switch(switchname, type, sitename, location, [ core01, core02 ])

            known_switches[switchname] = switch
            pass

        return known_switches

    def load_sites(self):
        """
        Load site specific configuration information
        """
        sites = {}
        site_nodes = self.tree.xpath('site')
        for node in site_nodes:

            # Site name is a new attribute, so allow a kind of backwards compatibility for now
            try:
                site_name = node.attrib['name']
            except KeyError:
                log.warning("Site name not set. This is important, but not fatal. Yet.")
                site_name = node.xpath('filer/@name')[0].split('-')[0]
                log.debug("site name is set to: %s", site_name)
                
            # Get the site type from the defaults if it isn't set
            try:
                site_type = node.attrib['type']

            except KeyError:
                site_type = self.defaults.get(site_name, 'type')

            # Get the site location from the defaults if it isn't set                
            try:
                site_location = node.attrib['location']
            except KeyError:
                log.warn('Site location not set!')
                site_location = self.defaults.get(site_name, 'location')
                pass

            # Add default site servers for CIFS
            # This should be added the DTD to allow manual override
            nameservers = self.defaults.get(site_name, 'nameservers').split()
            winsservers = self.defaults.get(site_name, 'winsservers').split()
            
            sites[site_name] = Site(site_name, site_type, site_location, nameservers, winsservers)
            pass
        return sites

    def load_hosts(self):
        """
        Load all the hosts
        """
        hosts = {}
        hostnodes = self.tree.xpath('site/host')
        if len(hostnodes) == 0:
            if len(self.tree.findall('host')) > 0:
                log.error("Hosts need to be defined within a <site/>.")
            raise ValueError("No project hosts are defined.")

        for node in hostnodes:

            # find some mandatory attributes
            hostname = node.attrib['name']

            # See if a site name is defined, if not, use the first site of this type
            # since most implementations only have a single 'primary' site, for example.
            try:
                sitename = node.xpath('ancestor::site')[0].attrib['name']
                site = self.sites[sitename]
            except KeyError:
                sitetype = node.xpath('ancestor::site')[0].attrib['type']
                site = [ site for site in self.sites.values() if site.type == sitetype][0]

            # check to see if the host has already been defined
            if hostname in hosts.keys():
                errstr = "Host '%s' is defined more than once. Hostnames must be unique." % hostname
                log.error(errstr)
                raise ValueError(errstr)
            
            host_attribs = {}
            for attrib in ['platform', 'operatingsystem', 'location']:
                try:
                    host_attribs[attrib] = node.find(attrib).text
                except AttributeError:
                    log.error("Cannot find host attribute '%s' for host '%s'", attrib, hostname)
                    raise

            try:
                is_virtual = node.attrib['virtual']
                if is_virtual.lower() == 'yes':
                    is_virtual=True
                    log.debug("Host '%s' is virtual.", hostname)
                else:
                    is_virtual=False
            except KeyError:
                is_virtual=False

            try:
                description = node.find('description')[0].text
            except IndexError:
                description = ''

            try:
                iscsi_initiator = node.find('iscsi_initiator').text
            except AttributeError:
                iscsi_initiator = None

            drhostnodes = node.findall('drhost')
            drhosts = [ host.attrib['name'] for host in drhostnodes ]

            # Load host interfaces
            ifaces = []
            interface_nodes = node.findall('interface')
            log.debug("found host interfaces: %s", interface_nodes)
            for ifnode in interface_nodes:
                try:
                    switchname = ifnode.find('switchname').text
                    switchport = ifnode.find('switchport').text
                except AttributeError, e:
                    if not is_virtual:
                        log.warn("Host switch configuration not present for %s: %s", hostname, e)
                    switchname = None
                    switchport = None

                try:
                    hostport = ifnode.find('hostport').text
                except AttributeError, e:
                    log.warn("No host port defined for host: %s", hostname)
                    hostport = None

                try:
                    ipaddr = ifnode.find('ipaddr').text
                except AttributeError:
                    ipaddr = None


                type = ifnode.attrib['type']
                try:
                    mode = ifnode.attrib['mode']
                except KeyError:
                    mode = 'passive'

                try:
                    mtu = int(ifnode.attrib['mtu'])
                except KeyError:
                    # If the MTU isn't set on the interface, use the project VLAN MTU
                    vlan = self.get_project_vlan(site.type)
                    mtu = vlan.mtu

                # Figure out the VLANs this interface should be in.
                # If one isn't defined, but it in the first 'project' VLAN
                vlan_nums = ifnode.findall('vlan_number')
                if len(vlan_nums) == 0:
                    vlans = [ vlan for vlan in self.vlans if vlan.site == site.type and vlan.type == 'project' ]

                else:
                    # Find all the vlans this interface can talk to (ie: it's a trunk)
                    vlans = []
                    for vlan_num in vlan_nums:
                        vlans.extend([ vlan for vlan in self.vlans if vlan.site == site.type and vlan.number == vlan_num ])
                        pass
                    pass

                # Add the required switch to the project switches list
                if switchname is not None:
                    try:
                        switch = self.known_switches[switchname]
                    except KeyError:
                        raise KeyError("Switch '%s' is not defined. Is it in switches.conf?" % switchname)

                    log.debug("Adding switch '%s' to project switch list at site '%s'", switch, site)
                    switch.site = site
                    self.project_switches[switchname] = switch

                    # If this is an edge, make sure its connected cores are added to the
                    # list of project switches.
                    if switch.type == 'edge':
                        for coreswitch in switch.connected_switches:
                            if coreswitch not in self.project_switches:
                                self.project_switches[coreswitch] = self.known_switches[coreswitch]
                                self.project_switches[coreswitch].site = site
                                pass
                            pass
                        pass

                # Sanity check the interface parameters. The combination of switchname+switchport should
                # only occur once, unless either is None, in which case it doesn't matter.
                for iface in self.interfaces:
                    #log.debug("checking interface: %s", iface)
                    
                    if iface.switchname is not None and iface.switchname == switchname and iface.switchport == switchport:
                        log.warn("switch:port combination '%s:%s' is used more than once in project config." % (switchname, switchport) )
                
                iface = Interface(type, mode, switchname, switchport, hostport, ipaddr, mtu, vlans)
                ifaces.append(iface)
                self.interfaces.append(iface)
                
            hosts[hostname] = Host(hostname, platform=host_attribs['platform'],
                                   os=host_attribs['operatingsystem'],
                                   site=site,
                                   location=host_attribs['location'],
                                   description=description,
                                   drhosts=drhosts,
                                   interfaces=ifaces,
                                   iscsi_initiator=iscsi_initiator,
                                   is_virtual=is_virtual)
            site.hosts[hostname] = hosts[hostname]
        return hosts

    def sanity_check_hosts(self, hostdict):
        """
        Perform some sanity checking of the hosts configuration to
        ensure that silly things aren't done, such as duplicating
        IP addresses, or assigning the same interfaces to 2 hosts.
        """
        ifaces = []
        for host in hostdict.values():
            for host_iface in host.interfaces:
                for known_iface in ifaces:
                    # Check the same switchport isn't allocated to different hosts
                    # Multiple zones on a single physical host will use the same physical ports, though.
                    if host_iface.switchname is not None and host_iface.switchname == known_iface.switchname and host_iface.switchport == known_iface.switchport:
                        log.warn("Host '%s' is using the same switchport as another host in the project." % host.name)

                    # Check that IP addresses aren't duplicated
                    if host_iface.ipaddress is not None and host_iface.ipaddress == known_iface.ipaddress:
                        raise ValueError("Host '%s' is using the same IP address '%s' as another host in the project." % (host.name, host_iface.ipaddress) )
                    pass
                pass

            # add the checked interfaces to the master list
            ifaces.extend( host.interfaces )
            pass
        pass
    
    def sanity_check_vfilers(self, vfiler_dict):
        """
        Perform some sanity checking of vFilers.
        """
        #log.info("%d vfilers exist.", len(vfiler_dict.values()))
        known_ips = []
        for vfiler in vfiler_dict.values():
            #log.debug("checking %s", vfiler.name)
            #log.debug("ipaddress is: %s", vfiler.ipaddress)
            if vfiler.ipaddress in known_ips:
                raise ValueError("Duplicate IP address '%s' used on filer '%s'" % ( vfiler.ipaddress, vfiler.filer.name) )

            known_ips.append(vfiler.ipaddress)
            pass

    def load_filers(self):
        """
        Create filer objects from configuration
        """
        filers = {}
        filernodes = self.tree.xpath("site/filer")
        for node in filernodes:
            filername = node.attrib['name']

            # Check to make sure the filer name isn't already defined
            if filername in filers.keys():
                log.error("Filer name '%s' is already defined!", filername)
                raise ValueError("Filer named '%s' is already defined." % filername)

            # Figure out which site this Filer belongs to
            try:
                sitename = node.xpath('ancestor::site')[0].attrib['name']
                site = self.sites[sitename]

            except KeyError:
                sitetype = node.xpath('ancestor::site')[0].attrib['type']
                site = [ site for site in self.sites.values() if site.type == sitetype][0]

            sitetype = node.xpath("parent::*/@type")[0]

            if sitetype == 'secondary':
                self.has_dr = True

            filer = Filer(filername, node.attrib['type'], site)
            filers[filername] = filer

            # figure out which filer this is a secondary for
            if filer.type == 'secondary':
                my_primary = node.xpath("preceding-sibling::filer")[0].attrib['name']
                filer.secondary_for = filers[my_primary]
                filers[my_primary].secondary_is = filer
                pass

            log.debug("Created filer: %s", filer)
            pass
        
        return filers

    def load_vfilers(self):
        """
        Create vfiler objects from configuration
        """
        vfilers = {}
        vfilernodes = self.tree.xpath("site/filer/vfiler")
        for node in vfilernodes:

            filername = node.xpath("parent::*/@name")[0]
            
            try:
                name = node.attrib['name']
            except KeyError:
                name = self.shortname

            try:
                rootaggr = node.attrib['rootaggr']
            except KeyError:
                raise KeyError("vfiler '%s' on filer '%s' has no 'rootaggr' specified." % (name, filername) )

            filer = self.filers[filername]
            try:
                vlan = None
                vlan_num = node.xpath("ancestor::site/vlan/@number")[0]
                for v in self.vlans:
                    if v.type == 'project' and v.number == vlan_num and filer.site.type == v.site:
                        vlan = v

                if vlan is None:
                    raise ValueError("Cannot find VLAN '%s' for filer '%s'" % (vlan_num, filername) )
                
            except IndexError:
                log.error("Cannot find vlan number for %s" % filername )
                raise

            ipaddress = node.xpath("primaryip/ipaddr")[0].text

            try:
                netmask = node.xpath("primaryip/netmask")[0].text
            except IndexError:
                netmask = '255.255.255.254'
                pass

            # Add any alias IP addresses that may be defined.
            aliasnodes = node.findall('aliasip')
            alias_ips = []
            for alias_node in aliasnodes:
                alias_ipaddr = alias_node.find('ipaddr').text
                alias_netmask = alias_node.find('netmask').text
                alias_ips.append( (alias_ipaddr, alias_netmask) )

            gateway = vlan.networks[0].gateway
            #gateway = node.xpath("ancestor::site/vlan/@gateway")[0]

            vfiler_key = '%s:%s' % (filer.name, name)

            dns_domain_name = self.defaults.get('global', 'dns_domain_name')
            ad_account_location = self.defaults.get('global', 'ad_account_location')

            # FIXME: This is dependent on the filer.site value being a string of the site 'type',
            # rather than a reference to the Site object, as it should be. Much code change is
            # required to change this everywhere, though.
            site = [ site for site in self.sites.values() if site.type == filer.site.type ][0]
            
            vfilers[vfiler_key] = VFiler(filer, name, rootaggr, vlan, ipaddress, gateway, netmask,
                                         alias_ips,
                                         dns_domain_name, ad_account_location,
                                         site.nameservers, site.winsservers)

            for vlanip in node.xpath("vlanip"):
                # Find the vlan object that relates to the vlan mentioned here
                log.debug("found additional VLAN ip for vlan %s", vlanip.attrib['vlan'])
                try:
                    vlan_node = vlanip.xpath("ancestor::site/vlan[@type = 'services' and @number = '%s']" % vlanip.attrib['vlan'])[0]
                except IndexError:
                    raise ValueError("vlanip references non-existant VLAN '%s'" % vlanip.attrib['vlan'])
                log.debug("vlan_node is: %s", vlan_node)
                vlan = [ x for x in self.vlans if x.node == vlan_node ][0]
                vfilers[vfiler_key].add_service_ip( vlan, vlanip.find('ipaddr').text )
                pass

        return vfilers

    def load_volumes(self):
        """
        Create all the volumes in the configuration
        """
        volnodes = self.tree.xpath("site/filer/vfiler/aggregate/volume | site/filer/vfiler/aggregate/volumeset")

        # Add root volumes to the filers/vfilers
        self.add_root_volumes()

        # number volumes from 0
        volnum = 0
        for node in volnodes:
            if node.tag == 'volumeset':
                vols, volnum = self.create_volumeset(node, volnum)
                self.volumes.extend(vols)
            else:
                vol, volnum = self.create_volume(node, volnum)
                self.volumes.append(vol)
                
        # Add snapshots for those source volumes with snaprefs
        for vol in self.volumes:
            self.create_snapshot_for(vol)

        # Add snapmirror volumes for those source volumes with snapmirrorrefs
        for vol in [ x for x in self.volumes if len(x.snapmirrorref) > 0 ]:
            self.create_snapmirror_for(vol)

        # Add snapvault volumes for those source volumes with snapvaultrefs
        # This will snapvault the secondary root volumes to the secondary nearstore
        for vol in [ x for x in self.volumes if len(x.snapvaultref) > 0 ]:
            #log.debug("Adding snapvault for: %s", vol)
            self.create_snapvault_for(vol)

        return self.volumes

    def add_root_volumes(self):
        """
        Create root volumes for all filers.
        """
        # Create root volumes for defined vfilers

        # Always have a root volume on the primary filers
        for filer in [ x for x in self.filers.values() if x.type == 'primary' ]:
            for vfiler in filer.vfilers.values():
                log.debug("Adding root volume for vfiler '%s' on '%s'...", vfiler.name, filer.name)
                snapref = []
                # The expected name of the snapvault schedule for root volumes
                # is default_primary or default_secondary
                snapvaultref = ['default_%s' % filer.site.type]

                # We don't snapmirror root volumes
                snapmirrorref = []

                vol = Volume('%s_root' % self.shortname,
                             filer,
                             vfiler.rootaggr,
                             usable=0.02,
                             raw=0.02,
                             snapreserve=20,
                             snapref=snapref,
                             snapvaultref=snapvaultref,
                             snapmirrorref=snapmirrorref,
                             )
                self.volumes.append(vol)
                pass
        
        # Always have a root volume on the nearstores
        for filer in [ x for x in self.filers.values() if x.type == 'nearstore' ]:
            for vfiler in filer.vfilers.values():
                log.debug("Adding root volume for vfiler '%s' on '%s'...", vfiler.name, filer.name)

                snapref = []
                snapvaultref = []
                snapmirrorref = []

                vol = Volume('%s_root' % self.shortname,
                             filer,
                             vfiler.rootaggr,
                             usable=0.02,
                             raw=0.02,
                             snapreserve=20,
                             snapref=snapref,
                             snapvaultref=snapvaultref,
                             snapmirrorref=snapmirrorref,
                             )
                self.volumes.append(vol)
                pass
            pass
        pass
    
    def load_qtrees(self, site='primary'):
        """
        Build the qtrees for the configuration.
        """
        qtree_list = []
        vols = [ vol for vol in self.volumes if vol.filer.site.type == site and vol.type not in [ 'snapvaultdst', 'snapmirrordst' ] ]

        for vol in vols:

            # If no volnode exists for the volume, this is an automatically generated volume
            if vol.volnode is None:
                # If this is the root volume, don't create qtrees
                if vol.name.endswith('root'):
                    continue

                # otherwise, we only create 1 qtree per volume, by default
                # FIXME: include determination of qtree name due to databases
                else:
                    log.warn("No volume node available for: %s", vol)
                    rwexports = [ Export(host, vol.filer.vfilers.values()[0].ipaddress, 'rw') for host in self.hosts.values() ]
                    qtree = Qtree(vol, rwexports=rwexports )
                    qtree_list.append(qtree)
                    pass
                pass
            else:
                # There is a volume node, so we use it to look for qtree
                # definitions, which must be a child-element of the <volume/> node.
                
                # If there are qtrees defined, use their definitions.
                # This allows for more than one qtree per volume, if required.
                qtree_nodes = vol.volnode.xpath("qtree")
                if len(qtree_nodes) > 0:
                    #log.debug("Processing qtree nodes: %s", qtree_nodes)
                    for qtree_node in qtree_nodes:
                        try:
                            name = qtree_node.xpath("@name")[0]
                            qtree_name = '%s' % name
                        
                        except IndexError:
                            log.info("Qtree has no name, using 'data'.")
                            qtree_name = 'data'

                        try:
                            qtree_security = qtree_node.xpath("@security")[0]
                        except IndexError:
                            # If qtree security isn't set manually, use defaults for
                            # the kind of volume
                            log.debug("Determining qtree security mode: %s, %s", vol.name, vol.proto)
                            if vol.proto == 'cifs':
                                log.debug("CIFS volume '%s' qtree requires NTFS security.", vol.name)
                                qtree_security = 'ntfs'
                            else:
                                qtree_security = 'unix'

                        oplocks = self.get_oplocks_value(qtree_node)

                        try:
                            qtree_comment = qtree_node.find('description').text
                        except AttributeError:
                            if qtree_node.text is None:
                                qtree_comment = ''
                            else:
                                log.warn("Qtree description should be wrapped in <description> tags")
                                qtree_comment = qtree_node.text

                        rwexports, roexports = self.get_exports(qtree_node, self.get_vfiler_ips(vol.filer.vfilers.values()[0]))
                        
##                         log.error("Host named '%s' not defined" % hostname)
##                         raise ValueError("Attempt to export qtree to non-existant host: '%s'" % hostname)

                        qtree = Qtree(vol, qtree_name, qtree_security, qtree_comment, rwexports, roexports, qtreenode=qtree_node, oplocks=oplocks)

                        qtree_list.append(qtree)
                        pass
                    pass
                else:
                    log.debug("No qtrees defined. Inventing them for this volume.")

                    oplocks = self.get_oplocks_value(vol.volnode)

                    # If no qtrees are defined, invent one
                    if vol.type.startswith('ora'):
                        log.debug("Oracle volume type detected.")
                        # Build oracle qtrees

                        # We always number from 1
                        sid_id = 1

                        # Find the SID for the database this volume is for
                        # Oracle RAC quorum volume doesn't refer to a specific database
                        try:
                            sid=vol.volnode.xpath("@oracle")[0]
                            log.debug("Found oracle SID: %s", sid)

                            # Then find the list of hosts the database is on
                            onhost_names = self.tree.xpath("database[@id = '%s']/onhost/@name" % sid)
                            if len(onhost_names) == 0:
                                log.warn("Database with id '%s' is not defined. Manual exports must be defined for volume '%s'." % (sid, vol.name))
                            
                            log.debug("onhost_names are: %s", onhost_names)

                            # Add manually defined exports, if any exist
                            rwexports, roexports = self.get_exports(vol.volnode, self.get_vfiler_ips(vol.filer.vfilers.values()[0]), default_to_all=False)
                            log.debug("database hostlists: %s, %s", rwexports, roexports)
                            
                            for hostname in onhost_names:
                                log.debug("Database %s is on host %s. Adding to rwexports." % (sid, hostname) )
                                try:
                                    if self.hosts[hostname] not in [ export.tohost for export in rwexports ]:
                                        rwexports.append(Export(self.hosts[hostname], vol.filer.vfilers.values()[0].ipaddress, 'rw') )
                                except KeyError:
                                    log.error("Database '%s' is on host '%s', but the host is not defined." % (sid, hostname) )
                                    raise
                                pass

                        except IndexError:
                            rwexports, roexports = self.get_exports(vol.volnode, self.get_vfiler_ips(vol.filer.vfilers.values()[0]))

                        # If the hostlist is empty, assume qtrees are available to all hosts
                        if len(rwexports) == 0 and len(roexports) == 0:
                            log.debug("rwexports and roexports are both empty. Adding all hosts...")
                            rwexports = [ Export(host, vol.filer.vfilers.values()[0].ipaddress, 'rw') for host in self.hosts.values() ]

                        log.debug("hostlists are now: %s, %s", rwexports, roexports)
                            
                        if vol.type == 'oraconfig':
                            qtree_name = 'ora_config'
                            security = 'unix'
                            comment = 'Oracle configuration qtree'
                            qtree = Qtree(vol, qtree_name, security, comment, rwexports=rwexports, roexports=roexports, oplocks=oplocks)
                            qtree_list.append(qtree)

                        elif vol.type == 'oracm':
                            qtree_name = 'ora_cm'
                            security = 'unix'
                            comment = 'Oracle quorum qtree'
                            qtree = Qtree(vol, qtree_name, security, comment, rwexports=rwexports, roexports=roexports, oplocks=oplocks)
                            qtree_list.append(qtree)

                        else:
                            # qtree name is the voltype with the 'ora' prefex stripped off
                            qtree_name = 'ora_%s_%s%02d' % ( sid, vol.type[3:], sid_id)
                            security = 'unix'
                            comment = 'Oracle %s qtree' % vol.type[3:]
                            qtree = Qtree(vol, qtree_name, security, comment, rwexports=rwexports, roexports=roexports, oplocks=oplocks)
                            qtree_list.append(qtree)

                            #
                            # If this is an oraredo volume, it contains both an ora_redo qtree
                            # and an ora_temp area to hold the temporary data
                            #
                            if vol.type == 'oraredo':
                                qtree_name = 'ora_%s_temp%02d' % ( sid, sid_id )
                                security = 'unix'
                                comment = 'Oracle temp qtree'
                                qtree = Qtree(vol, qtree_name, security, comment, rwexports=rwexports, roexports=roexports, oplocks=oplocks)
                                qtree_list.append(qtree)
                                pass
                            pass
                        pass
                    #
                    # Not an Oracle volume, so this is a standard data volume
                    #

                    else:
                        if vol.proto == 'cifs':
                            log.debug("CIFS volume '%s' qtree requires NTFS security.", vol.name)
                            qtree_security = 'ntfs'
                        else:
                            qtree_security = 'unix'
                            pass

                        # Figure out the hostlist by checking for volume based export definitions
                        rwexports, roexports = self.get_exports(vol.volnode, self.get_vfiler_ips(vol.filer.vfilers.values()[0]))

                        qtree = Qtree(vol, security=qtree_security, rwexports=rwexports, roexports=roexports, oplocks=oplocks)
                        qtree_list.append(qtree)
                    pass
                pass

            # Check to see if we need to export the DR copy of the qtrees to the
            # dr hosts.
            # If this volume is snapmirrored, give any drhosts the same export
            # permissions at the remote side as they do on the local side
            if len(vol.snapmirrors) > 0:

                for qtree in vol.qtrees.values():
                    dr_rwexports = []
                    dr_roexports = []

                    # Add rw drhosts for the qtree
                    for export in qtree.rwexports:
                        for drhostname in export.tohost.drhosts:
                            dr_rwexports.append( Export(self.hosts[drhostname], export.fromip, export.type, export.toip))
                        pass

                    for export in qtree.roexports:
                        for drhostname in export.tohost.drhosts:
                            dr_roexports.append( Export(self.hosts[drhostname], export.fromip, export.type, export.toip))
                        pass

                    # If either list is not empty, we need to create a Qtree on the
                    # snapmirror target volume with appropriate exports
                    if len(dr_rwexports) > 0 or len(dr_roexports) > 0:
                        log.debug("qtree '%s:%s' needs to be exported at DR", qtree.volume.name, qtree.name)

                        # Create one remote qtree for each snapmirror relationship
                        for snapmirror in vol.snapmirrors:
                            log.debug("Adding remote exported qtree on targetvol: %s", snapmirror.targetvol.name)
                            mirrored_qtree = Qtree( snapmirror.targetvol,
                                                    qtree.name,
                                                    qtree.security,
                                                    qtree.comment,
                                                    dr_rwexports,
                                                    dr_roexports,
                                                    oplocks=qtree.oplocks
                                                    )
                            qtree_list.append(mirrored_qtree)
                            pass
                        pass
                    else:
                        log.debug("No hosts for qtree '%s' have corresponding DR hosts. Not exporting at DR.", qtree.name)
                    pass
                pass
            pass

        return qtree_list

    def get_host_qtree_mountoptions(self, host, qtree):
        """
        Find the mountoptions for a host for a specific qtree.
        This allows the system to automatically determine the
        mount options that a given host should use when mounting
        a qtree.
        It returns the additional mount options that are special
        for this qtree. It assumes that standard mount options, such
        as 'hard', will not be included in this list.
        """
        mountoptions = []
        osname = host.os

        # always add read/write or read-only mount options, because
        # they're really important.
        if host in [ export.tohost for export in qtree.rwexports ]:
            #log.debug("Read/Write host")
            mountoptions.append('rw')

        if host in [ export.tohost for export in qtree.roexports ]:
            #log.debug("Read-only host")
            mountoptions.append('ro')
            pass
        
        # See if there are any manually defined mount options for
        # the qtree, or volume the qtree lives in. Most specific wins.
        # If you specify mountoptions manually, you have to specify *all*
        # of them, or you'd risk the computer guessing what you meant,
        # and they usually get that wrong.. and then you have to wrestle with
        # the damn thing to get it to do what you mean.
        if qtree.qtreenode is not None:
            mountoptions.extend( self.get_extra_mountoptions(qtree.qtreenode, host) )
        elif qtree.volume.volnode is not None:
            mountoptions.extend( self.get_extra_mountoptions(qtree.volume.volnode, host) )

        # If you don't manually define mount options, use some sensible defaults
        else:
            
            if qtree.volume.type in [ 'oracm', 'oradata', 'oraindx', 'oraundo', 'oraarch', 'oraredo' ]:

                if osname.lower().startswith('solaris'):
                    #log.debug("Solaris mount option required")
                    mountoptions.extend( [ 'forcedirectio', 'noac', 'nointr' ] )

                elif osname.lower().startswith('linux'):

                    #log.debug("Linux mount option required")
                    mountoptions.extend( [ 'actimeo=0', ] )
                    pass

                else:
                    log.error("Unknown operating system '%s', cannot set mountoptions.", osname)
                    pass
                pass

            # Non Oracle volume options for Solaris
            elif osname.lower().startswith('solaris'):
                mountoptions.extend([ 'intr', ])

            elif osname.lower().startswith('linux'):
                mountoptions.extend([ 'intr', ])
                pass
            pass
        
        #log.debug("mountoptions are: %s", mountoptions)
        return mountoptions

    def load_luns(self):
        """
        Load LUN definitions.
        """
        lunlist = []
        smluns = []

        # The current lunid in use for automated numbering
        current_lunid = 0
        for vol in [ vol for vol in self.volumes if vol.proto == 'iscsi' and vol.type not in [ 'snapvaultdst', 'snapmirrordst' ] ]:
            log.debug("Found iSCSI volume for LUNs: %s", vol)
            lun_total = 0

            # check to see if any LUN nodes are defined.
            luns = vol.volnode.xpath("descendant-or-self::lun")
            if len(luns) > 0:
                log.debug("found lun nodes: %s", luns)

                # If you specify LUN sizes, the system will use exactly
                # what you define in the config file.
                # If you don't specify the LUN size, then the system will
                # divide up however much storage is left in the volume evenly
                # between the number of LUNs that don't have a size specified.

                for lunnode in vol.volnode.xpath("descendant-or-self::lun"):

                    # Check to see if we need to restart the lunid numbering
                    if lunnode.attrib.has_key('restartnumbering'):
                        current_lunid = int(lunnode.attrib['restartnumbering'])

                    # Check to see if the lunid is specified for this lun
                    try:
                        lunid = int(lunnode.attrib['lunid'])
                        log.debug("lunid manually specified: %d", lunid)
                    except KeyError:
                        lunid = current_lunid
                        current_lunid += 1

                    try:
                        lunsize = float(lunnode.xpath("@size")[0])
                    except IndexError:
                        log.debug("No LUN size specified. Figuring it out...")

                        # Count the number of LUNs with no size specified. Available
                        # usable storage will be divided evenly between them
                        nosize_luns = len(vol.volnode.xpath("descendant-or-self::lun[not(@size)]"))

                        # total the number of sized luns
                        sized_luns = vol.volnode.xpath("descendant-or-self::lun[(@size)]")
                        log.debug("sized luns are: %s", sized_luns)
                        sized_total = sum([ int(lun.attrib['size']) for lun in sized_luns ])
                        log.debug("sized total is: %s", sized_total)
                        
                        log.debug("Available for allocation: %s", vol.iscsi_usable - sized_total)

                        lunsize = float(vol.iscsi_usable - sized_total) / nosize_luns
                        log.debug("calculated lun size of: %s", lunsize)
                        pass
                    
                    log.debug("Allocating %sg storage to LUN", lunsize)
                    lun_total += lunsize
                    
                    rwexports, roexports = self.get_exports(lunnode, self.get_vfiler_ips(vol.filer.vfilers.values()[0]))
                    exportlist = rwexports + roexports

                    log.debug("LUN will be exported to %s", exportlist)

                    # See if a qtree parent node exists
                    try:
                        qtree_parent_node = lunnode.xpath('parent::qtree')[0]
                        qtree_parent = [ qtree for qtree in vol.qtrees.values() if qtree_parent_node == qtree.qtreenode ][0]
                    except IndexError:
                        # No qtree node defined, so use the first one in the volume.
                        # Technically, there should only be one.
                        qtree_parent = vol.qtrees.values()[0]

                    try:
                        lunname = lunnode.xpath("@name")[0]
                    except IndexError:
                        if exportlist[0].tohost.iscsi_initiator is None:
                            raise ValueError("Host %s has no iSCSI initiator defined." % exportlist[0].tohost.name)

                        lunname = '%s.lun%02d' % (self.shortname, lunid)
                        pass
                
                    # Add a LUN for each one found within the volume
                    newlun = LUN( lunname, qtree_parent, lunid, lunsize, exportlist[0].tohost.os, exportlist, lunnode)
                    lunlist.append( newlun )

                    # If the volume has snapmirrors, we will need to create a LUN on the
                    # snapmirrored volume that is exported to the drhosts for the original
                    # LUN's hosts.
                    smlun = self.add_mirrored_luns(newlun, vol)
                    if smlun is not None:
                        smluns.append( smlun )
                        pass
                    pass
                pass

            # If no LUNs are specified, invent one for the volume.
            else:
                log.debug("iSCSI volume specified, but no LUNs specified. A LUN will be created to use the whole volume.")
                lunnode = None

                lunsize = vol.usable / 2.0
                log.debug("calculated lun size of: %s", lunsize)
                lun_total += lunsize

                rwexports, roexports = self.get_exports(vol.volnode, self.get_vfiler_ips(vol.filer.vfilers.values()[0]))
                exports = rwexports + roexports

                log.debug("LUN will be exported to %s", exports)

                qtree_parent = vol.qtrees.values()[0]

                firsthost = exports[0].tohost
                if firsthost.iscsi_initiator is None:
                    raise ValueError("Host %s has no iSCSI initiator defined." % firsthost.name)

                lunid = current_lunid
                current_lunid += 1
                
                lunname = '%s.lun%02d' % (self.shortname, lunid)
                #lunname = '%s/%s_lun%02d.lun' % (qtree_parent.full_path(), self.shortname, lunid)

                # Add the new LUN to the lunlist
                # The LUN ostype defaults to the same type as the first one in its initiator list
                newlun = LUN( lunname, qtree_parent, lunid, lunsize, firsthost.os, exports, lunnode)
                lunlist.append( newlun )

                smlun = self.add_mirrored_luns(newlun, vol)
                if smlun is not None:
                    smluns.append( smlun )
                    pass
                pass
            pass
        
        log.debug("Loaded %d LUNs, %d mirrored LUNs", len(lunlist), len(smluns))
        return lunlist + smluns

    def add_mirrored_luns(self, srclun, srcvol):
        """
        Add a LUN to the snapmirror destination for a volume, if one exists.
        """
        for sm in srcvol.snapmirrors:
            qtree_parent = sm.targetvol.qtrees[srclun.qtree.name]

            # Figure out which hosts the LUN should be exported to
            exportlist = []
            for export in srclun.exportlist:
                for drhostname in export.tohost.drhosts:
                    drhost = self.hosts[drhostname]
                    if drhost not in [ host.tohost for host in exportlist ]:
                        exportlist.append(Export(drhost, export.fromip, export.type, export.toip))

            smlun = LUN( srclun.name, qtree_parent, srclun.lunid, srclun.size, srclun.ostype, exportlist )
            return smlun

    def load_igroups(self):
        """
        Load iGroup definitions based on previously loaded LUN definitions.
        If manually defined igroups exist, use those instead.
        """
        # For each LUN in the lunlist, create an iGroup for its exportlist.
        # If multiple LUNs are exported to the same exportlist, they are
        # exported to the same iGroup, so a new one is not created.
        igroups = []

        # Find manually defined igroups, if they exist
        igrouplist = self.tree.xpath('site/filer/vfiler/igroup')
        log.debug("Found %d igroups: %s", len(igrouplist), igrouplist)
        if len(igrouplist) > 0:
            log.debug("Manually defined igroups exist. Will not auto-generate any.")
            for ig in igrouplist:
                igroup_name = ig.attrib['name']
                filername = ig.xpath('ancestor::*/filer[1]')[0].attrib['name']
                filer = self.filers[filername]
                
                # Build the list of hosts this igroup maps to
                exportlist = [ Export(self.hosts[hostname], filer.vfilers.values()[0].ipaddress, 'rw') for hostname in ig.xpath('member/@name') ]
                log.debug("setting exportlist for igroup to: %s", exportlist)
                igroup = iGroup(igroup_name, filer, exportlist=exportlist)
                igroups.append(igroup)
                pass
        
            # Find all the LUNs that map to each iGroup
            lunlist = self.tree.xpath('descendant-or-self::*/lun')
            log.debug("Need to check %d luns: %s", len(lunlist), lunlist)
            for lun_node in lunlist:
                lun = [ lun for lun in self.luns if lun.lunnode == lun_node ][0]
                mapto_list = lun_node.findall('mapto')
                if len(mapto_list) == 0:
                    log.warn("<lun/> has no <mapto/> defined, and igroups are manually defined. <lun/> will be ignored.")
                    #raise ValueError("lun has no <mapto> defined, and igroups are manually defined.")
                    pass

                for mapto in mapto_list:
                    groupname = mapto.attrib['igroup']
                    log.debug("Found reference to igroup: %s", groupname)

                    # Get the igroup object
                    igroup = [ ig for ig in igroups if ig.name == groupname ][0]

                    # Set the igroup type to the same as the first LUN it has
                    if len(igroup.lunlist) == 0:
                        igroup.type = lun.ostype
                        pass
                    lun.igroup = igroup
                    igroup.lunlist.append(lun)
                    pass
                pass
            pass

        # Create igroups automatically for all the LUNs
        else:
            log.debug("No manually defined igroups exist. Auto-generating them...")
            log.debug("There are %d luns to process", len(self.luns) )

            # Split the LUNs into per-site lists
            for site in self.sites.values():
                siteluns = [ lun for lun in self.luns if lun.qtree.volume.filer.site == site ]
                log.debug("siteluns: %d luns in %s: %s", len(siteluns), site.type, siteluns)

                site_igroups = []
                for lun in siteluns:
                    log.debug("Building iGroups for LUN: %s", lun)
                    for ig in site_igroups:
                        log.debug("checking match of exportlist: %s with %s", ig.exportlist, lun.exportlist)
                        pass

                    # Check to see if the exports in both lists are equivalent
                    # This means that all of the exports in the igroup exportlist
                    # are to the same host/ip, with the same permissions as the
                    # lun's exportlist.
                    matchedgroups = []
                    for ig in site_igroups:
                        match = True
                        for a, b in zip(ig.exportlist, lun.exportlist):
                            if a != b:
                                match = False
                                pass
                            pass
                        if match is True:
                            matchedgroups.append(ig)
                        pass
                    
                    #matchedgroups = [ ig for ig in site_igroups if [ a == b for a,b in zip(ig.exportlist, lun.exportlist)] ]
                    if len(matchedgroups) == 0:
                        log.debug("exportlist %s has not had a group created for it yet", lun.exportlist)
                        igroup_number = len(site_igroups)
                        igroup_name = '%s_igroup%02d' % ( self.shortname, igroup_number )

                        # Add a list of one LUN to a brand new iGroup with this LUN's exportlist
                        # The iGroup type defaults the same as the first LUN type that it contains.
                        group = iGroup(igroup_name, lun.qtree.volume.filer, lun.exportlist, [lun,], type=lun.ostype)
                        lun.igroup = group
                        site_igroups.append(group)

                    else:
                        log.debug("Aha! An iGroup with this exportlist already exists!")
                        if len(matchedgroups) > 1:
                            log.warning("Multiple iGroups exist for the same exportlist! This is a bug!")
                            log.warning("groups are: %s", matchedgroups)
                        group = matchedgroups[0]
                        log.debug("Appending LUN to iGroup %s", group.name)
                        if group.type != lun.ostype:
                            log.error("LUN type of '%s' is incompatible with iGroup type '%s'", lun.ostype, igroup.type)
                        else:
                            lun.igroup = group
                            group.lunlist.append(lun)
                        pass
                    pass
                igroups.extend( site_igroups )
                pass
            pass

        return igroups

    def __get_qtree_mountoptions(self, qtree):
        """
        DEPRECATED
        Figure out the automatically defined mount options for a qtree
        """
        warn("use get_host_qtree_options instead", DeprecationWarning, stacklevel=1)
        mountoptions = []

        osname = qtree.rwexports[0].os
        
        if qtree.volume.type in ['oracm', ]:
            log.debug("Oracle quorum qtree detected.")
            if qtree.name == 'ora_cm':
                if osname.startswith('Solaris'):
                    log.debug("NOAC mount option added.")
                    mountoptions = [ 'forcedirectio', 'noac', 'nointr' ]
                    pass
                pass
            pass
        pass

        if qtree.volume.type in [ 'oradata', 'oraindx', 'oraundo', 'oraarch', 'oraredo' ]:

            if osname.lower().startswith('solaris'):
                #log.debug("Solaris mount option required")
                mountoptions = [ 'forcedirectio', 'noac', 'nointr' ]
                
            elif osname.lower().startswith('linux'):
                #log.debug("Linux mount option required")
                mountoptions = [ 'actimeo=0', ]
                pass

            else:
                log.error("Unsupported NFS operating system '%s'", osname)
                mountoptions = []
                pass
            pass

        # Non Oracle volume options for Solaris
        elif osname.lower().startswith('solaris'):
            mountoptions = [ 'intr', ]

        elif osname.loewr().startswith('linux'):
            mountoptions = [ 'intr', ]

        return mountoptions

    def setup_vlan_networks(self, nodelist):
        """
        Create a list of Network objects from a set of <network/> nodes.
        The nodes are child elements of a <vlan/> element.

        @return: a list of networks.
        """
        network_list = []
        
        log.debug("Found network nodes: %s", nodelist)
        for node in nodelist:

            try:
                number = node.attrib['number']
            except KeyError:
                raise KeyError("<network/> element has no 'number' attribute.")

            # Detect slash notation for network number/mask
            if number.find('/') > 0:
                try:
                    number, netmask, maskbits = self.str2net(number)
                except:
                    log.error("Error with network number for VLAN %s", number)
                    raise
            else:
                try:
                    netmask = node.attrib['netmask']
                except KeyError:
                    raise KeyError("network %s has no netmask defined." % number)
                pass

            try:
                gateway = node.attrib['gateway']
            except KeyError:
                raise KeyError("<network/> element has no 'gateway' attribute.")

            network_list.append( Network(number, netmask, maskbits, gateway) )
            pass

        return network_list

    def load_vlans(self):
        """
        Load all the vlan definitions
        """
        vlans = []
        vlan_nodes = self.tree.xpath("site/vlan")
        for node in vlan_nodes:

            site = node.xpath("ancestor::site/@type")[0]
            
            type = node.xpath("@type")[0]

            number = node.xpath("@number")[0]

            network_list = []

            # Detect the old form of network definition, and accept it
            # for now, converting it to the new form.
            try:

                log.warning("Old style network definition detected. Upgrade to new DTD schema should be performed.")

                # Build a network from the old style definitions
                network = node.xpath("@network")[0]
                netmask = None
                
                # check to see if the network is defined with slash notation for a netmask
                if network.find('/') > 0:
                    try:
                        network, netmask, maskbits = self.str2net(network)
                    except:
                        log.error("Error with network number for VLAN %s", number)
                        raise

                    log.debug("Slash notation found. Network is: %s, netmask is: %s", network, netmask)
                    pass
                
                # If a slashmask isn't used, try to find the netmask definition
                if netmask is None:
                    log.debug("netmask is None. Network is: %s", network)
                    try:
                        netmask = node.xpath("@netmask")[0]

                        # Also, convert netmask to the number of bits in a slash notation
                        maskbits = self.mask2bits(netmask)
                    
                    except IndexError:
                        log.error("VLANs must have a netmask defined.")
                        raise
                    pass

                gateway = node.xpath("@gateway")[0]

                # Add the network definition to the list of networks
                netobj = Network( network, netmask, maskbits, gateway )

                network_list.append( netobj )
                
            except IndexError:
                pass

            # Load new style network definitions
            network_nodes = node.findall('network')
            network_list.extend( self.setup_vlan_networks( network_nodes ) )
                
            description = node.text
            if description is None:
                description = ''

            try:
                mtu = int(node.attrib['mtu'])
            except KeyError:
                mtu = 9000
            
            vlan = Vlan(number, site, type, network_list, description, mtu, node)
            vlans.append(vlan)
            pass

        return vlans

    def verify_config(self):
        """
        Make sure that the document satisfies certain rules.
        """
        if self.tree.find('nas'):
            raise ValueError("Old <nas/> node format is now invalid. Please update project definition.")
    
        # Make sure any oracm volumes are larger than 100m in size.
        for vol in [ vol for vol in self.volumes if vol.type == 'oracm' ]:
            if vol.usable < 0.1:
                raise ValueError("oracm volume must be larger than 100m usable; try <usablestorage>0.4</usablestorage>")

    def get_filers(self, sitetype, type):

         return [ filer for filer in self.filers.values() if filer.site.type == sitetype and filer.type == type ]

    def get_vfiler_ips(self, vfiler):
        """
        Return a list of all the vfiler IP addresses that are configured.
        This is the primary IP, plus any aliases
        """
        ips = [ vfiler.ipaddress, ]
        for (ipaddr, netmask) in vfiler.alias_ips:
            ips.append( ipaddr )
            pass
        return ips

    def get_volumes(self, site='primary', filertype='primary'):
        """
        Build a list of all the primary volumes for the project.
        """
        volumes = [ vol for vol in self.volumes if vol.filer.site.type == site and vol.filer.type == filertype ]
        log.debug("Found %d volumes for site:%s/filer:%s", len(volumes), site, filertype)
        return volumes

    def create_volume(self, node, volnum):
        """
        Create a volume, using certain defaults as required.
        """
        # Find out which filer the volume is on
        filername = node.xpath("ancestor::filer/@name")[0]

        # Find out which vfiler the volume is on
        #vfilername = node.xpath("ancestor::vfiler/@name")[0]

        # Work out the volume name
        try:
            # If the volume has an explicit name set, use that
            volname = node.xpath("@name")[0]
        except IndexError:

            # otherwise, invent one

            # Try to find a volume prefix
            try:
                volprefix = node.xpath("@prefix")[0]
            except IndexError:
                volprefix = self.shortname
                pass

            # Try to find a volume suffix
            try:
                volsuffix = node.xpath("@suffix")[0]
            except IndexError:
                volsuffix = ''
                pass

            # Check to see if we want to restart the volume numbering
            try:
                volnum = int(node.xpath("@restartnumbering")[0])
            except IndexError:
                pass

            volname = '%s_vol%02d%s' % (volprefix, volnum, volsuffix)

        # aggregate is this one, or the same as the previous volume
        aggr = node.xpath("ancestor::aggregate/@name | preceding-sibling/ancestor::aggregate/@name")[0]

        snapref = node.xpath("snapsetref/@name")
        snapvaultref = node.xpath("snapvaultsetref/@name")
        snapmirrorref = node.xpath("snapmirrorsetref/@name")
        snapvaultmirrorref = node.xpath("snapvaultmirrorsetref/@name")

        voloptions = [ x.text for x in node.xpath("option") ]

        # The volume protocol is either a protocol set in the volume definition
        # using the 'proto' attribute, or it will be the first protocol in
        # the list of possible protocols for the vfiler.
        # If neither of these are set, it will default to nfs.
        try:
            proto = node.xpath("@proto")[0].lower()
            log.debug("Proto defined for volume: %s", proto)

        except IndexError:
            try:
                proto = node.xpath("ancestor::*/vfiler/protocol/text()")[0].lower()
                #log.debug("Found proto in vfiler ancestor: %s", proto)
            except IndexError:
                proto = 'nfs'
                #log.debug("Proto set to default: %s", proto)

        try:
            voltype = node.xpath("@type")[0]
        except IndexError:
            voltype = 'fs'

        # Set the amount of usable space in the volume
        try:
            usable = float(node.xpath("usablestorage")[0].text)

        except IndexError:
            log.warn("No usable size specified for volume number '%02d'. Assuming minimum of 100 GiB usable.", volnum)
            usable = 100
            pass

        # Default snap reserve to 20 unless specified otherwise
        # Default iscsi_snapspace to 0 unless specified otherwise
        iscsi_snapspace=0
        try:
            snapreserve = float(node.xpath("@snapreserve")[0])
        except IndexError:
            #log.debug("No snapreserve specified.")
            if proto == 'iscsi':
                snapreserve = 0
                # iSCSI volumes need the ability to define space used for storing
                # snapshots, but without turning on snapreserve, which functions
                # differently. This is usable space allocated as overhead for
                # snapshots, because snapreserve is set to 0, but won't be used
                # by the LUNs, because they are files of fixed size created inside
                # the usable space.
                # This percentage value will be added to the raw space provided for
                # the volume.
                try:
                    iscsi_snapspace = node.xpath("@iscsi_snapspace")[0]
                except IndexError:
                    iscsi_snapspace = 30

            elif voltype in ['oraundo', 'oraarch', ]:
                snapreserve = 50
            else:
                snapreserve = 20
                pass
            pass

        # See if we want to specify a particular amount of snapshot storage
        # This will override the snapreserve setting
        try:
            snapstorage = float(node.findall("snapstorage")[0].text)
            #log.info("snapstorage of %.2f GiB set", snapstorage)
            raw = usable + snapstorage
            #log.info("raw storage is now: %.2f", raw)

            # snapreserve is always an integer percentage, so round it            
            snapreserve = int(round(100 - ((usable / raw) * 100.0)))
            #log.info("snapreserve is: %s", snapreserve)

        except IndexError:
            snapstorage = None

        if snapstorage is not None:
            vol = Volume( volname, self.filers[filername], aggr, usable, snapreserve, raw, type=voltype, proto=proto, voloptions=voloptions, volnode=node, snapref=snapref, snapvaultref=snapvaultref, snapmirrorref=snapmirrorref, snapvaultmirrorref=snapvaultmirrorref, iscsi_snapspace=iscsi_snapspace)
        else:
            vol = Volume( volname, self.filers[filername], aggr, usable, snapreserve, type=voltype, proto=proto, voloptions=voloptions, volnode=node, snapref=snapref, snapvaultref=snapvaultref, snapmirrorref=snapmirrorref, snapvaultmirrorref=snapvaultmirrorref, iscsi_snapspace=iscsi_snapspace)

        # See if there is an autosize setting on either the volume, or the
        # containing aggregate. Use the first one we find.
        autosize = node.xpath('autosize | parent::*/autosize')
        if len(autosize) > 0:
            autosize = autosize[0]
            #log.debug("found autosize: %s", autosize)
            # Set autosize parameters
            vol.autosize = VolumeAutoSize(vol, autosize.attrib['max'], autosize.attrib['increment'])
            pass

        # See if there is an autodelete setting for snapshots
        autodelete = node.xpath('autodelete | parent::*/autodelete')
        if len(autodelete) > 0:
            autodelete = autodelete[0]
            #log.debug("found autodelete: %s", autodelete)
            # Set autodelete parameters
            vol.autodelete = VolumeAutoDelete(vol)
            vol.autodelete.configure_from_node(autodelete)
            pass

        volnum += 1
        return vol, volnum
    
    def create_volumeset(self, node, volnum):
        """
        Given a volumeset node, create a list of volumes from it.
        """
        vols = []

        # Check to see if we want to restart the volume numbering
        try:
            volnum = int(node.xpath("@restartnumbering")[0])
        except IndexError:
            pass

        filername = node.xpath("ancestor::filer/@name")[0]
        vol_filer = self.filers[filername]
        # aggregate is this one, or the same as the previous volume
        aggr = node.xpath("ancestor::aggregate/@name | preceding-sibling/ancestor::aggregate/@name")[0]

        snapref = node.xpath("snapsetref[not(@archivelogs)]/@name")
        snapvaultref = node.xpath("snapvaultsetref[not(@archivelogs)]/@name")
        snapmirrorref = node.xpath("snapmirrorsetref[not(@archivelogs)]/@name")
        snapvaultmirrorref = node.xpath("snapvaultmirrorsetref[not(@archivelogs)]/@name")

        if node.attrib.has_key('oracle'):

            #
            # Automated Oracle volume allocation is based on the following rules:
            # - The amount of usable storage for the volumeset is the total
            #   amount of usable storage for all the volumes. If 100g usable
            #   is specified, this equates to 20g data, 20g index, 10g archive, etc.
            #   depending on the percentage per volume in effect at the time.
            # - Each volume in the volumeset is sized as a percentage of the total
            #   usable storage. The data volume is 30% of total, for example, and
            #   the archive is 15% of total.
            # - The snap reserve for each volume may be different, since the
            #   archive data is likely to change a great deal, whereas the data isn't
            #   as likely to change.

            #
            # Because of the way backups work with Oracle, we often want to
            # backup the archivelogs after we backup the main data. This code
            # detects a special kind of snap/vault/mirror reference for the
            # archivelogs, if we want one. If we don't, the archivelogs volume
            # will just use the same ones as the other volumes.
            #
            #arch_snapref = node.xpath("snapsetref[@archivelogs]/@name")

            arch_snapvaultref = node.xpath("snapvaultsetref[@archivelogs]/@name")
            if len(arch_snapvaultref) == 0:
                arch_snapvaultref = snapvaultref
                # Warn the user if they aren't specifying an archivelog specific schedule.
                if len(snapvaultref) > 0:
                    log.warn("No archivelog specific snapvault defined for database '%s'.", node.attrib['oracle'])
            
            #arch_snapmirrorref = node.xpath("snapmirrorsetref[@archivelogs]/@name")

            sid = node.attrib['oracle']

            #
            # Find how much usable storage we want for the database.
            # We can do this in a couple of ways:
            # 1. We can use the total usable storage method, in which we define
            #    how much storage in total we wish to use, and it gets split up
            #    using a standard percentage for each volume, or
            # 2. We use the datastorage method, which takes the amount of storage
            #    required for the data volume, and figures out how much is
            #    needed for the index, archive, etc. based on standard percentages.

            try:
                datastorage = float(node.xpath("datastorage")[0].text)
                usable = datastorage * (1/0.4)
                #log.info("Total usable database storage: %s", usable)

            except IndexError:
                try:
                    usable = float(node.xpath("usablestorage")[0].text)
                except IndexError:
                    raise ValueError("Usable storage not specified for volumeset!")

            # config and quorum volume
            # This is shared between all databases for the project, and is a constant size
##             volname = '%s_vol%02d' % ( self.shortname, volnum )
##             vol = Volume( volname, vol_filer, aggr, 100, 20, type='oraconfig', volnode=node, snapref=snapref, snapvaultref=snapvaultref, snapmirrorref=snapmirrorref)
##             vols.append(vol)
##             volnum += 1

            # data volume, 40% of total
            volname = '%s_vol%02d' % ( self.shortname, volnum )
            vol = Volume( volname, vol_filer, aggr, usable * 0.4, 20, type='oradata', volnode=node, snapref=snapref, snapvaultref=snapvaultref, snapmirrorref=snapmirrorref, snapvaultmirrorref=snapvaultmirrorref)
            vols.append(vol)
            volnum += 1

            # index volume, 20% of total
            volname = '%s_vol%02d' % ( self.shortname, volnum )
            vol = Volume( volname, vol_filer, aggr, usable * 0.2, 20, type='oraindx', volnode=node, snapref=snapref, snapvaultref=snapvaultref, snapmirrorref=snapmirrorref, snapvaultmirrorref=snapvaultmirrorref)
            vols.append(vol)
            volnum += 1

            # redo volume, constant size, no snapreserve
            volname = '%s_vol%02d' % ( self.shortname, volnum )
            vol = Volume( volname, vol_filer, aggr, usable * 0.05, 0, type='oraredo', volnode=node, snapref=snapref, snapvaultref=snapvaultref, snapmirrorref=snapmirrorref, snapvaultmirrorref=snapvaultmirrorref)
            vols.append(vol)
            volnum += 1

            # temp volume, 5% of total, no snapreserve
            volname = '%s_vol%02d' % ( self.shortname, volnum )
            vol = Volume( volname, vol_filer, aggr, usable * 0.20, 0, type='oraundo', volnode=node, snapref=snapref, snapvaultref=snapvaultref, snapmirrorref=snapmirrorref, snapvaultmirrorref=snapvaultmirrorref)
            vols.append(vol)
            volnum += 1

            # archive volume, 35% of total
            volname = '%s_vol%02d' % ( self.shortname, volnum )
            vol = Volume( volname, vol_filer, aggr, usable * 0.35, 50, type='oraarch', volnode=node, snapref=snapref, snapvaultref=arch_snapvaultref, snapmirrorref=snapmirrorref, snapvaultmirrorref=snapvaultmirrorref)
            vols.append(vol)
            volnum += 1

        return vols, volnum

    def get_volume_totals(self, vol_list):
        usable_total = sum( [ vol.usable for vol in vol_list ])
        raw_total = sum( [ vol.raw for vol in vol_list ])
        return usable_total, raw_total

    def get_nearstore_volumes(self, ns, sitetype='primary'):
        """
        Fetch all the nearstore volumes at site 'site'
        """
        volumes = [ vol for vol in self.volumes if vol.filer.site.type == sitetype and vol.filer.type == 'nearstore' ]
        log.debug("nearstore volumes: %s", volumes)

        return volumes
    
    def get_dr_volumes(self, ns, source='primary'):
        """
        Automatically determine the DR site volume setup.
        This handles both DR of primary volumes, and also of NearStore volumes,
        as both are copied to the remote site via SnapMirror.
        FIXME: If there are any special differences in offsiting of
        volumes for DR or offsite backup, they will need to be catered for here.
        """
        volumes = [ vol for vol in self.volumes if vol.filer.site.type == 'secondary' and vol.filer.type == 'primary' ]
        log.debug("dr volumes: %s", volumes)
        return volumes

    def get_site_qtrees(self, ns, sitetype='primary'):
        """
        Fetch the list of qtrees for a given site. These will be linked
        to the specific volume they are on.
        """
        qtrees = [ x for x in self.qtrees if x.volume.filer.site.type == sitetype ]
        return qtrees

    def get_filer_iscsi_igroups(self, filer):
        """
        Fetch the iSCSI iGroups for a filer
        """
        igroups = [ igroup for igroup in self.igroups if igroup.filer == filer ]
        
        return igroups

    def get_filer_luns(self, filer):
        """
        Fetch all the LUNs on a certain filer
        """
        log.debug("getting luns on %s", filer)
        luns = [ lun for lun in self.luns if lun.qtree.volume.filer == filer ]
        log.debug("luns are: %s", luns)
        return luns

    def get_export_nodes(self, node):
        """
        Find export nodes that are children of the current node.
        This recurses upwards to the parent node if it can't find any exports.
        """
        exports = node.xpath("export")
        if len(exports) == 0:
            log.info("No export definitions for this node %s. Using parent exports.", node)
            try:
                parent_node = node.xpath("parent::*")[0]
            except IndexError:
                return []
            return self.get_export_nodes(parent_node)
        else:
            log.debug("found exports: %s", [x.xpath("@to")[0] for x in exports ])
            return exports

    def get_exports(self, node, default_iplist, default_to_all=True):
        """
        Find the list of exports for read/write and readonly mode based
        on the particular qtree, volume or lun node supplied.

        If default_to_all is set to True, this will set the rwexports
        to all known hosts if both rwexports and roexports would
        otherwise be empty.
        """
        roexports = []
        rwexports = []
        
        export_nodes = node.xpath("ancestor-or-self::*/export")
        for exnode in export_nodes:

            # See if we're exporting from a specific IP address
            # Override the default passed in if we are.
            try:
                fromip_list = [ exnode.attrib['fromip'], ]
            except KeyError:
                # Use the default passed in
                fromip_list = default_iplist
                pass

            # get the hostname
            hostname = exnode.attrib['to']
            try:
                host = self.hosts[hostname]
            except KeyError:
                raise KeyError("Hostname '%s' in <export/> is not defined." % hostname)

            # If we're exporting to a specific host IP address, get it
            try:
                toip = exnode.attrib['toip']
            except KeyError:
                toip = None
                pass

            log.debug("export to %s found", hostname)
            for fromip in fromip_list:
                try:
                    if exnode.attrib['ro'] == 'yes':
                        roexports.append( Export(host, fromip, 'ro', toip) )
                    else:
                        rwexports.append( Export(host, fromip, 'rw', toip) )
                    # If the 'ro' attrib isn't set, we export read/write
                except KeyError, e:
                    rwexports.append( Export(host, fromip, 'rw', toip) )
                    pass
                pass
            
        log.debug("roexports for %s: %s", node, roexports)
        log.debug("rwexports for %s: %s", node, rwexports)

        # If both lists are empty, default to exporting read/write to all hosts
        if default_to_all:
            if len(rwexports) == 0 and len(roexports) == 0:
                rwexports = []
                for fromip in default_iplist:
                    for host in self.hosts.values():
                        rwexports.append( Export(host, fromip, 'rw') )
                        pass
                    pass
                pass
            pass
        
        log.debug("roexports for %s: %s", node, roexports)
        log.debug("rwexports for %s: %s", node, rwexports)

        return rwexports, roexports

    def get_extra_mountoptions(self, node, host):
        """
        Find any mountoptions defined at a node for a specific host
        """
        nodes = node.xpath("ancestor-or-self::*/export[@to = '%s']/mountoption" % host.name)
        if len(nodes) > 0:
            log.debug("Found %d manually defined mountoptions: %s", len(nodes), nodes)
            pass
        
        mountoptions = [ x.text for x in nodes ]
#        log.debug("returning mountoptions: %s", mountoptions)
        return mountoptions

    def get_cifs_qtrees(self, filer):
        """
        Find the CIFS exports for the project.
        """
        return [ x for x in self.qtrees if x.volume.proto == 'cifs' and x.volume.filer == filer ]

    def create_snapshot_for(self, srcvol):
        """
        Create snapshot definitions for volumes, if they have a snapref.
        root volumes have a default snapshot schedule added if they have
        no snapref.
        """
        if len(srcvol.snapref) > 0:
            log.warn("Snapref addition not supported yet.")
            raise NotImplementedError("Snaprefs not yet supported.")

        # Add default snapshot schedule for root volumes 
        elif srcvol.name.endswith('root'):
            # NearStores get a default schedule to back up their configuration multiple times
            if srcvol.filer.type == 'nearstore':
                self.snapshots.append( Snapshot( srcvol, 4, 14, '6@8,12,16,20') )

            # Other root volumes don't
            else:
                self.snapshots.append( Snapshot( srcvol, 0, 0, '0') )


    def create_snapvault_for(self, srcvol):
        """
        Create snapvault volumes for a source volume.
        """
        #log.debug("Adding snapvaults for %s", srcvol)
        # get the snapvaultset for the volume

        # If the volume is of certain types, don't back them up
        if srcvol.type in ['oraredo', 'oracm' ]:
            log.info("Not backing up volume '%s' of type '%s'", srcvol.name, srcvol.type)
            return

        # Create target volumes based on the snapvault definition
        for ref in srcvol.snapvaultref:
            try:
                set_node = self.tree.xpath("snapvaultset[@id = '%s']" % ref)[0]
            except IndexError:
                log.error("Cannot find snapvaultset definition '%s'" % ref)
                raise ValueError("snapvaultset not defined: '%s'" % ref)

            # If a target volume has been pre-defined, we'll use that.
            # Otherwise, we'll invent one based on certain rules and settings.
            if set_node.attrib.has_key('targetvolume'):
                log.debug("Using specific volume for snapvault.")
                try:
                    filername = set_node.attrib['targetfiler']
                except KeyError:
                    raise KeyError("You must specify the target filer as well as target volume for snapvaultset '%s'" % id)
                volname = set_node.attrib['targetvolume']

                # There should only ever be one of these
                try:
                    targetvol = [ vol for vol in self.volumes if vol.filer.name == filername and vol.name == volname ][0]
                except IndexError:
                    raise ValueError("Cannot find volume '%s:%s' for snapvaultset" % (filername, volname))
                log.debug("Found specific volume: %s", targetvol)

                # Set the type of the volume to be a snapvault destination
                targetvol.type='snapvaultdst'

            else:

                # Set the target filer for the snapvault
                try:
                    target_filername = set_node.attrib['targetfiler']
                except KeyError:
                    # No target filer specified, so use the first nearstore at the same site as the primary
                    target_filername = self.tree.xpath("site[@type = '%s']/filer[@type = 'nearstore']/@name" % srcvol.filer.site.type)[0]
                    pass

                try:
                    target_filer = self.filers[target_filername]
                except KeyError:
                    log.error("Snapvault target is an unknown filer name: '%s'", target_filername)
                    raise

                # Find the target aggregate for the snapvault
                try:
                    targetaggr = set_node.attrib['targetaggregate']
                except:
                    try:
                        targetaggr = self.tree.xpath("site/filer[@name = '%s']/aggregate/@name" % target_filername)[0]
                    except:
                        # No aggregates are specified on the target filer, so use the same one as the source volume
                        targetaggr = srcvol.aggregate
                        pass
                    pass

                # Set a storage multiplier for the SnapVault destination volume.
                # This number is used to size the destination volume as a multiple
                # of the primary usable space.
                # This defaults to 2.5 based on historical averages.
                try:
                    multiplier = float(set_node.attrib['multiplier'])
                except KeyError:
                    multiplier = 2.5

                # Set a specific amount to be created for SnapVault destination
                # volume. This value (in gigabytes) will be used for all volumes
                # created as a result of applying the snapvault/snapvaultmirror
                # to volumes, so it will often only be useful for applying to a
                # single volume. This gives very fine grained control over storage
                # allocation for backups.
                try:
                    targetusable = float(set_node.attrib['targetusable'])
                except KeyError:
                    targetusable = None

                # SnapVault destination volumes are identified by having
                # a suffix appended to the volume name
                try:
                    target_suffix = set_node.attrib['target_suffix']
                except KeyError:
                    target_suffix = 'b'

                # Figure out how much usable storage to allocate to the target volume
                if targetusable is None:
                    # iSCSI is special, again. Grr.
                    if srcvol.proto == 'iscsi':
                        targetusable = srcvol.iscsi_usable * multiplier
                    else:
                        targetusable = srcvol.usable * multiplier
                    pass
                
                # target volume name is the src volume name with a 'b' suffix
                targetvol = Volume( '%s%s' % (srcvol.name, target_suffix),
                                    self.filers[target_filername],
                                    targetaggr,
                                    targetusable,
                                    snapreserve=0,
                                    type='snapvaultdst',
                                    proto=None,
                                    snapmirrorref=srcvol.snapvaultmirrorref,
                                    )
                pass
            # end determination of target volume

            # If the target volume or aggregate are actually defined in
            # the XML, and use those settings for autosize and autodelete.
            targetvol = self.set_volume_autosize(targetvol, targetvol.filer.name, targetvol.aggregate)
            targetvol = self.set_volume_autodelete(targetvol, targetvol.filer.name, targetvol.aggregate)
            
            self.volumes.append(targetvol)
            #log.debug("target volume filer type: %s", targetvol.filer.type)

            # Add the snapvaults themselves
            for svnode in set_node.findall("snapvault"):
                basename = svnode.attrib['basename']
                try:
                    snapsched = svnode.find('snapschedule').text
                except AttributeError:
                    snapsched = None
                    pass
                
                try:
                    svsched = svnode.find('snapvaultschedule').text
                except AttributeError:
                    svsched = None
                    
                sv = SnapVault(srcvol, targetvol, basename, snapsched, svsched)
                self.snapvaults.append(sv)
                #log.debug("Added snapvault: %s", sv)

            # Add snapmirrors of the snapvaults if the source volume has snapvaultmirrorrefs set
            self.create_snapmirror_for(targetvol)

    def set_volume_autosize(self, vol, filername, aggrname):
        """
        Find autosize settings on a given filername and aggregate name
        and use it for the autosize setting for the given volume.
        """
        autosize = self.tree.xpath("child::*/filer[@name='%s']/vfiler/aggregate[@name='%s']/autosize" % (filername, aggrname))
        if len(autosize) > 0:
            autosize = autosize[0]
            #log.info("found sv autosize: %s", autosize)
            # Set autosize parameters
            vol.autosize = VolumeAutoSize(vol, autosize.attrib['max'], autosize.attrib['increment'])
            pass
        return vol
    
    def set_volume_autodelete(self, vol, filername, aggrname):
        """
        Find autodelete nodes on a given filername and aggregate name
        and use it for the autodelete setting for a given volume.
        """
        autodelete = self.tree.xpath("child::*/filer[@name='%s']/vfiler/aggregate[@name='%s']/autodelete" % (filername, aggrname))
        #log.debug("sv autodelete: %s", autodelete)
        if len(autodelete) > 0:
            autodelete = autodelete[0]
            #log.debug("found sv autodelete: %s", autodelete)
            # Set autodelete parameters
            vol.autodelete = VolumeAutoDelete(vol)
            vol.autodelete.configure_from_node(autodelete)
            pass
        return vol
            
    def create_snapmirror_for(self, srcvol):
        """
        Create snapmirror volumes for a source volume.
        """
        log.debug("Creating snapmirror for srcvol: %s", srcvol)
        # If the volume is of certain types, don't back them up
##         if srcvol.type in [ 'oracm' ]:
##             log.info("Not snapmirroring volume '%s' of type '%s'", srcvol.name, srcvol.type)
##             return

        # get the snapmirrorset for the volume
        for ref in srcvol.snapmirrorref:
            try:
                set_node = self.tree.xpath("snapmirrorset[@id = '%s']" % ref)[0]
            except IndexError:
                log.error("Cannot find snapmirrorset definition '%s'" % ref)
                raise ValueError("snapmirrorset not defined: '%s'" % ref)

            try:
                target_filername = set_node.attrib['targetfiler']
                
            except KeyError:
                # No target filer specified, so use the first primary at a site other than the source
                # This auto-created DR snapmirrors, but may not be what you mean.
                target_filername = self.tree.xpath("site[not(@type = '%s')]/filer[@type = 'primary']/@name" % srcvol.filer.site.type)[0]
                log.warn("No destination for snapmirror provided, using '%s'" % target_filername)
                pass

            try:
                target_filer = self.filers[target_filername]
                
            except KeyError:
                log.error("Snapmirror target is an unknown filer name: '%s'", target_filername)
                raise
                
            try:
                targetaggr = set_node.attrib['targetaggregate']
            except:
                try:
                    targetaggr = self.tree.xpath("site/filer[@name = '%s']/aggregate/@name" % target_filername)[0]
                except:
                    # No aggregates are specified on the target filer, so use the same one as the source volume
                    targetaggr = srcvol.aggregate
                    pass
                pass

            try:
                target_suffix = set_node.attrib['target_suffix']
            except KeyError:
                target_suffix = 'r'

            # target volume name is the src volume name with a 'r' suffix
            targetvol = Volume( '%s%s' % (srcvol.name, target_suffix), 
                                self.filers[target_filername],
                                targetaggr,
                                srcvol.usable,
                                snapreserve=srcvol.snapreserve,
                                raw=srcvol.raw,
                                type='snapmirrordst',
                                proto=srcvol.proto,
                                voloptions=srcvol.voloptions,
                                )
            self.volumes.append(targetvol)
            log.debug("Created snapmirror targetvol: %s", targetvol)
            
            snapmirror_schedule = {}
            for svnode in set_node.findall("snapmirror"):

                # Find the parameters for snapmirror schedules, defaulting to '*'
                # if a parameter is not set.
                for nodename in ['minute', 'hour', 'dayofmonth', 'dayofweek']:
                    node = svnode.find(nodename)
                    try:
                        snapmirror_schedule[nodename] = node.text
                    except AttributeError, e:
                        snapmirror_schedule[nodename] = '*'
                    
                sm = SnapMirror(srcvol, targetvol,
                                snapmirror_schedule['minute'],
                                snapmirror_schedule['hour'],
                                snapmirror_schedule['dayofmonth'],
                                snapmirror_schedule['dayofweek'],
                                )
                
                self.snapmirrors.append(sm)

    def get_snapvaults(self, ns):
        """
        Fetch the snapvault definitions for the configuration.
        """
        return self.snapvaults

    def get_snapmirrors(self, ns):
        """
        Fetch the snapmirror definitions for the configuration.
        """
        return self.snapmirrors

    def get_oplocks_value(self, node):
        """
        Take a node, and determine if qtree oplocks should be enabled.
        Returns a Boolean.
        """
        # qtree oplocks may need to be disabled sometimes
        try:
            qtree_oplocks = node.xpath("ancestor-or-self::*/@oplocks")[0].lower()
            log.debug("qtree oplocks: %s", qtree_oplocks)
            if qtree_oplocks in [ 'no', 'false' ]:
                oplocks = False
                log.debug("oplocks is manually set to false")
            else:
                oplocks = True
                log.debug("oplocks is manually set to true")
                pass
            pass
        except IndexError:
            oplocks = True
            log.debug("oplocks is automatically set to true")
            pass

        return oplocks

    #
    # A bunch of handy function to provide the commands that can be used to implement
    # the various aspects of the configuration
    #
    def filer_vol_create_commands(self, filer):
        """
        Build the filer vol create and options commands for a filer at a certain site and type.
        """
        cmdset = []

        for vol in filer.volumes:
            
            # volume creation
            cmd = "vol create %s -s %s %s %s" % (vol.name, vol.space_guarantee(), vol.aggregate, vol.get_create_size())
            cmdset.append(cmd)

            # volume options
            for opt in vol.voloptions:
                opt = opt.replace('=', ' ')
                cmd = "vol options %s %s" % (vol.name, opt)
                cmdset.append(cmd)
                pass

            # volume autosize settings
            if vol.autosize:
                cmdset.extend(vol.autosize.command_add())
            pass
                
        return cmdset

    def filer_vol_size_commands(self, filer):
        """
        The volume size commands. Useful for doing volume resizing.
        """
        cmdset = []

        for vol in filer.volumes:

            # If a volume is a snapmirror destination, you need to
            # do a snapmirror update before resizing it.
            if vol.type in ['snapmirrordst',]:
                cmdset.append("snapmirror update %s" % vol.name)
                
            # Volume size
            cmd = "vol size %s %s" % (vol.name, vol.get_create_size())
            cmdset.append(cmd)

        return cmdset

    def filer_qtree_create_commands(self, filer):
        """
        Build the qtree creation commands for qtrees on volumes on filers at site and type.
        """
        cmdset = []
        for vol in [ vol for vol in filer.volumes if vol.type not in ['snapvaultdst', 'snapmirrordst'] ]:
            for qtree in vol.qtrees.values():
                cmdset.append( "qtree create /vol/%s/%s" % (qtree.volume.name, qtree.name) )
                cmdset.append( "qtree security /vol/%s/%s %s" % (qtree.volume.name, qtree.name, qtree.security) )
                if qtree.oplocks == False:
                    cmdset.append( "qtree oplocks /vol/%s/%s disable" % (qtree.volume.name, qtree.name) )
                pass
            pass
        return cmdset

    def vlan_create_commands(self, filer, vfiler):
        """
        Find the project VLAN for the filer's site,
        and return the command for how to create it.
        """
        cmdset = []
        vlan = self.get_project_vlan(filer.site.type)
        cmdset.append("vlan add svif0 %s" % vlan.number)

        for vlan,ipaddr in vfiler.services_ips:
            cmdset.append("vlan add svif0 %s" % vlan.number)

        return cmdset

    def ipspace_create_commands(self, filer, ns):
        """
        Determine how to create the ipspace for the filer.
        """
        cmdset = []
        vlan = self.get_project_vlan(filer.site.type)
        cmdset.append("ipspace create ips-%s" % self.shortname)
        cmdset.append("ipspace assign ips-%s svif0-%s" % (self.shortname, vlan.number) )

        for vlan in self.get_services_vlans(filer.site.type):
            cmdset.append("ipspace assign ips-%s svif0-%s" % (self.shortname, vlan.number) )
            pass
        
        return cmdset

    def vfiler_create_commands(self, filer, vfiler, ns):
        cmdset = []
        cmdset.append("vfiler create %s -n -s ips-%s -i %s /vol/%s_root" % (vfiler.name,
                                                                            vfiler.name,
                                                                            vfiler.ipaddress,
                                                                            vfiler.name,
                                                                            ) )
        for vlan,ipaddr in vfiler.services_ips:
            cmdset.append("vfiler add %s -i %s" % (vfiler.name, ipaddr,) )
        #log.debug( '\n'.join(cmdset) )
        return cmdset

    def vfiler_add_volume_commands(self, filer, ns):
        cmdset = []
        for vol in filer.volumes:

            # Skip the root volume, because it's already part of the vfiler
            if vol.name.endswith("root"):
                continue
            
            cmdset.append("vfiler add %s /vol/%s" % (self.shortname, vol.name))
            pass
        
        #log.debug( '\n'.join(cmdset) )
        return cmdset

    def vfiler_add_storage_interface_commands(self, filer, vfiler):
        cmdset = []

        mtu = vfiler.vlan.mtu

        if filer.type == 'secondary':
            cmd = "ifconfig svif0-%s mtusize %s" % ( vfiler.vlan.number, mtu )
            #cmd = "ifconfig svif0-%s 0.0.0.0 netmask %s mtusize 9000 up" % ( vfiler.vlan.number, vfiler.netmask)

        else:
            cmd = "ifconfig svif0-%s %s netmask %s mtusize %s up" % (vfiler.vlan.number,
                                                                     vfiler.ipaddress,
                                                                     vfiler.netmask,
                                                                     mtu)

        # Add partner clause if this is a primary or secondary filer
        if filer.type in [ 'primary', 'secondary' ]:
            cmd += " partner svif0-%s" % self.get_project_vlan(filer.site.type).number
        cmdset.append(cmd)

        #
        # Aliases, if applicable
        #
        for (ipaddr, netmask) in vfiler.alias_ips:
            cmdset.append("ifconfig svif0-%s alias %s netmask %s mtusize %s up" % (vfiler.vlan.number, ipaddr, netmask, mtu))

        #
        # Services VLAN interfaces
        #
        for vlan,ipaddr in vfiler.services_ips:
            if filer.type == 'secondary':
                cmd = "ifconfig svif0-%s mtusize 1500" % ( vlan.number )
                pass
            else:
                cmd = "ifconfig svif0-%s %s netmask %s mtusize 1500 up" % (vlan.number,
                                                                           ipaddr,
                                                                           vlan.networks[0].netmask)
                pass

            # Add partner clause if this is a primary or secondary filer
            if filer.type in [ 'primary', 'secondary' ]:
                cmd += " partner svif0-%s" % vlan.number
                cmdset.append(cmd)
                pass
            
        #log.debug( '\n'.join(cmdset) )
        return cmdset

    def _vfiler_add_inter_project_routing(self, vfiler):
        """
        Provide the routing commands required to route to services VLANs
        FIXME: Look at the services VLANs in the configuration. Add to vfiler?
        """
        cmdset = []        

        # Add inter-project route if required?
        cmdset.append("vfiler run %s route add default %s 1" % (vfiler.vlan.number,
                                                                vfiler.gateway) )

        return cmdset

    def get_project_vlan(self, sitetype='primary'):
        """
        Find the project vlan for the site
        """
        for vlan in self.vlans:
            if vlan.site == sitetype and vlan.type == 'project':
                return vlan

    def get_services_vlans(self, site='primary'):
        """
        Return a list of all vlans of type 'services'
        """
        return [ vlan for vlan in self.vlans if vlan.type == 'services' and vlan.site == site ]

    def default_route_command(self, filer, vfiler):
        """
        The default route points to the VRF address for the primary VLAN.
        It may not exist yet, but having this here means no additional
        routing needs to be configured if the VRF is configured at some point.
        """
        cmdset = []
        title = "Default Route"
        proj_vlan = self.get_project_vlan(filer.site.type)
        cmdset.append("vfiler run %s route add default %s 1" % (vfiler.name, proj_vlan.networks[0].gateway) )
        return title, cmdset
    
    def services_vlan_route_commands(self, vfiler):
        """
        Services VLANs are different from VRFs. Services VLANs are actual VLANs
        that are routed via firewalls into the main corporate network to provide
        access to services, such as Active Directory.
        """
        cmdset = []
        log.debug("vfiler services vlans: %s", vfiler.services_ips)

        known_dests = []
        for (vlan, ipaddress) in vfiler.services_ips:
            log.debug("Adding services routes: %s", vlan)
            for ipaddr in vfiler.nameservers:
                if ipaddr not in known_dests:
                    cmdset.append("vfiler run %s route add host %s %s 1" % (vfiler.name, ipaddr, vlan.networks[0].gateway) )
                    known_dests.append(ipaddr)
                    pass
                pass
            
            for ipaddr in vfiler.winsservers:
                if ipaddr not in known_dests:
                    cmdset.append("vfiler run %s route add host %s %s 1" % (vfiler.name, ipaddr, vlan.networks[0].gateway) )
                    known_dests.append(ipaddr)
                    pass
                pass
            pass

        if len(vfiler.services_ips) > 0:
            # add the cifs prefdc commands to prefer domain controllers in the right order
            cmdset.append( "vfiler run %s cifs prefdc add %s %s" % (vfiler.name, vfiler.dns_domain_name, ' '.join(vfiler.winsservers)))
            pass
        
        return cmdset
            
    def vfiler_set_allowed_protocols_commands(self, vfiler, ns):
        cmdset = []

        # first, disallow everything
        cmdset.append("vfiler disallow %s proto=rsh proto=http proto=ftp proto=iscsi proto=nfs proto=cifs" % vfiler.name)

        # then, allow the ones we want
        for proto in self.allowed_protocols:
            cmdset.append("vfiler allow %s proto=%s" % (vfiler.name, proto) )

        #log.debug( '\n'.join(cmdset) )
        return cmdset

    def vfiler_setup_secureadmin_ssh_commands(self, vfiler):
        """
        Setup the vfiler for secure administration.
        """
        cmdset = []
        cmdset.append('vfiler run %s secureadmin setup -q ssh 768 512 768' % vfiler.name)
        return cmdset

    def vfiler_set_options_commands(self, vfiler, ns):
        cmdset = []

        options = [
            # not required, since we snapvault in vfiler0
            #'snapvault.enable on',
            'nfs.tcp.recvwindowsize 65536',
            'nfs.tcp.xfersize 65536',
            'cifs.tcp_window_size 64240',
            'cifs.neg_buf_size 33028',
            'iscsi.max_ios_per_session 256',
            'nfs.udp.enable off',
            ]

        for vol in vfiler.volumes:
            if len(vol.snapmirrors) > 0:
                options.append('snapmirror.enable on')
                break

        # DNS enablement options for CIFS capable vfilers
        if 'cifs' in self.allowed_protocols:
            options.append("dns domainname %s" % vfiler.dns_domain_name)
            options.append("dns enable on")
            
        for opt in options:
            cmdset.append("vfiler run %s options %s" % (vfiler.name, opt) )
            pass
        
        #log.debug( '\n'.join(cmdset) )
        return cmdset

    def vfiler_quotas_file_contents(self, filer, vfiler, ns):
        """
        Generate the /etc/quotas file contents for the vfiler
        """
        quota_file = """#
# Quotas for %s
#
""" % vfiler.name

        for vol in [x for x in filer.volumes if x.type not in ['snapmirrordst']]:
            if not vol.name.endswith('root'):
                quota_file += '*    tree@/vol/%s    -    -    -    -    -\n' % vol.name
                pass
            pass

        #log.debug(quota_file)
        return quota_file

    def vfiler_quotas_add_commands(self, filer, vfiler, ns):
        """
        Return a list of commands that can be used to activate the quotas
        """
        cmdset = []
        file_contents = self.vfiler_quotas_file_contents(filer, vfiler, ns)
        for line in file_contents.split('\n'):
            if len(line) == 0:
                continue
            line = line.replace('#', '##')

            cmdset.append('wrfile -a /vol/%s_root/etc/quotas "%s"' % (vfiler.name, line))
            pass

        return cmdset
        
    def vfiler_quota_enable_commands(self, filer, vfiler):
        cmdset = []
        for vol in [x for x in filer.volumes if x.type not in ['snapmirrordst']]:
            if not vol.name.endswith('root'):
                cmdset.append("vfiler run %s quota on %s" % (vfiler.name, vol.name))
                pass
            pass
        return cmdset
    
    def vfiler_nfs_exports_commands(self, filer, vfiler, ns):
        """
        Provide a list of nfs export commands.
        We need to change into the vfiler context to run these commands.
        """
        cmdset = []
        #cmdset.append("vfiler context %s" % vfiler.name)
        log.debug("Finding NFS exports for filer: %s", filer.name)
        for vol in [ x for x in filer.volumes if x.proto == 'nfs' ]:
            log.debug("Found volume: %s", vol)
            for qtree in vol.qtrees.values():
                log.debug("exporting qtree: %s", qtree)

                # Find read/write exports
                rw_export_to = []
                for export in qtree.rwexports:
                    if export.toip is not None:
                        rw_export_to.append( export.toip )
                    else:
                        rw_export_to.extend(export.tohost.get_storage_ips())
                        pass
                    pass

                # Find read-only exports
                ro_export_to = []
                for export in qtree.roexports:
                    if export.toip is not None:
                        ro_export_to.append( export.toip )
                    else:
                        ro_export_to.extend(export.tohost.get_storage_ips())
                        pass
                    pass
                
                if len(ro_export_to) > 0:
                    #log.debug("Read only exports required!")
                    ro_export_str = "ro=%s," % ':'.join(ro_export_to)
                else:
                    ro_export_str = ''

                if len(rw_export_to) > 0:
                    rw_export_str = "rw=%s," % ':'.join(rw_export_to)
                else:
                    rw_export_str = ''

                # allow root mount of both rw and ro hosts
                root_exports = rw_export_to + ro_export_to
                
                export_line = "vfiler run %s exportfs -p %s%sroot=%s /vol/%s/%s" % (
                    vfiler.name,
                    rw_export_str,
                    ro_export_str,
                    ':'.join(root_exports),
                    vol.name, qtree.name,
                    )
                cmdset.append(export_line)
                
                # Manual linewrap setup
##                 if len(export_line) > 90:
##                     wraplines = textwrap.wrap(export_line, 90)
##                     cmdset.append( '\\\n'.join(wraplines))
            pass
        #log.debug('\n'.join(cmdset))
        #cmdset.append("vfiler context vfiler0")
        return cmdset

    def vfiler_cifs_dns_commands(self, vfiler):
        """
        Return the commands for configuring DNS for CIFS access
        """
        cmds = []
        for nameserver in vfiler.nameservers:
            cmds.append("wrfile -a /vol/%s_root/etc/resolv.conf nameserver %s" % (vfiler.name, nameserver))

        return cmds

    def vfiler_cifs_shares_commands(self, vfiler):
        """
        For all the CIFS qtrees in the VFiler, return the commands
        used to configure the shares.
        """
        cmds = []
        volumes = [ x for x in vfiler.filer.volumes if x.proto == 'cifs' ]
        for vol in volumes:
            for qtree in vol.qtrees.values():
                log.debug("Determining CIFS config commands for %s", qtree)
                cmds.append("vfiler run %s cifs shares -add %s %s -f" % (vfiler.name, qtree.cifs_share_name(), qtree.full_path()) )
                cmds.append("vfiler run %s cifs access -delete %s everyone" % (vfiler.name, qtree.cifs_share_name() ) )

                cmds.append('vfiler run %s cifs access %s \"domain admins\" rwx' % (vfiler.name, qtree.cifs_share_name() ) )

##                 for host in qtree.rwexports:
##                     cmds.append("vfiler run %s cifs access %s CORP\%s Full Control" % (vfiler.name, qtree.cifs_share_name(), host.name ) )
##                 for host in qtree.roexports:
##                     cmds.append("vfiler run %s cifs access %s CORP\%s rx" % (vfiler.name, qtree.cifs_share_name(), host.name ) )

        return cmds

    def vfiler_iscsi_chap_enable_commands(self, filer, vfiler, prefix):
        """
        Return the commands required to enable the vfiler configuration
        """
        title = "iSCSI CHAP Configuration for %s" % filer.name
        cmds = []
        cmds.append("vfiler run %s iscsi security default -s CHAP -n %s -p %s" % (vfiler.name, vfiler.name, self.get_iscsi_chap_password(prefix) ) )
        return title, cmds

    def get_iscsi_chap_password(self, prefix='docgen'):
        """
        Create the iSCSI CHAP password to use.
        """
        chap_password = '%s%s123' % (prefix, self.shortname)
        # The password has to be longer than 12 characters. If it isn't pad it with zeros
        if len(chap_password) < 12:
            chap_password  = chap_password + ( '0' * (12 - len(chap_password)) )

        # The password also has to be no longer than 16 characters. If it's shorter,
        # that's fine, this will still work.
        chap_password = chap_password[:16]
            
        return chap_password

    def vfiler_igroup_enable_commands(self, filer, vfiler):
        """
        Return the commands required to enable the vfiler iGroup configuration
        """
        title = "iSCSI iGroup Configuration for %s" % filer.name
        cmds = []
        for igroup in self.get_filer_iscsi_igroups(filer):
            if igroup.exportlist[0].tohost.iscsi_initiator is None:
                raise ValueError("Host %s in igroup has no iSCSI initiator defined" % igroup.exportlist[0].tohost.name)
            cmds.append("vfiler run %s igroup create -i -t %s %s %s" % (vfiler.name, igroup.type, igroup.name, igroup.exportlist[0].tohost.iscsi_initiator) )
            if len(igroup.exportlist) > 1:
                for export in igroup.exportlist[1:]:
                    cmds.append("vfiler run %s igroup add %s %s" % (vfiler.name, igroup.name, export.tohost.iscsi_initiator) )
        return title, cmds

    def vfiler_lun_enable_commands(self, filer, vfiler):
        """
        Return the commands required to enable the vfiler LUN configuration
        """
        title = "iSCSI LUN Configuration for %s" % filer.name
        cmds = []
        for igroup in self.get_filer_iscsi_igroups(filer):
            for lun in igroup.lunlist:
                # Don't create LUNs on snapmirror destination volumes
                if lun.qtree.volume.type not in ['snapmirrordst']:
                    cmds.append("vfiler run %s lun create -s %s -t %s %s" % (vfiler.name, lun.get_create_size(), lun.ostype, lun.full_path()) )
                cmds.append("vfiler run %s lun map %s %s %s" % (vfiler.name, lun.full_path(), igroup.name, lun.lunid) )
                pass
            pass

        return title, cmds

    
    def filer_snapreserve_commands(self, filer, ns):
        cmdset = []

        for vol in filer.volumes:
            # snapreserve must be a non-negative integer
            cmdset.append("snap reserve %s %s" % ( vol.name, int(vol.snapreserve) ) )
            pass

        #log.debug('\n'.join(cmdset))
        return cmdset

    def filer_snapshot_commands(self, filer, ns):
        """
        Filer snapshot configuration commands for the project
        """
        cmdset = []

        for vol in filer.volumes:
            # Do snapshot schedules
            if len(vol.snaps) > 0:
                for snap in vol.snaps:
                    cmdset.append("snap sched %s %s %s %s" % (vol.name, snap.numweekly, snap.numdaily, snap.hourly_schedule))
                pass
            else:
                cmdset.append("snap sched %s 0 0 0" % (vol.name) )
                pass

            if vol.autodelete:
                cmdset.extend(vol.autodelete.command_add())
            # Add snapshot autodelete commands, if required
            pass
                
        #log.debug('\n'.join(cmdset))
        return cmdset

    def filer_snapvault_commands(self, filer, ns):
        cmdset = []
        for vol in filer.volumes:
            if len(vol.snapvaults) > 0:
                for snap in vol.snapvaults:
                    # If the snapvault sourcevol == the volume, this is a source snapvault schedule
                    if snap.sourcevol == vol:
                        # Only create a snapvault on the source if a source schedule exists
                        if snap.src_schedule is not None:
                            cmdset.append("snapvault snap sched %s %s %s" % (vol.name, snap.basename, snap.src_schedule))
                        
                    elif snap.targetvol == vol:
                        if snap.dst_schedule is not None:
                            # Use a transfer schedule if the snapvault has a corresponding snapschedule
                            if snap.src_schedule is not None:
                                cmdset.append("snapvault snap sched -x %s %s %s" % (vol.name, snap.basename, snap.dst_schedule))
                                pass

                            # Otherwise, do a local snapvault snap on the device
                            else:
                                cmdset.append("snapvault snap sched %s %s %s" % (vol.name, snap.basename, snap.dst_schedule))
                                pass
                            pass
                        pass
                            
                    else:
                        log.error("snapvault target and source are not for '%s'" % vol.name)
                        pass
                    pass
                pass
            else:
                # No command to set up a blank schedule required.
                #cmdset.append("snapvault snap sched %s 0" % (vol.name) )
                pass
            
            pass
        
        #log.debug('\n'.join(cmdset))
        return cmdset

    def filer_snapvault_init_commands(self, filer, ns):
        """
        Commands used to initialise the snapvaults.
        We need to make sure we only attempt to initilise each
        snapvault once: One snapvault relationship per qtree, regardless
        of how many schedules it may have.
        """
        cmdset = []
        donelist = []
        for vol in filer.volumes:
            if len(vol.snapvaults) > 0:
                for snap in vol.snapvaults:
                    # If the snapvault sourcevol == the volume, this is a source snapvault schedule
                    if snap.sourcevol == vol:
                        log.error("You cannot initialise the snapvaults from the source filer.")
                        
                    elif snap.targetvol == vol:
                        if snap.sourcevol.name.endswith('root'):
                            if (snap.sourcevol.filer, snap.sourcevol, 'root') not in donelist:
                                cmdset.append("snapvault start -S %s-svif0-2000:/vol/%s/- /vol/%s/%s" % (snap.sourcevol.filer.name, snap.sourcevol.name, snap.targetvol.name, snap.sourcevol.name ))
                                
                                donelist.append( (snap.sourcevol.filer, snap.sourcevol, 'root') )

                        # Snapvault relationships are done at the qtree level
                        for qtree in snap.sourcevol.qtrees.values():
                            if (snap.sourcevol.filer, snap.sourcevol, qtree) not in donelist:
                                cmdset.append("snapvault start -S %s-svif0-2000:/vol/%s/%s /vol/%s/%s" % (snap.sourcevol.filer.name, snap.sourcevol.name, qtree.name, snap.targetvol.name, qtree.name ))
                                donelist.append( (snap.sourcevol.filer, snap.sourcevol, qtree) )
                            else:
                                log.debug("Skipping duplicate snapvault initialisation for %s:/vol/%s/%s", snap.sourcevol.filer.name, snap.sourcevol.name, qtree.name)
                    else:
                        log.error("snapvault target and source are not for '%s'" % vol.name)
                        pass
                    pass
                pass
            pass
        
        #log.debug('\n'.join(cmdset))
        return cmdset

    def filer_snapmirror_init_commands(self, filer):
        """
        Commands used to initialise the snapmirrors.
        We need to make sure we only attempt to initilise each
        snapmirror once: One snapmirror relationship per volume, regardless
        of how many schedules it may have.
        """
        cmdset = []
        donelist = []
        for vol in filer.volumes:
            if len(vol.snapmirrors) > 0:
                for snap in vol.snapmirrors:
                    # If the sourcevol == the volume, this is a source snapmirror schedule
                    if snap.sourcevol == vol:
                        log.error("You cannot initialise the snapmirror from the source filer.")
                        
                    elif snap.targetvol == vol:
                        if (snap.sourcevol, snap.targetvol) not in donelist:
                            cmdset.append("vol restrict %s" % snap.targetvol.name)
                            cmdset.append("snapmirror initialize -S %s-svif0-2000:%s %s" % (snap.sourcevol.filer.name, snap.sourcevol.name, snap.targetvol.name))
                                
                            donelist.append( (snap.sourcevol, snap.targetvol) )
                    else:
                        log.error("snapmirror target and source are not for '%s'" % vol.name)
                        pass
                    pass
                pass
            pass
        
        #log.debug('\n'.join(cmdset))
        return cmdset

    def filer_etc_snapmirror_contents(self, filer):
        """
        Returns the lines to append to the /etc/snapmirror file
        on the filer for this project.
        """
        cmdset = []
        for vol in filer.volumes:
            for snap in vol.snapmirrors:
                # If the sourcevol == the volume, this is the source side, so ignore it
                if snap.sourcevol == vol:
                    log.warn("/etc/snapmirror not used on the source filer.")
                        
                elif snap.targetvol == vol:
                    # Use a transfer schedule
                    cmdset.append("%s-svif0-2000:%s %s:%s %s %s" % (snap.sourcevol.filer.name, snap.sourcevol.name, snap.targetvol.filer.name, snap.targetvol.name, snap.arguments, snap.etc_snapmirror_conf_schedule()))
                else:
                    log.error("snapmirror target and source are not for '%s'" % vol.name)
                    pass
                pass
            pass

        if len(cmdset) > 0:
            cmdset.insert(0, "#")
            cmdset.insert(0, "# %s" % self.shortname)
            cmdset.insert(0, "#")

        #log.debug('\n'.join(cmdset))
        return cmdset

    def filer_etc_snapmirror_conf_commands(self, filer):
        """
        Returns a list of commands that can be used to append to
        the /etc/snapmirror file on the filer for this project.
        """
        cmdset = []
        file_contents = self.filer_etc_snapmirror_contents(filer)
        
        for line in file_contents:
            if len(line) == 0:
                continue
            line = line.replace('#', '##')

            cmdset.append('wrfile -a /etc/snapmirror.conf "%s"' % (line))
            pass

        return cmdset

    def vfiler_etc_hosts_contents(self, filer, vfiler):
        """
        Generate the additions for the /etc/hosts file on the
        vfiler that are specific to this project.
        """
        file = """#
# %s
#
%s %s-svif0-%s
""" % (vfiler.name, vfiler.ipaddress, filer.name, vfiler.vlan.number )

        for (vlan, ipaddress) in vfiler.services_ips:
            file += '\n%s %s-svif0-%s' % (ipaddress, filer.name, vlan.number)
        return file

    def vfiler_etc_hosts_commands(self, filer, vfiler):
        """
        Returns a list of commands that can be used to create the /etc/hosts
        file within a particular vfiler for the project.
        """
        cmdset = []
        file_contents = self.vfiler_etc_hosts_contents(filer, vfiler)
        for line in file_contents.split('\n'):
            if len(line) == 0:
                continue
            line = line.replace('#', '##')

            cmdset.append('wrfile -a /vol/%s_root/etc/hosts "%s"' % (vfiler.name, line))
            pass

        return cmdset

    def filer_etc_rc_commands(self, filer, vfiler):
        """
        Returns a list of commands that can be used to add the /etc/rc
        entries to the filer.
        """
        cmdset = []
        cmds = [ '#', '# %s' % vfiler.name, '#' ] 
        cmds += self.vlan_create_commands(filer, vfiler)
        cmds += self.vfiler_add_storage_interface_commands(filer, vfiler)
        cmds += self.services_vlan_route_commands(vfiler)
        title, routecmds = self.default_route_command(filer, vfiler)
        cmds += routecmds
        
        for line in cmds:
            if len(line) == 0:
                continue
            line = line.replace('#', '##')
            cmdset.append('wrfile -a /vol/vol0/etc/rc "%s"' % line)

        return cmdset

    def str2net(self, netstr):
        """
        Convert a network string such as 10.0.0.0/8 to a network
        integer and a netmask
        """

        fields = netstr.split('/')
        addrstr = fields[0]
        if len(fields) > 1:
            maskbits = int(fields[1])
        else:
            maskbits = 32
            pass

        hostbits = 32 - maskbits
        mask = 0xFFFFFFFFL - ((1L << hostbits) - 1)
        maskstr = socket.inet_ntoa(struct.pack('!L',mask))

        addr = socket.inet_aton(addrstr)
        addr = long(struct.unpack('!I', addr)[0])
        addr = addr & mask

        return addrstr, maskstr, maskbits

    def mask2bits(self, netmask):
        """
        Take a netmask and work out what number it
        would need on the righthand side of slash notation.
        eg: A netmask of 255.255.255.0 == /24
        """
        mask = socket.inet_aton(netmask)
        mask = long(struct.unpack('!I', mask)[0])

        bits = 0
        for byte in range(4):
            testval = (mask >> (byte * 8)) & 0xff
            while (testval != 0):
                if ((testval & 1) == 1):
                    bits += 1
                testval >>= 1
        return bits        

    def inverse_mask_str(self, netmaskstr):
        """
        Take a netmask and return the inverse mask, used for Cisco ACLs
        """
        maskint = long(struct.unpack('!I', socket.inet_aton(netmaskstr))[0])
        newmask = 0xFFFFFFFFL - maskint
        newmaskstr = socket.inet_ntoa(struct.pack('!L', newmask))
        return newmaskstr

    def switch_vlan_activation_commands(self, switch):
        """
        Return activation commands for configuring the VLAN
        This code is common to both edge and core switches.
        """
        cmdset = []

        # Add the main project VLAN
        vlan = self.get_project_vlan(switch.site.type)
        cmdset.append('Vlan %s' % vlan.number)
        cmdset.append('  name %s_01' % self.shortname)
        cmdset.append('  mtu %s' % vlan.mtu)
        return cmdset

    def core_switch_activation_commands(self, switch):
        """
        Return a list of commands that can be used to build the switch configuration.
        """
        cmdset = []

        cmdset.extend( self.switch_vlan_activation_commands(switch))

        # If services VLANs exist, add them to the core
        # These aren't added on edges, which is why the commands go here,
        # and not in switch_vlan_activation_commands()
        log.warn("Services vlans are only detected at the primary site for now.")
        vlans = self.get_services_vlans(switch.site)
        if len(vlans) > 0:
            cmdset.append('! Services VLANs')
            for i, vlan in enumerate(vlans):
                cmdset.append('Vlan %s' % vlan.number)
                cmdset.append('  name %s_svc_%02d' % (self.shortname, i+1) )
        return cmdset

    def edge_switch_activation_commands(self, switch):
        """
        Return a list of commands that can be used to build an edge switch configuration.
        """
        cmdset = []
        cmdset.extend( self.switch_vlan_activation_commands )
        cmdset.append('!')
        cmdset.extend( self.edge_switch_port_acl_commands )
        return cmdset

    def edge_switch_port_acl_commands(self, switch):
        """
        Return a list of edge port ACL commands used to build an edge switch configuration.
        """
        log.debug("Fetching vlan for site: %s", switch.site)
        vlan = self.get_project_vlan(switch.site.type)
        cmdset = []

        # Removed due to ticket #29
        #cmdset.append("mac access-list extended FilterL2")
        #cmdset.append("  deny any any")        
        #cmdset.append("!")

        # inbound access list
        cmdset.append("ip access-list extended %s_in" % self.shortname)

        # Stop hosts pretending to be a storage device by blocking
        # inbound packets purporting to be from a storage device address.
        # Storage devices are always the first 8 IPs in the subnet
        # FIXME: If this changes to another number, we'll need to update the 0.0.0.7 part

        # FIXME: This assumes that networks are assigned on the ideal network
        # boundary, not across nominal /24 boundaries by making a /24 out of
        # 2 /25s that span a third octet. Eg: 10.10.3.128/25 + 10.10.4.0/25
        cmdset.append("  remark AntiSpoofing For Storage Devices")

        for network in vlan.networks:
            cmdset.append("  deny ip %s 0.0.0.7 any" % network.number)
            pass
        
        cmdset.append("  remark Permit Hosts To Storage Devices")
        for network in vlan.networks:
            hostmask = self.inverse_mask_str(network.netmask)
            cmdset.append("  permit ip %s %s %s 0.0.0.7" % (network.number, hostmask, network.number) )
            pass

        # outbound access list
        cmdset.append("ip access-list extended %s_out" % self.shortname)
        cmdset.append("  remark Permit Storage Devices To Hosts")
        for network in vlan.networks:
            cmdset.append("  permit ip %s 0.0.0.7 %s %s" % (network.number, network.number, hostmask) )
            pass
        
        return cmdset

    def edge_switch_interfaces_commands(self, switch):
        """
        Build the configuration commands required to activate the ports
        for all hosts that have interfaces connected to this switch.
        """
        cmdset = []

        vlan = self.get_project_vlan(switch.site.type)
        
        for host in self.hosts.values():
            for iface in host.interfaces:
                if iface.switchname == switch.name:

                    cmdset.extend(
                        [ "interface %s" % iface.switchport,
                          "  description %s" % host.name,
                         ])

                    # If we're trunking, we need different config than an access port.
                    # Trunking is often used for vmware ports
                    if iface.mode == 'trunk':
                        log.info("Detected trunk port. Configuring...")
                        cmdset.extend(
                            [ "  switchport mode trunk",
                              ])
                        for vlan in iface.vlans:
                            cmdset.append("  switchport trunk allowed vlan add %s" % vlan.number)
                            pass
                        
                    else:
                        cmdset.extend(
                            [
                             #"  switchport mode access",
                             #"  switchport port-security maximum 10",
                             #"  switchport port-security aging time 300",
                             #"  switchport port-security violation restrict",
                             #"  switchport post-security limit rate invalid-source-mac 5",
                             "  switchport access vlan %s" % vlan.number,
                             "  ip access-group %s_in in" % self.shortname,
                             "  ip access-group %s_out out" % self.shortname,
                             "  mac access-group FilterL2 in",
                             #"  flowcontrol receive on",
                             #"  flowcontrol send on",

                             #"  no cdp enable",
                             #"  spanning-tree portfast",
                             ])
                        pass

                    # finish off with common end pieces
                    mtu = iface.mtu
                    #mtu = vlan.mtu
                    
                    # If the mtu is 9000, the switchport needs to have MTU of 9198
                    # in order to cater for various packet overheads.
                    if mtu == 9000:
                        mtu = 9198
                        pass

                    cmdset.extend([
                        "  mtu %s" % mtu,
                        "  no shutdown",
                        "!",
                        ])

        return cmdset

if __name__ == '__main__':

    log.setLevel(logging.DEBUG)

    configfile = sys.argv[1]

    try:
        doc = etree.parse(configfile)
        proj = ProjectConfig(doc)
    except:
        log.error("Cannot load configuration. Aborting.")
        import traceback
        traceback.print_exc()
        sys.exit(1)
